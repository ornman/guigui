"""``--ensure`` 静默执行体：幂等登录（含 WiFi 兜底）+ 状态翻转通知去重。

治弹窗核心：本模块**绝不**拉起 GUI/托盘进程，只做登录与通知。
通知仅在「断→通」或「登录失败」状态翻转时各发一次；已登录不打扰。

每个 ``--ensure`` 是独立进程，通过 ``ensure_state.json`` 跨进程记忆上次状态，
据此去重（避免长时间断网时每 N 分钟刷一条失败通知）。
"""

import json
import logging

from . import config, login as login_mod, notify
from .config import APP_DIR

log = logging.getLogger(__name__)

STATE_PATH = APP_DIR / "ensure_state.json"


def decide_notify(prev: str | None, *, connected: bool,
                  login_attempted: bool, login_succeeded: bool) -> tuple[str | None, str]:
    """根据上次状态与本次结果，决定通知种类与新的持久化状态。

    Args:
        prev: 上次持久化的状态（"up"/"down"/"failed"/None）。
        connected: 本次最终是否已登录。
        login_attempted: 本次是否尝试过登录。
        login_succeeded: 本次登录是否成功。

    Returns:
        (notify_kind, new_state)，notify_kind 为 "recovered"/"failed"/None。
    """
    if connected:
        new_state = "up"
        # 仅在「之前确实有问题」时才报恢复；首次运行就在线不打扰
        notify_kind = "recovered" if prev in ("down", "failed") else None
        return notify_kind, new_state
    if login_attempted and not login_succeeded:
        new_state = "failed"
        notify_kind = None if prev == "failed" else "failed"
        return notify_kind, new_state
    # 不可达且未尝试登录：只记录 down，不通知（避免刷屏）
    return None, "down"


def _load_prev_state() -> str | None:
    """读取上次持久化状态；无文件/出错返回 None。"""
    try:
        if STATE_PATH.exists():
            return json.loads(STATE_PATH.read_text(encoding="utf-8")).get("last_state")
    except Exception as e:
        log.warning("Ensure: 读取状态失败: %s", e)
    return None


def _save_prev_state(state: str) -> None:
    """持久化本次状态（失败只记日志，不影响主流程）。"""
    try:
        STATE_PATH.write_text(json.dumps({"last_state": state}), encoding="utf-8")
    except Exception as e:
        log.warning("Ensure: 状态持久化失败: %s", e)


def run() -> int:
    """静默执行主流程，返回退出码（0=正常）。

    探测状态 → 必要时完整登录（含 WiFi 兜底）→ 状态翻转去重通知。
    """
    cfg = config.load()
    if not cfg.get("username") or not cfg.get("password"):
        log.warning("Ensure: 未配置凭据，跳过")
        return 0

    auth = login_mod.check_auth_status()
    log.info("Ensure: auth=%s", auth)

    login_attempted = False
    login_succeeded = False
    if auth == "not_logged_in":
        login_attempted = True
        try:
            # 完整重连（含 WiFi 兜底），不再 skip_wifi——否则窗口/巡逻无法真正保登录
            result = login_mod.attempt_login(cfg)
            login_succeeded = (result == "success")
        except Exception as e:
            log.warning("Ensure: 登录异常: %s", e)
        # 以最终探测状态为准（登录后可能已在线）
        auth = login_mod.check_auth_status()

    connected = (auth == "logged_in")
    prev = _load_prev_state()
    notify_kind, new_state = decide_notify(
        prev, connected=connected,
        login_attempted=login_attempted, login_succeeded=login_succeeded)

    if notify_kind and cfg.get("notification_enabled", True):
        if notify_kind == "recovered":
            notify.send("校园网已恢复", "已重新连上网络")
        else:  # "failed"
            notify.send("校园网登录失败", "多次重试未成功，请检查账号或网络")

    _save_prev_state(new_state)
    return 0
