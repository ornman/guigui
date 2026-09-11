"""scheduler:L1 起点公式/任务 XML 生成/CRUD/rev 判定(全 mock schtasks)。"""

import subprocess
from pathlib import Path

import pytest

from guigui.core import scheduler


# ── L1 窗口公式(修 v1 反向 bug)──────────────────────────

def test_l1_window_default():
    assert scheduler.l1_window("07:00", 5) == ("06:30", 25)   # 拍 06:30–06:55


def test_l1_window_heartbeat_10_and_15():
    assert scheduler.l1_window("07:00", 10) == ("06:30", 50)
    assert scheduler.l1_window("07:00", 15) == ("06:30", 75)


def test_l1_window_wraps_midnight():
    assert scheduler.l1_window("00:10", 5) == ("23:40", 25)


def test_l1_window_rejects_bad_time():
    with pytest.raises(ValueError):
        scheduler.l1_window("25:00", 5)
    with pytest.raises(ValueError):
        scheduler.l1_window("", 5)


# ── 主任务 XML ────────────────────────────────────────────


def _cfg(**over):
    base = {
        "trigger_time": "07:00", "heartbeat_minutes": 5,
        "boot_login": True, "wake_login": False,
    }
    base.update(over)
    return base


def test_main_task_xml_triggers_and_rev():
    """P1-7:主任务只含 CalendarTrigger(LogonTrigger 已迁到独立任务 GuiGui-Boot)。"""
    xml = scheduler.build_main_task_xml(_cfg(), rev=7)
    assert "GuiGui v2 automation rev=7" in xml
    assert "<RegistrationInfo><Description>GuiGui v2 automation rev=7</Description>" in xml
    assert "<Triggers><CalendarTrigger>" in xml        # schema 顺序:触发器必须包壳(联调实测教训)
    assert "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>" in xml
    assert "T06:30:00" in xml
    assert "<Interval>PT5M</Interval>" in xml and "<Duration>PT25M</Duration>" in xml
    assert "<LogonTrigger>" not in xml                  # P1-7:已迁出
    assert "<EventTrigger>" not in xml                  # wake_login 默认关 + 已迁出
    # 声明与 create_task 落盘编码必须同为 UTF-16(schtasks 规范;不一致报「无法切换编码」)
    assert xml.startswith('<?xml version="1.0" encoding="UTF-16"?>')
    # P1-7:Action Arguments 带 --trigger calendar,ensure.run 据此判 silent 豁免
    assert "--trigger calendar" in xml


def test_boot_task_xml_logon_only_with_trigger():
    """P1-7:GuiGui-Boot 只含 LogonTrigger,Action Arguments 带 --trigger boot。"""
    xml = scheduler.build_boot_task_xml(_cfg(), rev=2)
    assert "<LogonTrigger>" in xml
    assert "<CalendarTrigger>" not in xml
    assert "<EventTrigger>" not in xml
    assert "--trigger boot" in xml
    assert "rev=2" in xml


def test_wake_task_xml_event_only_with_trigger():
    """P1-7:GuiGui-Wake 只含 EventTrigger,Action Arguments 带 --trigger wake。"""
    xml = scheduler.build_wake_task_xml(_cfg(boot_login=False, wake_login=True), rev=1)
    assert "<EventTrigger>" in xml and "<Delay>PT30S</Delay>" in xml
    assert "Power-Troubleshooter" in xml and "EventID=1" in xml
    assert "<LogonTrigger>" not in xml
    assert "<CalendarTrigger>" not in xml
    assert "--trigger wake" in xml


def test_action_parts_unknown_trigger_falls_back_to_calendar():
    """P1-7:无效 trigger → 默认 calendar(向后兼容旧任务 / 手动运行)。"""
    exe, arguments, workdir = scheduler.action_parts("bogus")
    assert "--trigger calendar" in arguments
    assert workdir


