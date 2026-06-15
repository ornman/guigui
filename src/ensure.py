"""`--ensure` 心跳：幂等登录 + 看门狗 + 自修复。

由任务计划的多触发器调用。默认静默——仅当真发生恢复（重新登录 / 拉起托盘）时才通知。
"""

import logging
import subprocess
import sys
from dataclasses import dataclass

from . import config, instance, login as login_mod, notify, selfheal
from .scheduler import exe_path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnsureContext:
    auth_status: str
    tray_alive: bool
    cfg: dict


@dataclass
class EnsureActions:
    should_login: bool
    should_spawn_tray: bool
    should_reconcile_autostart: bool = True


def plan(ctx: EnsureContext) -> EnsureActions:
    """纯函数：给定上下文，决定本次心跳要做哪些动作。"""
    resilience = bool(ctx.cfg.get("resilience_enabled", True))
    return EnsureActions(
        should_login=(ctx.auth_status == "not_logged_in"),
        should_spawn_tray=(resilience and not ctx.tray_alive),
        should_reconcile_autostart=True,
    )


def _spawn_tray_detached() -> None:
    """detached 拉起 GUI/托盘进程，使任务计划不被阻塞。"""
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    target = [exe_path()]  # frozen=exe，dev=解析后的入口
    if not getattr(sys, "frozen", False):
        target = [sys.executable, str(exe_path())]
    subprocess.Popen(target, creationflags=flags, close_fds=True)
    log.info("Ensure: detached tray spawned")


def run() -> int:
    """心跳主流程，返回退出码（0=正常）。"""
    cfg = config.load()
    if not cfg.get("username") or not cfg.get("password"):
        log.warning("Ensure: 未配置凭据，跳过")
        return 0

    auth = login_mod.check_auth_status()
    log.info("Ensure: auth=%s", auth)
    tray_alive = instance.tray_is_running()

    actions = plan(EnsureContext(auth, tray_alive, cfg))
    recovered = False

    if actions.should_login:
        try:
            result = login_mod.attempt_login(cfg, skip_wifi=True)  # 心跳不做 WiFi 切换
            recovered = (result == "success")
        except Exception as e:
            log.warning("Ensure: 登录异常: %s", e)

    if actions.should_spawn_tray:
        try:
            _spawn_tray_detached()
            recovered = True
        except Exception as e:
            log.warning("Ensure: 拉起托盘失败: %s", e)

    if actions.should_reconcile_autostart:
        try:
            selfheal.reconcile_autostart(cfg)
        except Exception as e:
            log.warning("Ensure: 自愈自启对齐失败: %s", e)

    if recovered and cfg.get("notification_enabled", True):
        notify.send("校园网自动恢复", "已重新登录 / 拉起守护进程")

    return 0
