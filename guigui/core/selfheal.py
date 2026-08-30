"""自愈对齐 — 把任务计划幂等对齐到 config 意图(技术方案 §3.3)。

判据「任务存在 && Description rev == config.tasks_rev && Action 目标存在」,
任何不满足 → 重建(注册带 /f 幂等);master 关 → 删除。
"""

from __future__ import annotations

import logging

from . import scheduler

log = logging.getLogger(__name__)


def should_main_task_exist(cfg: dict) -> bool:
    return bool(cfg.get("master", True))


def should_patrol_task_exist(cfg: dict) -> bool:
    return bool(cfg.get("master", True) and cfg.get("patrol_enabled", False))


def _align(cfg: dict, task_name: str, desired: bool, build_xml) -> bool:
    """单个任务的对齐;返回是否发生改动。"""
    if desired:
        if not scheduler.is_task_current(task_name, cfg):
            if scheduler.create_task(task_name, build_xml()):
                log.info("selfheal: 已(重)建任务 %s", task_name)
                return True
            log.error("selfheal: 建任务 %s 失败", task_name)
        return False
    if scheduler.query_xml(task_name) is not None:
        if scheduler.remove_task(task_name):
            log.info("selfheal: 已删任务 %s", task_name)
            return True
        log.error("selfheal: 删任务 %s 失败", task_name)
    return False


def reconcile(cfg: dict) -> bool:
    """按 config 对齐 GuiGui / GuiGui-Patrol;返回是否做了改动。"""
    changed = _align(
        cfg, scheduler.TASK_MAIN, should_main_task_exist(cfg),
        lambda: scheduler.build_main_task_xml(cfg, cfg["tasks_rev"]),
    )
    changed |= _align(
        cfg, scheduler.TASK_PATROL, should_patrol_task_exist(cfg),
        lambda: scheduler.build_patrol_task_xml(cfg, cfg["tasks_rev"]),
    )
    return changed
