"""bridge api:契约形状(信封/错误码/事件/密码纪律)+ 关键分支。"""

import datetime as dt
import json
import time

import pytest

from guigui.app import api as api_mod
from guigui.app.api import GuiGuiApi
from guigui.core import config, ensure

_REAL_SLEEP = time.sleep   # 模块导入时绑定;Ctx 会全局打桩 time.sleep,_wait_for 需要真睡眠

# 钉死在锚后(07:00 > 06:50):锚点分支否则随真实时刻漂移(清晨跑测试会变道)
FIXED_NOW = dt.datetime(2026, 8, 31, 7, 0, 0)


class FakeWindow:
    def __init__(self):
        self.js = []

    def evaluate_js(self, code):
        self.js.append(code)

    def minimize(self):
        self.js.append("minimize()")

    def destroy(self):
        self.js.append("destroy()")


class Ctx:
    """把 api 依赖的 core 函数全部替换成可编程桩。"""

    def __init__(self, monkeypatch, *, cfg_over=None):
        over = {"uid": "2025000000001"}
        over.update(cfg_over or {})
        config.save(dict(config.DEFAULTS, **over))
        self.window = FakeWindow()
        self.api = GuiGuiApi()
        self.api.attach_window(self.window)
        self.probe_state = {"state": "logged_in", "ssid": "Campus-WiFi", "detail": ""}
        self.probe_seq = None      # 设为 [ {...}, ... ] 时逐次弹出(探测序列)
        self.http_state = {"state": "logged_in", "detail": ""}
        self.http_seq = None       # 同上,http_probe 序列(注销翻转轮询用)
        self.portal_html_text = "<html>no logout config</html>"
        self.logout_url = None     # None = drcom.logout 桩回报「门户无注销配置」
        self.login_seq = [("success", "")]
        self.login_calls = []      # drcom.login 位置参数记录
        self.set_calls = []        # vault.set_password 记录
        self.rekey_calls = []      # vault.rekey 记录
        self.chk_uid = None
        self.scan = [{"ssid": "Campus-WiFi", "signal": "strong"}]
        self.connect_ok = True
        self.reconciled = []
        self.reconcile_ret = (False, False)   # selfheal.reconcile 桩返回 (changed, misaligned)
        self.reconcile_seq = None             # 同 probe_seq:设为 [(changed, misaligned), …] 时逐次弹出
        self.task_blocked_calls = []
        self.task_linger_calls = []
        self.task_current = True   # scheduler.is_task_current 桩返回值

        monkeypatch.setattr(api_mod.detect, "probe",
                            lambda cfg=None: dict(self.probe_seq.pop(0)) if self.probe_seq
                            else dict(self.probe_state))
        monkeypatch.setattr(api_mod.detect, "http_probe",
                            lambda base=None, timeout=5, cfg=None:
                            dict(self.http_seq.pop(0)) if self.http_seq
                            else dict(self.http_state))
        monkeypatch.setattr(api_mod.detect, "portal_html",
                            lambda cfg=None, timeout=5: self.portal_html_text)
        monkeypatch.setattr(api_mod.drcom, "login", self._login_stub)
        monkeypatch.setattr(api_mod.drcom, "login_ex", self._login_ex_stub)
        monkeypatch.setattr(api_mod.drcom, "logout",
                            lambda html, base, timeout=5: self.logout_url)
        monkeypatch.setattr(api_mod.drcom, "chkstatus_uid",
                            lambda base, timeout=5: self.chk_uid)
        monkeypatch.setattr(api_mod.wifictl, "scan_networks", lambda: self.scan)
        monkeypatch.setattr(api_mod.wifictl, "connect",
                            lambda ssid, timeout=90, progress=None: self.connect_ok)
        monkeypatch.setattr(api_mod.vault, "has_password", lambda uid: True)
        monkeypatch.setattr(api_mod.vault, "get_password", lambda uid: "old")
        monkeypatch.setattr(api_mod.vault, "set_password",
                            lambda uid, pw: (self.set_calls.append((uid, pw)) or None))
        monkeypatch.setattr(api_mod.vault, "rekey",
                            lambda old, new, pw:
                            (self.rekey_calls.append((old, new, pw)) or None))
        monkeypatch.setattr(api_mod.selfheal, "reconcile", self._reconcile_stub)
        monkeypatch.setattr(api_mod.notify, "task_blocked",
                            lambda: self.task_blocked_calls.append(1))
        monkeypatch.setattr(api_mod.notify, "task_linger",
                            lambda: self.task_linger_calls.append(1))
        monkeypatch.setattr(api_mod.scheduler, "is_task_current",
                            lambda name, cfg, require_logon=False: self.task_current)
        monkeypatch.setattr(api_mod.time, "sleep", lambda s: None)
        monkeypatch.setattr(api_mod.ensure, "_now", lambda: FIXED_NOW)

    def _login_stub(self, *a, **k):
        """drcom.login 桩:记录位置参数;seq 多于一条时逐次前进,末条重复。"""
        self.login_calls.append(a)
        if len(self.login_seq) > 1:
            return self.login_seq.pop(0)
        return self.login_seq[0]

    def _login_ex_stub(self, base, uid, password, operator=..., timeout=...):
        """drcom.login_ex 桩(QA P1-6):把 login_seq 提升为 LoginResult,默认 waitsec=None。
        seq 元素若 4 元组 → 直接用作 LoginResult;若 2 元组 → 视为 (result, msg) 包装。
        调用记录统一挂到 self.login_calls(沿用旧 test 期望,等同 login 桩语义)。"""
        self.login_calls.append((base, uid, password, operator))
        if len(self.login_seq) > 1:
            entry = self.login_seq.pop(0)
        else:
            entry = self.login_seq[0]
        if len(entry) == 4:
            result, msg, payload, http = entry
        else:
            result, msg = entry
            payload, http = None, 200
        return api_mod.drcom.LoginResult(result, msg, payload, http, None)

    def _reconcile_stub(self, cfg):
        self.reconciled.append(cfg["master"])
        if self.reconcile_seq:
            return tuple(self.reconcile_seq.pop(0))
        return self.reconcile_ret


