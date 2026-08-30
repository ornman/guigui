"""凭据保险库 — Windows 凭据管理器(keyring / DPAPI 背书)。

纪律(契约 §0):密码只在「login() 上行 → 本模块存储」和「登录时读出」
两个边界流动;任何 API 返回、日志、config 序列化都不含密码。
"""

from __future__ import annotations

import logging

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
