"""自修复：把任务计划 / 自启注册表按 config 意图幂等对齐。

只在"缺失 / 规格不符 / 状态不符"时动手，不覆盖用户的对齐状态。
自启与任务计划互为兜底：任一存活即可重建另一个。
"""

import logging

from . import autostart, scheduler

log = logging.getLogger(__name__)


def should_autostart_be_enabled(cfg: dict) -> bool:
    """resilience 开 或 auto_start 开 → 自启应为开。"""
    return bool(cfg.get("resilience_enabled", True) or cfg.get("auto_start"))


def should_task_be_enabled(cfg: dict) -> bool:
    """scheduled_login 开 或 resilience 开 → 多触发器任务应为开。"""
    return bool(cfg.get("scheduled_login_enabled", False)
                or cfg.get("resilience_enabled", True))


def reconcile_autostart(cfg: dict) -> bool:
    """对齐自启注册表，返回是否做了改动。"""
    want = should_autostart_be_enabled(cfg)
    current = autostart.is_enabled()
    if want and not current:
        autostart.enable()
        log.info("Self-heal: 重新开启自启")
        return True
    if not want and current:
        autostart.disable()
        log.info("Self-heal: 关闭自启")
        return True
    return False


def reconcile_scheduler(cfg: dict) -> bool:
    """对齐任务计划（缺失→重建 / 旧版→迁移 / 应关却存在→删除），返回是否改动。"""
    want = should_task_be_enabled(cfg)
    info = scheduler.get_scheduled_task_info()
    time_str = cfg.get("scheduled_login_time", "06:55")
    interval = cfg.get("heartbeat_interval_minutes", 15)
    if want and not info.get("exists"):
        scheduler.create_scheduled_task_multi(time_str, interval)
        log.info("Self-heal: 重建任务计划")
        return True
    if want and info.get("exists") and scheduler.is_legacy_task():
        scheduler.create_scheduled_task_multi(time_str, interval)
        log.info("Self-heal: 迁移旧任务到多触发器")
        return True
    if not want and info.get("exists"):
        scheduler.remove_scheduled_task()
        log.info("Self-heal: 删除任务计划")
        return True
    return False
