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

from guigui.core import config, detect, diagnostics, drcom, ensure, logstore, notify, selfheal, vault, wifictl
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


def _configured(cfg: dict) -> bool:
    """首装完成判定:学号已存且凭据管理器里有密码(契约 §4 单行道终点)。"""
    return bool(cfg.get("uid")) and vault.has_password(cfg["uid"])


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

    def _align_saved(self, saved: dict) -> None:
        """后台对齐任务计划(saveConfig / login 共用)。

        守卫:首装未完成(uid 空或密码未存)时不建任务 —— 任务属于
        「开启每日自动登录」那一步,由 login 存完凭据后首次对齐;
        master 关 → 删任务不受守卫影响。"""
        misaligned = False
        try:
            if saved.get("master", True) and not _configured(saved):
                log.info("api: 首装未完成,暂不建任务(等 login 存凭据后再对齐)")
            else:
                _, misaligned = selfheal.reconcile(saved)
        except Exception:
            log.exception("api: selfheal 对齐失败")
            misaligned = bool(saved.get("master", True))
        if misaligned and saved.get("master", True):
            notify.task_blocked()
        self._emit("schedule:changed",
                   {"master": saved["master"], "trigger_time": saved["trigger_time"]})

    # ── 事件(契约 §3)──────────────────────────────

    def _eval(self, js: str) -> None:
        w = self._window
        if w is None:
            return
        try:
            w.evaluate_js(js)
        except Exception as e:
            log.warning("api: JS 执行失败(%s)", e)

    def _emit(self, type_: str, payload: dict) -> None:
        self._eval(
            f"window.guiguiEmit && window.guiguiEmit("
            f"{json.dumps(type_)}, {json.dumps(payload, ensure_ascii=False)})")

    # ── 2.1 probe ─────────────────────────────────

    def probe(self) -> dict:
        try:
            cfg = config.load()
            net = detect.probe(cfg)
            configured = _configured(cfg)
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
                return self._login_submitted_credential(cfg, sid, password, payload)
            return self._login_stored_credential(cfg)
        except Exception:
            log.exception("api.login")
            return _err(INTERNAL, "登录过程出了点问题,再试一次")

    def _login_stored_credential(self, cfg: dict) -> dict:
        """已存凭据路径(立即登录/每日任务同款):探测→重试登录。"""
        uid = cfg.get("uid") or ""
        if not uid or not vault.has_password(uid):
            return _err(NOT_CONFIGURED, "还没存过密码,先填一次")
        # 凭据单次读出(重试不碰 keyring);读出为空 → 明确报未配置,
        # 不让 None 流进 drcom.build_login_url(quote(None) 炸成 INTERNAL)。
        stored = vault.get_password(uid)
        if not stored:
            return _err(NOT_CONFIGURED, "还没存过密码,先填一次")

        self._emit("login:progress", {"phase": "probe"})
        net = detect.probe(cfg)
        if net["state"] == detect.LOGGED_IN:
            ensure.settle_from_gui(cfg, uid, 0)
            return _ok({"result": "already", "uid": drcom.mask_uid(uid), "attempts": 0,
                        "verified": bool(ensure.load_state().get("cred_verified"))})
        if net["state"] in (detect.UNREACHABLE, detect.WAITING):
            return _err(NET_UNREACHABLE, "现在够不着校园网")

        result, msg, attempts = self._attempt_login(
            cfg, uid, stored, cfg.get("operator", drcom.DEFAULT_OPERATOR))
        if result == drcom.SUCCESS:
            ensure.settle_from_gui(cfg, uid, attempts)
            return _ok({"result": "success", "uid": drcom.mask_uid(uid),
                        "attempts": attempts, "verified": True})
        if result == drcom.REJECTED:
            return _err(AUTH_REJECTED, "密码可能改过了,改下面的密码再点一次")
        if result == drcom.UNREACHABLE:
            return _err(NET_UNREACHABLE, "现在够不着校园网")
        return _err(INTERNAL, msg or "认证服务器返回了不认识的格式")

    def _login_submitted_credential(self, cfg: dict, sid: str,
                                    password: str, payload: dict) -> dict:
        """提交新密码路径 — 先验证后入库(凭证神圣:垃圾密码绝不能「成功」入库)。

        探测先行:离线(not_logged_in)= 服务器可达,真刀真枪验证,拒绝永不入库;
        在线(logged_in)= 走验证阶梯「注销→等状态翻转→真登一次」,
        门户不给注销配置或注销无效则降级存入(verified=false);
        失败时用旧凭据把网接回来(注销是破坏性动作,得给用户留条退路)。"""
        operator = payload.get("operator")
        if not (isinstance(operator, str) and operator in drcom.OPERATOR_TABLE):
            operator = cfg.get("operator") or drcom.DEFAULT_OPERATOR
        uid = sid or cfg.get("uid") or ""
        if not uid:
            return _err(NOT_CONFIGURED, "先填学号,再开启")
        old_uid = cfg.get("uid") or ""
        old_pw = vault.get_password(old_uid) if old_uid else None   # 旧凭证,失败时恢复网络用

        self._emit("login:progress", {"phase": "probe"})
        net = detect.probe(cfg)

        if net["state"] == detect.NOT_LOGGED_IN:
            result, msg, attempts = self._attempt_login(cfg, uid, password, operator)
            if result == drcom.SUCCESS:
                saved = self._store_credential(cfg, uid, operator, password, verified=True)
                if saved is None:
                    return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
                ensure.settle_from_gui(saved, uid, attempts)
                return _ok({"result": "success", "uid": drcom.mask_uid(uid),
                            "attempts": attempts, "verified": True})
            if result == drcom.REJECTED:
                return _err(AUTH_REJECTED, "密码可能改过了,改下面的密码再点一次")
            if result == drcom.UNREACHABLE:
                # 循环中途断网:密码没被否认,存了给明早一次机会
                saved = self._store_credential(cfg, uid, operator, password, verified=False)
                if saved is None:
                    return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
                return _err(NET_UNREACHABLE, "现在够不着校园网")
            return _err(INTERNAL, msg or "认证服务器返回了不认识的格式")

        if net["state"] == detect.LOGGED_IN:
            used = drcom.logout(detect.portal_html(cfg), cfg["url"])
            flipped = False
            if used is not None:
                for _ in range(6):   # 注销生效要一拍:最多 6×0.5s 等状态翻转
                    time.sleep(0.5)
                    if detect.http_probe(cfg=cfg)["state"] != detect.LOGGED_IN:
                        flipped = True
                        break
            if used is not None and flipped:
                result, msg, tries = self._verify_login_once(cfg, uid, password, operator)
                if result == drcom.SUCCESS:
                    saved = self._store_credential(cfg, uid, operator, password,
                                                   verified=True)
                    if saved is None:
                        return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
                    ensure.settle_from_gui(saved, uid, tries)
                    return _ok({"result": "success", "uid": drcom.mask_uid(uid),
                                "attempts": tries, "verified": True})
                if result == drcom.REJECTED:
                    restored = self._restore_network(cfg, old_uid, uid, old_pw)
                    return _err(AUTH_REJECTED, "密码被服务器拒绝了" +
                                (";已用旧密码把网接回来了,改对再点一次" if restored
                                 else ";旧密码也没能接回网络,改对密码再点一次"))
                if result == drcom.UNREACHABLE:
                    self._restore_network(cfg, old_uid, uid, old_pw)  # 尽力恢复,不看成败
                    saved = self._store_credential(cfg, uid, operator, password,
                                                   verified=False)
                    if saved is None:
                        return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
                    return _err(NET_UNREACHABLE,
                                "验证做到一半网络够不着了,密码先存着,明早首试见真章")
                self._restore_network(cfg, old_uid, uid, old_pw)
                return _err(INTERNAL, msg or "认证服务器返回了不认识的格式")
            # 门户无注销配置 / 注销未见翻转:降级存入,verified=false
            saved = self._store_credential(cfg, uid, operator, password, verified=False)
            if saved is None:
                return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
            return _ok({"result": "already", "uid": drcom.mask_uid(uid),
                        "attempts": 0, "verified": False})

        # unreachable / waiting:密码没被否认,存了给明早一次机会
        saved = self._store_credential(cfg, uid, operator, password, verified=False)
        if saved is None:
            return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
        return _err(NET_UNREACHABLE, "现在够不着校园网")

    def _attempt_login(self, cfg: dict, uid: str, password: str,
                       operator: str) -> tuple[str, str, int]:
        """重试节奏按配置(retries × interval),期间推进度事件。"""
        retries = max(1, int(cfg.get("login_retries", 3)))
        interval = int(cfg.get("retry_seconds", 5))
        result, msg, attempts = drcom.UNREACHABLE, "", 0
        for i in range(retries):
            attempts = i + 1
            self._emit("login:progress",
                       {"phase": "requesting", "attempt": attempts, "attempts": retries})
            result, msg = drcom.login(cfg["url"], uid, password, operator)
            if result == drcom.SUCCESS:
                break
            if i < retries - 1:
                self._emit("login:progress",
                           {"phase": "retrying", "attempt": attempts, "attempts": retries})
                time.sleep(interval)
        return result, msg, attempts

    def _verify_login_once(self, cfg: dict, uid: str, password: str,
                           operator: str) -> tuple[str, str, int]:
        """阶梯验证单发:刚注销立即重登会被 waitsec 节流 → 等 4s 重试一次。"""
        result, msg = drcom.login(cfg["url"], uid, password, operator)
        tries = 1
        if result in (drcom.REJECTED, drcom.UNREACHABLE) and "waitsec" in (msg or ""):
            time.sleep(4)
            result, msg = drcom.login(cfg["url"], uid, password, operator)
            tries = 2
        return result, msg, tries

    def _restore_network(self, cfg: dict, old_uid: str, uid: str,
                         old_pw: str | None) -> bool:
        """验证失败后用旧凭据把网接回来(注销是破坏性动作)。返回是否恢复成功。"""
        if not old_pw:
            return False
        restore_operator = cfg.get("operator", drcom.DEFAULT_OPERATOR)
        result, msg = drcom.login(cfg["url"], old_uid or uid, old_pw, restore_operator)
        if result in (drcom.REJECTED, drcom.UNREACHABLE) and "waitsec" in (msg or ""):
            time.sleep(4)
            result, msg = drcom.login(cfg["url"], old_uid or uid, old_pw,
                                      restore_operator)
        return result == drcom.SUCCESS

    def _store_credential(self, cfg: dict, uid: str, operator: str,
                          password: str, *, verified: bool) -> dict | None:
        """入库:vault(换学号清旧条目)→ config(uid/operator)→ cred_verified。
        成功后后台对齐任务计划;VaultError 返回 None(调用方回 INTERNAL 信封)。"""
        try:
            if cfg.get("uid") and cfg["uid"] != uid:
                vault.rekey(cfg["uid"], uid, password)   # 换学号:清旧凭据
            else:
                vault.set_password(uid, password)
        except VaultError as e:
            log.warning("api.login: 凭据存储失败: %s", e)
            return None
        saved = config.save({**cfg, "uid": uid, "operator": operator})
        state = ensure.load_state()
        state["cred_verified"] = verified
        ensure.save_state(state)
        # 存好凭据 = 「开启每日自动登录」落地;对齐放后台(与 saveConfig 同款)
        threading.Thread(target=lambda: self._align_saved(saved),
                         daemon=True, name="guigui-align").start()
        return saved

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
        threading.Thread(target=lambda: self._align_saved(saved),
                         daemon=True, name="guigui-align").start()
        return _ok(config.to_bridge(saved))

    # ── 2.8 masterToggle ──────────────────────────

    def masterToggle(self, on=None) -> dict:
        try:
            value = bool(on.get("on")) if isinstance(on, dict) else bool(on)
            cfg = config.load()
            saved = config.save(config.apply_patch(cfg, {"master": value}))
            # 语义重(建/删任务):同步做完再回话
            if value and not _configured(saved):
                misaligned = False   # 首装未完成不建任务(与 _align_saved 同口径)
            else:
                _, misaligned = selfheal.reconcile(saved)
            if misaligned and value:
                notify.task_blocked()
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
