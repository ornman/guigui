"""凭据保险库 — Windows 凭据管理器(keyring / DPAPI 背书)+ 备份库自愈链(1.6.0)。

纪律(契约 §0):密码只在「login() 上行 → 本模块存储」和「登录时读出」
两个边界流动;任何 API 返回、日志、config 序列化都不含密码。

两层降级(QA P1-4):keyring 库异常(包导入失败 / Python 启动时坏)时,
凭据管理器作为系统服务还可能活着 — 同一个 DLL 还能直调 CredWriteW/
CredReadW/CredDeleteW,安全属性(CRED_TYPE_GENERIC + 用户作用域)不变。
两者都挂才抛 VaultError。

库链(契约 1.6.0,用户拍板 2026-09-11「真做」):每次成功存/读凭据后镜像
备份库 JSON;两层都抛异常(= 凭据管理器真坏)时走自愈链 — 自动重建 ×3
(每轮重新 keyring 存取,轮间不 sleep)→ 3 败降级切备份库 JSON
(vault_state=degraded,登录照常)→ 备份也坏 vault_state=failed(不发通知,
日志 + diagnose 第 5 步可见)。
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import tempfile
from ctypes import wintypes
from pathlib import Path

import keyring

from . import paths

log = logging.getLogger(__name__)

_SERVICE = "GuiGui"

# ── 库链状态机(契约 1.6.0 vault_state 四态)──────────────

STATE_OK = "ok"                  # 凭据管理器正常
STATE_REBUILDING = "rebuilding"  # 损坏自动重建中(3 轮)
STATE_DEGRADED = "degraded"      # 已降级:备份库 JSON 接管,登录照常
STATE_FAILED = "failed"          # 凭据管理器与备份都不可用

REBUILD_ROUNDS = 3               # 拍板:损坏自动重建 ×3


class VaultError(RuntimeError):
    """凭据管理器不可用或操作失败。不回退明文落盘。"""


# ── advapi32 直调(降级层,与 WinVaultKeyring 同 CRED_TYPE_GENERIC)──

_CRED_TYPE_GENERIC = 1
# Persist 只决定「存储寿命」,不改变用户隔离 — CredWriteW/CredReadW 永远
# 落当前用户的凭据库,LOCAL_MACHINE(=2)意为「存本机、跨重启、直至显式删除」,
# 不是「全机共享」;与 keyring WinVault 的兼容要点在 CRED_TYPE_GENERIC(同一
# 条凭据两路互写),其 25.x 默认 Persist=ENTERPRISE(=3),无域个人机上两者
# 存储行为一致(均本机持久、按用户隔离),此处取语义最直白的一档。
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


# ── 备份库 + 状态持久化(契约 1.6.0 库链)────────────────


def backup_path() -> Path:
    """备份库 JSON(数据目录 vault_backup.json;内容 uid + 密码)。

    安全边界(与 advapi32 降级层同口径):不做应用层混淆 — advapi32 直调把
    UTF-16-LE 明文 blob 交给系统凭据管理器,保护责任在 OS(用户作用域);
    本文件落在 %LOCALAPPDATA%\\GuiGui,保护责任在 NTFS 用户目录 ACL。
    两者信任边界等价:同用户进程皆可读。该文件仅作凭据管理器损坏时的
    降级恢复源,永不经 API 返回 / 日志 / config 序列化外泄(契约 §0)。"""
    return paths.data_dir() / "vault_backup.json"


def _state_path() -> Path:
    """库链状态独立小文件(不塞进备份库:备份损坏时状态仍可读)。"""
    return paths.data_dir() / "vault_state.json"


def _atomic_write(path: Path, payload: dict) -> None:
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp",
                                   prefix=".vault_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        log.warning("vault: 落盘失败(%s): %s", path.name, e)
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def get_state() -> str:
    """当前 vault_state(四态;每次直读状态小文件,不进程缓存 —
    ensure/GUI 双进程都要读到对方的最新状态)。备份/状态文件缺失 = ok
    (从未存过凭据不算坏)。"""
    try:
        raw = json.loads(_state_path().read_text(encoding="utf-8"))
        value = raw.get("vault_state") if isinstance(raw, dict) else None
    except (OSError, ValueError):
        value = None
    if value not in (STATE_OK, STATE_REBUILDING, STATE_DEGRADED, STATE_FAILED):
        value = STATE_OK
    return value


def _set_state(value: str) -> None:
    if get_state() == value:
        return
    _atomic_write(_state_path(), {"vault_state": value})


def _read_backup() -> dict | None:
    """读备份库;缺失/损坏/形状不对返回 None(不抛)。"""
    try:
        raw = json.loads(backup_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    uid = raw.get("uid") or ""
    pw = raw.get("password") or ""
    return {"uid": uid, "password": pw} if uid and pw else None


def _mirror_backup(uid: str, password: str) -> None:
    """成功存/读后镜像备份库;内容未变跳过(防每拍重写)。"""
    cur = _read_backup()
    if cur and cur["uid"] == uid and cur["password"] == password:
        return
    _atomic_write(backup_path(), {"uid": uid, "password": password})


def _remove_backup_if(uid: str) -> None:
    """删除条目时同步清备份(仅备份还指向同一学号时,防误清新凭据镜像)。"""
    cur = _read_backup()
    if cur and cur["uid"] == uid:
        try:
            backup_path().unlink()
        except OSError:
            pass


# ── 公共 API:主路 keyring + 降级 advapi32 + 库链自愈 ─────


def _fetch(uid: str) -> tuple[str | None, bool]:
    """裸读(不递归库链):返回 (密码|None, 是否两层都抛异常)。

    两层都异常 = 凭据管理器真坏(条目缺失时两层干净地返回 None,不算坏)。"""
    target = _target(uid)
    keyring_err = advapi_err = False
    try:
        pw = keyring.get_password(_SERVICE, uid)
        if pw is not None:
            return pw, False
    except Exception as e:
        log.warning("vault: get 主路失败(%s),降级 advapi32", type(e).__name__)
        keyring_err = True
    try:
        pw = _direct_get(target)
        if pw is not None:
            return pw, False
    except Exception as e:
        log.warning("vault: get 降级也失败(uid=%s…): %s", uid[:4], e)
        advapi_err = True
    return None, keyring_err and advapi_err


def _store(uid: str, password: str) -> None:
    """裸存(不镜像、不动状态;重建轮复用):keyring → advapi32,失败抛异常。"""
    target = _target(uid)
    try:
        keyring.set_password(_SERVICE, uid, password)
        return
    except Exception as e:
        log.warning("vault: set 主路失败(%s),降级 advapi32", type(e).__name__)
    _direct_set(target, password)


def _rebuild_or_degrade(uid: str) -> str | None:
    """库链自愈:重建 ×3 → 3 败降级备份接管 → 备份也坏 failed。

    返回可用的密码(degraded 时来自备份)或 None;状态迁移全程落盘,
    recentResult.vault_state / diagnose 第 5 步据此可见。不发任何通知
    (拍板:库降级后端自动处理,不打扰用户)。"""
    backup = _read_backup()
    if backup is None:
        _set_state(STATE_FAILED)
        log.error("vault: 凭据管理器与备份库都不可用(vault_state=failed)")
        return None
    _set_state(STATE_REBUILDING)
    for _round in range(REBUILD_ROUNDS):   # 轮间不 sleep(拍板:秒级重试不等)
        try:
            _store(backup["uid"], backup["password"])
            got, still_broken = _fetch(backup["uid"])
            if not still_broken and got == backup["password"]:
                _set_state(STATE_OK)
                log.info("vault: 凭据管理器第 %d 轮重建成功(vault_state=ok)",
                         _round + 1)
                return got if backup["uid"] == uid else None
        except Exception as e:
            log.warning("vault: 重建第 %d 轮失败: %s", _round + 1, e)
    _set_state(STATE_DEGRADED)
    log.warning("vault: %d 轮重建未成,备份库接管(vault_state=degraded)",
                REBUILD_ROUNDS)
    return backup["password"] if backup["uid"] == uid else None


def set_password(uid: str, password: str) -> None:
    if not uid or not password:
        raise VaultError("学号与密码不能为空")
    try:
        _store(uid, password)
    except Exception as e:
        # 存路径不走备份兜底(拍板口径:存不上就如实 VaultError,P1-4 语义不变)
        raise VaultError(f"凭据管理器操作失败(set): {e}") from e
    _set_state(STATE_OK)
    _mirror_backup(uid, password)


def get_password(uid: str) -> str | None:
    """读取密码:主路 keyring → 降级 advapi32 → 库链自愈(1.6.0)。

    两层干净地说「没有条目」→ None(不抛);两层都抛 = 凭据管理器真坏 →
    重建 ×3 → 3 败降级备份接管(返回备份里的密码,登录不中断)。
    VaultError 仅在调用方显式要求严格模式时抛出;日常读路径吞掉异常
    转 None(契约 §0「密码永不下行」,读失败不该让上层判错)。"""
    if not uid:
        return None
    pw, broken = _fetch(uid)
    if not broken:
        if pw is not None:
            _set_state(STATE_OK)
            _mirror_backup(uid, pw)
        return pw
    return _rebuild_or_degrade(uid)


def has_password(uid: str) -> bool:
    return get_password(uid) is not None


def delete_password(uid: str) -> None:
    """删除凭据;条目不存在视为成功(幂等)。备份库同步清(同 uid 才清)。"""
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
    _remove_backup_if(uid)


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

    卸载「彻底清理」用:不依赖 config 当前学号,历史遗留条目一并清;
    备份库与库链状态文件同批清除(密码不残留磁盘)。返回删除条数;
    枚举失败抛 VaultError(调用方回退逐条删);单条删除失败不挡其余。
    enum/delete 可注入,便于单测。"""
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
    for p in (backup_path(), _state_path()):   # 卸载清盘:备份密码不留磁盘
        try:
            p.unlink()
        except OSError:
            pass
    return deleted
