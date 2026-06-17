"""Tests for src.config — load, save, defaults merge."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import _DEFAULTS, load, save


class TestDefaults:
    def test_defaults_has_required_keys(self):
        required = ["url", "username", "password", "max_retries",
                     "retry_interval_seconds", "scheduled_login_time",
                     "window_duration_minutes", "notification_enabled",
                     "resilience_enabled", "heartbeat_interval_minutes",
                     "patrol_enabled", "patrol_interval_minutes"]
        for key in required:
            assert key in _DEFAULTS, f"Missing default: {key}"

    def test_defaults_drops_legacy_fields(self):
        """旧的轮询/自启/定时登录开关已移除（被巡逻任务取代）。"""
        for legacy in ("polling_enabled", "polling_interval_seconds",
                       "auto_start", "scheduled_login_enabled"):
            assert legacy not in _DEFAULTS, f"Legacy field should be removed: {legacy}"


class TestLoad:
    def test_load_returns_defaults_when_no_file(self, tmp_path: Path):
        with patch("src.config.CONFIG_PATH", tmp_path / "nope.json"):
            cfg = load()
        assert cfg["username"] == ""
        assert cfg["max_retries"] == 3

    def test_load_merges_saved_over_defaults(self, tmp_path: Path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"username": "123", "max_retries": 10}), encoding="utf-8")
        with patch("src.config.CONFIG_PATH", p):
            cfg = load()
        assert cfg["username"] == "123"
        assert cfg["max_retries"] == 10
        # Defaults still present for unoverridden keys
        assert cfg["password"] == ""
        assert cfg["retry_interval_seconds"] == 5


class TestSave:
    def test_save_creates_file(self, tmp_path: Path):
        p = tmp_path / "sub" / "config.json"
        with patch("src.config.CONFIG_PATH", p):
            save({"username": "test", "password": "pw"})
        assert p.exists()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["username"] == "test"

    def test_save_roundtrip(self, tmp_path: Path):
        p = tmp_path / "config.json"
        original = {**_DEFAULTS, "username": "abc", "max_retries": 5}
        with patch("src.config.CONFIG_PATH", p):
            save(original)
            loaded = load()
        assert loaded["username"] == original["username"]
        assert loaded["max_retries"] == original["max_retries"]


class TestWindowedAutomationFields:
    """窗口化自动化模型新增配置字段的校验测试。"""

    def test_defaults_include_window_patrol_fields(self):
        from src import config
        d = config.validate({})
        assert d["resilience_enabled"] is True              # 自动化总开关，默认开
        assert d["scheduled_login_time"] == "06:55"          # 窗口中心
        assert d["window_duration_minutes"] == 60            # 前后各 30 分钟
        assert d["heartbeat_interval_minutes"] == 5          # 窗口内每 5 分钟
        assert d["patrol_enabled"] is False                  # 全天巡逻默认关
        assert d["patrol_interval_minutes"] == 30            # 巡逻每 30 分钟

    def test_window_duration_invalid_falls_back(self):
        from src import config
        assert config.validate({"window_duration_minutes": 0})["window_duration_minutes"] == 60
        assert config.validate({"window_duration_minutes": "x"})["window_duration_minutes"] == 60

    def test_patrol_interval_invalid_falls_back(self):
        from src import config
        assert config.validate({"patrol_interval_minutes": 0})["patrol_interval_minutes"] == 30
        assert config.validate({"patrol_interval_minutes": -5})["patrol_interval_minutes"] == 30

    def test_patrol_enabled_must_be_bool(self):
        from src import config
        assert config.validate({"patrol_enabled": "yes"})["patrol_enabled"] is False

    def test_heartbeat_interval_invalid_falls_back(self):
        from src import config
        d = config.validate({"heartbeat_interval_minutes": 0})
        assert d["heartbeat_interval_minutes"] == 5
        d = config.validate({"heartbeat_interval_minutes": "x"})
        assert d["heartbeat_interval_minutes"] == 5

    def test_resilience_enabled_must_be_bool(self):
        from src import config
        d = config.validate({"resilience_enabled": "yes"})
        assert d["resilience_enabled"] is True  # 非布尔 → 回退默认 True

    def test_legacy_fields_in_saved_file_are_dropped(self):
        """旧 config.json 里残留的轮询/自启字段应被丢弃（不在新 schema 内）。"""
        from src import config
        d = config.validate({"polling_enabled": True, "auto_start": True,
                             "polling_interval_seconds": 9})
        assert "polling_enabled" not in d
        assert "auto_start" not in d
        assert "polling_interval_seconds" not in d