def test_patrol_task_xml():
    import datetime as dt
    now = dt.datetime(2026, 8, 31, 12, 0, 0)
    xml = scheduler.build_patrol_task_xml(
        {"patrol_minutes": 30, **_cfg()}, rev=3, now=now)
    assert "<Triggers><TimeTrigger>" in xml and "<CalendarTrigger>" not in xml
    assert "<Interval>PT30M</Interval>" in xml
    assert "<Duration>P3650D</Duration>" in xml
    assert "rev=3" in xml
    assert "2026-08-31T12:00:00" in xml
    # P1-7:巡逻任务 Action Arguments 带 --trigger patrol
    assert "--trigger patrol" in xml


def test_main_task_xml_settings_and_action():
    """主任务 settings 块 + Action 字段不变(P1-7 拆分不影响 shell 包装)。"""
    xml = scheduler.build_main_task_xml(_cfg(), rev=0)
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml
    assert "<ExecutionTimeLimit>PT15M</ExecutionTimeLimit>" in xml
    assert "<WakeToRun>true</WakeToRun>" in xml
    assert "<LogonType>InteractiveToken</LogonType>" in xml
    assert "--ensure" in xml and "<WorkingDirectory>" in xml


# ── CRUD / rev 判定(mock schtasks)──────────────────────


class FakeCmd:
    def __init__(self):
        self.calls = []
        self.xml_to_return: dict[str, str] = {}
        self.exists_paths = True

    def run(self, args, timeout=30):
        self.calls.append(args)
        key = args[1] if args[0] in ("/create", "/delete", "/query") else args[0]
        if args[0] == "/query":
            xml = self.xml_to_return.get(args[2])
            if xml is None:
                return subprocess.CompletedProcess(args, 1, "", "找不到")
            return subprocess.CompletedProcess(args, 0, xml, "")
        return subprocess.CompletedProcess(args, 0, "", "")


@pytest.fixture
def fake(monkeypatch):
    f = FakeCmd()
    monkeypatch.setattr(scheduler, "_run", f.run)
    return f


def test_create_task_passes_xml_file(fake):
    xml = scheduler.build_main_task_xml(_cfg(), rev=1)
    # 截住临时文件内容再放行
    sent = {}
    orig = scheduler._run

    def spy(args, timeout=30):
        if args[0] == "/create":
            sent["xml"] = Path(args[4]).read_text(encoding="utf-16")
        return orig(args, timeout)
    scheduler._run = spy
    try:
        assert scheduler.create_task(scheduler.TASK_MAIN, xml)
    finally:
        scheduler._run = orig
    assert sent["xml"] == xml


def test_remove_task_treats_missing_as_success(fake):
    assert fake.run(["/query", "/tn", "nope", "/xml"])  # 不存在
    assert scheduler.remove_task("GuiGui") is True


def test_create_task_sweeps_stale_own_prefix_only(fake, tmp_path, monkeypatch):
    """临时文件残留清理(附录 A-2):入口 sweep 只清自有前缀 + 超龄文件;
    他人文件 / 在途新文件不动;自己的临时文件用完即 finally 删净。"""
    import os
    import tempfile as _tf
    import time as _time

    monkeypatch.setattr(_tf, "gettempdir", lambda: str(tmp_path))
    old = _time.time() - scheduler._STALE_TMP_AGE_SEC * 2

    stale = tmp_path / (scheduler._TMP_PREFIX + "crash.xml")   # 崩溃残留(超龄)
    stale.write_text("x", encoding="utf-16")
    os.utime(stale, (old, old))
    fresh = tmp_path / (scheduler._TMP_PREFIX + "inflight.xml")  # 在途(新)→ 不动
    fresh.write_text("x", encoding="utf-16")
    alien = tmp_path / "other-tmp.xml"                           # 非本前缀 → 不动
    alien.write_text("x", encoding="utf-16")
    os.utime(alien, (old, old))

    assert scheduler.create_task("GuiGui", "<Task/>") is True
    assert not stale.exists()
    assert fresh.exists() and alien.exists()
    # 本前缀只剩在途文件 — create_task 自己的临时文件已 finally 删净
    assert list(tmp_path.glob(scheduler._TMP_PREFIX + "*.xml")) == [fresh]


