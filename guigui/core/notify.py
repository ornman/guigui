"""通知 — Windows Toast(WinRT 进程内直调主通道 + powershell 兜底)+ guigui:// 协议激活 + 决策纯函数。

- 通道 ADR-0002(2026-09-11):主通道 pythonnet 早绑定直调 WinRT
  ToastNotificationManager(spike 实测通:Type.GetType(..., ContentType=
  WindowsRuntime) 加载投影类型;InvokeMember 迟绑定不可用 — WinRT 无
  IDispatch,必须早绑定点调用),powershell 降为兜底 — 通知主链不再 spawn
  子进程,自救指引(task_blocked)与 powershell 单点解耦。
- v1 落地形态是 powershell 激活同一套 WinRT API(ShellExperienceHost
  AppId,零依赖生产验证);升级:toast 带 activationType=protocol,点击按
  路由唤起 GUI(技术方案 §9)。
- decide_notify 是纯函数:1.6.0 通知矩阵(用户拍板 2026-09-11 重写)—
  任务成功=发(默认开、设置可关)/ 凭据类失败=发带原因 / 连不上=也发(纯诊断)/
  维护页连续≥3拍=发 / 锚前一切失败永不通知 / 节流、库降级=静默;
  冷却:同类 30 分钟合并 + 每类每天 ≤1(账本经 ensure_state 持久化)。
  假期模式的进出由 ensure 判定(连续 3 天不可达进 / 恢复可达退),
  本函数只收 vacation 布尔(假期中失败类全静默,任务照跑日志照记)。
"""

from __future__ import annotations

import datetime as dt
import logging
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

SUCCESS = "success"              # 任务成功(1.6.0:默认开、设置可关)
FAILED = "fail_cred"             # 任务失败·凭据类(带原因)
NET_FAIL = "fail_net"            # 任务失败·连不上(1.6.0:纯诊断也发)
MAINTENANCE = "maintenance"      # 维护页连续 ≥3 拍
TASK_LOST = "task_lost"          # 任务被拦/丢失(ensure 自检发现,QA P1-5)

COOLDOWN_S = 30 * 60             # 拍板 #5:同类 30 分钟内合并为一条

LAUNCH_MAIN = "guigui://main"
LAUNCH_CREDS = "guigui://creds"
LAUNCH_SETTINGS = "guigui://settings"
# 1.6.0 深链(契约 §4 open_route):通知落点直达四视图
LAUNCH_FORM = "guigui://v-form"        # 登录页(凭据类失败通知)
LAUNCH_STATUS = "guigui://v-status"    # 状态页(成功/连不上/维护页通知)
LAUNCH_SUCCESS = "guigui://v-success"  # 成功/拦截页
LAUNCH_FEEDBACK = "guigui://v-feedback"
# 启动路由枚举(契约 §4;壳层与 __main__ 共用白名单)
OPEN_ROUTES = ("v-form", "v-status", "v-success", "v-feedback")


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


# WinRT 目标 API 从 v1 起就是它(powershell 里激活的也是这套);AppId 维持现值
_APP_ID = "Microsoft.Windows.ShellExperienceHost_cw5n1h2txyewy!App"

# 投影类型/静态方法缓存(首条通知加载后复用;加载失败不缓存,下次通知重试)
_WINRT_CACHE: dict = {}


def _winrt_mgr_create_notifier():
    """拿 CreateToastNotifier(String) 的 MethodInfo;失败抛异常(调用方降级)。

    Type.GetType 的 ", ContentType=WindowsRuntime" 后缀走 .NET 4.5+ 的 WinRT
    投影(spike 2026-09-11 实测通);投影静态方法是真 .NET 方法,MethodInfo
    .Invoke 可用 — InvokeMember 迟绑定不行(WinRT 对象无 IDispatch)。
    """
    if "create" not in _WINRT_CACHE:
        import clr                                     # noqa: F401 — pythonnet 随 pywebview 在运行时内
        from System import Type
        mgr_t = Type.GetType("Windows.UI.Notifications.ToastNotificationManager,"
                             " Windows.UI.Notifications, ContentType=WindowsRuntime")
        if mgr_t is None:
            raise RuntimeError("WinRT ToastNotificationManager 投影加载失败")
        mi = [m for m in mgr_t.GetMethods()
              if m.Name == "CreateToastNotifier" and m.GetParameters().Length == 1]
        _WINRT_CACHE["create"] = mi[0] if mi else None
    mi = _WINRT_CACHE["create"]
    if mi is None:
        raise RuntimeError("CreateToastNotifier(String) 未找到")
    return mi


