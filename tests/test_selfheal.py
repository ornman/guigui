"""self-heal：窗口化任务模型的对齐测试。

核心任务 SchoolAutoLogin（AtLogon + 窗口）由 resilience_enabled 控制；
巡逻任务 SchoolAutoLogin-Patrol 由 resilience_enabled AND patrol_enabled 控制。
"""

from unittest.mock import patch

from src import scheduler, selfheal


# ── should_* 判定 ─────────────────────────────────────


def test_core_task_on_when_resilience():
    assert selfheal.should_core_task_exist({"resilience_enabled": True}) is True


def test_core_task_off_when_resilience_off():
    assert selfheal.should_core_task_exist({"resilience_enabled": False}) is False


def test_patrol_on_only_when_resilience_and_patrol():
    assert selfheal.should_patrol_task_exist(
        {"resilience_enabled": True, "patrol_enabled": True}) is True


def test_patrol_off_when_patrol_disabled():
    assert selfheal.should_patrol_task_exist(
        {"resilience_enabled": True, "patrol_enabled": False}) is False


def test_patrol_off_when_resilience_off():
    """resilience 关 → 全自动停，巡逻也停。"""
    assert selfheal.should_patrol_task_exist(
        {"resilience_enabled": False, "patrol_enabled": True}) is False


_BASE = {"scheduled_login_time": "06:55", "window_duration_minutes": 60,
         "heartbeat_interval_minutes": 5, "patrol_interval_minutes": 30}


def test_reconcile_creates_windowed_when_missing():
    cfg = {"resilience_enabled": True, "patrol_enabled": False, **_BASE}
    with patch("src.scheduler.is_windowed_task", return_value=False), \
         patch("src.scheduler.is_legacy_task", return_value=False), \
         patch("src.scheduler.is_patrol_task", return_value=False), \
         patch("src.scheduler.create_windowed_task") as create_win, \
         patch("src.scheduler.create_patrol_task") as create_patrol, \
         patch("src.scheduler.remove_scheduled_task") as remove:
        changed = selfheal.reconcile_scheduler(cfg)
    assert changed is True
    create_win.assert_called_once_with("06:55", 60, 5)
    create_patrol.assert_not_called()
    remove.assert_not_called()


def test_reconcile_migrates_legacy_core():
    cfg = {"resilience_enabled": True, "patrol_enabled": False, **_BASE}
    with patch("src.scheduler.is_windowed_task", return_value=False), \
         patch("src.scheduler.is_legacy_task", return_value=True), \
         patch("src.scheduler.is_patrol_task", return_value=False), \
         patch("src.scheduler.create_windowed_task") as create_win:
        changed = selfheal.reconcile_scheduler(cfg)
    assert changed is True
    create_win.assert_called_once_with("06:55", 60, 5)


def test_reconcile_noop_when_core_correct():
    cfg = {"resilience_enabled": True, "patrol_enabled": False, **_BASE}
    with patch("src.scheduler.is_windowed_task", return_value=True), \
         patch("src.scheduler.is_legacy_task", return_value=False), \
         patch("src.scheduler.is_patrol_task", return_value=False), \
         patch("src.scheduler.create_windowed_task") as create_win, \
         patch("src.scheduler.remove_scheduled_task") as remove:
        changed = selfheal.reconcile_scheduler(cfg)
    assert changed is False
    create_win.assert_not_called()
    remove.assert_not_called()


def test_reconcile_not_changed_when_create_fails():
    """创建任务失败（PowerShell 报错）→ changed 为 False，不谎报成功。"""
    cfg = {"resilience_enabled": True, "patrol_enabled": False, **_BASE}
    with patch("src.scheduler.is_windowed_task", return_value=False), \
         patch("src.scheduler.is_legacy_task", return_value=False), \
         patch("src.scheduler.is_patrol_task", return_value=False), \
         patch("src.scheduler.create_windowed_task", return_value=False):
        changed = selfheal.reconcile_scheduler(cfg)
    assert changed is False


def test_reconcile_removes_core_when_disabled():
    cfg = {"resilience_enabled": False, "patrol_enabled": False, **_BASE}
    with patch("src.scheduler.is_windowed_task", return_value=True), \
         patch("src.scheduler.is_legacy_task", return_value=False), \
         patch("src.scheduler.is_patrol_task", return_value=False), \
         patch("src.scheduler.remove_scheduled_task") as remove:
        changed = selfheal.reconcile_scheduler(cfg)
    assert changed is True
    # 核心任务用默认名移除
    remove.assert_any_call()


def test_reconcile_creates_patrol_when_enabled():
    cfg = {"resilience_enabled": True, "patrol_enabled": True, **_BASE}
    with patch("src.scheduler.is_windowed_task", return_value=True), \
         patch("src.scheduler.is_legacy_task", return_value=False), \
         patch("src.scheduler.is_patrol_task", return_value=False), \
         patch("src.scheduler.create_patrol_task") as create_patrol:
        changed = selfheal.reconcile_scheduler(cfg)
    assert changed is True
    create_patrol.assert_called_once_with(30)


def test_reconcile_removes_patrol_when_disabled():
    cfg = {"resilience_enabled": True, "patrol_enabled": False, **_BASE}
    with patch("src.scheduler.is_windowed_task", return_value=True), \
         patch("src.scheduler.is_legacy_task", return_value=False), \
         patch("src.scheduler.is_patrol_task", return_value=True), \
         patch("src.scheduler.remove_scheduled_task") as remove:
        changed = selfheal.reconcile_scheduler(cfg)
    assert changed is True
    # 巡逻任务用独立名移除
    remove.assert_called_with(scheduler.PATROL_TASK_NAME)


def test_reconcile_removes_both_when_resilience_off():
    """resilience 关 → 核心与巡逻任务都应移除。"""
    cfg = {"resilience_enabled": False, "patrol_enabled": True, **_BASE}
    with patch("src.scheduler.is_windowed_task", return_value=True), \
         patch("src.scheduler.is_legacy_task", return_value=False), \
         patch("src.scheduler.is_patrol_task", return_value=True), \
         patch("src.scheduler.remove_scheduled_task") as remove:
        changed = selfheal.reconcile_scheduler(cfg)
    assert changed is True
    assert remove.call_count == 2
    calls = remove.call_args_list
    # 核心任务用默认名（无位置参数）
    assert any(c.args == () and not c.kwargs for c in calls)
    # 巡逻任务用独立名
    assert any(c.args == (scheduler.PATROL_TASK_NAME,) for c in calls)