def parse_emitted(window) -> list[tuple[str, dict]]:
    out = []
    for j in window.js:
        head = "window.guiguiEmit && window.guiguiEmit("
        if not j.startswith(head):
            continue
        args = j[len(head):-1]
        type_, payload = args.split(", ", 1)
        out.append((json.loads(type_), json.loads(payload)))
    return out


@pytest.fixture
def ctx(monkeypatch):
    return Ctx(monkeypatch)


# ── probe / identify ──────────────────────────────────────


def test_probe_envelope_and_shape(ctx):
    out = ctx.api.probe()
    assert out["ok"] is True
    assert out["data"]["net"]["state"] == "logged_in"
    assert out["data"]["net"]["ssid"] == "Campus-WiFi"
    assert out["data"]["configured"] is True


def test_identify_prefers_chkstatus_then_config(ctx):
    ctx.chk_uid = "2025000000001"
    out = ctx.api.identify()
    assert out["data"] == {"uid": "2025000000001", "source": "chkstatus"}
    ctx.chk_uid = None
    out = ctx.api.identify()
    assert out["data"]["source"] == "config"


# ── login:三分支 + 凭据纪律 ───────────────────────────────


def test_login_success_masked_uid_no_password_leak(ctx):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "Campus-WiFi", "detail": ""}
    out = ctx.api.login({})
    assert out["ok"] is True
    assert out["data"] == {"result": "success", "uid": "2025…0001", "attempts": 1,
                           "verified": True}
    assert "password" not in json.dumps(out)          # 契约总则:密码永不下行


def test_login_already(ctx):
    out = ctx.api.login({})
    assert out["data"]["result"] == "already" and out["data"]["attempts"] == 0
    assert out["data"]["verified"] is False           # 已存凭据未经今次真验证


# ── P0-2:「已经在线」核对在线者身份(共享会话不冒领)─────


def test_login_already_checks_online_identity(ctx):
    """线上是别人的学号 → 不报 already,用自己凭据真登(把会话换过来)。"""
    ctx.chk_uid = "2025090270999"                    # 探测 logged_in + 他人学号
    ctx.login_seq = [("success", "")]
    out = ctx.api.login({})
    assert out["data"]["result"] == "success" and out["data"]["attempts"] == 1
    assert ctx.login_calls                           # 真登发生了


def test_login_already_matching_uid_stays_already(ctx):
    ctx.chk_uid = "2025000000001"                    # 线上就是本人
    out = ctx.api.login({})
    assert out["data"]["result"] == "already" and out["data"]["attempts"] == 0
    assert ctx.login_calls == []


def test_login_already_identity_unknown_stays_already(ctx):
    ctx.chk_uid = None                              # chkstatus 不可得 → 不阻塞
    out = ctx.api.login({})
    assert out["data"]["result"] == "already"
    assert ctx.login_calls == []


def test_login_rejected_maps_auth_rejected(ctx):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    ctx.login_seq = [("rejected", "密码错误")]
    out = ctx.api.login({})
    # 不认识的拒绝:原文直显、不带 reason(前端不猜)
    assert out == {"ok": False, "code": "AUTH_REJECTED", "message": "密码错误"}


def test_login_rejected_three_states_carry_reason(ctx):
    """AC-19:三态拒绝文案由后端拼好随 reason 下行,前端直显。"""
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    for msg, reason, expect in (
        ("userid error2", "wrong_password", "密码不对,改一下再试"),
        ("userid error1", "wrong_account", "学号或运营商选错了,核对一下再试"),
        ("bind userid error", "bound",
         "密码是对的,但这个账号被绑在别处/受限 — 去自助服务平台看看绑定"),
    ):
        ctx.login_seq = [(msg and "rejected", msg)]
        out = ctx.api.login({})
        assert out["code"] == "AUTH_REJECTED" and out["reason"] == reason
        assert out["message"] == expect
        ctx.set_calls.clear()


def test_login_unreachable_maps_net_unreachable(ctx):
    ctx.probe_state = {"state": "unreachable", "ssid": None, "detail": "refused"}
    out = ctx.api.login({})
    assert out["ok"] is False and out["code"] == "NET_UNREACHABLE"


def test_login_without_credentials_maps_not_configured(monkeypatch):
    config.save(dict(config.DEFAULTS, uid=""))
    c = Ctx(monkeypatch)
    monkeypatch.setattr(api_mod.vault, "has_password", lambda uid: False)
    out = c.api.login({})
    assert out["code"] == "NOT_CONFIGURED"


