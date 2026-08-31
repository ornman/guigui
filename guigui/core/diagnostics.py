"""问题反馈 — 打码诊断文本(契约 §2.12 feedback() 的内容源)。

纪律:密码永不出现;学号打码(drcom.mask_uid);只聚合既有状态 + 一次实时探测,
不发起新登录、不写任何文件。
"""

from __future__ import annotations

import datetime as dt
import platform

import guigui
from . import config, detect, drcom, logstore, scheduler, vault

LOG_DAYS = 3

_STATE_ZH = {
    "logged_in": "已登录",
    "not_logged_in": "未登录",
    "unreachable": "不可达",
    "waiting": "网络未就绪",
}


def _on_off(flag: bool) -> str:
    return "开" if flag else "关"


def _net_line(cfg: dict) -> str:
    net = detect.probe(cfg)
    state = _STATE_ZH.get(net.get("state"), str(net.get("state")))
    ssid = net.get("ssid") or "未连接"
    return f"WiFi:{ssid} · 认证服务器:{cfg.get('server_name', '')}({state})"


def _config_line(cfg: dict) -> str:
    return (
        f"登录时间 {cfg['trigger_time']} · 心跳 {cfg['heartbeat_minutes']} 分钟"
        f" · 开机补登 {_on_off(cfg['boot_login'])} · 唤醒补登 {_on_off(cfg['wake_login'])}"
        f" · 巡逻 {_on_off(cfg['patrol_enabled'])}"
        f" · WiFi兜底 {_on_off(cfg['wifi_fallback_enabled'])}"
        f" · 假期静默 {_on_off(cfg['vacation_silence'])}"
        f" · 通知 {_on_off(cfg['notifications'])} · 总开关 {_on_off(cfg['master'])}"
    )


def _task_line(task_name: str) -> str:
    xml = scheduler.query_xml(task_name)
    if xml is None:
        return f"{task_name}:未注册"
    rev = scheduler.parse_rev(xml)
    return f"{task_name}:已注册(rev={rev})" if rev is not None else f"{task_name}:已注册(rev 未知)"


def _credential_line(cfg: dict) -> str:
    uid = cfg.get("uid") or ""
    if not uid:
        return "学号:未配置"
    saved = "凭据已保存" if vault.has_password(uid) else "凭据未保存"
    return f"学号:{drcom.mask_uid(uid)}({saved})"


def _logs_block() -> list[str]:
    lines = []
    for day in logstore.query(LOG_DAYS):
        for e in day["entries"]:
            lines.append(
                f"[{day['label']} {e.get('ts', '')} {str(e.get('level', '')).upper()}] "
                f"{e.get('text', '')}")
    return lines


def build_text() -> str:
    """生成多行纯文本诊断信息(可直接复制粘贴给开发者/AI 排查)。"""
    cfg = config.load()
    now = dt.datetime.now()
    parts = [
        f"桂桂 v{guigui.__version__} 诊断信息",
        f"生成时间:{now:%Y-%m-%d %H:%M:%S}",
        f"系统:{platform.system()} {platform.release()}({platform.version()}) {platform.machine()}",
        "",
        "── 网络 ──",
        _net_line(cfg),
        "",
        "── 配置 ──",
        _config_line(cfg),
        _credential_line(cfg),
        "",
        "── 自动化任务 ──",
        _task_line(scheduler.TASK_MAIN),
        _task_line(scheduler.TASK_PATROL),
        "",
        f"── 最近日志({LOG_DAYS} 天)──",
    ]
    logs = _logs_block()
    parts.extend(logs if logs else ["(暂无日志)"])
    return "\n".join(parts)
