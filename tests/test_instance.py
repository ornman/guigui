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
