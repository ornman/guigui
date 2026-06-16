"""Windows Task Scheduler management for SchoolAutoLogin."""

import logging
import re
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

TASK_NAME = "SchoolAutoLogin"
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


def autostart_command(*, executable: str | None = None,
                      script: str | None = None) -> str:
    """构造 HKCU Run 注册表值字符串。

    frozen → '"exe"'
    dev   → '"pythonw.exe" "main.py"'：无窗口且绕开 .py 关联。
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = executable or _interpreter()
    scr = script or _main_script()
    return f'"{exe}" "{scr}"'


def _ps_escape(s: str) -> str:
    """Escape a string for safe embedding in a PowerShell single-quoted string."""
    return "'" + s.replace("'", "''") + "'"


def create_scheduled_task(time_str: str) -> bool:
    """Create or update a daily scheduled task at *time_str* (HH:MM).

    Returns True on success.
    """
    if not _TIME_RE.match(time_str):
        log.error("Invalid time format (expected HH:MM): %r", time_str)
        return False

    execute, argument = scheduled_action_parts("--silent")
    task = _ps_escape(TASK_NAME)
    ps = (
        "$action = New-ScheduledTaskAction "
        f"-Execute {_ps_escape(execute)} -Argument {_ps_escape(argument)}; "
        f"$trigger = New-ScheduledTaskTrigger -Daily -At '{time_str}:00'; "
        "$settings = New-ScheduledTaskSettingsSet "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-StartWhenAvailable -WakeToRun "
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 5); "
        f"Register-ScheduledTask -TaskName {task} "
        "-Action $action -Trigger $trigger -Settings $settings -Force"
    )
    try:
        r = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            log.info("Scheduled task created/updated: %s at %s", TASK_NAME, time_str)
            return True
        log.error("Failed to create task: %s", r.stderr.strip())
        return False
    except Exception as e:
        log.error("Scheduler error: %s", e)
        return False


def remove_scheduled_task() -> bool:
    """Delete the scheduled task. Returns True on success."""
    try:
        r = subprocess.run(
            ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            log.info("Scheduled task removed: %s", TASK_NAME)
            return True
        # Task doesn't exist is not an error
        if "cannot find" in r.stderr.lower() or "找不到" in r.stderr:
            log.info("Scheduled task does not exist, nothing to remove")
            return True
        log.warning("Failed to remove task: %s", r.stderr.strip())
        return False
    except Exception as e:
        log.error("Remove task error: %s", e)
        return False


def get_scheduled_task_info() -> dict:
    """Query the scheduled task status.

    Returns dict with keys: exists (bool), next_run (str), enabled (bool).
    """
    info = {"exists": False, "next_run": "", "enabled": False}
    try:
        r = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST"],
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
    except Exception:
        pass
    return info


def create_scheduled_task_multi(time_str: str, interval_minutes: int = 15) -> bool:
    """创建多触发器任务：登录时 + 每 N 分钟心跳 + 每天 time_str。都跑 --ensure。

    Returns True on success.
    """
    if not _TIME_RE.match(time_str):
        log.error("Invalid time format (expected HH:MM): %r", time_str)
        return False
    if not isinstance(interval_minutes, int) or interval_minutes < 1:
        log.error("Invalid interval_minutes (must be int >= 1): %r", interval_minutes)
        return False

    execute, argument = scheduled_action_parts("--ensure")
    task = _ps_escape(TASK_NAME)
    ps = (
        "$action = New-ScheduledTaskAction "
        f"-Execute {_ps_escape(execute)} -Argument {_ps_escape(argument)}; "
        "$tLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
        "$tRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date) "
        f"-RepetitionInterval (New-TimeSpan -Minutes {int(interval_minutes)}) "
        "-RepetitionDuration (New-TimeSpan -Days 3650); "
        f"$tDaily = New-ScheduledTaskTrigger -Daily -At '{time_str}:00'; "
        "$settings = New-ScheduledTaskSettingsSet "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-StartWhenAvailable -WakeToRun "
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 5) "
        "-MultipleInstances IgnoreNew; "
        f"Register-ScheduledTask -TaskName {task} "
        "-Action $action -Trigger @($tLogon, $tRepeat, $tDaily) "
        "-Settings $settings -Force"
    )
    try:
        r = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            log.info("Multi-trigger task created: %s (every %dmin + logon + daily %s)",
                     TASK_NAME, interval_minutes, time_str)
            return True
        log.error("Failed to create multi-trigger task: %s", r.stderr.strip())
        return False
    except Exception as e:
        log.error("Scheduler error: %s", e)
        return False


def is_legacy_task() -> bool:
    """旧任务跑 --silent（单触发器），新版跑 --ensure（多触发器）。"""
    try:
        r = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME, "/xml"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return False
        return "--silent" in r.stdout and "--ensure" not in r.stdout
    except Exception:
        return False
