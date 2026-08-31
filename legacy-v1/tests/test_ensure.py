"""ensure：治弹窗（不拉 GUI）+ 完整重连 + 状态翻转通知去重。"""

import json
from unittest.mock import patch

from src import ensure


# ── decide_notify 纯函数（跨进程去重核心）──────────────────────


def test_decide_recovered_from_down():
    n, s = ensure.decide_notify("down", connected=True,
                                login_attempted=True, login_succeeded=True)
    assert (n, s) == ("recovered", "up")


def test_decide_recovered_from_failed():
    n, s = ensure.decide_notify("failed", connected=True,
                                login_attempted=True, login_succeeded=True)
    assert (n, s) == ("recovered", "up")


def test_decide_steady_up_no_notify():
    assert ensure.decide_notify("up", connected=True,
                                login_attempted=False, login_succeeded=False) == (None, "up")


def test_decide_first_run_up_no_notify():
    """首次运行且本就在线 → 不打扰。"""
    assert ensure.decide_notify(None, connected=True,
                                login_attempted=False, login_succeeded=False) == (None, "up")


def test_decide_failed_once():
    assert ensure.decide_notify(None, connected=False,
                                login_attempted=True, login_succeeded=False) == ("failed", "failed")


def test_decide_no_repeat_failed():
    """上次已 failed → 本次仍失败不重复通知。"""
    assert ensure.decide_notify("failed", connected=False,
                                login_attempted=True, login_succeeded=False) == (None, "failed")


def test_decide_down_unreachable_no_spam():
    """断网但未尝试登录（服务器不可达）→ 不通知，避免刷屏。"""
    assert ensure.decide_notify("down", connected=False,
                                login_attempted=False, login_succeeded=False) == (None, "down")


def test_decide_failed_then_recovered_flips():
    """failed → 恢复 → 再 failed：每次翻转都通知一次。"""
    assert ensure.decide_notify("failed", connected=True,
                                login_attempted=True, login_succeeded=True)[0] == "recovered"
    assert ensure.decide_notify("up", connected=False,
                                login_attempted=True, login_succeeded=False)[0] == "failed"


# ── run 编排 ─────────────────────────────────────────


_CREDS = {"username": "u", "password": "p", "notification_enabled": True}


def _state_file(tmp_path, last_state):
    p = tmp_path / "ensure_state.json"
    if last_state is not None:
        p.write_text(json.dumps({"last_state": last_state}), encoding="utf-8")
    return p


def test_run_notifies_recovered_on_flip(tmp_path):
    state = _state_file(tmp_path, "down")
    with patch("src.ensure.config") as mcfg, \
         patch("src.ensure.login_mod") as mlogin, \
         patch("src.ensure.notify") as mnotify, \
         patch("src.ensure.STATE_PATH", state):
        mcfg.load.return_value = _CREDS
        mlogin.check_auth_status.side_effect = ["not_logged_in", "logged_in"]
        mlogin.attempt_login.return_value = "success"
        code = ensure.run()
    assert code == 0
    mlogin.attempt_login.assert_called_once()  # 完整重连（无 skip_wifi）
    # 确认没有传 skip_wifi=True
    _, kwargs = mlogin.attempt_login.call_args
    assert kwargs.get("skip_wifi") in (None, False)
    mnotify.send.assert_called_once()
    assert "恢复" in mnotify.send.call_args.args[0]
    # 状态翻转为 up
    assert json.loads(state.read_text(encoding="utf-8"))["last_state"] == "up"


def test_run_quiet_when_already_logged_in(tmp_path):
    state = _state_file(tmp_path, "up")
    with patch("src.ensure.config") as mcfg, \
         patch("src.ensure.login_mod") as mlogin, \
         patch("src.ensure.notify") as mnotify, \
         patch("src.ensure.STATE_PATH", state):
        mcfg.load.return_value = _CREDS
        mlogin.check_auth_status.return_value = "logged_in"
        ensure.run()
    mlogin.attempt_login.assert_not_called()
    mnotify.send.assert_not_called()


def test_run_notifies_failed_once_then_quiet(tmp_path):
    """连续两次失败：第一次通知，第二次静默。"""
    state = _state_file(tmp_path, None)
    with patch("src.ensure.config") as mcfg, \
         patch("src.ensure.login_mod") as mlogin, \
         patch("src.ensure.notify") as mnotify, \
         patch("src.ensure.STATE_PATH", state):
        mcfg.load.return_value = _CREDS
        mlogin.check_auth_status.return_value = "not_logged_in"
        mlogin.attempt_login.return_value = "failed"
        ensure.run()
    mnotify.send.assert_called_once()  # 第一次：failed

    # 第二次心跳（状态已是 failed）
    with patch("src.ensure.config") as mcfg, \
         patch("src.ensure.login_mod") as mlogin, \
         patch("src.ensure.notify") as mnotify, \
         patch("src.ensure.STATE_PATH", state):
        mcfg.load.return_value = _CREDS
        mlogin.check_auth_status.return_value = "not_logged_in"
        mlogin.attempt_login.return_value = "failed"
        ensure.run()
    mnotify.send.assert_not_called()  # 不重复


def test_run_quiet_when_unreachable_and_not_attempted(tmp_path):
    """服务器不可达（未尝试登录）→ 不通知。"""
    state = _state_file(tmp_path, "up")
    with patch("src.ensure.config") as mcfg, \
         patch("src.ensure.login_mod") as mlogin, \
         patch("src.ensure.notify") as mnotify, \
         patch("src.ensure.STATE_PATH", state):
        mcfg.load.return_value = _CREDS
        mlogin.check_auth_status.return_value = "unreachable"
        ensure.run()
    mlogin.attempt_login.assert_not_called()
    mnotify.send.assert_not_called()


def test_run_skips_when_no_credentials(tmp_path):
    state = _state_file(tmp_path, None)
    with patch("src.ensure.config") as mcfg, \
         patch("src.ensure.notify") as mnotify, \
         patch("src.ensure.STATE_PATH", state):
        mcfg.load.return_value = {"username": "", "password": ""}
        assert ensure.run() == 0
    mnotify.send.assert_not_called()


def test_run_never_spawns_gui(tmp_path):
    """治弹窗核心：--ensure 绝不拉起 GUI/托盘进程（无 subprocess.Popen）。"""
    state = _state_file(tmp_path, "down")
    with patch("src.ensure.config") as mcfg, \
         patch("src.ensure.login_mod") as mlogin, \
         patch("src.ensure.notify"), \
         patch("src.ensure.STATE_PATH", state), \
         patch("subprocess.Popen") as mpopen:
        mcfg.load.return_value = _CREDS
        mlogin.check_auth_status.side_effect = ["not_logged_in", "logged_in"]
        mlogin.attempt_login.return_value = "success"
        ensure.run()
    mpopen.assert_not_called()


def test_run_survives_login_exception(tmp_path):
    state = _state_file(tmp_path, None)
    with patch("src.ensure.config") as mcfg, \
         patch("src.ensure.login_mod") as mlogin, \
         patch("src.ensure.notify") as mnotify, \
         patch("src.ensure.STATE_PATH", state):
        mcfg.load.return_value = _CREDS
        mlogin.check_auth_status.return_value = "not_logged_in"
        mlogin.attempt_login.side_effect = RuntimeError("boom")
        code = ensure.run()
    assert code == 0  # 不崩溃
