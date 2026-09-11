"""diagnostics:collect/render — 七区结构 / 瘦身规则 / 打码红线 / 采集失败 in-band。

测试走模块接口 collect(kind)/render(bundle),不测内部采集器(PRD §7.1);
进程内采集 seam(sysinfo.net_interfaces / sysinfo.wmi_rows / scheduler 查询)
与网络探测函数全部注入固定应答。
"""

import json

import pytest

from guigui.core import diagnostics, drcom, logstore

# sysinfo.net_interfaces 桩应答(ADR-0003:网卡/DNS 进程内采集)
NI = [
    {"name": "WLAN", "description": "Intel(R) Wi-Fi 6 AX201 160MHz",
     "type_id": 71, "is_wireless": True, "is_up": True,
     "ipv4": "10.20.30.40", "dns": ["192.168.1.1", "10.1.2.9"], "index": 4},
    {"name": "以太网", "description": "Realtek PCIe GbE Family Controller",
     "type_id": 6, "is_wireless": False, "is_up": True,
     "ipv4": "172.16.0.1", "dns": [], "index": 20},
    {"name": "Clash", "description": "Clash Virtual Adapter(TUN 模式)",
     "type_id": 53, "is_wireless": False, "is_up": True,
     "ipv4": "198.18.0.1", "dns": [], "index": 18},
    {"name": "蓝牙网络连接", "description": "Bluetooth Device (Personal Area Network)",
     "type_id": 6, "is_wireless": False, "is_up": False,
     "ipv4": None, "dns": [], "index": 21},
]

TASKINFO = {   # scheduler.task_runtime_info 桩返回值(COM 通道,ADR-0001 后)
    "GuiGui": {"last_run": "09-07 07:00:03", "last_result": "0x0"},
    "GuiGui-Patrol": {"last_run": "09-07 07:15:00", "last_result": "0x1"},
}


def _av_rows():
    return [{"displayName": "火绒安全软件"}, {"displayName": "Windows Defender"}]


def fake_wmi(wql, scope=None):
    if "AntiVirusProduct" in wql:
        return _av_rows()
    return []


@pytest.fixture
def canned(monkeypatch):
    """固定应答:进程内采集 / SSID / 任务查询 / 探测函数。"""
    from guigui.core import config

    config.save(dict(config.DEFAULTS, uid="2025000000001"))
    monkeypatch.setattr(diagnostics.sysinfo, "net_interfaces",
                        lambda: [dict(n) for n in NI])
    monkeypatch.setattr(diagnostics.sysinfo, "wmi_rows", fake_wmi)
    monkeypatch.setattr(diagnostics.wifictl, "current_ssid",
                        lambda: "Campus-WiFi")
    monkeypatch.setattr(diagnostics.scheduler, "query_xml",
                        lambda name: "<Description>rev=3</Description>"
                        if name == "GuiGui" else None)
    monkeypatch.setattr(diagnostics.scheduler, "task_runtime_info",
                        lambda name: TASKINFO.get(name))
    monkeypatch.setattr(diagnostics, "_env_clock_skew", lambda cfg: 2.1)
    monkeypatch.setattr(diagnostics, "_latest_ver", lambda: "2.1.2")
    monkeypatch.setattr(diagnostics, "_env_webview2", lambda: "120.0.2210.61")
    monkeypatch.setattr(diagnostics, "_env_proxy",
                        lambda: {"system": False, "env": False})

    def fake_net(cfg):
        return {"dns_resolved": "10.1.2.3", "tcp": True, "http": 200,
                "latency_ms": 340, "route_iface": "以太网", "errors": []}
    monkeypatch.setattr(diagnostics, "_collect_net", fake_net)


