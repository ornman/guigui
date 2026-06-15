"""Tests for src.config — load, save, defaults merge."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import _DEFAULTS, load, save


class TestDefaults:
    def test_defaults_has_required_keys(self):
        required = ["url", "username", "password", "max_retries",
                     "retry_interval_seconds", "polling_enabled",
                     "polling_interval_seconds", "scheduled_login_enabled",
                     "scheduled_login_time", "auto_start",
                     "notification_enabled", "resilience_enabled",
                     "heartbeat_interval_minutes"]
        for key in required:
            assert key in _DEFAULTS, f"Missing default: {key}"


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


class TestResilienceFields:
    """意外恢复系统新增配置字段的校验测试。"""

    def test_defaults_include_resilience_fields(self):
        from src import config
        d = config.validate({})
        assert d["resilience_enabled"] is True
        assert d["heartbeat_interval_minutes"] == 15
        assert d["polling_enabled"] is True  # 默认改为开

    def test_heartbeat_interval_invalid_falls_back(self):
        from src import config
        d = config.validate({"heartbeat_interval_minutes": 0})
        assert d["heartbeat_interval_minutes"] == 15
        d = config.validate({"heartbeat_interval_minutes": "x"})
        assert d["heartbeat_interval_minutes"] == 15

    def test_resilience_enabled_must_be_bool(self):
        from src import config
        d = config.validate({"resilience_enabled": "yes"})
        assert d["resilience_enabled"] is True  # 非布尔 → 回退默认 True
