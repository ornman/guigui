"""窗口化自动化模型的任务计划测试。

核心模型：
  - 窗口任务 SchoolAutoLogin：AtLogon + Daily@start + Repetition(interval, window)
  - 巡逻任务 SchoolAutoLogin-Patrol：Once + Repetition(interval, 3650d)
  - is_legacy_task：核心任务存在但不符合窗口模型 → 需迁移
"""

import re
from unittest.mock import patch, MagicMock

from src import scheduler


def _capture_ps():
    """捕获传给 powershell 的命令列表，并伪装注册成功。"""
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return MagicMock(returncode=0, stderr="", stdout="")

    return captured, fake_run


# ── 窗口时间算术（纯函数）──────────────────────────────


class TestWindowStartFromCenter:
    def test_basic_half_before(self):
        assert scheduler.window_start_from_center("06:55", 60) == "06:25"

    def test_wraps_past_midnight(self):
        assert scheduler.window_start_from_center("00:10", 60) == "23:40"

    def test_odd_duration_floors(self):
        # 50 分钟窗口 → 前 25 分钟 → 06:55 - 25 = 06:30
        assert scheduler.window_start_from_center("06:55", 50) == "06:30"

    def test_full_duration_wraps(self):
        assert scheduler.window_start_from_center("06:25", 120) == "05:25"


# ── create_windowed_task ──────────────────────────────


class TestCreateWindowedTask:
    def test_ps_contains_atlogon_window_repetition_and_ensure(self):
        captured, fake = _capture_ps()
        with patch("subprocess.run", side_effect=fake):
            assert scheduler.create_windowed_task("06:55", 60, 5) is True
        ps = " ".join(captured["cmd"])
        assert "--ensure" in ps
        assert "-AtLogOn -User $env:USERNAME" in ps   # AtLogon 限当前用户
        assert "-Daily -At '06:25:00'" in ps          # 窗口起点 = 中心 - 30
        assert "New-TimeSpan -Minutes 5" in ps         # 窗口内间隔
        assert "New-TimeSpan -Minutes 60" in ps        # 窗口时长
        assert "IgnoreNew" in ps                       # 防重叠实例堆积

    def test_rejects_bad_center(self):
        with patch("subprocess.run") as run:
            assert scheduler.create_windowed_task("6:55", 60, 5) is False
            run.assert_not_called()

    def test_rejects_bad_duration(self):
        with patch("subprocess.run") as run:
            assert scheduler.create_windowed_task("06:55", 0, 5) is False
            assert scheduler.create_windowed_task("06:55", -10, 5) is False
            run.assert_not_called()

    def test_rejects_bad_interval(self):
        with patch("subprocess.run") as run:
            assert scheduler.create_windowed_task("06:55", 60, 0) is False
            run.assert_not_called()

    def test_returns_false_on_powershell_failure(self):
        bad = MagicMock(returncode=1, stderr="denied", stdout="")
        with patch("subprocess.run", return_value=bad):
            assert scheduler.create_windowed_task("06:55", 60, 5) is False


# ── create_patrol_task ────────────────────────────────


class TestCreatePatrolTask:
    def test_ps_uses_patrol_name_and_all_day_repetition(self):
        captured, fake = _capture_ps()
        with patch("subprocess.run", side_effect=fake):
            assert scheduler.create_patrol_task(30) is True
        ps = " ".join(captured["cmd"])
        assert "--ensure" in ps
        assert "SchoolAutoLogin-Patrol" in ps          # 独立任务名
        assert "New-TimeSpan -Minutes 30" in ps         # 巡逻间隔
        assert "New-TimeSpan -Days 3650" in ps          # 全天（约 10 年）
        assert "IgnoreNew" in ps
        assert "-AtLogOn" not in ps                     # 巡逻不绑登录
        assert "-Daily" not in ps                       # 巡逻不绑窗口

    def test_rejects_bad_interval(self):
        with patch("subprocess.run") as run:
            assert scheduler.create_patrol_task(0) is False
            assert scheduler.create_patrol_task(-5) is False
            run.assert_not_called()


# ── 任务类型检测（is_windowed / is_legacy / is_patrol）────────


def _xml(*triggers, actions="--ensure"):
    """拼一个最小任务 XML，triggers 为若干触发器字符串片段。"""
    trig = "".join(f"<{t}/>" if not t.startswith("<") else t for t in triggers)
    return (f"<Task><Triggers>{trig}</Triggers>"
            f"<Actions><Exec><Arguments>main.py {actions}</Arguments></Exec></Actions></Task>")


_WINDOW_XML = (
    "<Task><Triggers>"
    "<LogonTrigger></LogonTrigger>"
    "<CalendarTrigger><StartBoundary>2026-06-17T06:25:00</StartBoundary>"
    "<Repetition><Interval>PT5M</Interval><Duration>PT1H</Duration></Repetition>"
    "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
    "</CalendarTrigger></Triggers>"
    "<Actions><Exec><Arguments>main.py --ensure</Arguments></Exec></Actions></Task>"
)

# 旧版多触发器任务：LogonTrigger + TimeTrigger(含 Repetition) + CalendarTrigger(无 Repetition)
_OLD_MULTI_XML = (
    "<Task><Triggers>"
    "<LogonTrigger></LogonTrigger>"
    "<TimeTrigger><Repetition><Interval>PT15M</Interval></Repetition></TimeTrigger>"
    "<CalendarTrigger><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>"
    "</Triggers>"
    "<Actions><Exec><Arguments>main.py --ensure</Arguments></Exec></Actions></Task>"
)


class TestTaskDetection:
    def test_is_windowed_task_true_for_new_model(self):
        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=_WINDOW_XML)):
            assert scheduler.is_windowed_task() is True
            assert scheduler.is_legacy_task() is False

    def test_is_legacy_for_old_silent(self):
        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stdout="<Task>--silent</Task>")):
            assert scheduler.is_windowed_task() is False
            assert scheduler.is_legacy_task() is True

    def test_is_legacy_for_old_multi_ensure(self):
        """旧多触发器 --ensure 任务（CalendarTrigger 无 Repetition）→ 视为 legacy 迁移。"""
        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=_OLD_MULTI_XML)):
            assert scheduler.is_windowed_task() is False
            assert scheduler.is_legacy_task() is True

    def test_not_legacy_when_task_missing(self):
        with patch("subprocess.run",
                   return_value=MagicMock(returncode=1, stdout="")):
            assert scheduler.is_legacy_task() is False
            assert scheduler.is_windowed_task() is False

    def test_is_patrol_task_true(self):
        patrol_xml = (
            "<Task><Triggers>"
            "<TimeTrigger><Repetition><Interval>PT30M</Interval></Repetition></TimeTrigger>"
            "</Triggers>"
            "<Actions><Exec><Arguments>main.py --ensure</Arguments></Exec></Actions></Task>"
        )
        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=patrol_xml)):
            assert scheduler.is_patrol_task() is True

    def test_is_patrol_task_false_when_core_task(self):
        """窗口任务（含 LogonTrigger/CalendarTrigger）不是巡逻任务。"""
        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=_WINDOW_XML)):
            assert scheduler.is_patrol_task() is False