def _winrt_new_doc():
    """XmlDocument 实例(投影类型构造);失败抛异常。"""
    import clr                                         # noqa: F401
    from System import Activator, Type
    xml_t = Type.GetType("Windows.Data.Xml.Dom.XmlDocument,"
                         " Windows.Data.Xml.Dom, ContentType=WindowsRuntime")
    if xml_t is None:
        raise RuntimeError("WinRT XmlDocument 投影加载失败")
    return Activator.CreateInstance(xml_t)


def _winrt_new_toast(doc):
    """ToastNotification 实例(ctor 吃 XmlDocument);失败抛异常。"""
    import clr                                         # noqa: F401
    from System import Activator, Type
    toast_t = Type.GetType("Windows.UI.Notifications.ToastNotification,"
                           " Windows.UI.Notifications, ContentType=WindowsRuntime")
    if toast_t is None:
        raise RuntimeError("WinRT ToastNotification 投影加载失败")
    return Activator.CreateInstance(toast_t, doc)


def _toast_xml(t: str, m: str, lc: str) -> str:
    """Toast 模板拼装(双通道共用)。guigui:// 未注册成时降级纯展示(QA P2-8):
    不设 activationType/launch,不让 toast 承诺一个点了没反应的动作。"""
    if protocol_registered():
        toast_open = f'<toast activationType="protocol" launch="{lc}" duration="long">'
    else:
        toast_open = '<toast duration="long">'
    return (f"{toast_open}<visual><binding template=\"ToastGeneric\">"
            f"<text>{t}</text><text>{m}</text>"
            "</binding></visual></toast>")


def _send_winrt(xml: str) -> bool:
    """主通道:pythonnet 进程内直调 WinRT;失败只记日志返回 False(降级 powershell)。

    早绑定点调用(LoadXml / Show),绝不 InvokeMember 迟绑定 — WinRT 无
    IDispatch。System.String → HSTRING 由 .NET 投影层自动封送。"""
    try:
        doc = _winrt_new_doc()
        doc.LoadXml(xml)                               # pythonnet 早绑定
        toast = _winrt_new_toast(doc)
        notifier = _winrt_mgr_create_notifier().Invoke(None, [_APP_ID])
        notifier.Show(toast)                            # pythonnet 早绑定
        return True
    except Exception as e:
        log.info("notify: WinRT 主通道失败,降级 powershell: %s", e)
        return False


def _send_powershell(xml: str) -> None:
    """兜底通道:v1 生产验证过的 powershell WinRT 激活;超时/失败只记日志。"""
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager,"
        " Windows.UI.Notifications, ContentType=WindowsRuntime]|Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom,"
        " ContentType=WindowsRuntime]|Out-Null;"
        f"$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('{xml}');"                          # xml 已实体转义,无裸单引号
        "$toast=[Windows.UI.Notifications.ToastNotification]::new($x);"
        '[Windows.UI.Notifications.ToastNotificationManager]'
        f'::CreateToastNotifier("{_APP_ID}")'
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


def send(title: str, message: str, launch: str = LAUNCH_MAIN) -> None:
    """发 Toast;永不抛异常(v1 行为)。主通道 WinRT 进程内直调(ADR-0002),
    失败降级 powershell — 自救指引可用性与 powershell 单点解耦(S4)。"""
    t, m, lc = _xml_escape(title), _xml_escape(message), _xml_escape(launch)
    xml = _toast_xml(t, m, lc)
    if _send_winrt(xml):
        return
    _send_powershell(xml)


# ── 去重决策(纯函数,AC-04)──────────────────────────────


_direct_last: dict[str, dict] = {}   # 直发类(task_blocked 等)进程内冷却账本


def _direct_gate(kind: str) -> bool:
    """直发类冷却(拍板 #5 同口径:同类 30 分钟合并 + 每天每类 ≤1)。

    task_blocked / task_linger / task_lost 由用户动作(GUI 保存/启动对齐)
    或 ensure 自检触发,不在 ensure 冷却账本里;用进程内账本挡同一 GUI
    会话内的连拍刷屏(保存 5 次 = 最多 1 条 toast)。"""
    now = time.time()
    today = dt.date.today().isoformat()
    rec = _direct_last.get(kind) or {}
    if rec.get("date") == today:
        return False
    if rec.get("ts") and now - rec["ts"] < COOLDOWN_S:
        return False
    _direct_last[kind] = {"date": today, "ts": now}
    return True