def test_full_bundle_regions(canned):
    logstore.append("ok", "已登录 · 2025…0001")
    bundle = diagnostics.collect(["problem"])
    assert set(bundle) >= {"env", "self", "net", "logs", "summary", "latest_ver"}
    env = bundle["env"]
    assert env["os"].startswith("Windows") and env["python"]
    assert env["clock_skew_s"] == 2.1
    kinds = {a["name"]: a for a in env["adapters"]}
    assert kinds["WLAN"]["kind"] == "wifi" and kinds["WLAN"]["ssid"] == "Campus-WiFi"
    assert kinds["以太网"]["kind"] == "ethernet" and kinds["以太网"]["up"]
    assert kinds["Clash"]["kind"] == "tun"
    assert not kinds["蓝牙网络连接"]["up"]
    assert "192.168.1.1" in env["dns"] and "10.1.2.9" in env["dns"]
    assert env["proxy"] == {"system": False, "env": False}
    assert env["av"]["huorong"] is True and env["av"]["defender"] is True
    assert env["av"]["qihoo360"] is False
    assert env["webview2"] == "120.0.2210.61"

    self_ = bundle["self"]
    assert self_["config"]["patrol_interval_minutes"] == 30   # 桥名映射
    assert self_["config"]["trigger_time"] == "07:00"
    assert "uid" not in self_["config"]                        # 学号只走信封 sender_uid
    assert isinstance(self_["proc_uptime_s"], int)
    tasks = {t["name"]: t for t in self_["tasks"]}
    assert tasks["GuiGui"]["registered"] and tasks["GuiGui"]["last_result"] == "0x0"
    assert tasks["GuiGui-Patrol"]["registered"] is False       # query_xml=None
    assert tasks["GuiGui"]["last_run"] == "09-07 07:00:03"

    assert bundle["net"]["http"] == 200 and bundle["net"]["tcp"] is True
    assert bundle["latest_ver"] == "2.1.2"


def test_suggestion_bundle_thin(canned):
    bundle = diagnostics.collect(["suggestion"])
    for absent in ("net", "server", "logs", "summary", "crashes"):
        assert absent not in bundle
    assert "env" in bundle and "self" in bundle and "latest_ver" in bundle


def test_logs_and_summary(canned):
    logstore.append("ok", "网络可达")
    logstore.append("ok", "已登录 · 2025…0001")
    logstore.append("fail", "登录被拒:密码不对,改一下再试")
    bundle = diagnostics.collect(["problem"])
    today = bundle["logs"][0]
    assert today["entries"][0]["level"] == "ok"
    marks = bundle["summary"].split(" · ")
    assert marks[-1].endswith("✗")            # 今天最后是失败 → ✗


def test_scrub_uid_everywhere(canned, monkeypatch):
    """红线:出机器即净数据——任何 ≥10 位数字串都打码。"""
    logstore.append("note", "线上会话 2025000000001 抓到了")
    bundle = diagnostics.collect(["problem"])
    assert "2025000000001" not in json.dumps(bundle, ensure_ascii=False)
    assert "2025…0001" in json.dumps(bundle, ensure_ascii=False)


def test_collector_failure_in_band(canned, monkeypatch):
    def boom():
        raise PermissionError("nope")
    monkeypatch.setattr(diagnostics, "_env_adapters", boom)
    bundle = diagnostics.collect(["problem"])
    assert "adapters: PermissionError" in bundle["env"]["errors"]
    assert bundle["env"]["os"]                            # 其余照发(AC-F5)
    assert bundle["self"]["config"]["trigger_time"]


def test_never_real_login_never_upass(canned, monkeypatch):
    """红线:诊断绝不发起真实登录;登录 URL(含 upass=)永不入包。"""
    def bomb(*a, **k):
        raise AssertionError("diagnostics 必须不发登录请求")
    monkeypatch.setattr(drcom, "login", bomb)
    bundle = diagnostics.collect(["problem"])
    assert "upass" not in json.dumps(bundle, ensure_ascii=False)


