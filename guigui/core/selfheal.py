"""自愈对齐 — 把任务计划幂等对齐到 config 意图(技术方案 §3.3)。

判据「任务存在 && Description rev == config.tasks_rev && Action 目标存在」,
任何不满足 → 重建(注册带 /f 幂等);master 关 → 删除。

P1-7:拆分为4 个任务 GuiGui(日历)/ GuiGui-Boot(开机)/ GuiGui-Wake(唤醒)/
GuiGui-Patrol(巡逻),每个 Action Arguments 带 --trigger <name>,ensure.run
据此对 silent 同日压制做 boot/wake 豁免。

ADR-0006(2026-09-12 拍板,阈值 3):同一任务连续 3 次 reconcile 建立失败 →
该任务停试(连败计数持久化进 ensure_state["task_fail_streak"],向后兼容),
不再随 saveConfig/GUI 启动自动重试;恢复入口 = 用户动作 rebuildTask
(无条件全量重试并清零计数)。Wake 任务的 EventTrigger 无降级注册路径,
停试即其收敛手段 — misaligned 从「永远重试」变「如实降级 + 等用户」。
"""

from __future__ import annotations

import logging

from . import ensure, scheduler

log = logging.getLogger(__name__)

# ADR-0006 停试阈值(2026-09-12 拍板:3 次)
FAIL_STREAK_STOP = 3


def should_main_task_exist(cfg: dict) -> bool:
    return bool(cfg.get("master", True))


def should_boot_task_exist(cfg: dict) -> bool:
    return bool(cfg.get("master", True) and cfg.get("boot_login", True))


def should_wake_task_exist(cfg: dict) -> bool:
    return bool(cfg.get("master", True) and cfg.get("wake_login", False))


def should_patrol_task_exist(cfg: dict) -> bool:
    return bool(cfg.get("master", True) and cfg.get("patrol_enabled", False))


def _align(cfg: dict, task_name: str, desired: bool, is_current, build_xml,
           streaks: dict) -> tuple[bool, bool]:
    """单个任务的对齐;返回 (是否发生改动, 是否未达成意图)。

    streaks:连败账本(ensure_state["task_fail_streak"],任务名 → 连续建立
    失败次数),就地把成功清零/失败 +1 — ADR-0006:达阈值(3)跳过重建
    (停试,记 degraded),不再随 saveConfig/启动自动重试。"""
    if desired:
        if streaks.get(task_name, 0) >= FAIL_STREAK_STOP:
            log.warning("selfheal: 任务 %s 连败 %d 次已停试(降级),等用户重建",
                        task_name, streaks[task_name])
            return False, True
        if not is_current():
            xml = build_xml()
            if scheduler.create_task(task_name, xml):
                log.info("selfheal: 已(重)建任务 %s", task_name)
                streaks.pop(task_name, None)     # 建成 = 连败清零
                return True, False
            # 完整版被拒 → 降级注册(无 LogonTrigger)。
            # P1-7 拆分后:被拒的多半是 boot/wake 任务(独立任务,无降级路径),
            # 日历/巡逻任务不含 LogonTrigger 不需要降级。
            if "<LogonTrigger>" in xml and scheduler.create_task(
                    task_name, scheduler.drop_logon_trigger(xml)):
                log.warning(
                    "selfheal: 完整任务 %s 被拒(多为安全软件拦登录触发),"
                    "已降级注册:开机补登录暂缺", task_name)
                streaks.pop(task_name, None)     # 降级注册成功也算达成意图
                return True, False
        else:
            streaks.pop(task_name, None)         # 在岗 = 连败清零(外部已恢复)
            return False, False
        streaks[task_name] = streaks.get(task_name, 0) + 1
        n = streaks[task_name]
        log.error("selfheal: 建任务 %s 失败(连败 %d/%d)",
                  task_name, n, FAIL_STREAK_STOP)
        return False, True
    if scheduler.query_xml(task_name) is not None:
        if scheduler.remove_task(task_name):
            log.info("selfheal: 已删任务 %s", task_name)
            streaks.pop(task_name, None)         # 删除达成 = 意图满足
            return True, False
        log.error("selfheal: 删任务 %s 失败", task_name)
        return False, True
    streaks.pop(task_name, None)                 # 不该存在且不存在 = 意图满足
    return False, False


def reconcile(cfg: dict) -> tuple[bool, bool]:
    """按 config 对齐 GuiGui / GuiGui-Boot / GuiGui-Wake / GuiGui-Patrol。

    Returns:
        (changed, misaligned):changed=是否做了改动;
        misaligned=最终状态是否仍不符合意图(建/删失败或已停试降级,典型
        原因是安全软件拦截建任务 —— 调用方可据此提示用户)。
        连败计数随调用持久化进 ensure_state(ADR-0006,键 task_fail_streak;
        旧 state 无该键不炸,load_state 对未知键宽容)。
    """
    state = ensure.load_state()
    streaks = dict(state.get("task_fail_streak") or {})
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
        c, m = _align(cfg, task_name, desired, is_current, build_xml, streaks)
        changed |= c
        misaligned |= m
    _save_streaks(state, streaks)
    return changed, misaligned


def _save_streaks(state: dict, streaks: dict) -> None:
    """连败账本写回 ensure_state(空账本也落键,便于排查;原子写)。"""
    state["task_fail_streak"] = streaks
    ensure.save_state(state)


def degraded_tasks() -> list[str]:
    """已停试降级的任务名列表(ADR-0006;taskStatus 信封 degraded 字段数据源)。"""
    streaks = ensure.load_state().get("task_fail_streak") or {}
    return [t for t, n in streaks.items() if n >= FAIL_STREAK_STOP]


def clear_fail_streaks() -> None:
    """清零连败账本(rebuildTask 专用:恢复入口 = 用户动作,无条件全量重试)。"""
    state = ensure.load_state()
    if state.get("task_fail_streak"):
        state.pop("task_fail_streak", None)
        ensure.save_state(state)
