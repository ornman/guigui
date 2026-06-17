"""Windows Task Scheduler management for SchoolAutoLogin."""

import logging
import re
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

TASK_NAME = "SchoolAutoLogin"
PATROL_TASK_NAME = "SchoolAutoLogin-Patrol"
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def exe_path() -> str:
    """Return the current executable path (works in both script and frozen mode)."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return str(Path(sys.argv[0]).resolve())


def _main_script() -> str:
    """dev 模式入口脚本绝对路径（frozen 模式不用）。"""
    return str(Path(sys.argv[0]).resolve())


def _interpreter() -> str:
    """dev 模式无窗口解释器：优先 pythonw.exe，缺失时回退 python.exe。"""
    pyw = Path(sys.executable).with_name("pythonw.exe")
    if pyw.exists():
        return str(pyw)
    log.warning("pythonw.exe 不存在（%s），回退 python.exe（任务计划可能短暂弹出控制台窗口）", pyw)
    return sys.executable


def scheduled_action_parts(mode: str, *, executable: str | None = None,
                           script: str | None = None) -> tuple[str, str]:
    """构造 New-ScheduledTaskAction 的 (Execute, Argument)。

    frozen → (exe, mode)：exe 自带入口，Argument 仅含模式参数。
    dev   → (pythonw.exe, '"main.py" mode')：显式指定解释器，
            绕开被 VSCode 等 UserChoice 抢占的 .py 关联。
    """
    if getattr(sys, "frozen", False):
        return sys.executable, mode
    exe = executable or _interpreter()
    scr = script or _main_script()
    return exe, f'"{scr}" {mode}'


def _ps_escape(s: str) -> str:
    """Escape a string for safe embedding in a PowerShell single-quoted string."""
    return "'" + s.replace("'", "''") + "'"


def remove_scheduled_task(task_name: str = TASK_NAME) -> bool:
    """Delete the scheduled task *task_name*. Returns True on success."""
    try:
        r = subprocess.run(
            ["schtasks", "/delete", "/tn", task_name, "/f"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            log.info("Scheduled task removed: %s", task_name)
            return True
        # Task doesn't exist is not an error
        if "cannot find" in r.stderr.lower() or "找不到" in r.stderr:
            log.info("Scheduled task does not exist, nothing to remove: %s", task_name)
            return True
        log.warning("Failed to remove task %s: %s", task_name, r.stderr.strip())
        return False
    except Exception as e:
        log.error("Remove task error: %s", e)
        return False


def get_scheduled_task_info(task_name: str = TASK_NAME) -> dict:
    """Query the scheduled task *task_name* status.

    Returns dict with keys: exists (bool), next_run (str), enabled (bool).
    """
    info = {"exists": False, "next_run": "", "enabled": False}
    try:
        r = subprocess.run(
            ["schtasks", "/query", "/tn", task_name, "/fo", "LIST"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return info
        info["exists"] = True
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("Next Run Time:"):
                info["next_run"] = line.split(":", 1)[1].strip()
            elif line.startswith("Status:"):
                status = line.split(":", 1)[1].strip().lower()
                info["enabled"] = status in ("ready", "running", "正在运行")
    except Exception as e:
        # 查询失败 ≠ 任务缺失：记录日志，避免 self-heal 误判后反复重建
        log.warning("get_scheduled_task_info(%s) 查询失败: %s", task_name, e)
    return info


# ── 窗口化任务（新模型）──────────────────────────────────────


def window_start_from_center(center: str, duration_minutes: int) -> str:
    """窗口中心(HH:MM) + 总时长(分钟) → 窗口起点(HH:MM)，跨午夜回绕。

    例：``('06:55', 60) → '06:25'``（前后各 30 分钟）；
    ``('00:10', 60) → '23:40'``（跨午夜）。奇数时长向前取整。
    """
    h, m = center.split(":")
    total = (int(h) * 60 + int(m) - int(duration_minutes) // 2) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"


def create_windowed_task(center_time: str, window_minutes: int,
                         interval_minutes: int) -> bool:
    """创建核心自动化任务：AtLogon(当前用户) + 窗口(Daily@start + Repetition)。

    窗口起点 = ``center_time - window_minutes/2``，窗口内每 ``interval_minutes``
    分钟跑一次 ``--ensure``。AtLogon 保证开机/登录时静默登录一次。

    Returns True on success.
    """
    if not _TIME_RE.match(center_time):
        log.error("Invalid center_time (expected HH:MM): %r", center_time)
        return False
    if not isinstance(window_minutes, int) or window_minutes < 1:
        log.error("Invalid window_minutes (must be int >= 1): %r", window_minutes)
        return False
    if not isinstance(interval_minutes, int) or interval_minutes < 1:
        log.error("Invalid interval_minutes (must be int >= 1): %r", interval_minutes)
        return False

    start = window_start_from_center(center_time, window_minutes)
    execute, argument = scheduled_action_parts("--ensure")
    task = _ps_escape(TASK_NAME)
    ps = (
        "$action = New-ScheduledTaskAction "
        f"-Execute {_ps_escape(execute)} -Argument {_ps_escape(argument)}; "
        f"$tWin = New-ScheduledTaskTrigger -Daily -At '{start}:00'; "
        "$rep = New-ScheduledTaskTrigger -Once -At (Get-Date) "
        f"-RepetitionInterval (New-TimeSpan -Minutes {int(interval_minutes)}) "
        f"-RepetitionDuration (New-TimeSpan -Minutes {int(window_minutes)}); "
        "$tWin.Repetition = $rep.Repetition; "
        "$tLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
        "$settings = New-ScheduledTaskSettingsSet "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-StartWhenAvailable -WakeToRun "
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 5) "
        "-MultipleInstances IgnoreNew; "
        f"Register-ScheduledTask -TaskName {task} "
        "-Action $action -Trigger @($tWin, $tLogon) -Settings $settings -Force"
    )
    try:
        r = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            log.info("Windowed task created: %s (%s ±%dmin, every %dmin)",
                     TASK_NAME, center_time, window_minutes // 2, interval_minutes)
            return True
        log.error("Failed to create windowed task: %s", r.stderr.strip())
        return False
    except Exception as e:
        log.error("Scheduler error: %s", e)
        return False


def create_patrol_task(interval_minutes: int) -> bool:
    """创建全天巡逻任务（独立任务名）：Once + Repetition(全天每 N 分钟)。

    全天断网自动重连，由 GUI「全天巡逻」开关控制。Action 跑 ``--ensure``。

    Returns True on success.
    """
    if not isinstance(interval_minutes, int) or interval_minutes < 1:
        log.error("Invalid interval_minutes (must be int >= 1): %r", interval_minutes)
        return False

    execute, argument = scheduled_action_parts("--ensure")
    task = _ps_escape(PATROL_TASK_NAME)
    ps = (
        "$action = New-ScheduledTaskAction "
        f"-Execute {_ps_escape(execute)} -Argument {_ps_escape(argument)}; "
        "$tPatrol = New-ScheduledTaskTrigger -Once -At (Get-Date) "
        f"-RepetitionInterval (New-TimeSpan -Minutes {int(interval_minutes)}) "
        "-RepetitionDuration (New-TimeSpan -Days 3650); "
        "$settings = New-ScheduledTaskSettingsSet "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-StartWhenAvailable -WakeToRun "
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 5) "
        "-MultipleInstances IgnoreNew; "
        f"Register-ScheduledTask -TaskName {task} "
        "-Action $action -Trigger @($tPatrol) -Settings $settings -Force"
    )
    try:
        r = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            log.info("Patrol task created: %s (every %dmin)",
                     PATROL_TASK_NAME, interval_minutes)
            return True
        log.error("Failed to create patrol task: %s", r.stderr.strip())
        return False
    except Exception as e:
        log.error("Scheduler error: %s", e)
        return False


# ── 任务类型检测（self-heal 对齐用）─────────────────────────


def _task_xml(task_name: str = TASK_NAME) -> str | None:
    """读取任务 XML；不存在/出错返回 None。"""
    try:
        r = subprocess.run(
            ["schtasks", "/query", "/tn", task_name, "/xml"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return None
        return r.stdout
    except Exception as e:
        # 查询失败时返回 None（视同缺失），但记录日志便于排查 self-heal 反复重建
        log.warning("_task_xml(%s) 查询失败: %s", task_name, e)
        return None


def _calendar_trigger_has_repetition(xml: str) -> bool:
    """XML 中是否存在「含 Repetition 的 CalendarTrigger」（窗口任务标志）。

    旧多触发器任务的 CalendarTrigger 无 Repetition（其 Repetition 在 TimeTrigger 上），
    据此区分新窗口模型与旧模型。
    """
    for m in re.finditer(r"<CalendarTrigger\b.*?</CalendarTrigger>", xml, re.IGNORECASE | re.DOTALL):
        if "<Repetition>" in m.group(0):
            return True
    return False


def is_windowed_task() -> bool:
    """核心任务是否已为窗口模型（--ensure + LogonTrigger + 窗口 CalendarTrigger）。"""
    xml = _task_xml(TASK_NAME)
    if not xml:
        return False
    return ("--ensure" in xml
            and "<LogonTrigger>" in xml
            and _calendar_trigger_has_repetition(xml))


def is_patrol_task() -> bool:
    """巡逻任务是否已注册为正确模型（--ensure + TimeTrigger/Repetition，无登录/窗口触发器）。"""
    xml = _task_xml(PATROL_TASK_NAME)
    if not xml:
        return False
    return ("--ensure" in xml
            and "<TimeTrigger>" in xml
            and "<Repetition>" in xml
            and "<LogonTrigger>" not in xml
            and "<CalendarTrigger>" not in xml)


def is_legacy_task() -> bool:
    """核心任务存在但不符合窗口模型 → 需迁移（含旧 --silent 与旧多触发器 --ensure）。"""
    if not _task_xml(TASK_NAME):
        return False
    return not is_windowed_task()
