from unittest.mock import patch
from src import selfheal


def test_should_autostart_when_resilience_on():
    assert selfheal.should_autostart_be_enabled({"resilience_enabled": True, "auto_start": False}) is True


def test_should_not_autostart_when_both_off():
    assert selfheal.should_autostart_be_enabled({"resilience_enabled": False, "auto_start": False}) is False


def test_reconcile_autostart_enables_when_missing():
    with patch("src.autostart.is_enabled", return_value=False), \
         patch("src.autostart.enable") as enable:
        changed = selfheal.reconcile_autostart({"resilience_enabled": True})
    assert changed is True
    enable.assert_called_once()


def test_reconcile_autostart_noop_when_aligned():
    with patch("src.autostart.is_enabled", return_value=True), \
         patch("src.autostart.enable") as enable:
        changed = selfheal.reconcile_autostart({"resilience_enabled": True})
    assert changed is False
    enable.assert_not_called()


def test_reconcile_scheduler_recreates_when_missing():
    with patch("src.scheduler.get_scheduled_task_info",
               return_value={"exists": False}), \
         patch("src.scheduler.is_legacy_task", return_value=False), \
         patch("src.scheduler.create_scheduled_task_multi") as create:
        changed = selfheal.reconcile_scheduler(
            {"resilience_enabled": True, "scheduled_login_enabled": True,
             "scheduled_login_time": "06:55", "heartbeat_interval_minutes": 15})
    assert changed is True
    create.assert_called_once_with("06:55", 15)


def test_reconcile_scheduler_migrates_legacy():
    with patch("src.scheduler.get_scheduled_task_info",
               return_value={"exists": True}), \
         patch("src.scheduler.is_legacy_task", return_value=True), \
         patch("src.scheduler.create_scheduled_task_multi") as create:
        changed = selfheal.reconcile_scheduler(
            {"resilience_enabled": True, "scheduled_login_enabled": True,
             "scheduled_login_time": "07:00", "heartbeat_interval_minutes": 20})
    assert changed is True
    create.assert_called_once_with("07:00", 20)


def test_reconcile_scheduler_removes_when_disabled():
    with patch("src.scheduler.get_scheduled_task_info",
               return_value={"exists": True}), \
         patch("src.scheduler.remove_scheduled_task") as remove:
        changed = selfheal.reconcile_scheduler(
            {"resilience_enabled": False, "scheduled_login_enabled": False})
    assert changed is True
    remove.assert_called_once()
