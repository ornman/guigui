"""bridge api:契约形状(信封/错误码/事件/密码纪律)+ 关键分支。"""

import json

import pytest

from guigui.app import api as api_mod
from guigui.app.api import GuiGuiApi
from guigui.core import config, ensure


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
        self.http_state = {"state": "logged_in", "detail": ""}
        self.login_seq = [("success", "")]
        self.chk_uid = None
        self.scan = [{"ssid": "Campus-WiFi", "signal": "strong"}]
        self.connect_ok = True
        self.reconciled = []

        monkeypatch.setattr(api_mod.detect, "probe", lambda cfg=None: dict(self.probe_state))
        monkeypatch.setattr(api_mod.detect, "http_probe",
                            lambda base=None, timeout=5, cfg=None: dict(self.http_state))
        monkeypatch.setattr(api_mod.drcom, "login",
                            lambda *a, **k: self.login_seq[0])
        monkeypatch.setattr(api_mod.drcom, "chkstatus_uid",
                            lambda base, timeout=5: self.chk_uid)
        monkeypatch.setattr(api_mod.wifictl, "scan_networks", lambda: self.scan)
        monkeypatch.setattr(api_mod.wifictl, "connect",
                            lambda ssid, timeout=90, progress=None: self.connect_ok)
        monkeypatch.setattr(api_mod.vault, "has_password", lambda uid: True)
        monkeypatch.setattr(api_mod.vault, "get_password", lambda uid: "pw")
        monkeypatch.setattr(api_mod.vault, "set_password",
                            lambda uid, pw: self._raise_nothing())
        monkeypatch.setattr(api_mod.vault, "rekey",
                            lambda old, new, pw: self._raise_nothing())
        monkeypatch.setattr(api_mod.selfheal, "reconcile",
                            lambda cfg: self.reconciled.append(cfg["master"]))
        monkeypatch.setattr(api_mod.time, "sleep", lambda s: None)


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
    assert out["data"] == {"result": "success", "uid": "2025…0001", "attempts": 1}
    assert "password" not in json.dumps(out)          # 契约总则:密码永不下行


def test_login_already(ctx):
    out = ctx.api.login({})
    assert out["data"]["result"] == "already" and out["data"]["attempts"] == 0


def test_login_rejected_maps_auth_rejected(ctx):
    ctx.probe_state = {"state": "not_logged_in", "ssid": "x", "detail": ""}
    ctx.login_seq = [("rejected", "密码错误")]
    out = ctx.api.login({})
    assert out == {"ok": False, "code": "AUTH_REJECTED",
                   "message": "密码可能改过了,改下面的密码再点一次"}


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


# ── 日志 / 昨晚 ───────────────────────────────────────────


def test_logs_days_shape(ctx):
    from guigui.core import logstore
    logstore.append("ok", "网络可达")
    out = ctx.api.logs({})
    day = out["data"]["days"][0]
    assert day["label"] == "今天"
    assert {"ts", "level", "text"} == set(day["entries"][0])


def test_recent_result_none_when_no_record(ctx):
    assert ctx.api.recentResult()["data"]["outcome"] == "none"


def test_recent_result_when_labels(ctx):
    import datetime as dt
    ensure.save_state({"last_result": {"date": dt.date.today().isoformat(),
                                       "time": "07:00", "tries": 1, "outcome": "ok"}})
    assert ctx.api.recentResult()["data"]["when"] == "今早"
    ensure.save_state({"last_result": {"date": (dt.date.today() - dt.timedelta(days=1)).isoformat(),
                                       "time": "07:00", "tries": 3, "outcome": "fail"}})
    data = ctx.api.recentResult()["data"]
    assert data["when"] == "昨天" and data["outcome"] == "fail"


# ── 窗口控制 ──────────────────────────────────────────────


def test_feedback_returns_masked_text(ctx, monkeypatch):
    from guigui.core import diagnostics as diag_mod

    def fake_build():
        return "桂桂 v2.0.0 诊断信息\n学号:2025…0001"
    monkeypatch.setattr(diag_mod, "build_text", fake_build)
    out = ctx.api.feedback()
    assert out["ok"] is True and "诊断信息" in out["data"]["text"]


def test_feedback_internal_on_failure(ctx, monkeypatch):
    from guigui.core import diagnostics as diag_mod

    def boom():
        raise RuntimeError("diag down")
    monkeypatch.setattr(api_mod.diagnostics, "build_text", boom)
    out = ctx.api.feedback()
    assert out["ok"] is False and out["code"] == "INTERNAL"


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
