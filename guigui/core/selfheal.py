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


def _align(cfg: dict, task_name: str, desired: bool, is_current, build_xml) -> tuple[bool, bool]:
    """单个任务的对齐;返回 (是否发生改动, 是否未达成意图)。"""
    if desired:
        if not is_current():
            xml = build_xml()
            if scheduler.create_task(task_name, xml):
                log.info("selfheal: 已(重)建任务 %s", task_name)
                return True, False
            # 完整版被拒 → 降级注册(无开机触发)。日历触发(每日定时)不受影响,
            # 只是 boot_login 缺席;is_current 的形状检查保证放行后自动升级。
            if "<LogonTrigger>" in xml and scheduler.create_task(
                    task_name, scheduler.drop_logon_trigger(xml)):
                log.warning(
                    "selfheal: 完整任务 %s 被拒(多为安全软件拦登录触发),"
                    "已降级注册:每日定时登录正常,开机补登录暂缺", task_name)
                return True, False
            log.error("selfheal: 建任务 %s 失败", task_name)
            return False, True
        return False, False
    if scheduler.query_xml(task_name) is not None:
        if scheduler.remove_task(task_name):
            log.info("selfheal: 已删任务 %s", task_name)
            return True, False
        log.error("selfheal: 删任务 %s 失败", task_name)
        return False, True
    return False, False


def reconcile(cfg: dict) -> tuple[bool, bool]:
    """按 config 对齐 GuiGui / GuiGui-Patrol。

    Returns:
        (changed, misaligned):changed=是否做了改动;
        misaligned=最终状态是否仍不符合意图(建/删失败,典型原因是
        安全软件拦截建任务 —— 调用方可据此提示用户)。
    """
    changed = misaligned = False

    def _main_current(cfg_):
        # boot_login 开着时,降级任务(无登录触发)不算最新 → 每次对齐重试完整版
        return scheduler.is_task_current(
            scheduler.TASK_MAIN, cfg_, require_logon=bool(cfg_.get("boot_login")))

    for task_name, desired, is_current, build_xml in (
        (scheduler.TASK_MAIN, should_main_task_exist(cfg), lambda: _main_current(cfg),
         lambda: scheduler.build_main_task_xml(cfg, cfg["tasks_rev"])),
        (scheduler.TASK_PATROL, should_patrol_task_exist(cfg),
         lambda: scheduler.is_task_current(scheduler.TASK_PATROL, cfg),
         lambda: scheduler.build_patrol_task_xml(cfg, cfg["tasks_rev"])),
    ):
        c, m = _align(cfg, task_name, desired, is_current, build_xml)
        changed |= c
        misaligned |= m
    return changed, misaligned
