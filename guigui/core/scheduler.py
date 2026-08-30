"""任务计划 — 任务 XML 生成 + schtasks CRUD + L1 起点公式。

- v2 改用完整任务 XML(v1 用 PS cmdlets):生成物可单元测试,且 L5 唤醒
  EventTrigger 在 cmdlets 里没有一等支持(技术方案 §3.3)。
- rev 版本标记写在任务 Description(config.tasks_rev 每次调度字段变更 +1),
  selfheal 以「任务存在 && rev 匹配 && Action 目标存在」判对齐。
- 窗口公式(修 v1 反向 bug):起点 = T − 30min,六拍,时长 = 5×步长。
"""

from __future__ import annotations

import getpass
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

log = logging.getLogger(__name__)

TASK_MAIN = "GuiGui"
TASK_PATROL = "GuiGui-Patrol"

L1_LEAD_MINUTES = 30   # 提前 30 分钟开始试(PRD §6.1)
L1_BEATS = 6           # 共 6 次
TIME_LIMIT = "PT15M"   # 容纳等门 10min(技术方案 §3.5)
WAKE_DELAY = "PT30S"   # L5 唤醒后 30s(PRD §5)
PATROL_DURATION_DAYS = 3650

_REV_RE = re.compile(r"GuiGui v2 automation rev=(\d+)")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ── L1 公式 ──────────────────────────────────────────────


def l1_window(trigger_time: str, heartbeat_minutes: int) -> tuple[str, int]:
    """(窗口起点 "HH:MM", 重复时长分钟)。起点 = T−30min,跨午夜回绕。

    例:('07:00', 5) → ('06:30', 25) → 拍在 06:30/35/40/45/50/55。
    """
    if not _TIME_RE.match(trigger_time or ""):
        raise ValueError(f"invalid trigger_time: {trigger_time!r}")
    h, m = (int(x) for x in trigger_time.split(":"))
    start_total = (h * 60 + m - L1_LEAD_MINUTES) % 1440
    start = f"{start_total // 60:02d}:{start_total % 60:02d}"
    return start, (L1_BEATS - 1) * heartbeat_minutes


# ── Action(dev / frozen 双模式)─────────────────────────


def action_parts() -> tuple[str, str, str]:
    """返回 (Execute, Arguments, WorkingDirectory)。

    frozen → (guigui.exe, --ensure, exe 目录);
    dev    → (pythonw.exe, "-m guigui --ensure", 仓库根)。
    """
    if getattr(sys, "frozen", False):
        return sys.executable, "--ensure", str(Path(sys.executable).parent)
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pyw if pyw.exists() else Path(sys.executable))
    repo_root = Path(__file__).resolve().parent.parent.parent
    return exe, "-m guigui --ensure", str(repo_root)


# ── XML 生成 ─────────────────────────────────────────────

_WAKE_QUERY = (
    "<QueryList><Query Id='0' Path='System'>"
    "<Select Path='System'>*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter']"
    " and EventID=1]]</Select></Query></QueryList>"
)


def _principal_xml() -> str:
    domain = os.environ.get("USERDOMAIN") or os.environ.get("COMPUTERNAME", "")
    user = getpass.getuser()
    uid = escape(f"{domain}\\{user}" if domain else user)
    return f"<Principals><Principal id=\"Author\"><UserId>{uid}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>"


def _settings_xml() -> str:
    return (
        "<Settings>"
        "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
        "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>"
        "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>"
        "<StartWhenAvailable>true</StartWhenAvailable>"
        "<WakeToRun>true</WakeToRun>"
        f"<ExecutionTimeLimit>{TIME_LIMIT}</ExecutionTimeLimit>"
        "<Enabled>true</Enabled>"
        "</Settings>"
    )


def _exec_xml() -> str:
    execute, arguments, workdir = action_parts()
    return (
        "<Actions><Exec>"
        f"<Command>{escape(execute)}</Command>"
        f"<Arguments>{escape(arguments)}</Arguments>"
        f"<WorkingDirectory>{escape(workdir)}</WorkingDirectory>"
        "</Exec></Actions>"
    )


