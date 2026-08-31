"""单实例锁的单元测试。

通过 create_func 依赖注入 mock Win32 调用，不依赖真实操作系统。
"""

from unittest.mock import MagicMock
from src import instance


def test_acquire_when_no_existing_mutex():
    """create 返回非零 handle、last_error=0 → 抢到互斥量。"""
    # create 返回非零 handle、last_error=0 → 抢到
    fake_create = MagicMock(return_value=(42, 0))
    si = instance.SingleInstance(create_func=fake_create)
    assert si.acquire() is True
    fake_create.assert_called_once()


def test_acquire_fails_when_already_exists():
    """create 返回 ERROR_ALREADY_EXISTS → 另一实例已在运行。"""
    fake_create = MagicMock(return_value=(42, 183))  # ERROR_ALREADY_EXISTS
    si = instance.SingleInstance(create_func=fake_create)
    assert si.acquire() is False


def test_release_is_idempotent():
    """重复释放不报错。"""
    fake_create = MagicMock(return_value=(42, 0))
    si = instance.SingleInstance(create_func=fake_create)
    si.acquire()
    si.release()
    si.release()  # 重复释放不报错


def test_acquire_closes_handle_on_collision():
    """抢不到互斥量时，CreateMutex 返回的句柄也必须被关闭（防泄漏）。"""
    fake_create = MagicMock(return_value=(42, 183))  # ERROR_ALREADY_EXISTS
    fake_close = MagicMock(return_value=True)
    si = instance.SingleInstance(create_func=fake_create, close_func=fake_close)
    assert si.acquire() is False
    fake_close.assert_called_once_with(42)


def test_release_goes_through_close_func():
    fake_create = MagicMock(return_value=(42, 0))
    fake_close = MagicMock(return_value=True)
    si = instance.SingleInstance(create_func=fake_create, close_func=fake_close)
    si.acquire()
    si.release()
    fake_close.assert_called_once_with(42)


def test_release_noop_after_failed_acquire():
    """acquire 失败后 release 不应调用 close（没有句柄可关）。"""
    fake_create = MagicMock(return_value=(42, 183))
    fake_close = MagicMock(return_value=True)
    si = instance.SingleInstance(create_func=fake_create, close_func=fake_close)
    si.acquire()  # 失败，已自行关掉句柄
    fake_close.reset_mock()
    si.release()  # 此时无句柄，应无操作
    fake_close.assert_not_called()


def test_tray_is_running_true_when_mutex_exists():
    """已有实例时 tray_is_running 返回 True。"""
    fake_create = MagicMock(return_value=(42, 183))
    fake_close = MagicMock(return_value=True)
    assert instance.tray_is_running(create_func=fake_create, close_func=fake_close) is True
    fake_close.assert_called_once_with(42)  # 探测句柄已关闭


def test_tray_is_running_false_when_no_instance():
    """无实例时抢到互斥量，释放后返回 False。"""
    fake_create = MagicMock(return_value=(42, 0))
    fake_close = MagicMock(return_value=True)
    assert instance.tray_is_running(create_func=fake_create, close_func=fake_close) is False
    assert fake_close.call_count == 1  # release 关掉抢到的句柄
