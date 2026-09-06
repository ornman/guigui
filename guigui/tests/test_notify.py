"""notify:去重决策全表(PRD 4.5,2026-09-06 换代)+ Toast 脚本 + XML 转义 + 协议注册。"""

import sys
import types

from guigui.core import notify


# ── decide_notify(PRD 4.5 全表)─────────────────────────────


def test_first_run_online_no_notify():
    kind, updates = notify.decide_notify(None, connected=True, today="2026-09-06")
    assert kind is None and updates["last_net_state"] == "up"


def test_broken_to_online_recovers_once_per_day():
    kw = dict(connected=True, today="2026-09-06")
    kind, updates = notify.decide_notify(
        "down", last_recovered_date=None, **kw)
    assert kind == notify.RECOVERED
    assert updates["last_recovered_notify_date"] == "2026-09-06"
    # 同日第二次翻转:不再发
    kind2, _ = notify.decide_notify(
        "down", last_recovered_date="2026-09-06", **kw)
    assert kind2 is None
    # 次日再断→通:再发
    kind3, _ = notify.decide_notify(
        "failed", last_recovered_date="2026-09-06", connected=True, today="2026-09-07")
    assert kind3 == notify.RECOVERED


def test_rejected_notifies_immediately_once_per_day():
    """AC-13:开门后明确被拒当拍即弹,每日 ≤1 次(不再等连败×3)。"""
    kw = dict(connected=False, outcome="rejected", today="2026-09-06")
    kind, updates = notify.decide_notify("failed", fail_notify_date=None, **kw)
    assert kind == notify.FAILED and updates["fail_notify_date"] == "2026-09-06"
    # 同日第二拍:不再发
    kind2, _ = notify.decide_notify("failed", fail_notify_date="2026-09-06", **kw)
    assert kind2 is None
    # 次日:闸门重开,再弹
    kind3, _ = notify.decide_notify(
        "failed", fail_notify_date="2026-09-06", connected=False,
        outcome="rejected", today="2026-09-07")
    assert kind3 == notify.FAILED


def test_maintenance_needs_three_beats_then_daily_once():
    """维护页(格式不认识):连续 ≥3 拍才弹,每日 ≤1 次。"""
    kw = dict(connected=False, outcome="unexpected", today="2026-09-06")
    for streak in (1, 2):
        kind, _ = notify.decide_notify("failed", maintenance_streak=streak, **kw)
        assert kind is None
    kind, updates = notify.decide_notify("failed", maintenance_streak=3, **kw)
    assert kind == notify.MAINTENANCE
    assert updates["maintenance_notify_date"] == "2026-09-06"
    kind2, _ = notify.decide_notify(
        "failed", maintenance_streak=4, maintenance_notify_date="2026-09-06", **kw)
    assert kind2 is None


def test_before_anchor_never_notifies():
    """AC-12:06:50 前的被拒/维护/不可达一律不算断网事件,零通知零状态。"""
    for outcome in ("rejected", "unexpected", None):
        kind, updates = notify.decide_notify(
            "down", connected=False, outcome=outcome, before_anchor=True,
            today="2026-09-06")
        assert kind is None and updates == {}


def test_unreachable_never_notifies():
    kind, updates = notify.decide_notify(
        "down", connected=False, outcome=None, today="2026-09-06")
    assert kind is None and updates["last_net_state"] == "down"


# ── Toast 脚本 ────────────────────────────────────────────


def test_xml_escape():
    out = notify._xml_escape("已连<un>&'\"")
    assert "&lt;un&gt;" in out and "&amp;" in out and "&quot;" in out and "&apos;" in out
    assert any(tok for tok in out.split(";") if tok.startswith("&#x5DF2"))  # 「已」高位转义


def test_send_embeds_protocol_launch(monkeypatch):
    captured = {}

    def fake_run(args, **kw):
        captured["ps"] = args[-1]
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(notify.subprocess, "run", fake_run)
    notify.send("已连上 ✓", "网络回来了", launch=notify.LAUNCH_CREDS)
    ps = captured["ps"]
    assert 'activationType="protocol"' in ps
    assert "launch=&#x67;uigui://" in ps or "guigui://" in ps
    assert "ToastGeneric" in ps


def test_send_swallows_errors(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("powershell gone")
    monkeypatch.setattr(notify.subprocess, "run", boom)
    notify.send("t", "m")  # 不抛即通过


# ── 协议注册(fake winreg)──────────────────────────────


def test_register_protocol_writes_hkcu(monkeypatch):
    written = {}

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake_winreg = types.ModuleType("winreg")
    fake_winreg.HKEY_CURRENT_USER = 1
    fake_winreg.KEY_WRITE = 2
    fake_winreg.REG_SZ = 1

    def create_key_ex(root, path, reserved, access):
        k = FakeKey()
        if isinstance(root, FakeKey):        # 相对子键:拼出全路径
            k.path = root.path + "\\" + path
        else:
            k.path = path
        return k

    def set_value_ex(key, name, reserved, typ, value):
        written[key.path + "/" + str(name)] = value

    fake_winreg.CreateKeyEx = create_key_ex
    fake_winreg.SetValueEx = set_value_ex
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    assert notify.register_protocol()
    cmd = written[r"Software\Classes\guigui\shell\open\command" + "/None"]
    assert '"%1"' in cmd
    assert written[r"Software\Classes\guigui" + "/None"] == "URL:guigui protocol"
    assert written[r"Software\Classes\guigui" + "/URL Protocol"] == ""
