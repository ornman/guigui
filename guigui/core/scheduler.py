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

TASK_MAIN = "GuiGui"            # L1 日历拍(CalendarTrigger)
TASK_BOOT = "GuiGui-Boot"        # L2 开机拍(LogonTrigger)— P1-7 拆分
TASK_WAKE = "GuiGui-Wake"        # L5 唤醒拍(EventTrigger)— P1-7 拆分
TASK_PATROL = "GuiGui-Patrol"

VALID_TRIGGERS = ("calendar", "boot", "wake", "patrol")

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


def action_parts(trigger: str = "calendar") -> tuple[str, str, str]:
    """返回 (Execute, Arguments, WorkingDirectory)。

    frozen → (guigui.exe, "--ensure --trigger <name>", exe 目录);
    dev    → (pythonw.exe, "-m guigui --ensure --trigger <name>", 仓库根)。

    P1-7:每个任务 XML 的 Action Arguments 带上 --trigger,ensure.run 据此判
    豁免。trigger 不在白名单 → 默认 calendar(向后兼容旧任务 / 手动运行)。
    """
    if trigger not in VALID_TRIGGERS:
        trigger = "calendar"
    arg = f"--ensure --trigger {trigger}"
    if getattr(sys, "frozen", False):
        return sys.executable, arg, str(Path(sys.executable).parent)
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pyw if pyw.exists() else Path(sys.executable))
    repo_root = Path(__file__).resolve().parent.parent.parent
    return exe, f"-m guigui {arg}", str(repo_root)


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


def _exec_xml(trigger: str = "calendar") -> str:
    execute, arguments, workdir = action_parts(trigger)
    return (
        "<Actions><Exec>"
        f"<Command>{escape(execute)}</Command>"
        f"<Arguments>{escape(arguments)}</Arguments>"
        f"<WorkingDirectory>{escape(workdir)}</WorkingDirectory>"
        "</Exec></Actions>"
    )


def build_main_task_xml(cfg: dict, rev: int, now=None) -> str:
    """主任务 GuiGui:L1 Daily+Repetition(纯日历拍,P1-7 拆分后只含 CalendarTrigger)。

    开机/唤醒已迁到独立任务 GuiGui-Boot / GuiGui-Wake,以便 Action Arguments
    能带不同 --trigger,ensure.run 据此判 silent 同日豁免(返校日天然恢复点)。
    结构必须严格按 Task Scheduler schema 顺序:
    RegistrationInfo(含 Description/rev 标记)→ Triggers → Principals → Settings → Actions。
    """
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
    return (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        "<RegistrationInfo>"
        f"<Description>GuiGui v2 automation rev={rev}</Description>"
        "</RegistrationInfo>"
        f"<Triggers>{trig}</Triggers>"
        f"{_principal_xml()}"
        f"{_settings_xml()}"
        f"{_exec_xml('calendar')}"
        "</Task>"
    )


def build_boot_task_xml(cfg: dict, rev: int, now=None) -> str:
    """开机任务 GuiGui-Boot:仅 LogonTrigger,Action Arguments 带 --trigger boot。

    P1-7 拆分产物:返校日第一拍(刚开机 WiFi 未就绪)走这里,silent 同日豁免,
    探测 + 登录 + 通知全流程跑(天然恢复点)。
    """
    trig = "<LogonTrigger><Enabled>true</Enabled></LogonTrigger>"
    return (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        "<RegistrationInfo>"
        f"<Description>GuiGui v2 automation rev={rev}</Description>"
        "</RegistrationInfo>"
        f"<Triggers>{trig}</Triggers>"
        f"{_principal_xml()}"
        f"{_settings_xml()}"
        f"{_exec_xml('boot')}"
        "</Task>"
    )


def build_wake_task_xml(cfg: dict, rev: int, now=None) -> str:
    """唤醒任务 GuiGui-Wake:仅 EventTrigger(笔记本唤醒/拔电源),--trigger wake。

    P1-7 拆分产物:休眠恢复(返校日宿舍场景常见)走这里豁免 silent 压制。
    """
    trig = (
        "<EventTrigger><Enabled>true</Enabled>"
        f"<Subscription>{escape(_WAKE_QUERY)}</Subscription>"
        f"<Delay>{WAKE_DELAY}</Delay></EventTrigger>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        "<RegistrationInfo>"
        f"<Description>GuiGui v2 automation rev={rev}</Description>"
        "</RegistrationInfo>"
        f"<Triggers>{trig}</Triggers>"
        f"{_principal_xml()}"
        f"{_settings_xml()}"
        f"{_exec_xml('wake')}"
        "</Task>"
    )


def build_patrol_task_xml(cfg: dict, rev: int, now=None) -> str:
    """巡逻任务 GuiGui-Patrol:全天每 N 分钟一次,Action Arguments 带 --trigger patrol。"""
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
        "<RegistrationInfo>"
        f"<Description>GuiGui v2 automation rev={rev}</Description>"
        "</RegistrationInfo>"
        f"<Triggers>{trig}</Triggers>"
        f"{_principal_xml()}"
        f"{_settings_xml()}"
        f"{_exec_xml('patrol')}"
        "</Task>"
    )


# ── schtasks CRUD ────────────────────────────────────────


def _run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    # CREATE_NO_WINDOW:GUI 是无窗口进程,不加会为每个 schtasks 弹一个终端
    return subprocess.run(
        ["schtasks", *args], capture_output=True, text=True,
        encoding="gbk", errors="replace", timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def create_task(task_name: str, xml: str) -> bool:
    """用 XML 注册/覆盖任务(/f 幂等)。"""
    tmp: str | None = None
    try:
        # Task Scheduler 规范格式是 UTF-16(带 BOM);声明与文件编码必须一致,
        # 否则 schtasks 报「无法切换编码」(联调实测)
        with tempfile.NamedTemporaryFile(
                "w", suffix=".xml", delete=False, encoding="utf-16") as f:
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


def drop_logon_trigger(xml: str) -> str:
    """去掉任务 XML 里的 LogonTrigger(降级注册用)。

    实测(2026-08-31,火绒严格配置):部分安全软件按内容拦「未知程序注册
    登录触发任务」,同款 XML 去掉 LogonTrigger 即放行。降级只损失
    boot_login(开机补登录),每日日历触发不受影响。
    """
    return re.sub(r"<LogonTrigger>.*?</LogonTrigger>", "", xml, flags=re.DOTALL)


def is_task_current(task_name: str, cfg: dict, require_logon: bool = False) -> bool:
    """任务存在 && rev 与 config 一致 && Action 目标存在。

    require_logon=True 时额外要求含 LogonTrigger:降级注册的任务(完整版
    被安全软件拒、只注册了无开机触发版)不算最新,每次对齐自动重试完整版,
    放行后即无缝升级。
    """
    xml = query_xml(task_name)
    if not xml:
        return False
    if require_logon and "<LogonTrigger>" not in xml:
        return False
    return parse_rev(xml) == cfg["tasks_rev"] and action_target_exists(xml)
