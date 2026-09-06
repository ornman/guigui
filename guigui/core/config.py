"""config_v2.json 读写:默认值合并 + 枚举校验 + 原子写 + 调度版本号。

磁盘字段与桥接层同名(契约 §2.6,零映射);密码不在此文件(vault)。
凡影响任务计划的字段变更,tasks_rev 自动 +1,selfheal 据此对齐。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile

from . import drcom, paths

log = logging.getLogger(__name__)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# 桥接层可见字段(契约 §2.6;磁盘同名)
BRIDGE_FIELDS = (
    "trigger_time",
    "boot_login",
    "heartbeat_minutes",
    "wifi_fallback_enabled",
    "wifi_fallback_ssid",
    "patrol_enabled",
    "patrol_minutes",
    "wake_login",
    "vacation_silence",
    "notifications",
    "show_gui",
    "master",
    "login_retries",
    "retry_seconds",
    "operator",
)

# 内部字段(不进 getConfig)
INTERNAL_FIELDS = ("uid", "url", "server_name", "tasks_rev")

# 变更任一字段 → tasks_rev + 1(任务需要重建对齐)
SCHEDULING_FIELDS = (
    "trigger_time",
    "boot_login",
    "heartbeat_minutes",
    "wake_login",
    "patrol_enabled",
    "patrol_minutes",
    "master",
)

# 枚举约束(设置页自绘下拉的取值集,契约 §2.6 注释)
_ENUMS = {
    "heartbeat_minutes": {5, 10, 15},
    "patrol_minutes": {15, 30, 60},
    "login_retries": {1, 3, 5},
    "retry_seconds": {5, 10, 30},
}

_BOOL_FIELDS = frozenset({
    "boot_login", "wifi_fallback_enabled", "patrol_enabled", "wake_login",
    "vacation_silence", "notifications", "show_gui", "master",
})

DEFAULTS: dict = {
    "trigger_time": "07:00",
    "boot_login": True,
    "heartbeat_minutes": 5,
    "wifi_fallback_enabled": False,
    "wifi_fallback_ssid": None,
    "patrol_enabled": False,
    "patrol_minutes": 30,
    # PRD §5 默认关;契约 §2.6 示例为 true,分歧登记于技术方案 §14.5
    "wake_login": False,
    "vacation_silence": True,
    "notifications": True,
    "show_gui": True,
    "master": True,
    "login_retries": 3,
    "retry_seconds": 5,
    "operator": drcom.DEFAULT_OPERATOR,
    # 内部
    "uid": "",
    "url": "http://10.1.2.3",
    "server_name": "10.1.2.3",
    "tasks_rev": 0,
}


class ConfigError(ValueError):
    """配置值不合法(saveConfig 据此映射 SAVE_FAILED)。"""


def validate(cfg: dict) -> dict:
    """逐项校验:类型错/枚举外/格式错 → 回退默认值;丢弃 schema 外的键。"""
    result: dict = {}
    for key, fallback in DEFAULTS.items():
        value = cfg.get(key, fallback)
        if key in _BOOL_FIELDS:
            result[key] = value if isinstance(value, bool) else fallback
            if not isinstance(value, bool) and value != fallback:
                log.warning("config '%s': expected bool, got %r — 默认 %r", key, value, fallback)
        elif key == "trigger_time":
            ok = isinstance(value, str) and bool(_TIME_RE.match(value))
            result[key] = value if ok else fallback
        elif key in _ENUMS:
            # bool 是 int 子类:JSON true 不应被当枚举值接受
            ok = isinstance(value, int) and not isinstance(value, bool) and value in _ENUMS[key]
            result[key] = value if ok else fallback
        elif key == "operator":
            ok = isinstance(value, str) and (
                value in drcom.OPERATOR_TABLE or value in drcom.OPERATOR_ALIASES)
            result[key] = value if ok else fallback
            if not ok and value != fallback:
                log.warning("config 'operator': %r 不在枚举 %s — 默认 %r",
                            value, "/".join([*drcom.OPERATOR_TABLE, *drcom.OPERATOR_ALIASES]), fallback)
        elif key == "wifi_fallback_ssid":
            ok = value is None or (isinstance(value, str) and value.strip())
            result[key] = value if ok else fallback
        elif key == "uid":
            result[key] = value if isinstance(value, str) else fallback
        elif key == "url":
            ok = isinstance(value, str) and value.startswith("http")
            result[key] = value if ok else fallback
        elif key == "server_name":
            result[key] = value if isinstance(value, str) and value else fallback
        elif key == "tasks_rev":
            ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
            result[key] = value if ok else fallback
        else:  # 不可达分支,防御
            result[key] = fallback
        if result[key] != cfg.get(key, fallback) and key in _ENUMS:
            log.warning("config '%s': %r 不在枚举 %s — 默认 %r", key, value, sorted(_ENUMS[key]), fallback)
    return result


def load() -> dict:
    """读盘 + 默认值合并 + 校验;文件不存在返回全默认。"""
    saved: dict = {}
    p = paths.config_path()
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("config 读取失败(%s),使用默认值", e)
    return validate({**DEFAULTS, **saved})


def save(cfg: dict) -> dict:
    """校验 → 原子写盘;调度字段变更时 tasks_rev + 1。返回实际落盘的配置。"""
    old = load()
    new = validate(cfg)
    if any(new[k] != old[k] for k in SCHEDULING_FIELDS):
        new["tasks_rev"] = max(new["tasks_rev"], old["tasks_rev"]) + 1
    new["tasks_rev"] = new["tasks_rev"] if isinstance(new["tasks_rev"], int) else 0

    p = paths.config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp", prefix=".config_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(new, f, indent=2, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return new


def to_bridge(cfg: dict) -> dict:
    """getConfig 的返回形状(契约 §2.6,只含桥接字段)。"""
    return {k: cfg[k] for k in BRIDGE_FIELDS}


def apply_patch(cfg: dict, patch: dict) -> dict:
    """把 saveConfig 的增量 patch 应用到 cfg 上并返回新配置。

    只接受 BRIDGE_FIELDS 内的键;值不合法抛 ConfigError(消息可直接给前端)。
    未知键忽略(契约未定义行为,宽松处理避免前端版本差炸后端)。
    """
    new = dict(cfg)
    for key, value in (patch or {}).items():
        if key not in BRIDGE_FIELDS:
            continue
        if key in _BOOL_FIELDS and not isinstance(value, bool):
            raise ConfigError(f"{key} 应为开关值")
        if key == "trigger_time":
            if not isinstance(value, str) or not _TIME_RE.match(value):
                raise ConfigError("时间格式应为 HH:MM(00:00–23:59)")
        if key in _ENUMS:
            if not isinstance(value, int) or isinstance(value, bool) or value not in _ENUMS[key]:
                allowed = "/".join(str(v) for v in sorted(_ENUMS[key]))
                raise ConfigError(f"{key} 只能取 {allowed}")
        if key == "operator":
            if not isinstance(value, str) or not (
                    value in drcom.OPERATOR_TABLE or value in drcom.OPERATOR_ALIASES):
                raise ConfigError("运营商只能选 " + "/".join(
                    [*drcom.OPERATOR_TABLE, *drcom.OPERATOR_ALIASES]))
        if key == "wifi_fallback_ssid":
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ConfigError("兜底网络需从扫描列表选择")
        new[key] = value
    return new
