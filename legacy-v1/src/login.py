"""Core login logic — Dr.COM HTTP GET (JSONP)."""

import json
import logging
import re
import time
from logging.handlers import RotatingFileHandler
from urllib.parse import quote
from urllib.request import urlopen, Request

from .config import LOG_PATH, load as load_config

# ── Logging ──────────────────────────────────────
_fmt = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
_root = logging.getLogger()
if not _root.handlers:
    _root.setLevel(logging.INFO)
    _fh = RotatingFileHandler(
        str(LOG_PATH), maxBytes=512 * 1024, backupCount=3, encoding="utf-8",
    )
    _fh.setFormatter(_fmt)
    _root.addHandler(_fh)

log = logging.getLogger(__name__)

_DEFAULT_BASE = "http://10.1.2.3"
LOGIN_PATH = "/drcom/login"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

OPERATOR_SUFFIX: dict[str, str] = {
    "中国电信": "",
    "中国联通": "",
    "校园用户": "",
}


def _base_url() -> str:
    """Read the auth server URL from config (defaults to 10.1.2.3)."""
    try:
        return load_config().get("url", _DEFAULT_BASE) or _DEFAULT_BASE
    except Exception:
        return _DEFAULT_BASE


def wait_for_network(timeout: int = 120, interval: int = 5) -> bool:
    """Block until the auth server is reachable."""
    base = _base_url()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urlopen(Request(base + "/", headers={"User-Agent": UA}), timeout=3)
            return True
        except Exception:
            remaining = int(deadline - time.time())
            log.info("Network not ready, retrying... (%ds left)", remaining)
            time.sleep(interval)
    return False


def check_auth_status() -> str:
    """Check auth server reachability and login status.

    Returns:
        "logged_in"     -- server reachable, user already authenticated
        "not_logged_in" -- server reachable, user needs to login
        "unreachable"   -- server not reachable (network error)
    """
    base = _base_url()
    try:
        req = Request(base + "/", headers={"User-Agent": UA})
        with urlopen(req, timeout=5) as resp:
            html = resp.read().decode("gb2312", errors="replace")
        m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
        if m and "注销" in m.group(1):
            return "logged_in"
        return "not_logged_in"
    except Exception:
        return "unreachable"


def is_logged_in() -> bool:
    """Check current login status via page title."""
    return check_auth_status() == "logged_in"


def do_login(cfg: dict) -> bool:
    """Send login request. Returns True on success."""
    base = cfg.get("url", _DEFAULT_BASE) or _DEFAULT_BASE
    suffix = OPERATOR_SUFFIX.get(cfg.get("operator", ""), "")
    username = cfg["username"] + suffix

    params = (
        f"callback=dr1003"
        f"&DDDDD={quote(username, safe='@')}"
        f"&upass={quote(cfg['password'])}"
        f"&0MKKey=123456&R1=0&R2=&R3=1&R6=0"
        f"&para=00&v6ip=&terminal_type=1"
        f"&lang=zh-cn&jsVersion=4.2.1"
        f"&v={int(time.time())}&lang=zh"
    )
    url = f"{base}{LOGIN_PATH}?{params}"

    log.info("Login request (user=%s)", username)
    req = Request(url, headers={"User-Agent": UA, "Referer": f"{base}/"})
    with urlopen(req, timeout=10) as resp:
        body = resp.read().decode("gbk", errors="replace")

    m = re.search(r"\((\{.*\})\)", body)
    if not m:
        log.error("Unexpected response format: %s", body[:80])
        return False

    data = json.loads(m.group(1))
    result = data.get("result")
    msga = data.get("msga", "")

    if result == 1:
        log.info("Login successful")
        return True

    log.warning("Login rejected: result=%s, msg=%s", result, msga)

    return False


def attempt_login(cfg: dict, skip_wifi: bool = False) -> str:
    """完整的登录编排：探测状态 → 必要时切换 WiFi → 执行登录。

    以认证服务器（默认 10.1.2.3）为唯一决策枢纽。仅当服务器不可达时
    才尝试 WiFi 切换作为恢复手段。

    Args:
        cfg: 登录配置字典（username/password/wifi_ssid 等）。
        skip_wifi: 心跳场景使用。为 True 时，当服务器不可达会直接放弃，
            不切换 WiFi、不阻塞等待网络（避免后台心跳抢占用户 WiFi
            或长时间阻塞）。默认 False，保持原有的 WiFi 恢复行为。

    Returns:
        "already_logged_in" -- 已经登录，无需操作
        "success"           -- 登录成功
        "failed"            -- 重试耗尽后登录失败
        "unreachable"       -- 服务器始终不可达
    """
    # Step 1: 快速探测当前状态
    status = check_auth_status()
    log.info("Auth status: %s", status)

    if status == "logged_in":
        return "already_logged_in"

    # Step 2: 不可达时，尝试切换 WiFi 作为恢复（心跳 skip_wifi 时不做）
    if status == "unreachable":
        if cfg.get("wifi_ssid") and not skip_wifi:
            from . import wifi
            log.info("Server unreachable, switching WiFi to '%s'...", cfg["wifi_ssid"])
            wifi.connect(cfg["wifi_ssid"])
            if not wait_for_network():
                return "unreachable"
            # 网络恢复后重新探测
            status = check_auth_status()
            log.info("Auth status after remediation: %s", status)
            if status == "logged_in":
                return "already_logged_in"
            if status == "unreachable":
                return "unreachable"
            # 补救后状态为 not_logged_in：落到 Step 3 执行登录
        else:
            # skip_wifi=True 或无 wifi_ssid：不做 WiFi 恢复，直接放弃
            return "unreachable"

    # Step 3: "not_logged_in" → attempt login with retries
    retries = cfg.get("max_retries", 3)
    interval = cfg.get("retry_interval_seconds", 5)
    for i in range(retries):
        if do_login(cfg):
            return "success"
        if i < retries - 1:
            log.info("Retry in %ds...", interval)
            time.sleep(interval)
    return "failed"
