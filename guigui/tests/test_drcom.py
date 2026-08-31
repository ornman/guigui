"""drcom:登录四态/chkstatus/打码(URL 全 mock,不发真实请求)。"""

from guigui.core import drcom


class FakeResp:
    def __init__(self, body: str):
        self._b = body.encode("gbk", errors="replace")

    def read(self, size=None):
        return self._b[:size]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _stub_urlopen(monkeypatch, body=None, exc=None):
    def fake(req, timeout=None):
        if exc:
            raise exc
        return FakeResp(body)
    monkeypatch.setattr(drcom, "urlopen", fake)


def test_login_success(monkeypatch):
    _stub_urlopen(monkeypatch, body='dr1003({"result":1,"uid":"u"})')
    assert drcom.login("http://10.1.2.3", "2025000000001", "pw") == ("success", "")


def test_login_rejected_with_msga(monkeypatch):
    _stub_urlopen(monkeypatch, body='dr1003({"result":0,"msga":"密码错误"})')
    result, msg = drcom.login("http://10.1.2.3", "u", "bad")
    assert result == "rejected" and msg == "密码错误"


def test_login_rejected_without_msga_gets_human_default(monkeypatch):
    _stub_urlopen(monkeypatch, body='dr1003({"result":0})')
    result, msg = drcom.login("http://10.1.2.3", "u", "bad")
    assert result == "rejected" and "密码" in msg


def test_login_unexpected_body(monkeypatch):
    _stub_urlopen(monkeypatch, body="<html>维护中</html>")
    assert drcom.login("http://10.1.2.3", "u", "p")[0] == "unexpected"


def test_login_network_error_is_unreachable(monkeypatch):
    import urllib.error
    _stub_urlopen(monkeypatch, exc=urllib.error.URLError("refused"))
    assert drcom.login("http://10.1.2.3", "u", "p")[0] == "unreachable"


def test_build_login_url_shape():
    url = drcom.build_login_url("http://10.1.2.3", "2025000000001", "pw123", now=1756627200)
    assert url.startswith("http://10.1.2.3/drcom/login?")
    assert "DDDDD=2025000000001" in url          # 默认运营商=裸学号
    assert "upass=pw123" in url
    assert "0MKKey=123456" in url and "jsVersion=4.2.1" in url
    assert "v=1756627200" in url


def test_operator_suffix_table():
    assert drcom.operator_suffix("校园用户") == ""
    assert drcom.operator_suffix("校园电信") == "@dx"
    assert drcom.operator_suffix(None) == ""    # 默认运营商
    url = drcom.build_login_url("http://x", "u", "p", operator="校园联通")
    assert "DDDDD=u@lt" in url                 # safe='@':@ 不转义(v1 行为)


def test_chkstatus_uid_fields(monkeypatch):
    _stub_urlopen(monkeypatch, body='dr1003({"result":1,"uid":"2025000000001","AC":"x"})')
    assert drcom.chkstatus_uid("http://10.1.2.3") == "2025000000001"


def test_chkstatus_fallback_ddddd(monkeypatch):
    _stub_urlopen(monkeypatch, body='dr1003({"DDDDD":"2025000000001"})')
    assert drcom.chkstatus_uid("http://10.1.2.3") == "2025000000001"


def test_chkstatus_failures_return_none(monkeypatch):
    _stub_urlopen(monkeypatch, body="garbage")
    assert drcom.chkstatus_uid("http://10.1.2.3") is None
    _stub_urlopen(monkeypatch, exc=TimeoutError())
    assert drcom.chkstatus_uid("http://10.1.2.3") is None


def test_mask_uid():
    # 规则 = 前4…后4;PRD/契约里的「2025…7209」是手打示意串,非规则推得(后四位实为 0209)
    assert drcom.mask_uid("2025000000001") == "2025…0001"
    assert drcom.mask_uid("12345678") == "12345678"     # ≤8 不打码
    assert drcom.mask_uid(None) == ""


# ── 注销端点解析 + logout(实测门户 JS 配置,全桩)──────────────

