"""桥接层 — 契约 v1.0.0(docs/tech/guigui-bridge-api-v1.md)的 Python 实现。

- 方法名逐字沿用契约 camelCase;pywebview 原样暴露到 window.pywebview.api,
  前端 GG 适配器二级探测命中。
- 统一信封 {ok:true,data} / {ok:false,code,message};永不向 JS 抛异常。
- 事件经 window.evaluate_js("window.guiguiEmit(…)") 推送;跨进程事件
  (外部 ensure 落盘)由 gui.FileWatcher 翻译(见 gui.py)。
- 并发:pywebview 每个调用独立线程,长动作(login/connectWifi)挂住自己的
  promise 不阻塞查询类方法(契约 §0)。
"""

from __future__ import annotations

import json
import logging
import threading
import time

from guigui.core import config, detect, diagnostics, drcom, ensure, logstore, selfheal, vault, wifictl
from guigui.core.config import ConfigError
from guigui.core.vault import VaultError
from guigui.core.wifictl import WifiConnectError, WifiScanError

log = logging.getLogger(__name__)

# 契约 §1 错误码
NET_UNREACHABLE = "NET_UNREACHABLE"
AUTH_REJECTED = "AUTH_REJECTED"
WIFI_SCAN_FAILED = "WIFI_SCAN_FAILED"
WIFI_CONNECT_FAILED = "WIFI_CONNECT_FAILED"
WIFI_CONNECT_TIMEOUT = "WIFI_CONNECT_TIMEOUT"
NOT_CONFIGURED = "NOT_CONFIGURED"
SAVE_FAILED = "SAVE_FAILED"
INTERNAL = "INTERNAL"


def _ok(data: dict) -> dict:
    return {"ok": True, "data": data}


def _err(code: str, message: str) -> dict:
    return {"ok": False, "code": code, "message": message}