def test_login_progress_events_emitted(ctx):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    ctx.api.login({})
    phases = [t for t, _ in parse_emitted(ctx.window)]
    assert "login:progress" in phases


def test_login_success_settles_today_rows(ctx):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    ctx.api.login({})
    state = ensure.load_state()
    assert state["last_settle_date"] and state["last_result"]["outcome"] == "ok"


# ── WiFi ──────────────────────────────────────────────────


def test_scan_wifi_shape(ctx):
    out = ctx.api.scanWifi()
    assert out["data"]["networks"][0]["signal"] == "strong"


def test_scan_wifi_failure_code(ctx, monkeypatch):
    def boom():
        raise api_mod.wifictl.WifiScanError("netsh 拒绝")
    monkeypatch.setattr(api_mod.wifictl, "scan_networks", boom)
    assert ctx.api.scanWifi()["code"] == "WIFI_SCAN_FAILED"


def test_connect_wifi_emits_net_state(ctx):
    out = ctx.api.connectWifi({"ssid": "Campus-5G"})
    assert out["data"] == {"connected": True, "ssid": "Campus-5G"}
    kinds = [t for t, _ in parse_emitted(ctx.window)]
    assert "net:state" in kinds


def test_connect_wifi_timeout(ctx):
    ctx.connect_ok = False
    assert ctx.api.connectWifi({"ssid": "x"})["code"] == "WIFI_CONNECT_TIMEOUT"


# ── 配置 ──────────────────────────────────────────────────


def test_get_config_shape_matches_contract(ctx):
    out = ctx.api.getConfig()["data"]
    assert set(out) == set(config.BRIDGE_FIELDS)
    assert out["trigger_time"] == "07:00" and out["master"] is True


def test_save_config_returns_full_and_aligns(ctx):
    out = ctx.api.saveConfig({"trigger_time": "06:45"})
    assert out["ok"] is True and out["data"]["trigger_time"] == "06:45"
    assert out["data"]["notifications"] is True        # 未提到的字段原样回显
    assert ctx.reconciled == [True]                     # selfheal 已被串起


def test_save_config_invalid_enum(ctx):
    out = ctx.api.saveConfig({"heartbeat_minutes": 7})
    assert out["ok"] is False and out["code"] == "SAVE_FAILED"


def test_master_toggle_off_sync(ctx):
    out = ctx.api.masterToggle(False)
    assert out["data"]["master"] is False
    assert ctx.reconciled == [False]
    assert config.load()["master"] is False


def test_master_toggle_accepts_payload_object(ctx):
    assert ctx.api.masterToggle({"on": True})["data"]["master"] is True


# ── P0-3:关开关删任务失败 → 幽灵任务通知 ──────────────────


def test_master_toggle_off_delete_fail_notifies_linger(ctx):
    """关失败(删任务被拦)→ 弹 task_linger 如实说「明早还会登录」;
    信封照常返回(开关状态已存,由 schedule:changed/taskStatus 暴露在岗)。"""
    ctx.reconcile_ret = (False, True)                  # 删任务失败(misaligned)
    out = ctx.api.masterToggle(False)
    assert out == {"ok": True, "data": {"master": False}}
    assert ctx.task_linger_calls                        # 幽灵任务通知弹出
    assert ctx.task_blocked_calls == []                 # 不是「创建被拦」文案
    events = [p for t, p in parse_emitted(ctx.window) if t == "schedule:changed"]
    assert events and events[-1]["task_ok"] is False    # 在岗状态如实


def test_master_toggle_on_create_fail_still_task_blocked(ctx):
    """对照:开失败仍是创建被拦文案(task_linger 不掺和)。"""
    ctx.reconcile_ret = (False, True)
    assert ctx.api.masterToggle(True)["data"]["master"] is True
    assert ctx.task_blocked_calls and ctx.task_linger_calls == []


# ── 日志 / 昨晚 ───────────────────────────────────────────


def test_logs_days_shape(ctx):
    from guigui.core import logstore
    logstore.append("ok", "网络可达")
    out = ctx.api.logs({})
    day = out["data"]["days"][0]
    assert day["label"] == "今天"
    assert {"ts", "level", "text"} == set(day["entries"][0])


def test_recent_result_none_when_no_record(ctx):
    out = ctx.api.recentResult()
    assert out["data"]["outcome"] == "none"
    assert out["data"]["vault_state"] == "ok"      # 1.6.0:库维可见性恒在场


def test_recent_result_when_labels(ctx):
    import datetime as dt
    ensure.save_state({"last_result": {"date": dt.date.today().isoformat(),
                                       "time": "07:00", "tries": 1, "outcome": "ok"}})
    assert ctx.api.recentResult()["data"]["when"] == "今早"
    ensure.save_state({"last_result": {"date": (dt.date.today() - dt.timedelta(days=1)).isoformat(),
                                       "time": "07:00", "tries": 3, "outcome": "fail"}})
    data = ctx.api.recentResult()["data"]
    assert data["when"] == "昨天" and data["outcome"] == "fail"


