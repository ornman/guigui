"""自愈对齐 — 把任务计划幂等对齐到 config 意图(技术方案 §3.3)。

判据「任务存在 && Description rev == config.tasks_rev && Action 目标存在」,
任何不满足 → 重建(注册带 /f 幂等);master 关 → 删除。

P1-7:拆分为4 个任务 GuiGui(日历)/ GuiGui-Boot(开机)/ GuiGui-Wake(唤醒)/
GuiGui-Patrol(巡逻),每个 Action Arguments 带 --trigger <name>,ensure.run
据此对 silent 同日压制做 boot/wake 豁免。
"""

from __future__ import annotations

import logging

from . import scheduler

log = logging.getLogger(__name__)


def should_main_task_exist(cfg: dict) -> bool:
    return bool(cfg.get("master", True))


def should_boot_task_exist(cfg: dict) -> bool:
    return bool(cfg.get("master", True) and cfg.get("boot_login", True))


def should_wake_task_exist(cfg: dict) -> bool:
    return bool(cfg.get("master", True) and cfg.get("wake_login", False))


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
            # 完整版被拒 → 降级注册(无 LogonTrigger)。
            # P1-7 拆分后:被拒的多半是 boot/wake 任务(独立任务,无降级路径),
            # 日历/巡逻任务不含 LogonTrigger 不需要降级。
            if "<LogonTrigger>" in xml and scheduler.create_task(
                    task_name, scheduler.drop_logon_trigger(xml)):
                log.warning(
                    "selfheal: 完整任务 %s 被拒(多为安全软件拦登录触发),"
                    "已降级注册:开机补登录暂缺", task_name)
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
    """按 config 对齐 GuiGui / GuiGui-Boot / GuiGui-Wake / GuiGui-Patrol。

    Returns:
        (changed, misaligned):changed=是否做了改动;
        misaligned=最终状态是否仍不符合意图(建/删失败,典型原因是
        安全软件拦截建任务 —— 调用方可据此提示用户)。
    """
    changed = misaligned = False

    for task_name, desired, is_current, build_xml in (
        (scheduler.TASK_MAIN, should_main_task_exist(cfg),
         lambda: scheduler.is_task_current(scheduler.TASK_MAIN, cfg),
         lambda: scheduler.build_main_task_xml(cfg, cfg["tasks_rev"])),
        (scheduler.TASK_BOOT, should_boot_task_exist(cfg),
         lambda: scheduler.is_task_current(scheduler.TASK_BOOT, cfg,
                                           require_logon=True),
         lambda: scheduler.build_boot_task_xml(cfg, cfg["tasks_rev"])),
        (scheduler.TASK_WAKE, should_wake_task_exist(cfg),
         lambda: scheduler.is_task_current(scheduler.TASK_WAKE, cfg),
         lambda: scheduler.build_wake_task_xml(cfg, cfg["tasks_rev"])),
        (scheduler.TASK_PATROL, should_patrol_task_exist(cfg),
         lambda: scheduler.is_task_current(scheduler.TASK_PATROL, cfg),
         lambda: scheduler.build_patrol_task_xml(cfg, cfg["tasks_rev"])),
    ):
        c, m = _align(cfg, task_name, desired, is_current, build_xml)
        changed |= c
        misaligned |= m
    return changed, misaligned
