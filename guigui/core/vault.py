"""凭据保险库 — Windows 凭据管理器(keyring / DPAPI 背书)。

纪律(契约 §0):密码只在「login() 上行 → 本模块存储」和「登录时读出」
两个边界流动;任何 API 返回、日志、config 序列化都不含密码。

两层降级(QA P1-4):keyring 库异常(包导入失败 / Python 启动时坏)时,
凭据管理器作为系统服务还可能活着 — 同一个 DLL 还能直调 CredWriteW/
CredReadW/CredDeleteW,安全属性(CRED_TYPE_GENERIC + 用户作用域)不变。
两者都挂才抛 VaultError。
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


# ── advapi32 直调(降级层,与 WinVaultKeyring 同 CRED_TYPE_GENERIC)──

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2


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


def _target(uid: str) -> str:
    return f"{uid}@{_SERVICE}"


def _blob(password: str) -> bytes:
    """凭据 blob:UTF-16-LE 编码(WinVaultKeyring 同款)。"""
    return password.encode("utf-16-le")


def _direct_set(target: str, password: str) -> None:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    blob = _blob(password)
    blob_size = wintypes.DWORD(len(blob))
    blob_buf = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
    cred = _CREDENTIALW()
    cred.Flags = 0
    cred.Type = _CRED_TYPE_GENERIC
    cred.TargetName = ctypes.c_wchar_p(target)
    cred.CredentialBlobSize = blob_size
    cred.CredentialBlob = ctypes.cast(blob_buf, ctypes.POINTER(ctypes.c_byte))
    cred.Persist = _CRED_PERSIST_LOCAL_MACHINE
    cred.AttributeCount = 0
    if not advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise OSError(ctypes.get_last_error())


def _direct_get(target: str) -> str | None:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    pcred = ctypes.POINTER(_CREDENTIALW)()
    if not advapi32.CredReadW(ctypes.c_wchar_p(target), _CRED_TYPE_GENERIC, 0,
                              ctypes.byref(pcred)):
        err = ctypes.get_last_error()
        if err == 1168:    # ERROR_NOT_FOUND
            return None
        raise OSError(err)
    try:
        size = pcred.contents.CredentialBlobSize
        buf = (ctypes.c_byte * size).from_address(
            ctypes.cast(pcred.contents.CredentialBlob, ctypes.c_void_p).value or 0)
        return bytes(buf).decode("utf-16-le")
    finally:
        advapi32.CredFree(pcred)


def _direct_delete(target: str) -> None:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    if not advapi32.CredDeleteW(ctypes.c_wchar_p(target), _CRED_TYPE_GENERIC, 0):
        err = ctypes.get_last_error()
        if err != 1168:    # ERROR_NOT_FOUND 视为幂等成功
            raise OSError(err)


# ── 公共 API:主路 keyring + 降级 advapi32 ──────────────


def set_password(uid: str, password: str) -> None:
    if not uid or not password:
        raise VaultError("学号与密码不能为空")
    target = _target(uid)
    try:
        keyring.set_password(_SERVICE, uid, password)
        return
    except Exception as e:
        log.warning("vault: set 主路失败(%s),降级 advapi32", type(e).__name__)
    try:
        _direct_set(target, password)
    except Exception as e:
        raise VaultError(f"凭据管理器操作失败(set): {e}") from e


def get_password(uid: str) -> str | None:
    """读取密码:主路 keyring → 降级 advapi32;都拿不到返回 None(不抛)。

    VaultError 仅在调用方显式要求严格模式时抛出;日常读路径吞掉异常
    转 None(契约 §0「密码永不下行」,读失败不该让上层判错)。"""
    if not uid:
        return None
    target = _target(uid)
    try:
        pw = keyring.get_password(_SERVICE, uid)
        if pw is not None:
            return pw
    except Exception as e:
        log.warning("vault: get 主路失败(%s),降级 advapi32", type(e).__name__)
    try:
        return _direct_get(target)
    except VaultError:
        raise
    except Exception as e:
        log.warning("vault: get 降级也失败(uid=%s…): %s", uid[:4], e)
        return None


def has_password(uid: str) -> bool:
    return get_password(uid) is not None


def delete_password(uid: str) -> None:
    """删除凭据;条目不存在视为成功(幂等)。"""
    if not uid:
        return
    target = _target(uid)
    try:
        try:
            keyring.delete_password(_SERVICE, uid)
        except Exception as e:
            log.warning("vault: delete 主路失败(%s),降级 advapi32", type(e).__name__)
            _direct_delete(target)
    except VaultError:
        raise
    except Exception:
        # keyring 对不存在条目可能抛错,统一吞掉(幂等删除);advapi32 同样
        # 1168 视为成功。其它异常 = 凭据管理器不可用,调用方按 VaultError
        # 处理
        pass


def rekey(old_uid: str | None, new_uid: str, password: str) -> None:
    """学号变更:写新条目 + 清旧条目(旧密码不复用,调用方传新密码)。"""
    set_password(new_uid, password)
    if old_uid and old_uid != new_uid:
        delete_password(old_uid)


# ── 卸载全删(枚举式)────────────────────────────────────


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