def task_blocked() -> None:
    """建任务被安全软件拦时的指引通知(点开直达设置页)。

    仅在用户主动动作(保存设置/切总开关/GUI 启动对齐)后调用,
    --ensure 定时路径不建任务,不会每天刷屏。"""
    if not _direct_gate("task_blocked"):
        return
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
    if not _direct_gate("task_linger"):
        return
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
    if not _direct_gate("task_lost"):
        return
    send(
        "桂桂",
        "定时任务不见了,自动登录可能已经停了。"
        "点开设置,按「点此重建」就好。",
        launch=LAUNCH_SETTINGS,
    )


def _cooldown_gate(kind: str, sent: dict, *, today: str, now: float) -> bool:
    """冷却闸(纯):同类 30 分钟内合并为一条(不重发)+ 每类每天 ≤1。

    通过则当场记账(写回 sent),调用方把 sent 持久化进 ensure_state。"""
    rec = sent.get(kind) or {}
    if rec.get("date") == today:
        return False
    if rec.get("ts") and now - rec["ts"] < COOLDOWN_S:
        return False
    sent[kind] = {"date": today, "ts": now}
    return True


def decide_notify(prev_state: str | None, *, connected: bool,
                  outcome: str | None = None,
                  before_anchor: bool = False, maintenance_streak: int = 0,
                  sent: dict | None = None,
                  today: str = "", now: float = 0.0,
                  vacation: bool = False,
                  ) -> tuple[str | None, dict]:
    """1.6.0 通知矩阵(纯函数,用户拍板 2026-09-11)。

    Args:
        outcome: 本拍失败形态 — "rejected"(凭据类被拒)| "unexpected"(维护页)
                 | None(连不上/未尝试登录)。
        before_anchor: 06:50 开门前 → 一切失败只算「还没开门」,不算断网事件。
        sent: 冷却账本(kind → {date, ts}),来自 ensure_state["notify_sent"]。
        vacation: 假期模式(ensure 判定:连续 3 天不可达自动进 / 恢复可达退,
                 手动开关任一生效)— 假期中失败类全静默;成功类在恢复可达
                 (=假期自动退出)之后才判,故此处 vacation 只压失败类。

    Returns:
        (notify_kind, updates):kind ∈ success | fail_cred | fail_net |
        maintenance | None;updates 合并进 ensure_state(notify_sent 含新账本)。
    """
    book = {k: dict(v) for k, v in (sent or {}).items()}

    def out(kind, updates):
        updates["notify_sent"] = book
        return kind, updates

    if connected:
        # 任务成功 = 发(1.6.0;默认开,设置 notifications 可关 — 开关在调用方)
        updates = {"last_net_state": "up"}
        if _cooldown_gate(SUCCESS, book, today=today, now=now):
            return out(SUCCESS, updates)
        return out(None, updates)
    if before_anchor:
        # 锚前被拒/不可达:不判失败、不发通知、不动 net_state(防窗口期错怪,AC-12)
        return None, {}
    if outcome == "rejected":
        # 凭据类失败:发带原因(文案由调用方拼),当拍即判 + 冷却闸
        if not vacation and _cooldown_gate(FAILED, book, today=today, now=now):
            return out(FAILED, {"last_net_state": "failed"})
        return out(None, {"last_net_state": "failed"})
    if outcome == "unexpected":
        # 维护页:连续 ≥3 拍才弹(质量闸)+ 冷却闸
        if (not vacation and maintenance_streak >= 3
                and _cooldown_gate(MAINTENANCE, book, today=today, now=now)):
            return out(MAINTENANCE, {"last_net_state": "failed"})
        return out(None, {"last_net_state": "failed"})
    # 连不上(未尝试登录):也发,纯诊断(1.6.0;假期中静默)
    if not vacation and _cooldown_gate(NET_FAIL, book, today=today, now=now):
        return out(NET_FAIL, {"last_net_state": "down"})
    return out(None, {"last_net_state": "down"})


# ── guigui:// 协议注册(HKCU,免管理员)─────────────────


def protocol_registered() -> bool:
    """guigui:// 是否已注册到当前用户(读 HKCU command 子键)。

    供 send() 降级判断用:查不到一律当未注册(winreg 缺失/键不存在/
    读失败),宁降级展示也不让点击落空;永不抛异常。"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Classes\guigui\shell\open\command")
        with key:
            winreg.QueryValueEx(key, None)
        return True
    except Exception:
        return False


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
