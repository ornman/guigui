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

from guigui.core import config, detect, diagnostics, drcom, ensure, feedback, logstore, notify, scheduler, selfheal, vault, wifictl
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
FB_VALIDATION = "FB_VALIDATION"
INTERNAL = "INTERNAL"

# 学校自助服务平台(改密码 / 查流量 / 解绑设备)— openSelfService 交默认浏览器打开
SELF_SERVICE_URL = "https://bcs.guat.edu.cn/Cas/Login?appid=71999680"


def _configured(cfg: dict) -> bool:
    """首装完成判定:学号已存且凭据管理器里有密码(契约 §4 单行道终点)。"""
    return bool(cfg.get("uid")) and vault.has_password(cfg["uid"])


def _ok(data: dict) -> dict:
    return {"ok": True, "data": data}


def _err(code: str, message: str, reason: str | None = None) -> dict:
    """reason ∈ wrong_password|wrong_account|bound|before_open(契约 1.2.0,
    前端据此渲染拒绝三态文案;None=不分类,前端直显 message)。"""
    out = {"ok": False, "code": code, "message": message}
    if reason:
        out["reason"] = reason
    return out


class GuiGuiApi:
    """pywebview js_api 对象;gui.py 创建窗口时注入并 attach_window。"""

    def __init__(self):
        self._window = None

    def attach_window(self, window) -> None:
        self._window = window

    def _reconcile_and_report(self, saved: dict) -> bool:
        """对齐任务计划并回报在岗(masterToggle / login 收尾 / saveConfig 共用)。

        守卫:master 开但首装未完成(uid 空或密码未存)时不建任务 —— 任务属于
        「开启每日自动登录」那一步,由 login 存完凭据后首次对齐;
        master 关 → 删任务不受守卫影响。
        「已开启每日自动登录」是成功页的直接承诺,对齐同步做完才回话
        (PS 调用秒级):被拦时立刻弹 task_blocked,信封带 task_ok 让成功页如实说。
        返回任务是否在岗。"""
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
        # task_ok:任务在岗状态(契约 1.2.0;设置页「定时任务」行的数据源)
        self._emit("schedule:changed",
                   {"master": saved["master"], "trigger_time": saved["trigger_time"],
                    "task_ok": not misaligned})
        return not misaligned

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
            # 全屋共享会话:在线的可能是室友账号 — 核对线上学号,
            # 别人的成功不冒领(chkstatus 不可得则不阻塞,维持 already)
            online = drcom.chkstatus_uid(cfg["url"])
            if not online or online == uid:
                ensure.settle_from_gui(cfg, uid, 0)
                return _ok({"result": "already", "uid": drcom.mask_uid(uid),
                            "attempts": 0,
                            "verified": bool(ensure.load_state().get("cred_verified"))})
            log.info("api: 线上是他人学号(%s),不报 already,改走真登录",
                     drcom.mask_uid(online))
        if net["state"] in (detect.UNREACHABLE, detect.WAITING):
            return _err(NET_UNREACHABLE, "现在够不着校园网")

        result, msg, attempts = self._attempt_login(
            cfg, uid, stored, cfg.get("operator", drcom.DEFAULT_OPERATOR))
        if result == drcom.SUCCESS:
            ensure.settle_from_gui(cfg, uid, attempts)
            return _ok({"result": "success", "uid": drcom.mask_uid(uid),
                        "attempts": attempts, "verified": True})
        if result == drcom.REJECTED:
            if ensure.before_anchor():
                # 锚前被拒不判密码错误(4.1.2):明早开门后首拍真验证
                return _err(AUTH_REJECTED,
                            "还没到开门时间(06:50),明早开门后第一次自动登录会真验证",
                            reason="before_open")
            kind = drcom.classify_rejection(msg)
            return _err(AUTH_REJECTED,
                        drcom.rejection_text(kind, msg or "密码可能改过了,改下面的密码再点一次"),
                        reason=kind)
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
        if not (isinstance(operator, str) and (
                operator in drcom.OPERATOR_TABLE or operator in drcom.OPERATOR_ALIASES)):
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
                saved, task_ok = self._store_credential(
                    cfg, uid, operator, password, verified=True)
                if saved is None:
                    return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
                ensure.settle_from_gui(saved, uid, attempts)
                return _ok({"result": "success", "uid": drcom.mask_uid(uid),
                            "attempts": attempts, "verified": True,
                            "task_ok": task_ok})
            if result == drcom.REJECTED:
                if ensure.before_anchor():
                    # 4.1.2:开门前被拒不判「密码错误」— 密码先存着(未验证),明早首试真验证
                    saved, task_ok = self._store_credential(
                        cfg, uid, operator, password, verified=False)
                    if saved is None:
                        return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
                    return _ok({"result": "stored", "uid": drcom.mask_uid(uid),
                                "attempts": attempts, "verified": False,
                                "reason": "before_open", "task_ok": task_ok})
                kind = drcom.classify_rejection(msg)
                return _err(AUTH_REJECTED,
                            drcom.rejection_text(kind, msg or "密码被服务器拒绝了,核对一下再试"),
                            reason=kind)
            if result == drcom.UNREACHABLE:
                # 循环中途断网:密码没被否认,存了给明早一次机会
                saved, _ = self._store_credential(
                    cfg, uid, operator, password, verified=False)
                if saved is None:
                    return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
                return _err(NET_UNREACHABLE, "现在够不着校园网")
            return _err(INTERNAL, msg or "认证服务器返回了不认识的格式")

        if net["state"] == detect.LOGGED_IN:
            # 4.1.2:线上是别人的学号 → 提交等待行如实注明「验证时会先注销它」
            online = drcom.chkstatus_uid(cfg["url"])
            progress = {"phase": "logging_out"}
            if online and online != uid:
                progress["online_uid"] = drcom.mask_uid(online)
            self._emit("login:progress", progress)
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
                    saved, task_ok = self._store_credential(
                        cfg, uid, operator, password, verified=True)
                    if saved is None:
                        return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
                    ensure.settle_from_gui(saved, uid, tries)
                    return _ok({"result": "success", "uid": drcom.mask_uid(uid),
                                "attempts": tries, "verified": True,
                                "task_ok": task_ok})
                if result == drcom.REJECTED:
                    if ensure.before_anchor():
                        # 跨过锚点的边缘:注销后已过 06:50 依旧被拒按锚前口径(存未验证)
                        self._restore_network(cfg, old_uid, uid, old_pw)
                        saved, task_ok = self._store_credential(
                            cfg, uid, operator, password, verified=False)
                        if saved is None:
                            return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
                        return _ok({"result": "stored", "uid": drcom.mask_uid(uid),
                                    "attempts": tries, "verified": False,
                                    "reason": "before_open", "task_ok": task_ok})
                    kind = drcom.classify_rejection(msg)
                    restored = self._restore_network(cfg, old_uid, uid, old_pw)
                    base = drcom.rejection_text(kind, msg or "密码被服务器拒绝了")
                    return _err(AUTH_REJECTED, base + self._restore_suffix(restored),
                                reason=kind)
                if result == drcom.UNREACHABLE:
                    self._restore_network(cfg, old_uid, uid, old_pw)  # 尽力恢复,不看成败
                    saved, _ = self._store_credential(
                        cfg, uid, operator, password, verified=False)
                    if saved is None:
                        return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
                    return _err(NET_UNREACHABLE,
                                "验证做到一半网络够不着了,密码先存着,明早首试见真章")
                self._restore_network(cfg, old_uid, uid, old_pw)
                return _err(INTERNAL, msg or "认证服务器返回了不认识的格式")
            # 门户无注销配置 / 注销未见翻转:降级存入,verified=false
            saved, task_ok = self._store_credential(
                cfg, uid, operator, password, verified=False)
            if saved is None:
                return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
            return _ok({"result": "already", "uid": drcom.mask_uid(uid),
                        "attempts": 0, "verified": False, "task_ok": task_ok})

        # unreachable / waiting:密码没被否认,存了给明早一次机会
        saved, _ = self._store_credential(
            cfg, uid, operator, password, verified=False)
        if saved is None:
            return _err(INTERNAL, "系统凭据管理器不可用,存不下密码")
        return _err(NET_UNREACHABLE, "现在够不着校园网")

    def _attempt_login(self, cfg: dict, uid: str, password: str,
                       operator: str) -> tuple[str, str, int]:
        """重试节奏按配置(retries × interval),期间推进度事件。

        锚前(06:50 前)被拒直接收手 — 门没开,重试无意义(绝不暴力尝试)。"""
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
            if result == drcom.REJECTED and ensure.before_anchor():
                break
            if i < retries - 1:
                self._emit("login:progress",
                           {"phase": "retrying", "attempt": attempts, "attempts": retries})
                time.sleep(interval)
        return result, msg, attempts

    @staticmethod
    def _restore_suffix(restored: bool) -> str:
        """拒绝后的网络恢复说明(4.1.2:首装没旧密码/恢复失败时如实说网先断着)。"""
        if restored:
            return ";已用旧密码把网接回来了,改对再点一次"
        return ";网先断着,输对马上通"

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
                          password: str, *, verified: bool) -> tuple[dict | None, bool]:
        """入库:vault(换学号清旧条目)→ config(uid/operator)→ cred_verified
        → 同步对齐任务计划(承诺前确认,PS 调用秒级)。
        返回 (saved, task_ok);VaultError → (None, False),调用方回 INTERNAL 信封。"""
        try:
            if cfg.get("uid") and cfg["uid"] != uid:
                vault.rekey(cfg["uid"], uid, password)   # 换学号:清旧凭据
            else:
                vault.set_password(uid, password)
        except VaultError as e:
            log.warning("api.login: 凭据存储失败: %s", e)
            return None, False
        saved = config.save({**cfg, "uid": uid, "operator": operator})
        state = ensure.load_state()
        state["cred_verified"] = verified
        ensure.save_state(state)
        # 存好凭据 = 「开启每日自动登录」落地;同步确认任务在岗,信封如实带 task_ok
        task_ok = self._reconcile_and_report(saved)
        return saved, task_ok

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
        threading.Thread(target=lambda: self._reconcile_and_report(saved),
                         daemon=True, name="guigui-align").start()
        return _ok(config.to_bridge(saved))

    # ── 2.8 masterToggle ──────────────────────────

    def masterToggle(self, on=None) -> dict:
        try:
            value = bool(on.get("on")) if isinstance(on, dict) else bool(on)
            cfg = config.load()
            saved = config.save(config.apply_patch(cfg, {"master": value}))
            # 语义重(建/删任务):同步做完再回话(对齐+被拦通知+事件在共用函数里)
            self._reconcile_and_report(saved)
            return _ok({"master": saved["master"]})
        except Exception:
            log.exception("api.masterToggle")
            return _err(SAVE_FAILED, "开关没切过去,再试一次")

    # ── 2.13 taskStatus / rebuildTask(1.2.0 新增)──

    def taskStatus(self) -> dict:
        """定时任务在岗状态(AC-17,设置页「定时任务」行数据源)。"""
        try:
            cfg = config.load()
            if not cfg.get("master", True):
                # 总开关关着:任务本就不该存在,不是被拦
                return _ok({"ok": True, "note": "off"})
            ok_flag = scheduler.is_task_current(
                scheduler.TASK_MAIN, cfg, require_logon=bool(cfg.get("boot_login")))
            if ok_flag and cfg.get("patrol_enabled"):
                ok_flag = scheduler.is_task_current(scheduler.TASK_PATROL, cfg)
            return _ok({"ok": ok_flag})
        except Exception:
            log.exception("api.taskStatus")
            return _err(INTERNAL, "任务状态查不出来,再试一次")

    def rebuildTask(self) -> dict:
        """一键重建定时任务 — 仅用户点击触发(8.5.2),绝不后台静默重建。"""
        try:
            cfg = config.load()
            if cfg.get("master", True) and not _configured(cfg):
                return _err(NOT_CONFIGURED, "还没完成首次开启,先去开启每日自动登录")
            changed, misaligned = selfheal.reconcile(cfg)
            if misaligned:
                notify.task_blocked()
            self._emit("schedule:changed",
                       {"master": cfg["master"], "trigger_time": cfg["trigger_time"],
                        "task_ok": not misaligned})
            return _ok({"ok": not misaligned, "changed": changed})
        except Exception:
            log.exception("api.rebuildTask")
            return _err(INTERNAL, "重建没成功,再试一次")

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
            state = ensure.load_state()
            lr = state.get("last_result")
            if not lr:
                return _ok({"when": None, "time": None, "tries": 0,
                            "outcome": "none", "verified": bool(state.get("cred_verified"))})
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
                        "tries": lr.get("tries", 0), "outcome": lr.get("outcome", "none"),
                        "verified": bool(state.get("cred_verified"))})
        except Exception:
            log.exception("api.recentResult")
            return _err(INTERNAL, "昨晚的记录读不出来")

    # ── 2.12 feedback(1.1.0;1.3.0 起废弃,保留一个版本周期)──

    def feedback(self) -> dict:
        """复印机时代的复制文本;实现由 render(collect()) 派生,形状不变。"""
        try:
            return _ok({"text": diagnostics.render(diagnostics.collect(["problem"]))})
        except Exception:
            log.exception("api.feedback")
            return _err(INTERNAL, "诊断信息没生成出来,再试一次")

    # ── 2.15–2.17 feedback*(1.3.0 新增:真通道)──

    def feedbackSend(self, payload=None) -> dict:
        """发送反馈(契约 §2.15):三态 result;FB_VALIDATION 表单内提示不入队。"""
        payload = payload if isinstance(payload, dict) else {}
        kind = payload.get("kind")
        what = str(payload.get("what") or "")
        contact = str(payload.get("contact") or "")
        invalid = feedback.validate_input(kind, what, contact)
        if invalid:
            return _err(FB_VALIDATION, invalid)
        try:
            out = feedback.submit(kind, what, contact)
        except Exception:
            log.exception("api.feedbackSend")
            return _err(INTERNAL, "反馈没发出去,再试一次")
        if isinstance(out, feedback.Submitted):
            return _ok({"result": "submitted", "id": out.id})
        if isinstance(out, feedback.SubmittedDegraded):
            return _ok({"result": "submitted_degraded", "id": out.id})
        if isinstance(out, feedback.Queued):
            return _ok({"result": "queued", "next_attempt_at": out.next_attempt_at})
        return _err(FB_VALIDATION, out.detail)

    def feedbackDiag(self, payload=None) -> dict:
        """诊断预览(契约 §2.16):与发送渲染自同一份 bundle;uid 打码披露。"""
        payload = payload if isinstance(payload, dict) else {}
        kind = payload.get("kind") if isinstance(payload.get("kind"), list) else ["problem"]
        try:
            bundle = diagnostics.collect(kind)
            uid = config.load().get("uid") or ""
            return _ok({"text": diagnostics.render(bundle),
                        "uid_masked": drcom.mask_uid(uid) if uid else None})
        except Exception:
            log.exception("api.feedbackDiag")
            return _err(INTERNAL, "诊断信息没生成出来,再试一次")

    def feedbackPendingStatus(self) -> dict:
        """离线队列状态(契约 §2.17);补发后端自驱,前端零操作。"""
        try:
            return _ok(feedback.status())
        except Exception:
            log.exception("api.feedbackPendingStatus")
            return _err(INTERNAL, "队列状态读不出来")

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

    def openSelfService(self) -> dict:
        """自助服务平台交系统默认浏览器;桂桂本体内不开网页(GUI 低频,感知面仅通知)。"""
        import webbrowser

        try:
            webbrowser.open(SELF_SERVICE_URL)
        except Exception:
            log.exception("api.openSelfService")
            return _err(INTERNAL, "浏览器没能打开,再试一次")
        return _ok({})
