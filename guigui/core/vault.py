"""凭据保险库 — Windows 凭据管理器(keyring / DPAPI 背书)。

纪律(契约 §0):密码只在「login() 上行 → 本模块存储」和「登录时读出」
两个边界流动;任何 API 返回、日志、config 序列化都不含密码。
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

import keyring

log = logging.getLogger(__name__)

_SERVICE = "GuiGui"


class VaultError(RuntimeError):
    """凭据管理器不可用或操作失败。不回退明文落盘。"""


def _guard(fn, *args):
    try:
        return fn(_SERVICE, *args)
    except Exception as e:  # keyring 各后端异常类型不统一,统一收口
        raise VaultError(f"凭据管理器操作失败: {e}") from e


def set_password(uid: str, password: str) -> None:
    if not uid or not password:
        raise VaultError("学号与密码不能为空")
    _guard(keyring.set_password, uid, password)


def get_password(uid: str) -> str | None:
    if not uid:
        return None
    try:
        return _guard(keyring.get_password, uid)
    except VaultError:
        log.warning("vault: 读取凭据失败(uid=%s…)", uid[:4])
        return None


def has_password(uid: str) -> bool:
    return get_password(uid) is not None


def delete_password(uid: str) -> None:
    """删除凭据;条目不存在视为成功。"""
    if not uid:
        return
    try:
        _guard(keyring.delete_password, uid)
    except VaultError:
        # keyring 对不存在条目可能抛错,统一吞掉(幂等删除)
        pass


def rekey(old_uid: str | None, new_uid: str, password: str) -> None:
    """学号变更:写新条目 + 清旧条目(旧密码不复用,调用方传新密码)。"""
    set_password(new_uid, password)
    if old_uid and old_uid != new_uid:
        delete_password(old_uid)


# ── 卸载全删(枚举式)────────────────────────────────────


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_CRED_TYPE_GENERIC = 1


def _enum_targets_default() -> list[str]:
    """枚举当前用户全部凭据目标名(keyring 无枚举 API,直接走 advapi32)。"""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    count = wintypes.DWORD()
    pcreds = ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))()
    if not advapi32.CredEnumerateW(None, 0, ctypes.byref(count),
                                   ctypes.byref(pcreds)):
        if ctypes.get_last_error() == 1168:   # ERROR_NOT_FOUND:本用户无任何凭据
            return []
        raise OSError(ctypes.get_last_error())
    try:
        return [pcreds[i].contents.TargetName for i in range(count.value)]
    finally:
        advapi32.CredFree(pcreds)


def _delete_target_default(target: str) -> bool:
    return bool(ctypes.windll.advapi32.CredDeleteW(
        target, _CRED_TYPE_GENERIC, 0))


def delete_all_service_entries(enum_targets=None, delete_target=None) -> int:
    """删除凭据管理器中本服务全部条目(目标名 <学号>@GuiGui)。

    卸载「彻底清理」用:不依赖 config 当前学号,历史遗留条目一并清。
    返回删除条数;枚举失败抛 VaultError(调用方回退逐条删);
    单条删除失败不挡其余。enum/delete 可注入,便于单测。"""
    enum_targets = enum_targets or _enum_targets_default
    delete_target = delete_target or _delete_target_default
    suffix = "@" + _SERVICE
    try:
        targets = list(enum_targets())
    except Exception as e:
        raise VaultError(f"凭据枚举失败: {e}") from e
    deleted = 0
    for target in targets:
        if target and target.endswith(suffix):
            try:
                if delete_target(target):
                    deleted += 1
            except Exception:
                continue
    return deleted