def test_is_task_current_rev_match(fake):
    cfg = {"tasks_rev": 4}
    fake.xml_to_return["GuiGui"] = "…<Description>GuiGui v2 automation rev=4</Description>…"
    assert scheduler.is_task_current("GuiGui", cfg)      # 无 Command 节点 → 目标检查放行
    fake.xml_to_return["GuiGui"] = "…<Description>GuiGui v2 automation rev=3</Description>…"
    assert not scheduler.is_task_current("GuiGui", cfg)   # rev 失配 → 重建


def test_is_task_current_action_target_gone(fake):
    cfg = {"tasks_rev": 4}
    fake.xml_to_return["GuiGui"] = (
        "<Description>GuiGui v2 automation rev=4</Description>"
        "<Command>C:\\gone\\guigui.exe</Command>"         # 真实不存在的路径
    )
    assert not scheduler.is_task_current("GuiGui", cfg)   # 坏任务 → 重建


def test_parse_rev_absent():
    assert scheduler.parse_rev("<Description>别的</Description>") is None
    assert scheduler.parse_rev(None) is None


def test_drop_logon_trigger():
    """剥离 LogonTrigger(降级注册);其他触发器原样保留。"""
    from guigui.core.scheduler import drop_logon_trigger
    xml = ("<Triggers><CalendarTrigger><StartBoundary>2026-08-31T06:30:00</StartBoundary></CalendarTrigger>"
           "<LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>")
    out = drop_logon_trigger(xml)
    assert "<LogonTrigger>" not in out
    assert "<CalendarTrigger>" in out


# ── COM 主通道(fake folder 注入 + 降级链)────────────────


class _FakeType:
    """复刻迟绑定形态:obj.GetType().InvokeMember(name, flags, binder, obj, args)。"""

    def __init__(self, obj):
        self._obj = obj

    def InvokeMember(self, name, flags, binder, target, args):
        return self._obj.com_call(name, args)


_FileNotFoundException = type("FileNotFoundException", (Exception,), {})
_TargetInvocationException = type("TargetInvocationException", (Exception,), {})


def _raise_not_found():
    """模拟反射包装:InnerException 才是 FileNotFound(真机探针实测形态)。"""
    wrapper = _TargetInvocationException("调用的目标发生了异常")
    wrapper.InnerException = _FileNotFoundException("系统找不到指定的文件")
    raise wrapper


class FakeCom:
    """通用迟绑定假对象:方法走 methods,属性走 props。"""

    def __init__(self, props=None, methods=None):
        self.props = props or {}
        self.methods = methods or {}

    def GetType(self):
        return _FakeType(self)

    def com_call(self, name, args):
        if name in self.methods:
            return self.methods[name](*args)
        return self.props[name]


def make_folder(tasks=None, *, fail_register=False, fail_get=False,
                fail_delete=False):
    """假根 folder:tasks 为 name→xml;三个 fail 开关模拟 COM 环节异常。"""
    state = {"tasks": dict(tasks or {})}

    def register(name, xml, flags, user, pw, logon, sddl):
        if fail_register:
            raise RuntimeError("HRESULT 0x80070005 拒绝访问")
        state["tasks"][name] = xml

    def get(name):
        if fail_get:
            raise RuntimeError("COM GetTask boom")
        if name not in state["tasks"]:
            _raise_not_found()
        return FakeCom({"Xml": state["tasks"][name],
                        "LastRunTime": None, "LastTaskResult": None})

    def delete(name, flags):
        if fail_delete:
            raise RuntimeError("COM DeleteTask boom")
        if name not in state["tasks"]:
            _raise_not_found()
        del state["tasks"][name]

    folder = FakeCom(methods={"RegisterTask": register, "GetTask": get,
                              "DeleteTask": delete})
    return folder, state


@pytest.fixture
def com_off_spy(monkeypatch):
    """记录 _run 调用并一律视为失败(降级链用例里 schtasks 只需被叫到)。"""
    calls = []
    monkeypatch.setattr(scheduler, "_run",
                        lambda args, timeout=30: calls.append(args)
                        or subprocess.CompletedProcess(args, 0, "", ""))
    return calls