def build_main_task_xml(cfg: dict, rev: int, now=None) -> str:
    """主任务 GuiGui:L1 Daily+Repetition + L2 AtLogon + L5 唤醒(按开关注入)。"""
    import datetime as dt

    now = now or dt.datetime.now()
    start, duration = l1_window(cfg["trigger_time"], cfg["heartbeat_minutes"])
    hb = cfg["heartbeat_minutes"]
    start_boundary = f"{now:%Y-%m-%d}T{start}:00"

    trig = (
        "<CalendarTrigger>"
        f"<StartBoundary>{start_boundary}</StartBoundary>"
        "<Enabled>true</Enabled>"
        "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
        f"<Repetition><Interval>PT{hb}M</Interval><Duration>PT{duration}M</Duration>"
        "<StopAtDurationEnd>false</StopAtDurationEnd></Repetition>"
        "</CalendarTrigger>"
    )
    if cfg.get("boot_login", True):
        trig += "<LogonTrigger><Enabled>true</Enabled></LogonTrigger>"
    if cfg.get("wake_login", False):
        trig += (
            "<EventTrigger><Enabled>true</Enabled>"
            f"<Subscription>{escape(_WAKE_QUERY)}</Subscription>"
            f"<Delay>{WAKE_DELAY}</Delay></EventTrigger>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        f"<Description>GuiGui v2 automation rev={rev}</Description>"
        f"{trig}"
        f"{_principal_xml()}"
        f"{_settings_xml()}"
        f"{_exec_xml()}"
        "</Task>"
    )


def build_patrol_task_xml(cfg: dict, rev: int, now=None) -> str:
    """巡逻任务 GuiGui-Patrol:全天每 N 分钟一次。"""
    import datetime as dt

    now = now or dt.datetime.now()
    pm = cfg["patrol_minutes"]
    trig = (
        "<TimeTrigger>"
        f"<StartBoundary>{now:%Y-%m-%d}T{now:%H:%M:%S}</StartBoundary>"
        "<Enabled>true</Enabled>"
        f"<Repetition><Interval>PT{pm}M</Interval>"
        f"<Duration>P{PATROL_DURATION_DAYS}D</Duration>"
        "<StopAtDurationEnd>false</StopAtDurationEnd></Repetition>"
        "</TimeTrigger>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        f"<Description>GuiGui v2 automation rev={rev}</Description>"
        f"{trig}"
        f"{_principal_xml()}"
        f"{_settings_xml()}"
        f"{_exec_xml()}"
        "</Task>"
    )


# ── schtasks CRUD ────────────────────────────────────────


def _run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["schtasks", *args], capture_output=True, text=True,
        encoding="gbk", errors="replace", timeout=timeout,
    )


def create_task(task_name: str, xml: str) -> bool:
    """用 XML 注册/覆盖任务(/f 幂等)。"""
    tmp: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", suffix=".xml", delete=False, encoding="utf-8") as f:
            f.write(xml)
            tmp = f.name
        r = _run(["/create", "/tn", task_name, "/xml", tmp, "/f"])
        if r.returncode == 0:
            log.info("scheduler: 任务已注册 %s", task_name)
            return True
        log.error("scheduler: 注册 %s 失败: %s", task_name, (r.stderr or r.stdout).strip()[:160])
        return False
    except Exception as e:
        log.error("scheduler: 注册 %s 异常: %s", task_name, e)
        return False
    finally:
        if tmp:
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass


def remove_task(task_name: str) -> bool:
    """删除任务;「找不到」视为成功(幂等)。"""
    try:
        r = _run(["/delete", "/tn", task_name, "/f"], timeout=15)
        if r.returncode == 0:
            log.info("scheduler: 任务已删除 %s", task_name)
            return True
        err = (r.stderr or r.stdout or "").lower()
        if "cannot find" in err or "找不到" in err:
            return True
        log.warning("scheduler: 删除 %s 失败: %s", task_name, err[:120])
        return False
    except Exception as e:
        log.error("scheduler: 删除 %s 异常: %s", task_name, e)
        return False


def query_xml(task_name: str) -> str | None:
    """读任务 XML;不存在/查询失败返回 None。"""
    try:
        r = _run(["/query", "/tn", task_name, "/xml"], timeout=15)
    except Exception as e:
        log.warning("scheduler: 查询 %s 异常: %s", task_name, e)
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def parse_rev(xml: str) -> int | None:
    m = _REV_RE.search(xml or "")
    return int(m.group(1)) if m else None


def action_target_exists(xml: str) -> bool:
    """任务 Action 的 Command 目标是否真实存在(坏任务检测,v1 机制移植)。"""
    m = re.search(r"<Command>(.*?)</Command>", xml or "", re.DOTALL)
    if not m:
        return True
    return Path(m.group(1).strip()).exists()


def is_task_current(task_name: str, cfg: dict) -> bool:
    """任务存在 && rev 与 config 一致 && Action 目标存在。"""
    xml = query_xml(task_name)
    if not xml:
        return False
    return parse_rev(xml) == cfg["tasks_rev"] and action_target_exists(xml)
