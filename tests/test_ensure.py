from unittest.mock import patch
from src import ensure


def test_plan_logs_in_when_not_logged_in():
    ctx = ensure.EnsureContext(auth_status="not_logged_in", tray_alive=True,
                               cfg={"resilience_enabled": True})
    p = ensure.plan(ctx)
    assert p.should_login is True


def test_plan_skips_login_when_logged_in():
    ctx = ensure.EnsureContext(auth_status="logged_in", tray_alive=True,
                               cfg={"resilience_enabled": True})
    assert ensure.plan(ctx).should_login is False


def test_plan_spawns_tray_when_resilience_and_dead():
    ctx = ensure.EnsureContext(auth_status="logged_in", tray_alive=False,
                               cfg={"resilience_enabled": True})
    assert ensure.plan(ctx).should_spawn_tray is True


def test_plan_no_spawn_when_resilience_off():
    ctx = ensure.EnsureContext(auth_status="logged_in", tray_alive=False,
                               cfg={"resilience_enabled": False})
    assert ensure.plan(ctx).should_spawn_tray is False


def test_run_orchestrates_login_spawn_reconcile_and_quiet_when_nothing_recovered():
    cfg = {"resilience_enabled": True, "username": "u", "password": "p",
           "notification_enabled": True, "scheduled_login_time": "06:55",
           "heartbeat_interval_minutes": 15}
    with patch("src.ensure.config") as mcfg, \
         patch("src.ensure.login_mod") as mlogin, \
         patch("src.ensure.instance") as minst, \
         patch("src.ensure.selfheal") as mheal, \
         patch("src.ensure.notify") as mnotify, \
         patch("src.ensure._spawn_tray_detached") as mspawn:
        mcfg.load.return_value = cfg
        mlogin.check_auth_status.return_value = "logged_in"
        minst.tray_is_running.return_value = True  # 托盘在跑，不拉起
        code = ensure.run()
    assert code == 0
    mspawn.assert_not_called()
    mnotify.send.assert_not_called()  # 没发生恢复 → 静默
    mheal.reconcile_autostart.assert_called_once()


def test_run_spawns_tray_and_notifies_when_recovered():
    cfg = {"resilience_enabled": True, "username": "u", "password": "p",
           "notification_enabled": True, "scheduled_login_time": "06:55",
           "heartbeat_interval_minutes": 15}
    with patch("src.ensure.config") as mcfg, \
         patch("src.ensure.login_mod") as mlogin, \
         patch("src.ensure.instance") as minst, \
         patch("src.ensure.selfheal") as mheal, \
         patch("src.ensure.notify") as mnotify, \
         patch("src.ensure._spawn_tray_detached") as mspawn:
        mcfg.load.return_value = cfg
        mlogin.check_auth_status.return_value = "not_logged_in"
        mlogin.attempt_login.return_value = "success"
        minst.tray_is_running.return_value = False  # 托盘没活 → 拉起
        code = ensure.run()
    assert code == 0
    mlogin.attempt_login.assert_called_once()
    mspawn.assert_called_once()
    mnotify.send.assert_called_once()  # 发生恢复 → 通知


def test_run_skips_when_no_credentials():
    with patch("src.ensure.config") as mcfg:
        mcfg.load.return_value = {"username": "", "password": ""}
        assert ensure.run() == 0
