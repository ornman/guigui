"""drcom:登录四态/chkstatus/打码(URL 全 mock,不发真实请求)。"""

from guigui.core import drcom


class FakeResp:
    def __init__(self, body: str, status: int = 200):
        self._b = body.encode("gbk", errors="replace")
        self.status = status

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


# ── 拒绝三态分类(AC-19,2026-09-06 实测)────────────────


def test_classify_rejection_three_states():
    assert drcom.classify_rejection("userid error2") == drcom.REJ_WRONG_PASSWORD
    assert drcom.classify_rejection("userid error1") == drcom.REJ_WRONG_ACCOUNT
    assert drcom.classify_rejection("bind userid error") == drcom.REJ_BOUND
    assert drcom.classify_rejection("服务器维护中") is None      # 不认识 → 不猜
    assert drcom.classify_rejection("") is None
    assert drcom.classify_rejection(None) is None


def test_rejection_text_three_states_and_fallback():
    assert drcom.rejection_text(drcom.REJ_WRONG_ACCOUNT, "兜底") == "学号或运营商选错了,核对一下再试"
    assert drcom.rejection_text(drcom.REJ_WRONG_PASSWORD, "兜底") == "密码不对,改一下再试"
    assert "自助服务平台" in drcom.rejection_text(drcom.REJ_BOUND, "兜底")
    assert drcom.rejection_text(None, "原文照显") == "原文照显"


# ── 拒绝第四态 limit_users + login_ex(AC-F8,2026-09-07 测试床实测,附录 A)──

# 实测 JSONP 全文(已在别处登录态;密码不在响应中,uid 在 → data 采集时打码)
LIMIT_USERS_JSONP = (
    'dr1003({"result":0,"wopt":0,"msg":1,"uid":"2025000000001","hidm":0,'
    '"ss5":"172.16.0.1","ss6":"10.1.2.3","ss1":"00aa00bb00cc",'
    '"ss4":"00dd00ee00ff","aolno":9999,'
    '"ubind":"mac1=\u0027\u0027,ty1=0,mac2=\u0027\u0027,ty2=0",'
    '"msga":"Oppp error: Limit Users Err"})'
)


def test_classify_rejection_limit_users():
    assert drcom.classify_rejection("Oppp error: Limit Users Err") == drcom.REJ_LIMIT_USERS
    assert drcom.classify_rejection("oppp error: limit users err") == drcom.REJ_LIMIT_USERS


def test_rejection_text_limit_users_never_blames_password():
    """AC-F8:文案走「已在别的设备登录」方向,不出现改密提示。"""
    text = drcom.rejection_text(drcom.REJ_LIMIT_USERS, "兜底")
    assert "别的设备" in text
    assert "密码" not in text


def test_rej_code_map_for_diag_data():
    """诊断包 data.rej 用服务器码(§5),与契约 reason 枚举不同源。"""
    assert drcom.REJ_CODE[drcom.REJ_WRONG_ACCOUNT] == "error1"
    assert drcom.REJ_CODE[drcom.REJ_WRONG_PASSWORD] == "error2"
    assert drcom.REJ_CODE[drcom.REJ_BOUND] == "bind"
    assert drcom.REJ_CODE[drcom.REJ_LIMIT_USERS] == "limit_users"


def test_login_ex_limit_users_carries_payload(monkeypatch):
    _stub_urlopen(monkeypatch, body=LIMIT_USERS_JSONP)
    r = drcom.login_ex("http://10.1.2.3", "u", "p")
    assert r.result == drcom.REJECTED and r.http == 200
    assert r.msg == "Oppp error: Limit Users Err"
    assert r.payload["ss5"] == "172.16.0.1"
    assert r.payload["ss1"] == "00aa00bb00cc" and r.payload["ss4"] == "00dd00ee00ff"
    assert r.payload["aolno"] == 6152 and "mac1=" in r.payload["ubind"]


def test_login_ex_success_and_unreachable_shapes(monkeypatch):
    import urllib.error
    _stub_urlopen(monkeypatch, body='dr1003({"result":1})')
    r = drcom.login_ex("http://10.1.2.3", "u", "p")
    assert r.result == drcom.SUCCESS and r.payload["result"] == 1 and r.http == 200
    _stub_urlopen(monkeypatch, exc=urllib.error.URLError("refused"))
    r = drcom.login_ex("http://10.1.2.3", "u", "p")
    assert r.result == drcom.UNREACHABLE and r.payload is None and r.http is None


def test_scrub_uids():
    assert drcom.scrub_uids("uid=2025000000001 端口80") == "uid=2025…0001 端口80"
    assert drcom.scrub_uids("无数字串") == "无数字串"
    assert drcom.scrub_uids(None) == ""


