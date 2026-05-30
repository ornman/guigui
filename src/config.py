"""Config.json read/write."""

import json
import sys
from pathlib import Path

_FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if _FROZEN else Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"
LOG_PATH = APP_DIR / "login.log"

_DEFAULTS = {
    "url": "http://10.1.2.3",
    "wifi_ssid": "",
    "operator": "中国电信",
    "username": "",
    "password": "",
    "max_retries": 3,
    "retry_interval_seconds": 5,
    "polling_enabled": False,
    "polling_interval_seconds": 30,
    "scheduled_login_enabled": False,
    "scheduled_login_time": "06:55",
    "auto_start": False,
    "notification_enabled": True,
}


def load() -> dict:
    saved = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
    return {**_DEFAULTS, **saved}


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