def test_recent_result_carries_vault_state(ctx):
    """1.6.0 降级信封:vault_state 四态原样下行(前端只透传不弹横幅)。"""
    from guigui.core import vault
    vault._set_state(vault.STATE_DEGRADED)
    assert ctx.api.recentResult()["data"]["vault_state"] == "degraded"
    vault._set_state(vault.STATE_REBUILDING)
    assert ctx.api.recentResult()["data"]["vault_state"] == "rebuilding"
    vault._set_state(vault.STATE_OK)
    assert ctx.api.recentResult()["data"]["vault_state"] == "ok"


# ── 窗口控制 ──────────────────────────────────────────────


# ── 2.15–2.17 feedback*(1.3.0 真通道)─────────────────────


def test_feedback_send_three_states(ctx, monkeypatch):
    monkeypatch.setattr(api_mod.feedback, "submit",
                        lambda kind, what, contact: api_mod.feedback.Submitted("GG-33"))
    out = ctx.api.feedbackSend({"kind": ["problem"], "what": "没登上"})
    assert out == {"ok": True, "data": {"result": "submitted", "id": "GG-33"}}

    monkeypatch.setattr(api_mod.feedback, "submit",
                        lambda kind, what, contact: api_mod.feedback.SubmittedDegraded("GG-34"))
    out = ctx.api.feedbackSend({"kind": ["problem"], "what": "x"})
    assert out["data"] == {"result": "submitted_degraded", "id": "GG-34"}

    monkeypatch.setattr(api_mod.feedback, "submit",
                        lambda kind, what, contact: api_mod.feedback.Queued("E_NET_OFFLINE", "07:32"))
    out = ctx.api.feedbackSend({"kind": ["problem"], "what": "x"})
    assert out["data"] == {"result": "queued", "next_attempt_at": "07:32"}

    monkeypatch.setattr(api_mod.feedback, "submit",
                        lambda kind, what, contact: api_mod.feedback.Rejected("说说具体情况(必填)"))
    out = ctx.api.feedbackSend({"kind": ["problem"], "what": "x"})
    assert out["ok"] is False and out["code"] == "FB_VALIDATION"


def test_feedback_send_local_validation_no_roundtrip(ctx, monkeypatch):
    def bomb(*a, **k):
        raise AssertionError("校验失败不该碰网络")
    monkeypatch.setattr(api_mod.feedback, "submit", bomb)
    for bad in ({"kind": [], "what": "x"}, {"kind": "problem", "what": "x"},
                {"kind": ["problem"], "what": ""}):
        out = ctx.api.feedbackSend(bad)
        assert out["ok"] is False and out["code"] == "FB_VALIDATION"


def test_feedback_diag_preview_and_masked_uid(ctx, monkeypatch):
    from guigui.core import diagnostics as diag_mod

    monkeypatch.setattr(diag_mod, "collect", lambda kind: {"env": {"os": "x"}})
    monkeypatch.setattr(diag_mod, "render", lambda bundle: "七区预览")
    out = ctx.api.feedbackDiag({"kind": ["problem"]})
    assert out["ok"] is True and out["data"]["text"] == "七区预览"
    assert out["data"]["uid_masked"] == "2025…0001"     # 折叠区打码披露行


def test_feedback_pending_status(ctx, monkeypatch):
    monkeypatch.setattr(api_mod.feedback, "status",
                        lambda: {"pending": 1, "oldest_age_s": 3600})
    out = ctx.api.feedbackPendingStatus()
    assert out == {"ok": True, "data": {"pending": 1, "oldest_age_s": 3600}}


def test_window_controls(ctx):
    ctx.api.winMinimize()
    ctx.api.winClose()
    assert "minimize()" in ctx.window.js and "destroy()" in ctx.window.js