# ── 展示别名(移动/广电 → 校园其他,2026-09-06 用户拍板)────


def test_operator_aliases_map_to_empty_suffix():
    assert drcom.canonical_operator("中国移动") == "校园其他"
    assert drcom.canonical_operator("中国广电") == "校园其他"
    assert drcom.canonical_operator("校园电信") == "校园电信"   # 协议名原样
    assert drcom.canonical_operator(None) == "校园用户"
    assert drcom.canonical_operator("乱写") == "乱写"            # 未知原样(不猜)
    assert drcom.operator_suffix("中国移动") == ""               # 空后缀 = 校园其他同落点
    url = drcom.build_login_url("http://x", "u", "p", operator="中国移动")
    assert "DDDDD=u%40" not in url and "DDDDD=u&" in url        # 裸学号


def test_protocol_table_untouched_by_aliases():
    # AC-20:协议表仍与门户 carrier 配置逐字一致(别名只在展示层)
    assert set(drcom.OPERATOR_TABLE) == {"校园用户", "校园电信", "校园联通", "校园其他"}


# ── 节流 waitsec 三件套(QA P1-6)───────────────────


def test_parse_waitsec_from_json_field_waitsec():
    """实测前先按经验写:Dr.COM 系列常见 JSON 字段名 waitsec。"""
    assert drcom.parse_waitsec({"waitsec": 30}, "") == 30
    assert drcom.parse_waitsec({"waittime": 45}, "") == 45
    assert drcom.parse_waitsec({"wait": 12}, "") == 12


def test_parse_waitsec_fallback_to_msga_text():
    """JSON 没给字段时,从 msga 文本里抽数字(中文「请等待 30 秒」类)。"""
    assert drcom.parse_waitsec(None, "请等待 30 秒再试") == 30
    assert drcom.parse_waitsec(None, "wait 15 seconds") == 15
    assert drcom.parse_waitsec(None, "操作太频繁,请稍后再试") == 1   # 关键词命中无数字 → 保守 1s


def test_parse_waitsec_returns_none_when_no_throttle_signal():
    """无任何节流信号 → None(调用方按无节流处理,不要误诊)。"""
    assert drcom.parse_waitsec({"result": 0}, "userid error2") is None
    assert drcom.parse_waitsec(None, "") is None
    assert drcom.parse_waitsec(None, "userid error1") is None


def test_classify_rejection_throttle_wins_over_error2():
    """QA P1-6 核心保证:节流绝不被翻译成密码错。
    即便 msga 文本里同时含 error2 标记 + waitsec 提示,分类结果必须是 THROTTLED。"""
    # 显式传 waitsec 优先级最高
    assert drcom.classify_rejection("userid error2",
                                    waitsec=30) == drcom.REJ_THROTTLED
    # 从 payload 自己 parse 也能识出
    assert drcom.classify_rejection("userid error2 wait 5s",
                                    payload={"waitsec": 5}) == drcom.REJ_THROTTLED
    # 节流关键词 + 数字 → 归 throttle(无需 payload)
    assert drcom.classify_rejection("操作太频繁,请等待 10 秒",
                                    payload=None) == drcom.REJ_THROTTLED
    # 纯 error2 + 无节流信号 → 仍归 wrong_password(基线不漂)
    assert drcom.classify_rejection("userid error2") == drcom.REJ_WRONG_PASSWORD


def test_login_ex_captures_waitsec_from_payload(monkeypatch):
    """login_ex 解析 JSON waitsec 字段并写入 LoginResult.waitsec。"""
    body = 'dr1003({"result":0,"msga":"太快了","waitsec":12})'
    _stub_urlopen(monkeypatch, body=body)
    r = drcom.login_ex("http://10.1.2.3", "u", "p")
    assert r.result == drcom.REJECTED
    assert r.waitsec == 12


def test_login_ex_waitsec_none_when_field_absent(monkeypatch):
    body = 'dr1003({"result":0,"msga":"userid error2"})'
    _stub_urlopen(monkeypatch, body=body)
    r = drcom.login_ex("http://10.1.2.3", "u", "p")
    assert r.waitsec is None


def test_rej_code_map_includes_throttled():
    """诊断包 data.rej = throttled;契约 reason 仍用「throttled」枚举。"""
    assert drcom.REJ_CODE[drcom.REJ_THROTTLED] == "throttled"
    assert drcom.REJ_THROTTLED in drcom.REJ_CODE


def test_rejection_text_throttled_does_not_blame_password():
    """节流文案不能出现「密码」字样。"""
    text = drcom.rejection_text(drcom.REJ_THROTTLED, "兜底")
    assert "密码" not in text
