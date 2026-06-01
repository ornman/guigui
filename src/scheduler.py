"""Windows Task Scheduler management for SchoolAutoLogin."""

import logging
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

TASK_NAME = "SchoolAutoLogin"


def _exe_path() -> str:
    """Return the current executable path (works in both script and frozen mode)."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return str(Path(sys.argv[0]).resolve())


def create_scheduled_task(time_str: str) -> bool:
    """Create or update a daily scheduled task at *time_str* (HH:MM).

    Returns True on success.
    """
    exe = _exe_path()
    ps = (
        "$action = New-ScheduledTaskAction "
        f"-Execute '{exe}' -Argument '--silent'; "
        f"$trigger = New-ScheduledTaskTrigger -Daily -At '{time_str}:00'; "
        "$settings = New-ScheduledTaskSettingsSet "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-StartWhenAvailable -WakeToRun "
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 5); "
        f"Register-ScheduledTask -TaskName '{TASK_NAME}' "
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
            ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return info
        info["exists"] = True
        # Parse CSV output: "TaskName","Next Run Time","Status"
        parts = r.stdout.strip().split(",")
        if len(parts) >= 3:
            info["next_run"] = parts[1].strip('"')
            info["enabled"] = "Ready" in parts[2] or "正在运行" in parts[2]
    except Exception:
        pass
    return info
