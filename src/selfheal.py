"""自修复：把任务计划按 config 意图幂等对齐到窗口化模型。

窗口化模型两个任务：
  - 核心任务 SchoolAutoLogin（AtLogon + 窗口 Daily/Repetition）← resilience_enabled
  - 巡逻任务 SchoolAutoLogin-Patrol（全天 Repetition）           ← resilience AND patrol_enabled

仅在「缺失 / 旧版需迁移 / 应关却存在」时动手，不覆盖已对齐状态。
"""

import logging

from . import scheduler

log = logging.getLogger(__name__)


def should_core_task_exist(cfg: dict) -> bool:
    """resilience 开 → 核心窗口任务（含 AtLogon）应为开。"""
    return bool(cfg.get("resilience_enabled", True))


def should_patrol_task_exist(cfg: dict) -> bool:
    """resilience 开 且 patrol 开 → 全天巡逻任务应为开。"""
    return bool(cfg.get("resilience_enabled", True) and cfg.get("patrol_enabled", False))


def reconcile_scheduler(cfg: dict) -> bool:
    """对齐任务计划到窗口化模型，返回是否做了改动。

    核心任务：应开时缺失/旧版则建（迁移），不应开时存在则删。
    巡逻任务：应开时缺失则建，不应开时存在则删。
    """
    changed = False
    center = cfg.get("scheduled_login_time", "06:55")
    window = cfg.get("window_duration_minutes", 60)
    interval = cfg.get("heartbeat_interval_minutes", 5)
    patrol_interval = cfg.get("patrol_interval_minutes", 30)

    # ── 核心窗口任务 ──
    if should_core_task_exist(cfg):
        if not scheduler.is_windowed_task():  # 缺失或旧版 → 建/迁移
            scheduler.create_windowed_task(center, window, interval)
            log.info("Self-heal: 创建/迁移核心窗口任务")
            changed = True
    else:
        if scheduler.is_windowed_task() or scheduler.is_legacy_task():
            scheduler.remove_scheduled_task()
            log.info("Self-heal: 移除核心任务（自动化已停用）")
            changed = True

    # ── 巡逻任务 ──
    if should_patrol_task_exist(cfg):
        if not scheduler.is_patrol_task():
            scheduler.create_patrol_task(patrol_interval)
            log.info("Self-heal: 创建巡逻任务")
            changed = True
    else:
        if scheduler.is_patrol_task():
            scheduler.remove_scheduled_task(scheduler.PATROL_TASK_NAME)
            log.info("Self-heal: 移除巡逻任务")
            changed = True

    return changed
