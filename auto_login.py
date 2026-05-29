"""School network (Dr.COM) auto-login via HTTP GET (JSONP)."""

import json
import logging
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen, Request
from urllib.error import URLError

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    SCRIPT_DIR = Path(sys.executable).parent
else:
    SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
LOG_PATH = SCRIPT_DIR / "login.log"

logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# exe (交互模式) 显示控制台输出; pythonw (定时任务) 不显示
if sys.stdout is not None:
    _console = logging.StreamHandler(sys.stdout)
    _console.setLevel(logging.INFO)
    _console.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_console)

OPERATOR_SUFFIX = {
    "中国电信": "",
    "电信": "",
    "中国联通": "",
    "联通": "",
    "校园用户": "",
}
LOGIN_URL = "http://10.1.2.3/drcom/login"
CHECK_URL = "http://10.1.2.3/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"


def _xml_escape(text: str) -> str:
    """Escape text for safe embedding in XML attribute content."""
    text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
    return "".join(f"&#x{ord(c):X};" if ord(c) > 127 else c for c in text)


def notify(title: str, msg: str) -> None:
    """Send a Windows toast notification."""
    t, m = _xml_escape(title), _xml_escape(msg)
    ps_script = (
        "[Windows.UI.Notifications.ToastNotificationManager,"
        " Windows.UI.Notifications, ContentType=WindowsRuntime]|Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom,"
        " ContentType=WindowsRuntime]|Out-Null;"
        f'$t=\'<toast duration="long"><visual><binding template="ToastGeneric">'
        f"<text>{t}</text><text>{m}</text>"
        '</binding></visual></toast>\';'
        "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
        "$x.LoadXml($t);"
        "$toast=[Windows.UI.Notifications.ToastNotification]::new($x);"
        '[Windows.UI.Notifications.ToastNotificationManager]'
        '::CreateToastNotifier("Microsoft.Windows.ShellExperienceHost_cw5n1h2txyewy!App")'
        ".Show($toast)"
    )
    subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
    )


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_current_wifi() -> str | None:
    """Return the SSID of the currently connected Wi-Fi, or None."""
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("SSID") and ":" in line:
                return line.split(":", 1)[1].strip() or None
    except Exception as e:
        log.warning(f"Cannot detect current Wi-Fi: {e}")
    return None


def connect_wifi(target_ssid: str, timeout: int = 30) -> bool:
    """Ensure the machine is connected to *target_ssid*. Returns True on success."""
    current = get_current_wifi()
    if current == target_ssid:
        log.info(f"Already connected to Wi-Fi '{target_ssid}'")
        return True

    if current:
        log.info(f"Current Wi-Fi is '{current}', switching to '{target_ssid}'...")
    else:
        log.info(f"Not connected to any Wi-Fi, connecting to '{target_ssid}'...")

    try:
        result = subprocess.run(
            [
                "netsh", "wlan", "connect",
                f"ssid={target_ssid}",
                f"name={target_ssid}",
            ],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        log.info(f"netsh connect output: {result.stdout.strip()}")
        if "successfully" not in result.stdout.lower() and result.returncode != 0:
            log.warning(f"Connect command may have failed: {result.stderr.strip()}")
    except Exception as e:
        log.error(f"Failed to run netsh connect: {e}")
        return False

    # Wait for the connection to stabilise
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        if get_current_wifi() == target_ssid:
            log.info(f"Successfully connected to '{target_ssid}'")
            return True

    log.warning(f"Timed out waiting for Wi-Fi '{target_ssid}' ({timeout}s)")
    return False


def wait_for_network(timeout: int = 120, interval: int = 5) -> bool:
    """Block until the auth server (10.1.2.3) is reachable."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urlopen(Request(CHECK_URL, headers={"User-Agent": UA}), timeout=3)
            return True
        except Exception:
            remaining = int(deadline - time.time())
            log.info(f"Network not ready, retrying... ({remaining}s left)")
            time.sleep(interval)
    return False


def fetch_page() -> str:
    req = Request(CHECK_URL, headers={"User-Agent": UA})
    with urlopen(req, timeout=5) as resp:
        return resp.read().decode("gb2312", errors="replace")


def is_logged_in(page_html: str) -> bool:
    m = re.search(r"<title>(.*?)</title>", page_html, re.IGNORECASE)
    if m:
        return "注销" in m.group(1)
    return False


def do_login(cfg: dict) -> bool:
    suffix = OPERATOR_SUFFIX.get(cfg["operator"], "")
    username = cfg["username"] + suffix

    params = (
        f"callback=dr1003"
        f"&DDDDD={quote(username, safe='@')}"
        f"&upass={quote(cfg['password'])}"
        f"&0MKKey=123456"
        f"&R1=0&R2=&R3=1&R6=0"
        f"&para=00&v6ip="
        f"&terminal_type=1"
        f"&lang=zh-cn&jsVersion=4.2.1"
        f"&v={int(time.time())}&lang=zh"
    )
    url = f"{LOGIN_URL}?{params}"

    log.info(f"Sending login request (user={username})...")
    req = Request(url, headers={"User-Agent": UA, "Referer": "http://10.1.2.3/"})
    with urlopen(req, timeout=10) as resp:
        body = resp.read().decode("gbk", errors="replace")

    log.info(f"Response: {body[:300]}")

    m = re.search(r"\((\{.*\})\)", body)
    if not m:
        log.error("Unexpected response format.")
        return False

    data = json.loads(m.group(1))
    result = data.get("result")
    msga = data.get("msga", "")

    if result == 1:
        log.info("Login successful!")
        return True

    log.warning(f"Login rejected: result={result}, msg={msga}")
    return False


def main() -> None:
    cfg = load_config()
    max_retries: int = cfg.get("max_retries", 3)
    retry_interval: int = cfg.get("retry_interval_seconds", 5)
    target_wifi: str | None = cfg.get("wifi_ssid")

    log.info("=== Auto-login started ===")

    # Step 1: Ensure we're on the right Wi-Fi
    if target_wifi:
        if not connect_wifi(target_wifi):
            log.warning("Wi-Fi connect failed, will still try login...")

    # Step 2: Wait for network reachability
    if not wait_for_network(timeout=120, interval=5):
        log.error("Network unavailable after waiting 120s")
        notify("校园网登录失败", "网络不可用，请检查连接")
        sys.exit(1)

    try:
        page_html = fetch_page()
        log.info(f"Page fetched ({len(page_html)} bytes)")
    except Exception as e:
        log.error(f"Cannot reach login page: {e}")
        notify("校园网登录失败", f"无法连接: {e}")
        sys.exit(1)

    if is_logged_in(page_html):
        log.info("Already logged in, nothing to do.")
        log.info("=== Done ===")
        notify("校园网", "已登录，无需操作")
        return

    for attempt in range(1, max_retries + 1):
        try:
            log.info(f"Attempt {attempt}/{max_retries}")
            if do_login(cfg):
                log.info("=== Done (success) ===")
                notify("校园网登录成功", "已连接网络")
                return
        except URLError as e:
            log.error(f"Network error: {e}")
        except Exception as e:
            log.error(f"Attempt {attempt} error: {e}")

        if attempt < max_retries:
            log.info(f"Retrying in {retry_interval}s...")
            time.sleep(retry_interval)

    log.error("=== Auto-login failed after all retries ===")
    notify("校园网登录失败", "重试次数已用完")
    sys.exit(1)


if __name__ == "__main__":
    main()
