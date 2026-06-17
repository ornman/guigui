"""config.json 读写与 Schema 校验。"""

import json
import logging
import re
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# ── 路径解析 ──
# 打包模式（PyInstaller）用 exe 所在目录，开发模式用项目根目录
_FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if _FROZEN else Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"
LOG_PATH = APP_DIR / "login.log"

# ── 默认配置 ──
# 窗口化自动化模型：
#   scheduled_login_time  = 窗口中心（展示用，如 06:55）
#   window_duration_minutes = 窗口总时长（前后各半，默认 60 → 06:25–07:25）
#   heartbeat_interval_minutes = 窗口内每 N 分钟探测（默认 5）
#   patrol_enabled / patrol_interval_minutes = 全天巡逻（默认关，每 30 分钟）
#   resilience_enabled = 自动化总开关（窗口任务 + AtLogon 是否部署）
_DEFAULTS = {
    "url": "http://10.1.2.3",
    "wifi_ssid": "",
    "operator": "中国电信",
    "username": "",
    "password": "",
    "max_retries": 3,
    "retry_interval_seconds": 5,
    "scheduled_login_time": "06:55",
    "window_duration_minutes": 60,
    "heartbeat_interval_minutes": 5,
    "patrol_enabled": False,
    "patrol_interval_minutes": 30,
    "notification_enabled": True,
    "resilience_enabled": True,
}

# ── 校验规则 ──
# 每条规则：(键名, 期望类型, 校验 lambda, 不合法时的回退值)
# 注意：validate 只保留 schema 内的键，旧版残留字段（polling_*/auto_start/
# scheduled_login_enabled）会被丢弃，确保配置干净收敛到新模型。
_VALIDATORS = [
    ("url", str, lambda v: v.startswith("http"), _DEFAULTS["url"]),
    ("max_retries", int, lambda v: v > 0, _DEFAULTS["max_retries"]),
    ("retry_interval_seconds", int, lambda v: v >= 0, _DEFAULTS["retry_interval_seconds"]),
    ("scheduled_login_time", str, lambda v: bool(re.match(r"^\d{2}:\d{2}$", v)), _DEFAULTS["scheduled_login_time"]),
    ("window_duration_minutes", int, lambda v: v > 0, _DEFAULTS["window_duration_minutes"]),
    ("heartbeat_interval_minutes", int, lambda v: v >= 1, _DEFAULTS["heartbeat_interval_minutes"]),
    ("patrol_interval_minutes", int, lambda v: v >= 1, _DEFAULTS["patrol_interval_minutes"]),
    ("patrol_enabled", bool, lambda v: True, _DEFAULTS["patrol_enabled"]),
    ("notification_enabled", bool, lambda v: True, _DEFAULTS["notification_enabled"]),
    ("resilience_enabled", bool, lambda v: True, _DEFAULTS["resilience_enabled"]),
    ("wifi_ssid", str, lambda v: True, _DEFAULTS["wifi_ssid"]),
    ("operator", str, lambda v: True, _DEFAULTS["operator"]),
    ("username", str, lambda v: True, _DEFAULTS["username"]),
    ("password", str, lambda v: True, _DEFAULTS["password"]),
]


def validate(cfg: dict) -> dict:
    """校验并修正配置值，返回仅含 schema 键的新 dict（不修改原对象）。

    遍历 ``_VALIDATORS`` 中的每条规则：
    1. 键不存在 → 使用默认值
    2. 类型不匹配 → 使用默认值并记录警告日志
    3. 校验函数返回 False → 使用默认值并记录警告日志
    4. 合法则保留原值

    不在 schema 内的键（如旧版残留的 polling_*/auto_start）会被丢弃，
    保证配置干净收敛到当前模型。
    """
    result: dict = {}
    for key, expected_type, validator, fallback in _VALIDATORS:
        value = cfg.get(key, fallback)
        # bool 是 int 的子类：JSON true/false 不应被当作整数字段接受
        if isinstance(value, bool) and expected_type is not bool:
            log.warning("Config '%s': expected %s, got bool — using default %r",
                        key, expected_type.__name__, fallback)
            result[key] = fallback
            continue
        if not isinstance(value, expected_type):
            log.warning("Config '%s': expected %s, got %s — using default %r",
                        key, expected_type.__name__, type(value).__name__, fallback)
            result[key] = fallback
            continue
        if not validator(value):
            log.warning("Config '%s': invalid value %r — using default %r",
                        key, value, fallback)
            result[key] = fallback
        else:
            result[key] = value
    return result


def load() -> dict:
    """从 config.json 加载配置，与默认值合并后校验。

    文件不存在时返回全部默认值。
    """
    saved = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
    return validate({**_DEFAULTS, **saved})


def save(cfg: dict) -> None:
    """将配置字典写入 config.json（自动创建父目录）。"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
