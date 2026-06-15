"""端到端集成测试：真实 Windows 子系统（任务计划/注册表/互斥量/子进程）。

这些测试会修改真实的任务计划和注册表，默认跳过。
运行：set RUN_E2E=1 && python -m pytest tests/test_e2e_resilience.py -v
"""

import os
import subprocess
import sys

import pytest

from src import scheduler, selfheal, instance, autostart

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_E2E"),
    reason="E2E 测试改动真实任务计划/注册表；设置 RUN_E2E=1 后运行",
)

_TEST_MUTEX = "Local\\SchoolAutoLogin-E2E-Test"


@pytest.fixture
def clean_task():
    """每个测试前后确保 SchoolAutoLogin 任务计划不存在。"""
    scheduler.remove_scheduled_task()
    yield
    scheduler.remove_scheduled_task()


@pytest.fixture
def clean_autostart():
    """每个测试前后确保自启注册表键不存在。"""
    autostart.disable()
    yield
    autostart.disable()


def test_multi_trigger_task_registers_real_triggers(clean_task):
    """真实注册多触发器任务，校验 XML 含三触发器 + --ensure + IgnoreNew。"""
    assert scheduler.create_scheduled_task_multi("06:55", 5) is True

    r = subprocess.run(
        ["schtasks", "/query", "/tn", scheduler.TASK_NAME, "/xml"],
        capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0
    xml = r.stdout
    assert "--ensure" in xml            # 跑 --ensure，非 --silent
    assert "<LogonTrigger>" in xml      # 登录时触发器（① 开机代理）
    assert "<Repetition>" in xml        # 心跳重复触发器（③ 看门狗代理）
    assert "<CalendarTrigger>" in xml   # 每日触发器
    assert "IgnoreNew" in xml           # 防重叠实例堆积
    assert scheduler.is_legacy_task() is False


def test_selfheal_rebuilds_deleted_task(clean_task):
    """场景 ④a：删掉任务计划后，reconcile_scheduler 重建（多触发器 --ensure）。"""
    cfg = {"resilience_enabled": True, "scheduled_login_enabled": False,
           "scheduled_login_time": "06:55", "heartbeat_interval_minutes": 5}
    assert not scheduler.get_scheduled_task_info()["exists"]

    changed = selfheal.reconcile_scheduler(cfg)

    assert changed is True
    assert scheduler.get_scheduled_task_info()["exists"] is True
    assert scheduler.is_legacy_task() is False


def test_selfheal_migrates_legacy_task(clean_task):
    """旧 --silent 任务被 reconcile_scheduler 迁移成 --ensure 多触发器。"""
    cfg = {"resilience_enabled": True, "scheduled_login_enabled": True,
           "scheduled_login_time": "06:55", "heartbeat_interval_minutes": 5}
    assert scheduler.create_scheduled_task("06:55") is True   # legacy --silent
    assert scheduler.is_legacy_task() is True

    changed = selfheal.reconcile_scheduler(cfg)

    assert changed is True
    assert scheduler.is_legacy_task() is False


def test_selfheal_reenables_deleted_autostart(clean_autostart):
    """场景 ④b：删掉自启注册表后，reconcile_autostart 重建（resilience 开）。"""
    cfg = {"resilience_enabled": True, "auto_start": False}
    assert autostart.is_enabled() is False

    changed = selfheal.reconcile_autostart(cfg)

    assert changed is True
    assert autostart.is_enabled() is True


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
    """真实跑 python main.py --ensure，退出码 0（心跳可独立运行）。"""
    r = subprocess.run(
        [sys.executable, "main.py", "--ensure"],
        capture_output=True, timeout=60,
    )
    assert r.returncode == 0
