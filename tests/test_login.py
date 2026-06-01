"""Tests for src.login — URL construction and response parsing."""

import json
from unittest.mock import patch, MagicMock

import pytest

from src.login import do_login, is_logged_in


class TestIsLoggedIn:
    def test_logged_in_page(self):
        html = "<html><title>信息注销</title></html>"
        with patch("src.login.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = html.encode("gb2312")
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            assert is_logged_in() is True

    def test_not_logged_in_page(self):
        html = "<html><title>登录页面</title></html>"
        with patch("src.login.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = html.encode("gb2312")
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            assert is_logged_in() is False

    def test_network_error_returns_false(self):
        with patch("src.login.urlopen", side_effect=Exception("timeout")):
            assert is_logged_in() is False


class TestDoLogin:
    def _mock_response(self, result: int, msga: str = "") -> str:
        """Build a JSONP response body."""
        payload = json.dumps({"result": result, "msga": msga})
        return f"dr1003({payload})"

    def test_login_success(self):
        body = self._mock_response(1, "success")
        cfg = {"operator": "中国电信", "username": "123", "password": "pw"}
        with patch("src.login.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = body.encode("gbk")
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            assert do_login(cfg) is True

    def test_login_failure(self):
        body = self._mock_response(0, "wrong password")
        cfg = {"operator": "中国电信", "username": "123", "password": "wrong"}
        with patch("src.login.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = body.encode("gbk")
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            assert do_login(cfg) is False

    def test_unexpected_response(self):
        cfg = {"operator": "中国电信", "username": "123", "password": "pw"}
        with patch("src.login.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"not jsonp"
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            assert do_login(cfg) is False
