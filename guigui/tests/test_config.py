"""config_v2:默认值/校验/原子写/tasks_rev/桥接白名单。"""

import json

import pytest

from guigui.core import config, paths


def test_load_defaults_when_missing():
    cfg = config.load()
    assert cfg["trigger_time"] == "07:00"
    assert cfg["wake_login"] is False          # PRD §5 默认关(技术方案 §14.5)
    assert cfg["vacation_silence"] is True
    assert cfg["tasks_rev"] == 0


def test_validate_falls_back_on_bad_values():
    bad = {**config.DEFAULTS, "trigger_time": "25:99", "heartbeat_minutes": 7,
           "login_retries": True, "master": "yes"}
    out = config.validate(bad)
    assert out["trigger_time"] == "07:00"
    assert out["heartbeat_minutes"] == 5
    assert out["login_retries"] == 3            # bool 不冒充 int
    assert out["master"] is True


def test_validate_drops_unknown_keys():
    out = config.validate({**config.DEFAULTS, "polling_enabled": True})
    assert "polling_enabled" not in out


def test_save_atomic_and_load_roundtrip():
    cfg = dict(config.DEFAULTS)
    cfg["trigger_time"] = "07:30"
    config.save(cfg)
    assert json.loads(paths.config_path().read_text(encoding="utf-8"))["trigger_time"] == "07:30"
    assert config.load()["trigger_time"] == "07:30"


def test_save_bumps_tasks_rev_on_scheduling_change_only():
    base = config.save(dict(config.DEFAULTS))
    rev0 = base["tasks_rev"]
    no_bump = config.save({**base, "notifications": False})
    assert no_bump["tasks_rev"] == rev0
    bump = config.save({**no_bump, "trigger_time": "06:45"})
    assert bump["tasks_rev"] == rev0 + 1


def test_to_bridge_excludes_internal():
    bridge = config.to_bridge(config.load())
    assert set(bridge) == set(config.BRIDGE_FIELDS)
    assert "uid" not in bridge and "tasks_rev" not in bridge


def test_apply_patch_validates_enum():
    cfg = dict(config.DEFAULTS)
    with pytest.raises(config.ConfigError):
        config.apply_patch(cfg, {"heartbeat_minutes": 7})
    with pytest.raises(config.ConfigError):
        config.apply_patch(cfg, {"trigger_time": "7点"})
    ok = config.apply_patch(cfg, {"trigger_time": "08:00", "patrol_minutes": 60})
    assert ok["trigger_time"] == "08:00" and ok["patrol_minutes"] == 60
    # 未知键忽略、未提到的键保持
    same = config.apply_patch(ok, {"__proto__": 1})
    assert same["trigger_time"] == "08:00"


def test_operator_default_value():
    assert config.DEFAULTS["operator"] == "校园用户"
    assert config.load()["operator"] == "校园用户"


def test_validate_invalid_operator_falls_back():
    out = config.validate({**config.DEFAULTS, "operator": "乱写的运营商"})
    assert out["operator"] == "校园用户"
    out = config.validate({**config.DEFAULTS, "operator": 123})      # 类型错也回退
    assert out["operator"] == "校园用户"
    out = config.validate({**config.DEFAULTS, "operator": "校园电信"})
    assert out["operator"] == "校园电信"


def test_apply_patch_rejects_unknown_operator():
    cfg = dict(config.DEFAULTS)
    with pytest.raises(config.ConfigError, match="运营商"):
        config.apply_patch(cfg, {"operator": "乱写的运营商"})


def test_apply_patch_accepts_valid_operator():
    cfg = dict(config.DEFAULTS)
    ok = config.apply_patch(cfg, {"operator": "校园联通"})
    assert ok["operator"] == "校园联通"


def test_to_bridge_includes_operator():
    bridge = config.to_bridge(config.load())
    assert "operator" in bridge and bridge["operator"] == "校园用户"


def test_operator_campus_other_valid_roundtrip():
    out = config.validate({**config.DEFAULTS, "operator": "校园其他"})
    assert out["operator"] == "校园其他"
    ok = config.apply_patch(config.load(), {"operator": "校园其他"})
    assert ok["operator"] == "校园其他"


def test_operator_alias_accepted():
    # 2026-09-06:展示别名(移动/广电)合法入配置,登录侧归一到校园其他(空后缀)
    out = config.validate({**config.DEFAULTS, "operator": "中国移动"})
    assert out["operator"] == "中国移动"
    merged = config.apply_patch(dict(config.DEFAULTS), {"operator": "中国广电"})
    assert merged["operator"] == "中国广电"