# 实测门户页 JS 配置行(PRD §4.1.1 采集;authlogoutIP 空 = 与认证服务器同主机)
REAL_PORTAL_JS = (
    "authlogouttype=1;//注销协议 "
    "authlogoutIP='';//注销IP "
    "authlogoutport=801;//注销端口 "
    "authlogoutpath='/eportal/?c=ACSetting&a=Logout&ver=1.0';"
)


def test_parse_logout_endpoint_real_portal_config():
    url = drcom.parse_logout_endpoint(REAL_PORTAL_JS, "http://10.1.2.3")
    assert url == "http://10.1.2.3:801/eportal/?c=ACSetting&a=Logout&ver=1.0"


def test_parse_logout_endpoint_garbage_returns_none():
    assert drcom.parse_logout_endpoint("", "http://10.1.2.3") is None
    assert drcom.parse_logout_endpoint("<html>维护中</html>", "http://10.1.2.3") is None
    # 只有 port 没有 path / 只有 path 没有 port → 同样 None
    assert drcom.parse_logout_endpoint("authlogoutport=801;//x", "http://10.1.2.3") is None
    assert drcom.parse_logout_endpoint("authlogoutpath='/eportal/?c=Logout';", "http://10.1.2.3") is None


def test_parse_logout_endpoint_no_host_returns_none():
    assert drcom.parse_logout_endpoint(REAL_PORTAL_JS, "notaurl") is None
    assert drcom.parse_logout_endpoint(REAL_PORTAL_JS, "") is None


def test_logout_calls_endpoint_and_returns_url(monkeypatch):
    seen = []

    def fake(req, timeout=None):
        seen.append(req.full_url)
        return FakeResp("logout ok")
    monkeypatch.setattr(drcom, "urlopen", fake)
    url = drcom.logout(REAL_PORTAL_JS, "http://10.1.2.3")
    assert url == "http://10.1.2.3:801/eportal/?c=ACSetting&a=Logout&ver=1.0"
    assert seen == [url]                       # 恰好一次、URL 正确


def test_logout_swallows_network_error(monkeypatch):
    def fake(req, timeout=None):
        raise TimeoutError("boom")
    monkeypatch.setattr(drcom, "urlopen", fake)
    url = drcom.logout(REAL_PORTAL_JS, "http://10.1.2.3")
    assert url == "http://10.1.2.3:801/eportal/?c=ACSetting&a=Logout&ver=1.0"


def test_logout_none_when_portal_unconfigured(monkeypatch):
    called = []

    def fake(req, timeout=None):
        called.append(req.full_url)
        return FakeResp("x")
    monkeypatch.setattr(drcom, "urlopen", fake)
    assert drcom.logout("<html>没有配置</html>", "http://10.1.2.3") is None
    assert called == []                        # 没配置就不发请求


# ── 运营商:校园其他 + 门户 carrier 解析(2026-08-31 注销页实测)─────

_CARRIER_HTML = (
    "charset='gb2312';//页面编码 exparam=0; "
    "carrier='{\"yys\":{\"title\": \"服务类型\",\"mode\":\"radiobutton\",\"type\":\"0\","
    "\"data\":[{\"id\":\"1\",\"name\":\"校园用户\",\"suffix\":\"\"},"
    "{\"id\":\"2\",\"name\":\"校园电信\",\"suffix\":\"@dx\"},"
    "{\"id\":\"3\",\"name\":\"校园联通\",\"suffix\":\"@lt\"},"
    "{\"id\":\"4\",\"name\":\"校园其他\",\"suffix\":\"\"}],\"defaultID\":\"1\"}}';//运营商选择"
)


def test_operator_table_matches_real_portal():
    assert drcom.parse_operators(_CARRIER_HTML) == drcom.OPERATOR_TABLE


def test_parse_operators_garbage_returns_empty():
    assert drcom.parse_operators("") == {}
    assert drcom.parse_operators("carrier='not json';") == {}
    assert drcom.parse_operators("<html>无配置</html>") == {}


def test_campus_other_is_bare_uid():
    assert drcom.operator_suffix("校园其他") == ""
    url = drcom.build_login_url("http://x", "u", "p", operator="校园其他")
    assert "DDDDD=u&" in url                       # 裸学号,无后缀
