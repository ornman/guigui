"""WiFi management via netsh."""

import logging
import subprocess
import time

log = logging.getLogger(__name__)


def current_ssid() -> str | None:
    try:
        r = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("SSID") and "BSSID" not in line and ":" in line:
                return line.split(":", 1)[1].strip() or None
    except Exception as e:
        log.warning("Cannot detect Wi-Fi: %s", e)
    return None


def _find_profile(target_ssid: str) -> str | None:
    try:
        r = subprocess.run(
            ["netsh", "wlan", "show", "profiles"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        for line in r.stdout.splitlines():
            if ":" not in line:
                continue
            name = line.split(":", 1)[1].strip()
            if name == target_ssid:
                return name
    except Exception as e:
        log.warning("Cannot list WiFi profiles: %s", e)
    return None


def connect(target_ssid: str, retries: int = 3, wait: int = 30) -> bool:
    """Switch to *target_ssid*. Returns True on success."""
    cur = current_ssid()
    if cur == target_ssid:
        log.info("Already on '%s'", target_ssid)
        return True

    log.info("Switching to '%s'...", target_ssid)
    profile = _find_profile(target_ssid) or target_ssid

    for attempt in range(1, retries + 1):
        log.info("WiFi connect attempt %d/%d", attempt, retries)
        try:
            subprocess.run(
                ["netsh", "wlan", "connect", f"ssid={target_ssid}", f"name={profile}"],
                capture_output=True, text=True, timeout=15,
            )
        except Exception as e:
            log.error("netsh failed: %s", e)
            continue

        deadline = time.time() + wait
        while time.time() < deadline:
            time.sleep(3)
            if current_ssid() == target_ssid:
                log.info("Connected to '%s'", target_ssid)
                return True

    log.warning("Failed to connect to '%s'", target_ssid)
    return False
