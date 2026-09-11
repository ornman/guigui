"""notify:1.6.0 通知矩阵全表(用户拍板 2026-09-11)+ Toast 脚本 + XML 转义 + 协议注册。"""

import sys
import types

from guigui.core import notify


# ── decide_notify(1.6.0 通知矩阵)─────────────────────────


def test_success_notifies_daily_once():
    """任务成功 = 发(1.6.0);同类每天 ≤1。"""
    kind, updates = notify.decide_notify(None, connected=True,
                                         today="2026-09-11", now=1000.0)
    assert kind == notify.SUCCESS
    assert updates["last_net_state"] == "up"
    sent = updates["notify_sent"]
    assert sent[notify.SUCCESS]["date"] == "2026-09-11"
    # 同日第二拍:不再发
    kind2, _ = notify.decide_notify(None, connected=True, today="2026-09-11",
                                    now=1200.0, sent=sent)
    assert kind2 is None
    # 次日:闸门重开,再弹
    kind3, _ = notify.decide_notify(None, connected=True, today="2026-09-12",
                                    now=1000.0 + 86400, sent=sent)
    assert kind3 == notify.SUCCESS


def test_rejected_notifies_immediately_once_per_day():
    """AC-13 延续:开门后明确被拒当拍即判;同类每天 ≤1。"""
    kw = dict(connected=False, outcome="rejected", today="2026-09-11", now=1000.0)
    kind, updates = notify.decide_notify("failed", **kw)
    assert kind == notify.FAILED and updates["last_net_state"] == "failed"
    # 同日第二拍:不再发
    kind2, _ = notify.decide_notify("failed", sent=updates["notify_sent"], **kw)
    assert kind2 is None
    # 次日:闸门重开,再弹
    kind3, _ = notify.decide_notify(
        "failed", connected=False, outcome="rejected",
        today="2026-09-12", now=1000.0 + 86400, sent=updates["notify_sent"])
    assert kind3 == notify.FAILED


def test_maintenance_needs_three_beats_then_daily_once():
    """维护页(格式不认识):连续 ≥3 拍才弹,每天 ≤1 次。"""
    kw = dict(connected=False, outcome="unexpected", today="2026-09-11", now=1000.0)
    for streak in (1, 2):
        kind, _ = notify.decide_notify("failed", maintenance_streak=streak, **kw)
        assert kind is None
    kind, updates = notify.decide_notify("failed", maintenance_streak=3, **kw)
    assert kind == notify.MAINTENANCE
    kind2, _ = notify.decide_notify(
        "failed", maintenance_streak=4, sent=updates["notify_sent"], **kw)
    assert kind2 is None


def test_unreachable_notifies_pure_diagnostic():
    """1.6.0:连不上 = 也发(纯诊断);同类每天 ≤1。"""
    kind, updates = notify.decide_notify(
        "down", connected=False, outcome=None, today="2026-09-11", now=1000.0)
    assert kind == notify.NET_FAIL and updates["last_net_state"] == "down"
    kind2, _ = notify.decide_notify(
        "down", connected=False, outcome=None, today="2026-09-11", now=1200.0,
        sent=updates["notify_sent"])
    assert kind2 is None


def test_before_anchor_never_notifies():
    """AC-12:06:50 前的被拒/维护/不可达一律不算断网事件,零通知零状态。"""
    for outcome in ("rejected", "unexpected", None):
        kind, updates = notify.decide_notify(
            "down", connected=False, outcome=outcome, before_anchor=True,
            today="2026-09-11")
        assert kind is None and updates == {}


def test_vacation_silences_all_failure_kinds():
    """假期模式:失败类全静默(任务照跑、日志照记,只是不弹)。"""
    for outcome in ("rejected", "unexpected", None):
        kind, updates = notify.decide_notify(
            "down", connected=False, outcome=outcome, vacation=True,
            today="2026-09-11", now=1000.0)
        assert kind is None
        assert updates["last_net_state"] in ("down", "failed")


def test_cooldown_30min_merge_across_midnight():
    """拍板 #5:同类 30 分钟内合并为一条(不重发),跨午夜也压。"""
    sent = {notify.NET_FAIL: {"date": "2026-09-10", "ts": 1000.0}}
    kind, _ = notify.decide_notify(
        "down", connected=False, outcome=None, today="2026-09-11",
        now=1000.0 + 1200, sent=sent)      # 20 分钟前发过(昨天):合并
    assert kind is None
    kind2, _ = notify.decide_notify(
        "down", connected=False, outcome=None, today="2026-09-11",
        now=1000.0 + 2000, sent=sent)      # 超过 30 分钟:可发
    assert kind2 == notify.NET_FAIL


# ── Toast 脚本 ────────────────────────────────────────────


def test_xml_escape():
    out = notify._xml_escape("已连<un>&'\"")
    assert "&lt;un&gt;" in out and "&amp;" in out and "&quot;" in out and "&apos;" in out
    assert any(tok for tok in out.split(";") if tok.startswith("&#x5DF2"))  # 「已」高位转义


