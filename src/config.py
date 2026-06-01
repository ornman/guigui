"""Config.json read/write with schema validation."""

import json
import logging
import re
import sys
from pathlib import Path

log = logging.getLogger(__name__)

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

# Validation rules: (key, expected_type, validator, fallback)
_VALIDATORS = [
    ("url", str, lambda v: v.startswith("http"), _DEFAULTS["url"]),
    ("max_retries", int, lambda v: v > 0, _DEFAULTS["max_retries"]),
    ("retry_interval_seconds", int, lambda v: v >= 0, _DEFAULTS["retry_interval_seconds"]),
    ("polling_interval_seconds", int, lambda v: v >= 5, _DEFAULTS["polling_interval_seconds"]),
    ("scheduled_login_time", str, lambda v: bool(re.match(r"^\d{2}:\d{2}$", v)), _DEFAULTS["scheduled_login_time"]),
    ("polling_enabled", bool, lambda v: True, _DEFAULTS["polling_enabled"]),
    ("scheduled_login_enabled", bool, lambda v: True, _DEFAULTS["scheduled_login_enabled"]),
    ("auto_start", bool, lambda v: True, _DEFAULTS["auto_start"]),
    ("notification_enabled", bool, lambda v: True, _DEFAULTS["notification_enabled"]),
    ("wifi_ssid", str, lambda v: True, _DEFAULTS["wifi_ssid"]),
    ("operator", str, lambda v: True, _DEFAULTS["operator"]),
    ("username", str, lambda v: True, _DEFAULTS["username"]),
    ("password", str, lambda v: True, _DEFAULTS["password"]),
]


def _validate(cfg: dict) -> dict:
    """Validate and coerce config values, falling back to defaults."""
    for key, expected_type, validator, fallback in _VALIDATORS:
        value = cfg.get(key, fallback)
        if not isinstance(value, expected_type):
            log.warning("Config '%s': expected %s, got %s — using default %r",
                        key, expected_type.__name__, type(value).__name__, fallback)
            cfg[key] = fallback
            continue
        if not validator(value):
            log.warning("Config '%s': invalid value %r — using default %r",
                        key, value, fallback)
            cfg[key] = fallback
    return cfg


def load() -> dict:
    saved = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
    return _validate({**_DEFAULTS, **saved})


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