def test_all_failures_are_envelopes_never_exceptions(ctx, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("core down")
    monkeypatch.setattr(api_mod.detect, "probe", boom)
    monkeypatch.setattr(api_mod.detect, "http_probe", boom)
    monkeypatch.setattr(api_mod.config, "load", boom)
    monkeypatch.setattr(api_mod.wifictl, "scan_networks", boom)
    monkeypatch.setattr(api_mod.logstore, "query", boom)
    monkeypatch.setattr(api_mod.ensure, "load_state", boom)
    for call in (ctx.api.probe, ctx.api.identify, ctx.api.getConfig,
                 ctx.api.recentResult, ctx.api.logs):
        out = call()
        assert out["ok"] is False and out["code"] == "INTERNAL"
    # 扫描的任何异常都归 WIFI_SCAN_FAILED(对用户更直接,契约该码即此义)
    assert ctx.api.scanWifi()["code"] == "WIFI_SCAN_FAILED"


# ── 任务对齐守卫:首装未完成不建任务;login 存凭据后首建 ──────


def _wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        _REAL_SLEEP(0.01)
    return predicate()


def test_save_config_unconfigured_skips_task_creation(monkeypatch):
    c = Ctx(monkeypatch, cfg_over={"uid": ""})
    out = c.api.saveConfig({"trigger_time": "06:45"})
    assert out["ok"] is True
    # schedule:changed 无条件推(对齐函数已跑完),此刻 reconcile 应未被调
    assert _wait_for(
        lambda: any(t == "schedule:changed" for t, _ in parse_emitted(c.window)))
    assert c.reconciled == []


def test_save_config_uid_without_password_skips_task_creation(ctx, monkeypatch):
    # 守卫另一半:uid 有、密码没存 → 同样不建任务
    monkeypatch.setattr(api_mod.vault, "has_password", lambda uid: False)
    out = ctx.api.saveConfig({"trigger_time": "06:45"})
    assert out["ok"] is True
    assert _wait_for(
        lambda: any(t == "schedule:changed" for t, _ in parse_emitted(ctx.window)))
    assert ctx.reconciled == []


def test_login_with_password_triggers_alignment(ctx):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    ctx.login_seq = [("success", "")]
    out = ctx.api.login({"sid": "2025000000001", "password": "pw"})
    assert out["ok"] is True
    assert ctx.reconciled == [True]                    # P0-1:同步对齐,返回时已确认


def test_master_toggle_unconfigured_skips_create(monkeypatch):
    c = Ctx(monkeypatch, cfg_over={"uid": ""})
    out = c.api.masterToggle(True)
    assert out["ok"] is True and out["data"]["master"] is True
    assert c.reconciled == []


# ── login:凭据单次读出 + 空值防线 ─────────────────────────


def test_login_reads_vault_once_across_retries(ctx, monkeypatch):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    seq = [("rejected", "x"), ("rejected", "x"), ("success", "")]
    # Ctx 的 login 桩只回第一个元素不前进;这里覆写成逐次弹出,驱动真实重试
    monkeypatch.setattr(api_mod.drcom, "login", lambda *a, **k: seq.pop(0))
    # _attempt_login 走 login_ex(QA P1-6):同步覆写,保证重试循环正确推进
    monkeypatch.setattr(api_mod.drcom, "login_ex",
                        lambda *a, **k: api_mod.drcom.LoginResult(
                            *seq.pop(0), None, 200, None))
    calls = []
    monkeypatch.setattr(api_mod.vault, "get_password",
                        lambda uid: (calls.append(uid) or "pw"))
    out = ctx.api.login({})
    assert out["ok"] is True and out["data"]["attempts"] == 3
    assert len(calls) == 1                    # 旧实现每轮重读(3 次)


def test_login_vault_read_failure_maps_not_configured(ctx, monkeypatch):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    monkeypatch.setattr(api_mod.vault, "get_password", lambda uid: None)
    out = ctx.api.login({})
    assert out["code"] == "NOT_CONFIGURED"    # 旧实现 INTERNAL(quote(None) 炸)


# ── login:提交密码先验证后入库(在线走注销→真登阶梯)────────


def _online_flip(ctx):
    """在线 + 门户有注销配置 + 状态在第 6 次轮询翻转(5×logged_in→not_logged_in)。"""
    ctx.logout_url = "http://10.1.2.3:801/eportal/logout"
    ctx.http_seq = ([{"state": "logged_in", "detail": ""}] * 5
                    + [{"state": "not_logged_in", "detail": ""}])


def test_submit_password_online_garbage_rejected_never_stored(ctx):
    # 在线 + 错密码:注销→真登被拒 → 绝不入库,并用旧密码把网接回来
    _online_flip(ctx)
    ctx.login_seq = [("rejected", "密码错误"), ("success", "")]
    out = ctx.api.login({"sid": "2025000000001", "password": "garbage"})
    assert out["ok"] is False and out["code"] == "AUTH_REJECTED"
    assert "旧密码" in out["message"]
    assert ctx.set_calls == [] and ctx.rekey_calls == []   # 拒绝永不入库
    assert ensure.load_state()["cred_verified"] is False
    # 恢复尝试:旧学号 + 旧密码 + 配置里的运营商
    assert ctx.login_calls[1] == ("http://10.1.2.3", "2025000000001", "old", "校园用户")


def test_submit_password_online_correct_verifies_then_stores(ctx):
    _online_flip(ctx)
    ctx.login_seq = [("success", "")]
    out = ctx.api.login({"sid": "2025000000001", "password": "newpw"})
    assert out["data"] == {"result": "success", "uid": "2025…0001", "attempts": 1,
                           "verified": True, "task_ok": True}
    assert ctx.set_calls == [("2025000000001", "newpw")]
    assert ensure.load_state()["cred_verified"] is True
    assert ctx.reconciled == [True]                    # 同步:返回时已对齐(P0-1)


def test_submit_password_online_no_logout_config_fallback(ctx):
    # 默认桩:门户页无注销配置 → 降级存入,already + 未验证
    out = ctx.api.login({"sid": "2025000000001", "password": "pw"})
    assert out["data"] == {"result": "already", "uid": "2025…0001", "attempts": 0,
                           "verified": False, "task_ok": True}
    assert ctx.set_calls == [("2025000000001", "pw")]
    assert ensure.load_state()["cred_verified"] is False
    assert ctx.reconciled == [True]


def test_submit_password_online_throttle_retries_once(ctx):
    # 实测:刚注销立即重登会被 waitsec 节流 → 等 4s 再试一次
    _online_flip(ctx)
    ctx.login_seq = [("rejected", "error5 waitsec <3"), ("success", "")]
    out = ctx.api.login({"sid": "2025000000001", "password": "pw"})
    assert out["data"]["result"] == "success"
    assert out["data"]["attempts"] == 2 and out["data"]["verified"] is True


def test_submit_password_online_throttle_stuck_restores_network(ctx):
    """场景 4 节流变体:注销→真登一路被节流拒到底 → 网络必须用旧凭据尽力接回
    (不恢复 = 用户网断着+密码没存+还被节流三重伤害),信封如实带恢复说明。
    桩 waitsec 恒 None → 信封按封顶 30s 如实展示。"""
    _online_flip(ctx)
    ctx.login_seq = [("rejected", "error5 waitsec <3"),   # 验证单发被节流
                     ("rejected", "error5 waitsec <3"),   # 等 waitsec 后重试仍节流
                     ("success", "")]                     # 旧凭据恢复接回成功
    out = ctx.api.login({"sid": "2025000000001", "password": "garbage"})
    assert out == {"ok": False, "code": "AUTH_REJECTED", "reason": "throttled",
                   "message": "校园网侧让等 30 秒再试;已用旧密码把网接回来了,改对再点一次"}
    assert ctx.set_calls == []                                # 节流 ≠ 密码错,不入库
    assert ctx.login_calls[-1] == ("http://10.1.2.3", "2025000000001", "old", "校园用户")


def test_submit_password_offline_wrong_never_stored(ctx):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    ctx.login_seq = [("rejected", "密码错误")] * 3
    out = ctx.api.login({"sid": "2025000000001", "password": "bad"})
    assert out == {"ok": False, "code": "AUTH_REJECTED", "message": "密码错误"}
    assert ctx.set_calls == [] and ctx.rekey_calls == []


def test_submit_password_before_open_stores_unverified(ctx, monkeypatch):
    """4.1.2:06:50 前提交被拒 → 不判密码错误,存未验证,明早首试真验证。"""
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    ctx.login_seq = [("rejected", "userid error2")]
    monkeypatch.setattr(api_mod.ensure, "_now",
                        lambda: dt.datetime(2026, 8, 31, 6, 30))
    out = ctx.api.login({"sid": "2025000000001", "password": "pw"})
    assert out["ok"] is True
    assert out["data"] == {"result": "stored", "uid": "2025…0001", "attempts": 1,
                           "verified": False, "reason": "before_open", "task_ok": True}
    assert ctx.set_calls == [("2025000000001", "pw")]     # 存了
    assert ensure.load_state()["cred_verified"] is False  # 未验证
    assert ctx.login_calls and len(ctx.login_calls) == 1  # 锚前单发收手,不重试


def test_submit_password_offline_correct_stores_verified(ctx):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    ctx.login_seq = [("success", "")]
    out = ctx.api.login({"sid": "2025000000001", "password": "pw"})
    assert out["data"]["verified"] is True
    assert ctx.set_calls == [("2025000000001", "pw")]
    assert ensure.load_state()["cred_verified"] is True


def test_submit_password_operator_passthrough_and_invalid_fallback(ctx):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    ctx.api.login({"sid": "2025000000001", "password": "pw", "operator": "校园电信"})
    assert ctx.login_calls[0][3] == "校园电信"          # 第 4 位参数透传
    ctx.login_calls.clear()
    config.save(dict(config.DEFAULTS, uid="2025000000001"))   # 抹掉上轮存入的运营商
    ctx.api.login({"sid": "2025000000001", "password": "pw", "operator": "bogus"})
    assert ctx.login_calls[0][3] == "校园用户"          # 枚举外回退配置值


def test_submit_password_restore_fail_message(ctx):
    _online_flip(ctx)
    ctx.login_seq = [("rejected", "密码错误"), ("rejected", "再拒")]
    out = ctx.api.login({"sid": "2025000000001", "password": "garbage"})
    assert out["code"] == "AUTH_REJECTED"
    assert "网先断着" in out["message"]          # 4.1.2:首装/恢复失败时的如实说法
    assert ctx.set_calls == []


def test_ladder_discloses_other_online_uid(ctx):
    """4.1.2:线上是别人的学号 → 注销前推 logging_out 事件如实注明。"""
    _online_flip(ctx)
    ctx.chk_uid = "2025090270999"
    ctx.login_seq = [("success", "")]
    ctx.api.login({"sid": "2025000000001", "password": "pw"})
    events = [(t, p) for t, p in parse_emitted(ctx.window)
              if t == "login:progress" and p.get("phase") == "logging_out"]
    assert events and events[0][1]["online_uid"] == "2025…0999"


# ── 任务在岗(AC-17,1.2.0)────────────────────────────────


def test_task_status_ok_and_blocked(ctx):
    assert ctx.api.taskStatus()["data"] == {"ok": True}
    ctx.task_current = False
    assert ctx.api.taskStatus()["data"]["ok"] is False


def test_task_status_master_off_is_not_blocked(ctx):
    config.save(dict(config.DEFAULTS, uid="2025000000001", master=False))
    data = ctx.api.taskStatus()["data"]
    assert data["ok"] is True and data.get("note") == "off"


def test_rebuild_task_runs_reconcile_and_reports(ctx):
    out = ctx.api.rebuildTask()
    assert out["ok"] is True and out["data"]["ok"] is True
    assert ctx.reconciled == [True]                     # 用户点击才重建
    kinds = [t for t, p in parse_emitted(ctx.window)
             if t == "schedule:changed" and "task_ok" in p]
    assert kinds                                          # 事件带 task_ok


def test_rebuild_task_unconfigured_refuses(ctx, monkeypatch):
    c = Ctx(monkeypatch, cfg_over={"uid": ""})
    monkeypatch.setattr(api_mod.vault, "has_password", lambda uid: False)
    assert c.api.rebuildTask()["code"] == "NOT_CONFIGURED"


def test_rebuild_task_retries_until_aligned(ctx):
    """P1-15 重试环(白板 intercept2「重建直到正常」):首轮被拦、第二轮
    建成 → 补试一轮即达成,信封 ok=true。"""
    ctx.reconcile_seq = [(False, True), (True, False)]
    out = ctx.api.rebuildTask()
    assert out["ok"] is True and out["data"]["ok"] is True
    assert out["data"]["changed"] is True
    assert ctx.reconciled == [True, True]        # 恰好两轮
    assert ctx.task_blocked_calls == []          # 达成不弹拦截通知


def test_rebuild_task_retry_exhausts_at_three(ctx):
    """持续被拦 → 恰 3 轮收线(ok=false 即「3 败」)+ 拦截指引通知。"""
    ctx.reconcile_ret = (False, True)
    out = ctx.api.rebuildTask()
    assert out["ok"] is True and out["data"]["ok"] is False
    assert ctx.reconciled == [True, True, True]  # 上限 3 轮,不多烧
    assert ctx.task_blocked_calls == [1]
    kinds = [t for t, p in parse_emitted(ctx.window)
             if t == "schedule:changed" and p.get("task_ok") is False]
    assert kinds                                       # 事件如实带 task_ok=false


def test_recent_result_carries_verified(ctx):
    ensure.save_state({"cred_verified": True})
    assert ctx.api.recentResult()["data"]["verified"] is True
    ensure.save_state({"cred_verified": False})
    assert ctx.api.recentResult()["data"]["verified"] is False


def test_submit_password_logout_ineffective_falls_back(ctx):
    # 注销发起但 6 次轮询始终 logged_in → 判定注销无效,降级存入
    ctx.logout_url = "http://10.1.2.3:801/eportal/logout"
    ctx.http_seq = [{"state": "logged_in", "detail": ""}] * 6
    out = ctx.api.login({"sid": "2025000000001", "password": "pw"})
    assert out["data"] == {"result": "already", "uid": "2025…0001", "attempts": 0,
                           "verified": False, "task_ok": True}
    assert ctx.set_calls == [("2025000000001", "pw")]
    assert ctx.login_calls == []                       # 没走到真登验证


# ── P0-1:开启流程同步确认任务计划(承诺-验证对齐)─────────


def test_submit_password_task_ok_true_when_created(ctx):
    """提交密码成功 → 信封如实带 task_ok:true(任务同步建好,不等后台)。"""
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    ctx.login_seq = [("success", "")]
    out = ctx.api.login({"sid": "2025000000001", "password": "pw"})
    assert out["ok"] is True and out["data"]["task_ok"] is True
    assert ctx.reconciled == [True]                    # 返回前已同步对齐完
    assert ctx.task_blocked_calls == []


def test_submit_password_task_blocked_reports_honestly(ctx):
    """建任务被安全软件拦 → 密码验证仍算成功,但信封 task_ok:false、
    同步弹被拦指引、schedule:changed 如实 — 成功页不许空头承诺。"""
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    ctx.login_seq = [("success", "")]
    ctx.reconcile_ret = (False, True)                  # 建任务被拦(misaligned)
    out = ctx.api.login({"sid": "2025000000001", "password": "pw"})
    assert out["ok"] is True                           # 密码验证本身成功
    assert out["data"]["result"] == "success"
    assert out["data"]["task_ok"] is False
    assert ctx.task_blocked_calls                       # 同步弹指引通知
    events = [p for t, p in parse_emitted(ctx.window) if t == "schedule:changed"]
    assert events and events[-1]["task_ok"] is False


# ── 2.18 diagnose(1.5.0 验证器)──────────────────────────


def _diag_events(ctx):
    return [p for t, p in parse_emitted(ctx.window) if t == "diag:progress"]


def test_diagnose_all_ok_logged_in_identity_match(ctx):
    ctx.chk_uid = "2025000000001"          # 线上学号 = 配置学号 → 只读核对通过
    out = ctx.api.diagnose()
    assert out["ok"] is True
    d = out["data"]
    assert [s["key"] for s in d["steps"]] == [
        "network", "server", "credential", "task", "app"]
    assert [s["state"] for s in d["steps"]] == ["ok"] * 5
    assert d["steps"][0]["detail"] == "已连上 Campus-WiFi"
    assert d["steps"][2]["detail"] == "在线,学号一致 ✓"
    assert d["steps"][3]["detail"] == "2 项任务都在岗"   # 默认配置:日历+开机两拍
    assert d["exit"] == "ok" and d["verdict"] == "一切正常,网是通的"
    # 逐步推进事件:每步 running → 终态,顺序对齐(计划 2.2)
    ev = _diag_events(ctx)
    assert [(e["step"], e["state"]) for e in ev] == [
        (1, "running"), (1, "ok"), (2, "running"), (2, "ok"),
        (3, "running"), (3, "ok"), (4, "running"), (4, "ok"),
        (5, "running"), (5, "ok")]


def test_diagnose_net_down_skips_credential_but_checks_task(ctx):
    ctx.probe_state = {"state": "unreachable", "ssid": "iphone17 pro max",
                       "detail": "refused"}
    out = ctx.api.diagnose()
    d = out["data"]
    assert d["steps"][0]["state"] == "ok"                 # 链路在(热点)
    assert d["steps"][0]["detail"] == "已连上 iphone17 pro max"
    assert d["steps"][1]["state"] == "fail"
    assert d["steps"][1]["detail"] == "10.1.2.3 连不上"
    assert d["steps"][2]["state"] == "skip"               # 凭据没法验,不装结论
    assert d["steps"][3]["state"] == "ok"                 # 任务/程序照查(只读)
    assert d["exit"] == "net_down"


def test_diagnose_wrong_password_exit_login_with_reason(ctx):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "Campus-WiFi", "detail": ""}
    ctx.login_seq = [("rejected", "userid error2")]
    out = ctx.api.diagnose()
    s3 = out["data"]["steps"][2]
    assert s3["state"] == "fail"
    assert s3["detail"] == "密码不对,改一下再试"          # rejection_text 单一来源
    assert s3["reason"] == "wrong_password"               # 登录页警告块预填用
    assert out["data"]["exit"] == "login"