def test_render_preview(canned):
    logstore.append("fail", "登录被拒:这个学号已在别的设备上登录")
    text = diagnostics.render(diagnostics.collect(["problem"]))
    for marker in ("诊断信息", "── 环境 ──", "── 自身 ──", "── 网络(实时)──",
                   "── 最近七天 ──", "版本对照"):
        assert marker in text
    assert "2025000000001" not in text
    assert "已在别的设备上登录" in text


def test_last_fail_when(canned):
    import datetime as dt

    assert diagnostics.last_fail_when() == ""
    now = dt.datetime.now()
    logstore.append("ok", "网络可达", when=now)
    logstore.append("fail", "登录被拒:limit_users", when=now)
    assert diagnostics.last_fail_when() == f"{now:%m-%d} {now:%H:%M}"
    later = now + dt.timedelta(minutes=1)
    logstore.append("fail", "又失败了", when=later)
    assert diagnostics.last_fail_when() == f"{later:%m-%d} {later:%H:%M}"


def test_self_tasks_com_down_keeps_registered(canned, monkeypatch):
    """ADR-0001:COM 不可用(task_runtime_info=None)→ last_run/last_result
    允许缺失;registered 判定不受损(query_xml 双通道照跑)。"""
    monkeypatch.setattr(diagnostics.scheduler, "task_runtime_info",
                        lambda name: None)
    bundle = diagnostics.collect(["problem"])
    tasks = {t["name"]: t for t in bundle["self"]["tasks"]}
    assert tasks["GuiGui"]["registered"] is True        # query_xml 桩仍在岗
    assert tasks["GuiGui"]["last_run"] is None
    assert tasks["GuiGui"]["last_result"] is None


# ── ADR-0003:SecurityCenter2 / 路由反查(进程内采集)─────


def test_env_av_displayname_variants(monkeypatch):
    """displayName 变体(中英文产品名)→ 三家布尔;信封键不变。"""
    rows = [{"displayName": "Huorong Internet Security"},
            {"displayName": "360 Total Security"},
            {"displayName": "Windows Defender"}]
    monkeypatch.setattr(diagnostics.sysinfo, "wmi_rows",
                        lambda wql, scope=None: list(rows))
    av = diagnostics._env_av()
    assert av == {"huorong": True, "qihoo360": True, "defender": True}


def test_env_av_unknown_product_all_false(monkeypatch):
    """装了未知杀软:全 False(有信息,不是空对象)。"""
    monkeypatch.setattr(diagnostics.sysinfo, "wmi_rows",
                        lambda wql, scope=None: [{"displayName": "SomeVendor AV"}])
    assert diagnostics._env_av() == {"huorong": False, "qihoo360": False,
                                     "defender": False}


def test_env_av_missing_or_empty_no_tasklist(monkeypatch):
    """SecurityCenter2 缺失/为空 → 空对象,宁缺勿侦察(绝不回退 tasklist)。"""
    def boom(wql, scope=None):
        raise RuntimeError("服务器 SKU 无 SecurityCenter2")
    monkeypatch.setattr(diagnostics.sysinfo, "wmi_rows", boom)
    assert diagnostics._env_av() == {}
    monkeypatch.setattr(diagnostics.sysinfo, "wmi_rows",
                        lambda wql, scope=None: [])
    assert diagnostics._env_av() == {}


def test_route_iface_longest_prefix(monkeypatch):
    """最长前缀匹配 + InterfaceIndex 直查网卡名(ADR-0003:不绕 IP 二次匹配)。"""
    routes = [
        {"Destination": "0.0.0.0", "Mask": "0.0.0.0", "InterfaceIndex": 20},
        {"Destination": "10.1.2.3", "Mask": "255.255.255.255", "InterfaceIndex": 4},
    ]
    monkeypatch.setattr(diagnostics.sysinfo, "wmi_rows",
                        lambda wql, scope=None: list(routes))
    monkeypatch.setattr(diagnostics.sysinfo, "net_interfaces",
                        lambda: [dict(n) for n in NI])
    assert diagnostics._route_iface("10.1.2.3", {}) == "WLAN"    # /32 命中
    assert diagnostics._route_iface("8.8.8.8", {}) == "以太网"   # 默认路由兜住
    # 索引对不上网卡(拔了/换了)→ 退化为索引字符串,不抛
    routes.append({"Destination": "172.16.0.0", "Mask": "255.255.0.0",
                   "InterfaceIndex": 99})
    assert diagnostics._route_iface("172.16.9.9", {}) == "99"


