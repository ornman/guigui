"""Tests for src.login — URL construction and response parsing."""

import json
from unittest.mock import patch, MagicMock, call

import pytest

from src.login import attempt_login, check_auth_status, do_login, is_logged_in


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


class TestCheckAuthStatus:
    """Tests for the tri-state auth status detection."""

    def _mock_page(self, html: str) -> MagicMock:
        resp = MagicMock()
        resp.read.return_value = html.encode("gb2312")
        resp.__enter__ = lambda s: resp
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_logged_in_page(self):
        html = "<html><title>信息注销</title></html>"
        with patch("src.login.urlopen", return_value=self._mock_page(html)):
            assert check_auth_status() == "logged_in"

    def test_not_logged_in_page(self):
        html = "<html><title>登录页面</title></html>"
        with patch("src.login.urlopen", return_value=self._mock_page(html)):
            assert check_auth_status() == "not_logged_in"

    def test_network_error_returns_unreachable(self):
        with patch("src.login.urlopen", side_effect=Exception("timeout")):
            assert check_auth_status() == "unreachable"


class TestAttemptLogin:
    """Tests for the attempt_login orchestration function."""

    CFG = {"operator": "中国电信", "username": "123", "password": "pw"}

    def _mock_page(self, html: str) -> MagicMock:
        resp = MagicMock()
        resp.read.return_value = html.encode("gb2312")
        resp.__enter__ = lambda s: resp
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def _jsonp(self, result: int) -> MagicMock:
        payload = json.dumps({"result": result, "msga": ""})
        resp = MagicMock()
        resp.read.return_value = f"dr1003({payload})".encode("gbk")
        resp.__enter__ = lambda s: resp
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_already_logged_in(self):
        """Quick path: server reachable and already authenticated."""
        html = "<html><title>信息注销</title></html>"
        with patch("src.login.urlopen", return_value=self._mock_page(html)):
            assert attempt_login(self.CFG) == "already_logged_in"

    def test_not_logged_in_login_succeeds(self):
        """Server reachable, not logged in → login succeeds on first try."""
        login_page = self._mock_page("<html><title>登录页面</title></html>")
        success_resp = self._jsonp(1)

        with patch("src.login.urlopen", side_effect=[login_page, success_resp]):
            assert attempt_login(self.CFG) == "success"

    def test_not_logged_in_all_retries_fail(self):
        """Server reachable, not logged in → all login attempts fail."""
        login_page = self._mock_page("<html><title>登录页面</title></html>")
        fail_resp = self._jsonp(0)
        # 1 check + 3 login attempts = 4 calls total
        with patch("src.login.urlopen", side_effect=[login_page, fail_resp, fail_resp, fail_resp]):
            assert attempt_login(self.CFG) == "failed"

    def test_unreachable_no_wifi_configured(self):
        """Server unreachable, no wifi_ssid → gives up immediately."""
        cfg = {**self.CFG, "wifi_ssid": ""}
        with patch("src.login.urlopen", side_effect=Exception("timeout")):
            with patch("src.login.wait_for_network", return_value=False):
                assert attempt_login(cfg) == "unreachable"

    def test_unreachable_wifi_fix_then_login(self):
        """Server unreachable → WiFi switch → network up → login succeeds."""
        timeout = Exception("timeout")
        login_page = self._mock_page("<html><title>登录页面</title></html>")
        success_resp = self._jsonp(1)

        with patch("src.login.urlopen", side_effect=[timeout, login_page, success_resp]), \
             patch("src.login.wait_for_network", return_value=True), \
             patch("src.wifi.connect") as mock_connect:
            cfg = {**self.CFG, "wifi_ssid": "CampusNet"}
            assert attempt_login(cfg) == "success"
            mock_connect.assert_called_once_with("CampusNet")