def test_diagnose_step5_surfaces_vault_degraded(ctx):
    """1.6.0:库链可见性走 diagnose 第 5 步(拍板 #1,不新增 inspect)。"""
    from guigui.core import vault
    ctx.chk_uid = "2025000000001"
    vault._set_state(vault.STATE_DEGRADED)
    out = ctx.api.diagnose()
    s5 = out["data"]["steps"][4]
    assert s5["state"] == "fail"
    assert "凭据库降级中(备份接管,不影响自动登录)" in s5["detail"]
    assert out["data"]["exit"] == "app_fault"
    vault._set_state(vault.STATE_FAILED)
    out2 = ctx.api.diagnose()
    assert "凭据库与备份都不可用" in out2["data"]["steps"][4]["detail"]


def test_diagnose_real_login_success_emits_net_state(ctx):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "Campus-WiFi", "detail": ""}
    ctx.login_seq = [("success", "")]
    out = ctx.api.diagnose()
    assert out["data"]["steps"][2]["detail"] == "密码对,顺手把网登上了 ✓"
    types = [t for t, _p in parse_emitted(ctx.window)]
    assert "net:state" in types                            # 网态真翻了,各视图跟真


def test_diagnose_throttled_is_skip_not_fail(ctx, monkeypatch):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "Campus-WiFi", "detail": ""}
    ctx.login_seq = [("rejected", "登录太频繁")]
    monkeypatch.setattr(api_mod.drcom, "parse_waitsec", lambda *a, **k: 10)
    out = ctx.api.diagnose()
    s3 = out["data"]["steps"][2]
    assert s3["state"] == "skip" and "节流" in s3["detail"]
    assert out["data"]["exit"] == "ok"                    # 节流不是密码错,不跳登录页


