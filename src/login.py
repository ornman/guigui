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


def is_logged_in() -> bool:
    """Check current login status via page title."""
    base = _base_url()
    try:
        req = Request(base + "/", headers={"User-Agent": UA})
        with urlopen(req, timeout=5) as resp:
            html = resp.read().decode("gb2312", errors="replace")
        m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
        return bool(m and "注销" in m.group(1))
    except Exception:
        return False


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

    log.info("Response: %s", body[:300])

    m = re.search(r"\((\{.*\})\)", body)
    if not m:
        log.error("Unexpected response format")
        return False

    data = json.loads(m.group(1))
    result = data.get("result")
    msga = data.get("msga", "")

    if result == 1:
        log.info("Login successful")
        return True

    log.warning("Login rejected: result=%s, msg=%s", result, msga)
    return False
