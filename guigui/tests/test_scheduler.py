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
    xml = scheduler.build_main_task_xml(_cfg(), rev=7)
    assert "GuiGui v2 automation rev=7" in xml
    assert "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>" in xml
    assert "T06:30:00" in xml
    assert "<Interval>PT5M</Interval>" in xml and "<Duration>PT25M</Duration>" in xml
    assert "<LogonTrigger>" in xml                      # boot_login 默认开
    assert "<EventTrigger>" not in xml                  # wake_login 默认关


def test_main_task_xml_switch_reflects_config():
    xml = scheduler.build_main_task_xml(_cfg(boot_login=False, wake_login=True), rev=1)
    assert "<LogonTrigger>" not in xml
    assert "<EventTrigger>" in xml and "<Delay>PT30S</Delay>" in xml
    assert "Power-Troubleshooter" in xml
    assert "EventID=1" in xml


def test_main_task_xml_settings_and_action():
    xml = scheduler.build_main_task_xml(_cfg(), rev=0)
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml
    assert "<ExecutionTimeLimit>PT15M</ExecutionTimeLimit>" in xml
    assert "<WakeToRun>true</WakeToRun>" in xml
    assert "<LogonType>InteractiveToken</LogonType>" in xml
    assert "--ensure" in xml and "<WorkingDirectory>" in xml


def test_patrol_task_xml():
    import datetime as dt
    now = dt.datetime(2026, 8, 31, 12, 0, 0)
    xml = scheduler.build_patrol_task_xml(
        {"patrol_minutes": 30, **_cfg()}, rev=3, now=now)
    assert "<TimeTrigger>" in xml and "<CalendarTrigger>" not in xml
    assert "<Interval>PT30M</Interval>" in xml
    assert "<Duration>P3650D</Duration>" in xml
    assert "rev=3" in xml
    assert "2026-08-31T12:00:00" in xml


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
            sent["xml"] = Path(args[4]).read_text(encoding="utf-8")
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