def test_com_create_registers_without_schtasks(monkeypatch, com_off_spy):
    """COM 主通道:注册 + GetTask 回读全走 COM,_run(schtasks)零调用。"""
    folder, state = make_folder()
    monkeypatch.setattr(scheduler, "_com_folder", lambda: folder)
    xml = scheduler.build_boot_task_xml(_cfg(), rev=9)
    assert scheduler.create_task(scheduler.TASK_BOOT, xml) is True
    assert state["tasks"][scheduler.TASK_BOOT] == xml
    assert not com_off_spy                              # schtasks 兜底没被叫到


def test_com_create_failure_falls_back_to_schtasks(monkeypatch, com_off_spy):
    folder, _ = make_folder(fail_register=True)
    monkeypatch.setattr(scheduler, "_com_folder", lambda: folder)
    assert scheduler.create_task("GuiGui-Test", "<Task/>") is True
    assert com_off_spy and com_off_spy[0][0] == "/create"   # 降级被叫到


def test_com_create_verify_failure_falls_back(monkeypatch, com_off_spy):
    """「注册成功但回读失败」也要降级 schtasks 重试(ADR-0001 第 3 点)。"""
    folder, _ = make_folder(fail_get=True)
    monkeypatch.setattr(scheduler, "_com_folder", lambda: folder)
    assert scheduler.create_task("GuiGui-Test", "<Task/>") is True
    assert any(a[0] == "/create" for a in com_off_spy)


def test_com_query_hit_and_miss(monkeypatch, com_off_spy):
    folder, _ = make_folder({"GuiGui": "<Description>rev=1</Description>"})
    monkeypatch.setattr(scheduler, "_com_folder", lambda: folder)
    assert "rev=1" in scheduler.query_xml("GuiGui")
    assert scheduler.query_xml("GuiGui-None") is None     # 不存在 = COM 定论
    assert not com_off_spy                                  # 不再走 schtasks


def test_com_query_failure_falls_back(monkeypatch, fake):
    folder, _ = make_folder(fail_get=True)
    monkeypatch.setattr(scheduler, "_com_folder", lambda: folder)
    fake.xml_to_return["GuiGui"] = "<Description>rev=2</Description>"
    assert "rev=2" in scheduler.query_xml("GuiGui")       # 降级 schtasks 读回


def test_com_delete_missing_is_success(monkeypatch, com_off_spy):
    folder, _ = make_folder()
    monkeypatch.setattr(scheduler, "_com_folder", lambda: folder)
    assert scheduler.remove_task("GuiGui-None") is True   # 幂等,零 schtasks
    assert not com_off_spy


def test_com_delete_failure_falls_back(monkeypatch, com_off_spy):
    folder, _ = make_folder(fail_delete=True)
    monkeypatch.setattr(scheduler, "_com_folder", lambda: folder)
    assert scheduler.remove_task("GuiGui-Test") is True
    assert any(a[0] == "/delete" for a in com_off_spy)


def _fake_dt(**over):
    p = dict(Year=2026, Month=9, Day=7, Hour=7, Minute=0, Second=3)
    p.update(over)
    return FakeCom(props=p)


def test_task_runtime_info_formats(monkeypatch):
    folder, _ = make_folder()
    folder.methods["GetTask"] = lambda name: FakeCom(
        {"LastRunTime": _fake_dt(), "LastTaskResult": 267011})
    monkeypatch.setattr(scheduler, "_com_folder", lambda: folder)
    info = scheduler.task_runtime_info("GuiGui")
    assert info == {"last_run": "09-07 07:00:03", "last_result": "0x41303"}


def test_task_runtime_info_never_run_sentinel(monkeypatch):
    folder, _ = make_folder()
    # Task Scheduler 从未运行哨兵 = 1999-11-30(真机实测,非 1601/1899)
    folder.methods["GetTask"] = lambda name: FakeCom(
        {"LastRunTime": _fake_dt(Year=1999, Month=11, Day=30), "LastTaskResult": 267011})
    monkeypatch.setattr(scheduler, "_com_folder", lambda: folder)
    info = scheduler.task_runtime_info("GuiGui")
    assert info["last_run"] is None                    # 哨兵日期 → 未运行
    assert info["last_result"] == "0x41303"


def test_task_runtime_info_com_down_returns_none():
    """COM 不可用(conftest 默认关闸)→ None,不抛、不降级 schtasks。"""
    assert scheduler.task_runtime_info("GuiGui") is None
