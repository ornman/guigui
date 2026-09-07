"""diagnostics:collect/render — 七区结构 / 瘦身规则 / 打码红线 / 采集失败 in-band。

测试走模块接口 collect(kind)/render(bundle),不测内部采集器(PRD §7.1);
子进程/网络类 seam(_run、探测函数)全部注入固定应答。
"""

import json

import pytest

from guigui.core import diagnostics, drcom, logstore

IPC_OUT = """
Windows IP 配置

无线局域网适配器 WLAN:

   连接特定的 DNS 后缀 . . . . . . . :
   描述. . . . . . . . . . . . . . . : Intel(R) Wi-Fi 6 AX201 160MHz
   DHCP 已启用 . . . . . . . . . . . : 是
   IPv4 地址 . . . . . . . . . . . . : 10.20.30.40(首选)
   DNS 服务器 . . . . . . . . . . . . : 192.168.1.1
                                       10.1.2.9

以太网适配器 以太网:

   描述. . . . . . . . . . . . . . . : Realtek PCIe GbE Family Controller
   IPv4 地址 . . . . . . . . . . . . : 172.16.0.1(首选)

隧道适配器 Clash:

   描述. . . . . . . . . . . . . . . : Clash Virtual Adapter(TUN 模式)
   IPv4 地址 . . . . . . . . . . . . : 198.18.0.1(首选)

以太网适配器 蓝牙网络连接:

   媒体状态 . . . . . . . . . . . . . : 媒体已断开连接
"""

TASKLIST_OUT = '''
"hipsdaemon.exe","1234","Services","0","9,240 K"
"msmpeng.exe","5678","Services","0","300,120 K"
"explorer.exe","9012","Console","1","60,000 K"
'''

TASKINFO_JSON = (
    '[{"TaskName":"GuiGui","LastRunTime":"2026-09-07T07:00:03",'
    '"LastTaskResult":0},'
    '{"TaskName":"GuiGui-Patrol","LastRunTime":"2026-09-07T07:15:00",'
    '"LastTaskResult":1}]'
)

ROUTE_OUT = """
===========================================================================
接口列表
  11...00 11 22 33 44 55 ......Intel(R) Wi-Fi 6 AX201
  18...aa bb cc dd ee ff ......Realtek PCIe GbE
===========================================================================
IPv4 路由表
===========================================================================
活动路由:
网络目标        网络掩码          网关       接口   跃点数
          0.0.0.0          0.0.0.0     172.16.0.1   172.16.0.1     25
          10.1.2.3  255.255.255.255         在链上    172.16.0.1     21
===========================================================================
"""


@pytest.fixture
def canned(monkeypatch):
    """固定应答:子进程文本 / SSID / 任务 XML / 探测函数。"""
    from guigui.core import config

    def fake_run(cmd):
        key = " ".join(cmd[:2])
        if key == "ipconfig /all":
            return IPC_OUT
        if key == "tasklist /fo":
            return TASKLIST_OUT
        if key == "route print":
            return ROUTE_OUT
        if cmd[0] == "powershell":
            return TASKINFO_JSON
        return ""
    config.save(dict(config.DEFAULTS, uid="2025000000001"))
    monkeypatch.setattr(diagnostics, "_run", fake_run)
    monkeypatch.setattr(diagnostics.wifictl, "current_ssid",
                        lambda: "Campus-WiFi")
    monkeypatch.setattr(diagnostics.scheduler, "query_xml",
                        lambda name: "<Description>rev=3</Description>"
                        if name == "GuiGui" else None)
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
