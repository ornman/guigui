"""drcom:登录四态/chkstatus/打码(URL 全 mock,不发真实请求)。"""

from guigui.core import drcom


class FakeResp:
    def __init__(self, body: str):
        self._b = body.encode("gbk", errors="replace")

    def read(self):
        return self._b

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