def test_diagnose_task_blocked_from_missing_beats(ctx):
    ctx.chk_uid = "2025000000001"
    ctx.task_current = False
    out = ctx.api.diagnose()
    s4 = out["data"]["steps"][3]
    assert s4["state"] == "fail"
    assert s4["detail"] == "任务不在岗,多半被安全软件拦了"  # 如实「多半」,不装确定
    assert out["data"]["exit"] == "task_blocked"


def test_diagnose_master_off_task_step_skips(ctx):
    ctx.chk_uid = "2025000000001"
    config.save(config.apply_patch(config.load(), {"master": False}))
    out = ctx.api.diagnose()
    s4 = out["data"]["steps"][3]
    assert s4["state"] == "skip" and "总开关" in s4["detail"]


def test_diagnose_app_fault_on_recent_crash(ctx, monkeypatch):
    ctx.chk_uid = "2025000000001"
    monkeypatch.setattr(api_mod.crashlog, "recent", lambda n=3: [{"ts": "x"}])
    out = ctx.api.diagnose()
    s5 = out["data"]["steps"][4]
    assert s5["state"] == "fail" and "崩溃记录" in s5["detail"]
    assert out["data"]["exit"] == "app_fault"


def test_diagnose_priority_net_down_beats_task_blocked(ctx):
    ctx.probe_state = {"state": "unreachable", "ssid": None, "detail": ""}
    ctx.task_current = False
    out = ctx.api.diagnose()
    assert out["data"]["exit"] == "net_down"              # 先有网,才谈得上自动化


def test_diagnose_online_other_uid_exit_login(ctx):
    ctx.chk_uid = "2025000000002"                        # 线上是室友的号
    out = ctx.api.diagnose()
    s3 = out["data"]["steps"][2]
    assert s3["state"] == "fail" and "别人的学号" in s3["detail"]
    assert out["data"]["exit"] == "login"


def test_diagnose_no_stored_password(ctx):
    monkeypatch_vault = pytest.MonkeyPatch()
    monkeypatch_vault.setattr(api_mod.vault, "has_password", lambda uid: False)
    try:
        ctx.chk_uid = None
        ctx.probe_state = {"state": "not_logged_in", "ssid": "Campus-WiFi", "detail": ""}
        out = ctx.api.diagnose()
        s3 = out["data"]["steps"][2]
        assert s3["state"] == "fail" and "还没存密码" in s3["detail"]
        assert out["data"]["exit"] == "login"
    finally:
        monkeypatch_vault.undo()
