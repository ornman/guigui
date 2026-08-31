"""detect:四态/等待判定/等门轮询(全 mock)。"""

import urllib.error

from guigui.core import detect


class FakeResp:
    def __init__(self, body: str):
        self._b = body.encode("gb2312", errors="replace")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _title_page(title: str) -> str:
    return f"<html><head><title>{title}</title></head></html>"


def test_http_probe_logged_in_by_title(monkeypatch):
    monkeypatch_local = monkeypatch
    monkeypatch_local.setattr(detect, "urlopen",
                              lambda req, timeout=None: FakeResp(_title_page("注销页面")))
    assert detect.http_probe("http://10.1.2.3")["state"] == "logged_in"


def test_http_probe_not_logged_in(monkeypatch):
    monkeypatch.setattr(detect, "urlopen",
                        lambda req, timeout=None: FakeResp(_title_page("登录页面")))
    assert detect.http_probe("http://10.1.2.3")["state"] == "not_logged_in"


def test_http_probe_timeout_vs_refused(monkeypatch):
    monkeypatch.setattr(detect, "urlopen", lambda req, timeout=None: (_ for _ in ()).throw(TimeoutError()))
    assert detect.http_probe("http://10.1.2.3")["detail"] == "timeout"
    monkeypatch.setattr(detect, "urlopen",
                        lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("refused")))
    out = detect.http_probe("http://10.1.2.3")
    assert out["state"] == "unreachable" and out["detail"] == "refused"


def test_probe_waiting_skips_http(monkeypatch):
    monkeypatch.setattr(detect, "any_network_up", lambda: False)
    def boom(**kw):
        raise AssertionError("waiting 不该发 HTTP")
    monkeypatch.setattr(detect, "http_probe", boom)
    out = detect.probe({"url": "http://10.1.2.3", "server_name": "10.1.2.3"})
    assert out == {"state": "waiting", "ssid": None, "server": "10.1.2.3", "detail": ""}


def test_probe_normal_shape(monkeypatch):
    monkeypatch.setattr(detect, "any_network_up", lambda: True)
    monkeypatch.setattr(detect, "http_probe",
                        lambda base=None, timeout=5, cfg=None: {"state": "logged_in", "detail": ""})
    monkeypatch.setattr(detect.wifictl, "current_ssid", lambda: "Campus-WiFi")
    out = detect.probe({"url": "http://10.1.2.3", "server_name": "10.1.2.3"})
    assert out["state"] == "logged_in" and out["ssid"] == "Campus-WiFi"


def test_any_network_up_via_route(monkeypatch):
    monkeypatch.setattr(detect.wifictl, "current_ssid", lambda: None)
    monkeypatch.setattr(detect, "_default_route_exists", lambda: True)
    assert detect.any_network_up()
    monkeypatch.setattr(detect, "_default_route_exists", lambda: False)
    assert not detect.any_network_up()


def test_default_route_parse(monkeypatch):
    table = (
        "===========================================================================\n"
        "活动路由:\n"
        " 0.0.0.0          0.0.0.0    192.168.1.1   192.168.1.10     35\n"
        "===========================================================================\n"
    )
    class R:
        returncode = 0
        stdout = table
        stderr = ""
    monkeypatch.setattr(detect.subprocess, "run", lambda *a, **k: R())
    assert detect._default_route_exists()
    empty = ("活动路由:\n" "===========================================================================\n")
    monkeypatch.setattr(detect.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": empty, "stderr": ""})())
    assert not detect._default_route_exists()


def test_wait_for_gate_polls_until_reachable(monkeypatch):
    seen = {"n": 0}

    def flaky(*a, **kw):
        seen["n"] += 1
        return seen["n"] >= 3          # 第 3 次开门
    monkeypatch.setattr(detect, "server_reachable", flaky)
    monkeypatch.setattr(detect.time, "sleep", lambda s: None)
    assert detect.wait_for_gate(timeout=60)
    assert seen["n"] == 3


def test_wait_for_gate_never_raises(monkeypatch):
    monkeypatch.setattr(detect, "server_reachable", lambda *a, **kw: False)
    monkeypatch.setattr(detect.time, "sleep", lambda s: None)
    assert detect.wait_for_gate(timeout=0) is False


def test_portal_html_returns_page_text(monkeypatch):
    seen = []

    def fake(req, timeout=None):
        seen.append(req.full_url)
        return FakeResp("authlogoutport=801;//注销端口 authlogoutpath='/eportal/?c=Logout';")
    monkeypatch.setattr(detect, "urlopen", fake)
    html = detect.portal_html({"url": "http://10.1.2.3"})
    assert "authlogoutport=801" in html
    assert seen == ["http://10.1.2.3/"]


def test_portal_html_failure_returns_none(monkeypatch):
    monkeypatch.setattr(detect, "urlopen", lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("refused")))
    assert detect.portal_html({"url": "http://10.1.2.3"}) is None