def test_send_embeds_protocol_launch(monkeypatch, real_notify_send):
    captured = {}

    def fake_run(args, **kw):
        captured["ps"] = args[-1]
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(notify.subprocess, "run", fake_run)
    monkeypatch.setattr(notify, "protocol_registered", lambda: True)
    notify.send("已连上 ✓", "网络回来了", launch=notify.LAUNCH_CREDS)
    ps = captured["ps"]
    assert 'activationType="protocol"' in ps
    assert "launch=&#x67;uigui://" in ps or "guigui://" in ps
    assert "ToastGeneric" in ps


def test_send_degrades_without_protocol(monkeypatch, real_notify_send):
    """P2-8:协议未注册成 → 降级纯展示,toast 不设 activationType/launch,
    不承诺一个点了没反应的动作;文案原样可达。"""
    captured = {}

    def fake_run(args, **kw):
        captured["ps"] = args[-1]
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(notify.subprocess, "run", fake_run)
    monkeypatch.setattr(notify, "protocol_registered", lambda: False)
    notify.send("桂桂", "定时任务不见了", launch=notify.LAUNCH_SETTINGS)
    ps = captured["ps"]
    assert "activationType" not in ps
    assert "launch=" not in ps
    assert "ToastGeneric" in ps


def test_protocol_registered_reads_hkcu(monkeypatch):
    fake_winreg = types.ModuleType("winreg")
    fake_winreg.HKEY_CURRENT_USER = 1

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake_winreg.OpenKey = lambda root, path: FakeKey()
    fake_winreg.QueryValueEx = lambda key, name: ("cmd", None)
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    assert notify.protocol_registered() is True

    def boom(root, path):
        raise OSError("no key")

    fake_winreg.OpenKey = boom
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    assert notify.protocol_registered() is False


def test_task_linger_copy_is_honest(monkeypatch):
    """P0-3:幽灵任务文案必须说清「任务还在、明早还会自动登录」并给动作(直达设置)。"""
    sent = []
    monkeypatch.setattr(notify, "send",
                        lambda t, m, launch=None: sent.append((t, m, launch)))
    notify.task_linger()
    assert sent and "定时任务还在" in sent[0][1]
    assert "明早还会自动登录" in sent[0][1]
    assert sent[0][2] == notify.LAUNCH_SETTINGS


def test_direct_helpers_cooldown_same_kind(monkeypatch):
    """拍板 #5 同口径:直发类(task_blocked 等)同类 30 分钟合并,不同类各自计。"""
    sent = []
    monkeypatch.setattr(notify, "send",
                        lambda t, m, launch=None: sent.append((t, m, launch)))
    notify.task_blocked()
    notify.task_blocked()   # 同类 30 分钟内:合并,不重发
    assert len(sent) == 1
    notify.task_linger()    # 不同类:各自记账
    assert len(sent) == 2


def test_send_swallows_errors(monkeypatch, real_notify_send):
    def boom(*a, **kw):
        raise RuntimeError("powershell gone")
    monkeypatch.setattr(notify.subprocess, "run", boom)
    notify.send("t", "m")  # 不抛即通过


# ── 双通道(ADR-0002:主 WinRT / 兜底 powershell)──────────


def test_send_prefers_winrt_channel(monkeypatch, real_notify_send):
    """主通道优先:_send_winrt 吃到完整模板并返回 True → powershell 零调用。"""
    seen = []
    monkeypatch.setattr(notify, "_send_winrt",
                        lambda xml: seen.append(xml) or True)

    def boom(*a, **kw):
        raise AssertionError("powershell 兜底不该被调")
    monkeypatch.setattr(notify.subprocess, "run", boom)
    notify.send("已连上", "网络回来了", launch=notify.LAUNCH_STATUS)
    assert len(seen) == 1
    assert "ToastGeneric" in seen[0]
    assert "已连上" not in seen[0] and "&#x5DF2;" in seen[0]   # 实体转义后才入模板


def test_send_winrt_failure_falls_back_to_powershell(monkeypatch, real_notify_send):
    """主通道失败 → powershell 兜底被调(S4 解耦:自救指引发送不依赖单点)。"""
    captured = {}

    def fake_run(args, **kw):
        captured["ps"] = args[-1]
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(notify, "_send_winrt", lambda xml: False)
    monkeypatch.setattr(notify.subprocess, "run", fake_run)
    monkeypatch.setattr(notify, "protocol_registered", lambda: True)
    notify.send("t", "m")
    assert "LoadXml" in captured["ps"]


def test_send_winrt_swallows_and_returns_false(monkeypatch):
    """主通道任何异常(投影加载失败等)→ 只记日志返回 False,不抛。"""
    def boom():
        raise RuntimeError("no clr / winrt unavailable")
    monkeypatch.setattr(notify, "_winrt_new_doc", boom)
    assert notify._send_winrt("<toast/>") is False


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
