"""notify:去重决策全表 + Toast 脚本(协议激活)+ XML 转义 + 协议注册。"""

import sys
import types

from guigui.core import notify


# ── decide_notify(AC-04 全表)─────────────────────────────


def test_first_run_online_no_notify():
    kind, updates = notify.decide_notify(
        None, connected=True, login_attempted=False, login_succeeded=False,
        consecutive_fail=0, fail_notify_sent=False, last_recovered_date=None,
        today="2026-08-31")
    assert kind is None and updates["last_net_state"] == "up"


def test_broken_to_online_recovers_once_per_day():
    kw = dict(connected=True, login_attempted=True, login_succeeded=True,
              consecutive_fail=0, fail_notify_sent=False)
    kind, updates = notify.decide_notify(
        "down", last_recovered_date=None, today="2026-08-31", **kw)
    assert kind == notify.RECOVERED
    assert updates["last_recovered_notify_date"] == "2026-08-31"
    # 同日第二次翻转:不再发
    kind2, _ = notify.decide_notify(
        "down", last_recovered_date="2026-08-31", today="2026-08-31", **kw)
    assert kind2 is None
    # 次日再断→通:再发
    kind3, _ = notify.decide_notify(
        "failed", last_recovered_date="2026-08-31", today="2026-09-01", **kw)
    assert kind3 == notify.RECOVERED


def test_fail_notify_after_three_streaks_then_latch():
    kw = dict(connected=False, login_attempted=True, login_succeeded=False,
              last_recovered_date=None, today="2026-08-31")
    # 第 1、2 拍:不通知
    for n in (1, 2):
        kind, _ = notify.decide_notify(
            "failed", consecutive_fail=n, fail_notify_sent=False, **kw)
        assert kind is None
    # 第 3 拍:发一次
    kind, updates = notify.decide_notify(
        "failed", consecutive_fail=3, fail_notify_sent=False, **kw)
    assert kind == notify.FAILED and updates["fail_notify_sent"] is True
    # 第 4 拍:锁存,不再发
    kind, _ = notify.decide_notify(
        "failed", consecutive_fail=4, fail_notify_sent=True, **kw)
    assert kind is None


def test_unreachable_never_notifies():
    kind, updates = notify.decide_notify(
        "down", connected=False, login_attempted=False, login_succeeded=False,
        consecutive_fail=0, fail_notify_sent=False, last_recovered_date=None,
        today="2026-08-31")
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
    cmd = written["Software\\Classes\\guigui/shell\\open\\command/None"]
    assert '"%1"' in cmd
    assert written["Software\\Classes\\guigui/None"] == "URL:guigui protocol"
    assert written["Software\\Classes\\guigui/URL Protocol"] == ""
