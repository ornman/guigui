"""wifictl:扫描解析/去重分档/连接流程(全 mock netsh)。"""

import subprocess

import pytest

from guigui.core import wifictl


def _cp(stdout="", rc=0, stderr=""):
    return subprocess.CompletedProcess(["netsh"], rc, stdout, stderr)


_NETSH_ZH = """接口名称 : WLAN
当前有 4 个网络可见

SSID 1 : Campus-WiFi
    网络类型            : 结构
    身份验证            : 开放
    加密                : 无
    BSSID 1             : aa-bb-cc-dd-ee-ff
    信号                : 99%
    BSSID 2             : 11-22-33-44-55-66
    信号                : 70%

SSID 2 : Campus-WiFi
    网络类型            : 结构
    身份验证            : 开放
    加密                : 无
    BSSID 1             : 77-88-99-aa-bb-cc
    信号                : 40%

SSID 3 :
    网络类型            : 结构
    身份验证            : WPA2-企业
    BSSID 1             : 00-11-22-33-44-55
    信号                : 88%

SSID 4 : iphone17 pro max
    网络类型            : 结构
    身份验证            : WPA2-个人
    BSSID 1             : 66-77-88-99-aa-bb
    信号                : 20%
"""


def test_scan_dedupe_hidden_and_order(monkeypatch):
    monkeypatch.setattr(wifictl, "_run", lambda args, timeout=15: _cp(_NETSH_ZH))
    nets = wifictl.scan_networks()
    names = [n["ssid"] for n in nets]
    assert names == ["Campus-WiFi", "iphone17 pro max"]   # 隐藏 SSID 3 排除;强弱排序
    campus = nets[0]
    assert campus["signal"] == "strong"                    # 99% 与 40% 去重取最强


def test_scan_signal_tiers(monkeypatch):
    table = _NETSH_ZH.replace("99%", "65%").replace("70%", "30%").replace("20%", "10%")
    monkeypatch.setattr(wifictl, "_run", lambda args, timeout=15: _cp(table))
    nets = {n["ssid"]: n["signal"] for n in wifictl.scan_networks()}
    assert nets["Campus-WiFi"] == "medium"     # 65%
    assert nets["iphone17 pro max"] == "weak"  # 10%


def test_scan_failure_raises(monkeypatch):
    monkeypatch.setattr(wifictl, "_run", lambda args, timeout=15: _cp(rc=1, stderr="拒绝访问"))
    with pytest.raises(wifictl.WifiScanError):
        wifictl.scan_networks()


def test_current_ssid_parse(monkeypatch):
    out = "名称 : WLAN\n状态 : 已连接\nSSID : Campus-WiFi\nBSSID : aa-bb\n"
    monkeypatch.setattr(wifictl, "_run", lambda args, timeout=15: _cp(out))
    assert wifictl.current_ssid() == "Campus-WiFi"


def test_current_ssid_none_when_disconnected(monkeypatch):
    out = "名称 : WLAN\n状态 : 已断开连接\n"
    monkeypatch.setattr(wifictl, "_run", lambda args, timeout=15: _cp(out))
    assert wifictl.current_ssid() is None


def test_connect_already_on_target(monkeypatch):
    monkeypatch.setattr(wifictl, "current_ssid", lambda: "Campus-WiFi")
    assert wifictl.connect("Campus-WiFi", timeout=1)


def test_connect_uses_saved_profile(monkeypatch):
    state = {"ssid": None}

    def cur():
        return state["ssid"]
    monkeypatch.setattr(wifictl, "current_ssid", cur)
    monkeypatch.setattr(wifictl, "_profiles", lambda: {"Campus-WiFi"})

    def fake_sleep(s):
        state["ssid"] = "Campus-WiFi"       # 第一次 connect 命令后的轮询里切上
    monkeypatch.setattr(wifictl.time, "sleep", fake_sleep)

    cmds = []

    def fake_run(args, timeout=15):
        cmds.append(args)
        return _cp("已成功完成连接请求。")
    monkeypatch.setattr(wifictl, "_run", fake_run)
    assert wifictl.connect("Campus-WiFi", timeout=30)
    assert cmds[0][:3] == ["wlan", "connect", "ssid=Campus-WiFi"]
    assert cmds[0][3] == "name=Campus-WiFi"    # 已保存 profile 名优先


def test_connect_encrypted_without_profile_raises(monkeypatch):
    monkeypatch.setattr(wifictl, "current_ssid", lambda: None)
    monkeypatch.setattr(wifictl, "_profiles", lambda: set())
    monkeypatch.setattr(wifictl, "_add_open_profile", lambda ssid: False)
    with pytest.raises(wifictl.WifiConnectError):
        wifictl.connect("SecretNet", timeout=1)


def test_connect_open_profile_created_then_connected(monkeypatch):
    state = {"added": False, "ssid": None}

    monkeypatch.setattr(wifictl, "current_ssid", lambda: state["ssid"])
    monkeypatch.setattr(wifictl, "_profiles", lambda: set())

    def add_open(ssid):
        state["added"] = True
        return True
    monkeypatch.setattr(wifictl, "_add_open_profile", add_open)
    monkeypatch.setattr(wifictl, "_run", lambda args, timeout=15: _cp("ok"))

    def fake_sleep(s):
        state["ssid"] = "Campus-WiFi"
    monkeypatch.setattr(wifictl.time, "sleep", fake_sleep)
    monkeypatch.setattr(wifictl.time, "time", lambda: 0)
    assert wifictl.connect("Campus-WiFi", timeout=30)
    assert state["added"]


def test_connect_timeout_returns_false(monkeypatch):
    monkeypatch.setattr(wifictl, "current_ssid", lambda: None)
    monkeypatch.setattr(wifictl, "_profiles", lambda: {"Campus-WiFi"})
    monkeypatch.setattr(wifictl, "_run", lambda args, timeout=15: _cp("ok"))
    monkeypatch.setattr(wifictl.time, "sleep", lambda s: None)
    assert wifictl.connect("Campus-WiFi", timeout=0) is False


# ── 开放 profile XML 拼装(纯函数;审计附录 A-1 转义)──────


def test_open_profile_xml_escapes_special_chars():
    """SSID 含 <>&"' 时 profile 仍合法且 name 与 SSID 语义一致(附录 A-1)。"""
    import xml.etree.ElementTree as ET

    ssid = 'A<b>&"\'bomb'
    xml = wifictl.build_open_profile_xml(ssid)
    root = ET.fromstring(xml)                       # 非法 XML 会在此抛
    ns = "{http://www.microsoft.com/networking/WLAN/profile/v1}"
    names = [e.text for e in root.iter(f"{ns}name")]
    assert names == [ssid, ssid]                    # profile 名与 SSID 名还原为原 SSID
    assert "<bomb" not in xml and "'bomb" in xml    # 原文未裸入结构;引号在文本节点无需转义


def test_open_profile_xml_plain_ssid_unchanged():
    """普通 SSID 不受转义影响,两处 {name} 都落位。"""
    xml = wifictl.build_open_profile_xml("Campus-WiFi")
    assert xml.count("<name>Campus-WiFi</name>") == 2