class GuiGuiApi:
    """pywebview js_api 对象;gui.py 创建窗口时注入并 attach_window。"""

    def __init__(self):
        self._window = None

    def attach_window(self, window) -> None:
        self._window = window

    # ── 事件(契约 §3)──────────────────────────────

    def _emit(self, type_: str, payload: dict) -> None:
        w = self._window
        if w is None:
            return
        try:
            w.evaluate_js(
                f"window.guiguiEmit && window.guiguiEmit("
                f"{json.dumps(type_)}, {json.dumps(payload, ensure_ascii=False)})")
        except Exception as e:
            log.warning("api: 事件推送失败(%s): %s", type_, e)

    # ── 2.1 probe ─────────────────────────────────

    def probe(self) -> dict:
        try:
            cfg = config.load()
            net = detect.probe(cfg)
            configured = bool(cfg.get("uid")) and vault.has_password(cfg["uid"])
            return _ok({
                "configured": configured,
                "net": {"state": net["state"], "ssid": net.get("ssid"),
                        "server": cfg.get("server_name", "")},
            })
        except Exception as e:
            log.exception("api.probe")
            return _err(INTERNAL, "探不到网络状态,再试一次")

    # ── 2.2 identify ──────────────────────────────

    def identify(self) -> dict:
        try:
            cfg = config.load()
            uid, source = None, "none"
            probe = detect.http_probe(cfg=cfg)
            if probe["state"] in (detect.LOGGED_IN, detect.NOT_LOGGED_IN):
                found = drcom.chkstatus_uid(cfg["url"])
                if found:
                    uid, source = found, "chkstatus"
            if not uid and cfg.get("uid"):
                uid, source = cfg["uid"], "config"
            return _ok({"uid": uid, "source": source})
        except Exception:
            log.exception("api.identify")
            return _err(INTERNAL, "没认出学号,稍后再试")

    # ── 2.3 login ─────────────────────────────────

    def login(self, payload=None) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        try:
            cfg = config.load()
            sid = str(payload.get("sid") or "").strip()
            password = payload.get("password") or None

            if password:
                uid = sid or cfg.get("uid") or ""
                if not uid:
                    return _err(NOT_CONFIGURED, "先填学号,再开启")
                try:
                    if sid and cfg.get("uid") and sid != cfg["uid"]:
                        vault.rekey(cfg["uid"], sid, password)   # 换学号:清旧凭据
                    else:
                        vault.set_password(uid, password)
                except VaultError as e:
                    log.warning("api.login: 凭据存储失败: %s", e)
                    return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
                cfg = config.save({**cfg, "uid": uid})
            else:
                uid = cfg.get("uid") or ""
                if not uid or not vault.has_password(uid):
                    return _err(NOT_CONFIGURED, "还没存过密码,先填一次")

            self._emit("login:progress", {"phase": "probe"})
            net = detect.probe(cfg)
            if net["state"] == detect.LOGGED_IN:
                ensure.settle_from_gui(cfg, uid, 0)
                return _ok({"result": "already", "uid": drcom.mask_uid(uid), "attempts": 0})
            if net["state"] in (detect.UNREACHABLE, detect.WAITING):
                return _err(NET_UNREACHABLE, "现在够不着校园网")

            retries = max(1, int(cfg.get("login_retries", 3)))
            interval = int(cfg.get("retry_seconds", 5))
            result, msg, attempts = drcom.UNREACHABLE, "", 0
            for i in range(retries):
                attempts = i + 1
                self._emit("login:progress",
                           {"phase": "requesting", "attempt": attempts, "attempts": retries})
                result, msg = drcom.login(cfg["url"], uid, vault.get_password(uid))
                if result == drcom.SUCCESS:
                    break
                if i < retries - 1:
                    self._emit("login:progress",
                               {"phase": "retrying", "attempt": attempts, "attempts": retries})
                    time.sleep(interval)

            if result == drcom.SUCCESS:
                ensure.settle_from_gui(cfg, uid, attempts)
                return _ok({"result": "success", "uid": drcom.mask_uid(uid),
                            "attempts": attempts})
            if result == drcom.REJECTED:
                return _err(AUTH_REJECTED, "密码可能改过了,改下面的密码再点一次")
            if result == drcom.UNREACHABLE:
                return _err(NET_UNREACHABLE, "现在够不着校园网")
            return _err(INTERNAL, msg or "认证服务器返回了不认识的格式")
        except Exception:
            log.exception("api.login")
            return _err(INTERNAL, "登录过程出了点问题,再试一次")

    # ── 2.4 scanWifi ──────────────────────────────

    def scanWifi(self) -> dict:
        try:
            networks = wifictl.scan_networks()
            return _ok({"networks": networks})
        except WifiScanError as e:
            return _err(WIFI_SCAN_FAILED, f"扫不到附近网络({e})")
        except Exception:
            log.exception("api.scanWifi")
            return _err(WIFI_SCAN_FAILED, "扫不到附近网络")

    # ── 2.5 connectWifi ───────────────────────────

    def connectWifi(self, payload=None) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        ssid = str(payload.get("ssid") or "").strip()
        if not ssid:
            return _err(WIFI_CONNECT_FAILED, "没有指定要连的网络")
        try:
            self._emit("login:progress", {"phase": "connecting_wifi"})
            ok_flag = wifictl.connect(ssid)
            if not ok_flag:
                return _err(WIFI_CONNECT_TIMEOUT, "连了一会儿没连上,再试一次")
            cfg = config.load()
            net = detect.probe(cfg)
            self._emit("net:state", {"state": net["state"], "ssid": net.get("ssid")})
            return _ok({"connected": True, "ssid": ssid})
        except WifiConnectError as e:
            return _err(WIFI_CONNECT_FAILED, str(e))
        except Exception:
            log.exception("api.connectWifi")
            return _err(WIFI_CONNECT_FAILED, "连接没成功,再试一次")

    # ── 2.6 getConfig ─────────────────────────────

    def getConfig(self) -> dict:
        try:
            return _ok(config.to_bridge(config.load()))
        except Exception:
            log.exception("api.getConfig")
            return _err(INTERNAL, "设置读不出来,再试一次")

    # ── 2.7 saveConfig ────────────────────────────

    def saveConfig(self, patch=None) -> dict:
        try:
            cfg = config.load()
            merged = config.apply_patch(cfg, patch if isinstance(patch, dict) else {})
            saved = config.save(merged)
        except ConfigError as e:
            return _err(SAVE_FAILED, str(e))
        except OSError as e:
            log.warning("api.saveConfig: 落盘失败: %s", e)
            return _err(SAVE_FAILED, "设置没存上,再试一次")
        except Exception:
            log.exception("api.saveConfig")
            return _err(INTERNAL, "设置没存上,再试一次")

        # 任务计划对齐放后台线程(PS 调用秒级),完成后推 schedule:changed
        def _align():
            try:
                selfheal.reconcile(saved)
            except Exception:
                log.exception("api.saveConfig: selfheal 对齐失败")
            self._emit("schedule:changed",
                       {"master": saved["master"], "trigger_time": saved["trigger_time"]})

        threading.Thread(target=_align, daemon=True).start()
        return _ok(config.to_bridge(saved))

    # ── 2.8 masterToggle ──────────────────────────

    def masterToggle(self, on=None) -> dict:
        try:
            value = bool(on.get("on")) if isinstance(on, dict) else bool(on)
            cfg = config.load()
            saved = config.save(config.apply_patch(cfg, {"master": value}))
            # 语义重(建/删任务):同步做完再回话
            selfheal.reconcile(saved)
            self._emit("schedule:changed",
                       {"master": saved["master"], "trigger_time": saved["trigger_time"]})
            return _ok({"master": saved["master"]})
        except Exception:
            log.exception("api.masterToggle")
            return _err(SAVE_FAILED, "开关没切过去,再试一次")

    # ── 2.9 logs ──────────────────────────────────

    def logs(self, payload=None) -> dict:
        try:
            days = payload.get("days") if isinstance(payload, dict) else None
            return _ok({"days": logstore.query(days if days else logstore.DEFAULT_DAYS)})
        except Exception:
            log.exception("api.logs")
            return _err(INTERNAL, "日志读不出来,再试一次")

    # ── 2.10 recentResult ─────────────────────────

    def recentResult(self) -> dict:
        try:
            lr = ensure.load_state().get("last_result")
            if not lr:
                return _ok({"when": None, "time": None, "tries": 0, "outcome": "none"})
            import datetime as dt

            date = lr.get("date", "")
            today = dt.date.today().isoformat()
            yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
            if date == today:
                when = "今早"
            elif date == yesterday:
                when = "昨天"
            elif date:
                y, m, d = date.split("-")
                when = f"{int(m)}月{int(d)}日"
            else:
                when = None
            return _ok({"when": when, "time": lr.get("time"),
                        "tries": lr.get("tries", 0), "outcome": lr.get("outcome", "none")})
        except Exception:
            log.exception("api.recentResult")
            return _err(INTERNAL, "昨晚的记录读不出来")

    # ── 2.12 feedback(1.1.0 新增)─────────────────

    def feedback(self) -> dict:
        try:
            return _ok({"text": diagnostics.build_text()})
        except Exception:
            log.exception("api.feedback")
            return _err(INTERNAL, "诊断信息没生成出来,再试一次")

    # ── 2.11 winMinimize / winClose ───────────────

    def winMinimize(self) -> dict:
        try:
            if self._window is not None:
                self._window.minimize()
        except Exception:
            log.warning("api.winMinimize 失败")
        return _ok({})

    def winClose(self) -> dict:
        try:
            if self._window is not None:
                self._window.destroy()   # 关闭=退出 GUI,自动化不受影响(方案 §10)
        except Exception:
            log.warning("api.winClose 失败")
        return _ok({})
