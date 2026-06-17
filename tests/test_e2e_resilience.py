"""端到端集成测试：真实 Windows 子系统（任务计划/互斥量/子进程）。

这些测试会修改真实的任务计划，默认跳过。
运行：set RUN_E2E=1 && python -m pytest tests/test_e2e_resilience.py -v
"""

import os
import subprocess
import sys

import pytest

from src import scheduler, selfheal, instance

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_E2E"),
    reason="E2E 测试改动真实任务计划；设置 RUN_E2E=1 后运行",
)

_TEST_MUTEX = "Local\\SchoolAutoLogin-E2E-Test"


@pytest.fixture
def clean_tasks():
    """每个测试前后确保核心与巡逻任务计划都不存在。"""
    scheduler.remove_scheduled_task()
    scheduler.remove_scheduled_task(scheduler.PATROL_TASK_NAME)
    yield
    scheduler.remove_scheduled_task()
    scheduler.remove_scheduled_task(scheduler.PATROL_TASK_NAME)


def _register_legacy_silent_task():
    """注册一个旧版 --silent 单触发器每日任务（迁移源）。"""
    ps = (
        "$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c echo legacy'; "
        "$t = New-ScheduledTaskTrigger -Daily -At '06:55:00'; "
        "$s = New-ScheduledTaskSettingsSet; "
        "Register-ScheduledTask -TaskName 'SchoolAutoLogin' "
        "-Action $a -Trigger $t -Settings $s -Force"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, timeout=20,
    )


def _task_xml(name):
    r = subprocess.run(
        ["schtasks", "/query", "/tn", name, "/xml"],
        capture_output=True, text=True, timeout=15,
    )
    return r.stdout if r.returncode == 0 else ""


def test_windowed_task_registers_real_triggers(clean_tasks):
    """真实注册窗口任务：XML 含 CalendarTrigger+Repetition(PT5M/PT1H) + LogonTrigger。"""
    assert scheduler.create_windowed_task("06:55", 60, 5) is True
    xml = _task_xml(scheduler.TASK_NAME)
    assert "--ensure" in xml
    assert "<LogonTrigger>" in xml
    assert "<CalendarTrigger>" in xml
    assert "<Interval>PT5M</Interval>" in xml
    assert "<Duration>PT1H</Duration>" in xml
    assert "IgnoreNew" in xml
    assert scheduler.is_windowed_task() is True
    assert scheduler.is_legacy_task() is False


def test_patrol_task_registers_all_day_repetition(clean_tasks):
    """真实注册巡逻任务：TimeTrigger + Repetition PT30M，独立任务名。"""
    assert scheduler.create_patrol_task(30) is True
    xml = _task_xml(scheduler.PATROL_TASK_NAME)
    assert "--ensure" in xml
    assert "<TimeTrigger>" in xml
    assert "<Interval>PT30M</Interval>" in xml
    assert "<LogonTrigger>" not in xml
    assert scheduler.is_patrol_task() is True


def test_selfheal_rebuilds_windowed_when_deleted(clean_tasks):
    """删掉核心任务后，reconcile_scheduler 重建窗口任务。"""
    cfg = {"resilience_enabled": True, "patrol_enabled": False,
           "scheduled_login_time": "06:55", "window_duration_minutes": 60,
           "heartbeat_interval_minutes": 5, "patrol_interval_minutes": 30}
    assert not scheduler.is_windowed_task()

    changed = selfheal.reconcile_scheduler(cfg)

    assert changed is True
    assert scheduler.is_windowed_task() is True


def test_selfheal_migrates_legacy_task(clean_tasks):
    """旧 --silent 单触发器任务被 reconcile_scheduler 迁移成窗口任务。"""
    _register_legacy_silent_task()
    assert scheduler.is_legacy_task() is True
    assert scheduler.is_windowed_task() is False

    cfg = {"resilience_enabled": True, "patrol_enabled": False,
           "scheduled_login_time": "06:55", "window_duration_minutes": 60,
           "heartbeat_interval_minutes": 5, "patrol_interval_minutes": 30}
    changed = selfheal.reconcile_scheduler(cfg)

    assert changed is True
    assert scheduler.is_windowed_task() is True
    assert scheduler.is_legacy_task() is False


def test_selfheal_creates_and_removes_patrol(clean_tasks):
    """patrol 开 → 建巡逻；patrol 关 → 删巡逻。"""
    cfg_on = {"resilience_enabled": True, "patrol_enabled": True,
              "scheduled_login_time": "06:55", "window_duration_minutes": 60,
              "heartbeat_interval_minutes": 5, "patrol_interval_minutes": 20}
    selfheal.reconcile_scheduler(cfg_on)
    assert scheduler.is_patrol_task() is True

    cfg_off = {**cfg_on, "patrol_enabled": False}
    selfheal.reconcile_scheduler(cfg_off)
    assert scheduler.is_patrol_task() is False


def test_single_instance_mutex_blocks_second_holder():
    """真实 Win32 互斥量：A 持有时 B 抢不到；A 释放后 C 可抢。"""
    si1 = instance.SingleInstance(name=_TEST_MUTEX)
    assert si1.acquire() is True
    try:
        si2 = instance.SingleInstance(name=_TEST_MUTEX)
        assert si2.acquire() is False          # 被阻塞
    finally:
        si1.release()

    si3 = instance.SingleInstance(name=_TEST_MUTEX)
    assert si3.acquire() is True               # 释放后可抢
    si3.release()


def test_ensure_subprocess_exits_zero():
    """真实跑 python main.py --ensure，退出码 0（静默执行体可独立运行）。"""
    r = subprocess.run(
        [sys.executable, "main.py", "--ensure"],
        capture_output=True, timeout=60,
    )
    assert r.returncode == 0
