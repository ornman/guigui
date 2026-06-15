"""单实例锁：Win32 命名互斥量（ctypes 实现，无 pywin32 依赖）。

进程退出（含崩溃）时 OS 自动回收互斥量，不会留死锁。
"""

import ctypes
import logging
from collections.abc import Callable
from ctypes import wintypes

log = logging.getLogger(__name__)

# Local\ 前缀：会话级互斥量，无需 SeCreateGlobalPrivilege 权限
_MUTEX_NAME = "Local\\SchoolAutoLogin-Instance"
_ERROR_ALREADY_EXISTS = 183

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _default_create_mutex(name: str) -> tuple[int, int]:
    """调用 Win32 CreateMutexW，返回 (handle, last_error)。"""
    handle = _kernel32.CreateMutexW(None, False, name)
    return int(handle or 0), ctypes.get_last_error()


def _default_close_handle(handle: int) -> bool:
    """调用 Win32 CloseHandle，返回是否成功。"""
    return bool(_kernel32.CloseHandle(handle))


class SingleInstance:
    """持有命名互斥量；acquire 返回是否抢到（本进程是否为主实例）。"""

    def __init__(
        self,
        name: str = _MUTEX_NAME,
        create_func: Callable[[str], tuple[int, int]] | None = None,
        close_func: Callable[[int], bool] | None = None,
    ):
        self._name = name
        self._create = create_func or _default_create_mutex
        self._close = close_func or _default_close_handle
        self._handle: int | None = None

    def acquire(self) -> bool:
        handle, err = self._create(self._name)
        if not handle:
            log.error("CreateMutex 失败: err=%d", err)
            return False
        if err == _ERROR_ALREADY_EXISTS:
            # 抢不到也要关掉 CreateMutex 返回的句柄，否则每次探测泄漏一个内核句柄
            self._close(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is not None:
            if not self._close(self._handle):
                log.warning("CloseHandle 失败")
            self._handle = None


def tray_is_running(
    name: str = _MUTEX_NAME,
    create_func: Callable[[str], tuple[int, int]] | None = None,
    close_func: Callable[[int], bool] | None = None,
) -> bool:
    """探测托盘是否在跑：尝试抢互斥量，抢不到=有人在跑。抢到则立即释放。"""
    si = SingleInstance(name, create_func=create_func, close_func=close_func)
    got = si.acquire()
    if got:
        si.release()
        return False
    return True
