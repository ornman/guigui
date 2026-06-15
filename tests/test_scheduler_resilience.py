from unittest.mock import patch, MagicMock
from src import scheduler


def _capture_ps(func):
    """捕获传给 powershell 的 -Command 字符串。"""
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return MagicMock(returncode=0, stderr="", stdout="")

    return captured, fake_run


def test_create_multi_task_has_three_triggers_and_ensure_arg():
    captured, fake = _capture_ps(scheduler.create_scheduled_task_multi)
    with patch("subprocess.run", side_effect=fake):
        scheduler.create_scheduled_task_multi("06:55", interval_minutes=15)
    ps = " ".join(captured["cmd"])
    assert "--ensure" in ps
    assert "-AtLogOn" in ps
    assert "RepetitionInterval" in ps
    assert "New-TimeSpan -Minutes 15" in ps
    assert "-Daily -At '06:55:00'" in ps
    assert "IgnoreNew" in ps  # 防止重叠实例堆积


def test_create_multi_atlogon_scoped_to_current_user():
    """AtLogon 触发器必须限定到当前用户，否则非管理员无法注册（机器级 any-user 触发器需提权）。

    回归：缺 -User 时 Register-ScheduledTask 在非 admin 会话返回 0x80070005 拒绝访问，
    导致 resilience 自愈（重建/迁移任务）对普通用户失效。
    """
    captured, fake = _capture_ps(scheduler.create_scheduled_task_multi)
    with patch("subprocess.run", side_effect=fake):
        scheduler.create_scheduled_task_multi("06:55", interval_minutes=5)
    ps = " ".join(captured["cmd"])
    assert "-AtLogOn -User $env:USERNAME" in ps


def test_is_legacy_task_detects_silent():
    fake = MagicMock(returncode=0, stdout="<Task><Actions>...--silent...</Actions></Task>")
    with patch("subprocess.run", return_value=fake):
        assert scheduler.is_legacy_task() is True


def test_is_legacy_task_false_for_new_ensure_task():
    fake = MagicMock(returncode=0, stdout="<Task>...--ensure...</Task>")
    with patch("subprocess.run", return_value=fake):
        assert scheduler.is_legacy_task() is False


def test_is_legacy_task_false_when_missing():
    fake = MagicMock(returncode=1, stdout="")
    with patch("subprocess.run", return_value=fake):
        assert scheduler.is_legacy_task() is False


def test_create_multi_rejects_bad_time():
    """非法 time_str 时直接返回 False，不调用 subprocess。"""
    with patch("subprocess.run") as run:
        assert scheduler.create_scheduled_task_multi("6:55") is False
        run.assert_not_called()


def test_create_multi_rejects_bad_interval():
    """interval_minutes < 1 或非整数时直接返回 False，不调用 subprocess。"""
    with patch("subprocess.run") as run:
        assert scheduler.create_scheduled_task_multi("06:55", interval_minutes=0) is False
        assert scheduler.create_scheduled_task_multi("06:55", interval_minutes=-5) is False
        run.assert_not_called()