# ── server / crashes 区(S3)─────────────────────

class _Resp:
    def __init__(self, body, status=200):
        self._b = body.encode("gbk", errors="replace")
        self.status = status

    def read(self, size=None):
        return self._b[:size]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _stub_dhttp(monkeypatch, *, body="", status=200, err=None):
    def fake(req, timeout=None):
        if err is not None:
            raise err
        return _Resp(body, status)
    monkeypatch.setattr(diagnostics, "urlopen", fake)


def test_server_chkstatus_three_states(canned, monkeypatch):
    import io
    import urllib.error

    # uid_online(登录态,返回 uid → 学号在 raw_head 里也必须打码)
    _stub_dhttp(monkeypatch, body='dr1003({"uid":"2025000000001","AC":"x"})')
    got = diagnostics._server_chkstatus({"url": "http://10.1.2.3"})
    assert got["state"] == "uid_online"
    assert "2025000000001" not in got["raw_head"]

    # no_session = HTTP 400(AC-F9:正常形态,不是异常)
    err = urllib.error.HTTPError("u", 400, "Bad Request", None,
                                 io.BytesIO("({})".encode("gbk")))
    _stub_dhttp(monkeypatch, err=err)
    assert diagnostics._server_chkstatus({"url": "http://10.1.2.3"})["state"] == "no_session"

    # unreachable = 够不着(超时/拒绝都归此)
    _stub_dhttp(monkeypatch, err=TimeoutError())
    assert diagnostics._server_chkstatus({"url": "http://10.1.2.3"})["state"] == "unreachable"


def test_server_last_verdict_from_log_data(canned, monkeypatch):
    _stub_dhttp(monkeypatch, body='dr1003({"uid":"2025000000001"})')
    logstore.append("fail", "登录被拒:这个学号已在别的设备上登录",
                    data={"rej": "limit_users", "body_head": "Oppp error: Limit Users Err",
                          "server_view_ip": "172.16.0.1",
                          "mac_hint": ["00aa00bb00cc", "00dd00ee00ff"],
                          "aolno": 6152, "ubind": "mac1='',ty1=0", "tries": 2, "http": 200})
    bundle = diagnostics.collect(["problem"])
    verdict = bundle["server"]["last_verdict"]
    assert verdict["rej"] == "limit_users"
    assert verdict["server_view_ip"] == "172.16.0.1"
    assert verdict["mac_hint"] == ["00aa00bb00cc", "00dd00ee00ff"]
    assert verdict["msga"] == "Oppp error: Limit Users Err"
    assert verdict["ts"].startswith(diagnostics.dt.date.today().strftime("%m-%d"))
    # 日志区 fail 行带 data 现场
    today = bundle["logs"][0]
    fail_row = [e for e in today["entries"] if e["level"] == "fail"][0]
    assert fail_row["data"]["rej"] == "limit_users"


def test_crashes_region_from_crashlog(canned, monkeypatch):
    from guigui.core import crashlog
    monkeypatch.setattr(crashlog.sys, "__excepthook__", lambda *a: None)
    crashlog.install("gui")
    try:
        raise ValueError("gui 崩了 2025000000001")
    except ValueError:
        crashlog._sys_hook(*crashlog.sys.exc_info())
    bundle = diagnostics.collect(["problem"])
    assert bundle["crashes"] and bundle["crashes"][0]["proc"] == "gui"
    assert "gui 崩了" in bundle["crashes"][0]["trace"]
    assert "2025000000001" not in json.dumps(bundle, ensure_ascii=False)
    assert "── 崩溃(最近)──" in diagnostics.render(bundle)
