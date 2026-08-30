"""GUI 单实例锁 — Win32 命名互斥量(v1 src/instance.py 移植)。

进程退出(含崩溃)时 OS 自动回收互斥量;抢不到时必须关掉返回的句柄,
否则每次探测泄漏一个内核句柄(v1 已修的坑,一并移植)。
"""

from __future__ import annotations

import ctypes
import logging
from collections.abc import Callable
from ctypes import wintypes

log = logging.getLogger(__name__)

_MUTEX_NAME = "Local\\GuiGui-GUI"   # 会话级,无需 SeCreateGlobalPrivilege
_ERROR_ALREADY_EXISTS = 183

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _default_create_mutex(name: str) -> tuple[int, int]:
    handle = _kernel32.CreateMutexW(None, False, name)
    return int(handle or 0), ctypes.get_last_error()


def _default_close_handle(handle: int) -> bool:
    return bool(_kernel32.CloseHandle(handle))


class SingleInstance:
    """持有命名互斥量;acquire 返回是否抢到(本进程是否为主实例)。"""

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
            self._close(handle)   # 抢不到也要关句柄,防泄漏
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is not None:
            if not self._close(self._handle):
                log.warning("CloseHandle 失败")
            self._handle = None
