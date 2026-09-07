"""通知 — Windows Toast(PowerShell WinRT)+ guigui:// 协议激活 + 决策去重纯函数。

- 通道移植 v1 src/notify.py(ShellExperienceHost AppId,零依赖生产验证);
  升级:toast 带 activationType=protocol,点击按路由唤起 GUI(技术方案 §9)。
- decide_notify 是纯函数:PRD §4.5 语义(2026-09-06 重梳理)—
  开门后明确被拒当拍即弹(每日≤1)/ 维护页连续≥3拍才弹(每日≤1)/
  断→通每日 1 次 / 锚前(06:50 前)一切失败永不通知。
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

RECOVERED = "recovered"
FAILED = "failed"            # 开门后明确被拒 → 当拍即弹(PRD 4.5)
MAINTENANCE = "maintenance"  # 维护页连续 ≥3 拍(PRD 4.5)
TASK_LOST = "task_lost"      # 任务被拦/丢失(ensure 自检发现,QA P1-5)

LAUNCH_MAIN = "guigui://main"
LAUNCH_CREDS = "guigui://creds"
LAUNCH_SETTINGS = "guigui://settings"


def _xml_escape(text: str) -> str:
    """XML 实体转义 + 高位字符转 &#xHH;(防 Toast 模板注入与乱码,v1 移植)。"""
    text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
    return "".join(f"&#x{ord(c):X};" if ord(c) > 127 else c for c in text)


def send(title: str, message: str, launch: str = LAUNCH_MAIN) -> None:
    """发 Toast;超时/失败只记日志,永不抛异常(v1 行为)。"""
    t, m, lc = _xml_escape(title), _xml_escape(message), _xml_escape(launch)
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager,"
        " Windows.UI.Notifications, ContentType=WindowsRuntime]|Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom,"
        " ContentType=WindowsRuntime]|Out-Null;"
        f'$t=\'<toast activationType="protocol" launch="{lc}" duration="long">'
        "<visual><binding template=\"ToastGeneric\">"
        f"<text>{t}</text><text>{m}</text>"
        '</binding></visual></toast>\';'
        "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
        "$x.LoadXml($t);"
        "$toast=[Windows.UI.Notifications.ToastNotification]::new($x);"
        '[Windows.UI.Notifications.ToastNotificationManager]'
        '::CreateToastNotifier("Microsoft.Windows.ShellExperienceHost_cw5n1h2txyewy!App")'
        ".Show($toast)"
    )
    try:
        r = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,  # 不弹终端窗口
        )
        if r.returncode != 0:
            log.warning("notify: 发送失败(rc=%d): %s", r.returncode, r.stderr.strip()[:120])
    except Exception as e:
        log.warning("notify: 发送异常: %s", e)


# ── 去重决策(纯函数,AC-04)──────────────────────────────


def task_blocked() -> None:
    """建任务被安全软件拦时的指引通知(点开直达设置页)。

    仅在用户主动动作(保存设置/切总开关/GUI 启动对齐)后调用,
    --ensure 定时路径不建任务,不会每天刷屏。"""
    send(
        "桂桂",
        "安全软件拦住了定时任务的创建,自动登录还没生效。"
        "把桂桂加入它的信任区,再回来保存一次设置就好。",
        launch=LAUNCH_SETTINGS,
    )


def task_linger() -> None:
    """关总开关但删任务失败(幽灵任务)时的如实通知(点开直达设置页)。

    开着被拦是「没动静」;关着删不掉 = 任务还在、明早照常登录 —
    背着用户干活更伤信任,必须告知;回设置页再关一次即重试删除。"""
    send(
        "桂桂",
        "没关干净:定时任务还在,明早还会自动登录。"
        "点开设置,把开关再关一次试试。",
        launch=LAUNCH_SETTINGS,
    )


def task_lost() -> None:
    """ensure 静默自检发现定时任务不在岗(QA P1-5)。

    区别 task_blocked:那边是「建任务当场被拦」,用户已看见保存提示;
    这边是「昨天建好今天消失」(安全软件事后删 / exe 被挪),悄无声息 —
    必须告知,否则「每天 07:00」最大长期承诺已死无人知晓;回设置页点
    「点此重建」即可(契约 §2.14 rebuildTask 仅用户点击触发,绝不在
    --ensure 静默进程里重建,避免静默进程和管理侧抢)。"""
    send(
        "桂桂",
        "定时任务不见了,自动登录可能已经停了。"
        "点开设置,按「点此重建」就好。",
        launch=LAUNCH_SETTINGS,
    )


def decide_notify(prev_state: str | None, *, connected: bool,
                  outcome: str | None = None,
                  before_anchor: bool = False, maintenance_streak: int = 0,
                  last_recovered_date: str | None = None,
                  fail_notify_date: str | None = None,
                  maintenance_notify_date: str | None = None,
                  today: str = "",
                  ) -> tuple[str | None, dict]:
    """根据上次持久化状态与本次结果,决定通知种类与状态更新(PRD 4.5)。

    Args:
        outcome: 本拍失败形态 — "rejected"(服务器明确拒绝)| "unexpected"(维护页)
                 | None(不可达/未尝试登录)。
        before_anchor: 06:50 开门前 → 一切失败只算「还没开门」,不算断网事件。

    Returns:
        (notify_kind, updates):kind ∈ recovered | failed | maintenance | None;
        updates 为需要合并进 ensure_state 的键值(last_net_state 等)。
    """
    if connected:
        updates = {"last_net_state": "up"}
        kind = None
        if prev_state in ("down", "failed"):
            # 断→通:每天只报一次;同日已报过只记状态
            if last_recovered_date != today:
                kind = RECOVERED
                updates["last_recovered_notify_date"] = today
        return kind, updates
    if before_anchor:
        # 锚前被拒/不可达:不判失败、不发通知、不动 net_state(防窗口期错怪,AC-12)
        return None, {}
    if outcome == "rejected":
        # 开门后明确被拒:当拍即弹,每日 ≤1 次(AC-13)
        updates = {"last_net_state": "failed"}
        if fail_notify_date != today:
            return FAILED, {**updates, "fail_notify_date": today}
        return None, updates
    if outcome == "unexpected":
        # 维护页:连续 ≥3 拍才弹,每日 ≤1 次
        updates = {"last_net_state": "failed"}
        if maintenance_streak >= 3 and maintenance_notify_date != today:
            return MAINTENANCE, {**updates, "maintenance_notify_date": today}
        return None, updates
    # 不可达(未尝试登录):只记 down,不通知(防刷屏)
    return None, {"last_net_state": "down"}


# ── guigui:// 协议注册(HKCU,免管理员)─────────────────


def register_protocol() -> bool:
    """注册 guigui:// URL 协议到当前用户;失败只记日志。"""
    try:
        import winreg
    except ImportError:
        return False
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}" "%1"'
    else:
        entry = Path(__file__).resolve().parent.parent / "__main__.py"
        cmd = f'"{sys.executable}" "{entry}" "%1"'
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                                 r"Software\Classes\guigui", 0, winreg.KEY_WRITE)
        with key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "URL:guigui protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
            sub = winreg.CreateKeyEx(key, r"shell\open\command", 0, winreg.KEY_WRITE)
            with sub:
                winreg.SetValueEx(sub, None, 0, winreg.REG_SZ, cmd)
        return True
    except OSError as e:
        log.warning("notify: 协议注册失败: %s", e)
        return False
