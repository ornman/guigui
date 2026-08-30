"""WiFi 操控 — netsh 扫描/连接/当前 SSID;开放网络可自动建临时 profile。

- 扫描:去重(同 SSID 取最强信号)、隐藏网络排除、信号分档 strong/medium/weak(契约 §2.4)。
- 连接:优先已保存 profile;无 profile 且网络为开放认证时自动建临时 profile
  (校园 Web 认证网通常开放);加密网络无 profile 则失败(需用户先在系统连过一次)。
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 90  # 契约 §2.5 时延承诺上限


class WifiScanError(RuntimeError):
    """netsh 扫描失败(→ WIFI_SCAN_FAILED)。"""


class WifiConnectError(RuntimeError):
    """连接失败/超时(→ WIFI_CONNECT_FAILED / WIFI_CONNECT_TIMEOUT)。"""


def _run(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    # 中文系统 netsh 输出为 GBK;errors=replace 保证任何代码页都不炸
    return subprocess.run(
        ["netsh", *args], capture_output=True, text=True,
        encoding="gbk", errors="replace", timeout=timeout,
    )


def current_ssid() -> str | None:
    """当前连接的 WiFi SSID;未连接/出错返回 None(v1 wifi.py 移植)。"""
    try:
        r = _run(["wlan", "show", "interfaces"])
    except Exception as e:
        log.warning("wifictl: 探测接口失败: %s", e)
        return None
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("SSID") and "BSSID" not in line and ":" in line:
            return line.split(":", 1)[1].strip() or None
    return None


def _profiles() -> set[str]:
    """已保存的 profile 名集合(v1 _find_profile 改集合版)。"""
    try:
        r = _run(["wlan", "show", "profiles"])
    except Exception as e:
        log.warning("wifictl: 列 profile 失败: %s", e)
        return set()
    out = set()
    for line in r.stdout.splitlines():
        if ":" not in line:
            continue
        name = line.split(":", 1)[1].strip()
        if name:
            out.add(name)
    return out


def _signal_label(percent: int) -> str:
    if percent >= 66:
        return "strong"
    if percent >= 33:
        return "medium"
    return "weak"


def _order(label: str) -> int:
    return {"strong": 0, "medium": 1, "weak": 2}[label]


def scan_networks() -> list[dict]:
    """扫描可见网络 → [{"ssid", "signal"(strong|medium|weak)}],按信号强→弱排序。

    抛 WifiScanError(netsh 失败);SSIDs 去重取最强;隐藏(空 SSID)排除。
    """
    try:
        r = _run(["wlan", "show", "networks", "mode=bssid"], timeout=20)
    except Exception as e:
        raise WifiScanError(f"扫描命令失败: {e}") from e
    if r.returncode != 0:
        raise WifiScanError((r.stderr or r.stdout or "netsh 失败").strip()[:120])

    best: dict[str, int] = {}
    auth: dict[str, str] = {}
    cur_ssid: str | None = None
    for line in r.stdout.splitlines():
        s = line.strip()
        m_ssid = s.startswith("SSID ") and ":" in s
        if m_ssid and "BSSID" not in s:
            name = s.split(":", 1)[1].strip()
            cur_ssid = name or None  # 空 = 隐藏网络
            if cur_ssid:
                best.setdefault(cur_ssid, 0)
                auth.setdefault(cur_ssid, "")
            continue
        if not cur_ssid:
            continue
        low = s.lower()
        if low.startswith(("signal", "信号")) and ":" in s:
            m = next((tok for tok in s.replace("：", ":").split(":")[1:] if tok.strip()), "")
            digits = "".join(ch for ch in m if ch.isdigit())
            if digits:
                best[cur_ssid] = max(best[cur_ssid], int(digits))
        elif low.startswith(("authentication", "身份验证")) and ":" in s:
            auth[cur_ssid] = s.split(":", 1)[1].strip()
    if not best:
        raise WifiScanError("没有扫到可见网络")
    out = [{"ssid": ssid, "signal": _signal_label(pct)} for ssid, pct in best.items()]
    out.sort(key=lambda n: (_order(n["signal"]), n["ssid"]))
    return out


def _is_open_auth(auth_str: str) -> bool:
    s = (auth_str or "").strip().lower()
    if not s:
        return False
    if "开放" in s or s == "open":
        return True
    return not any(k in s for k in ("wpa", "wep", "802.1x", "个人", "企业", "eap"))


_OPEN_PROFILE_TMPL = """<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
    <name>{name}</name>
    <SSIDConfig><SSID><name>{name}</name></SSID></SSIDConfig>
    <connectionType>ESS</connectionType>
    <connectionMode>manual</connectionMode>
    <MSM><security><authEncryption>
        <authentication>open</authentication>
        <encryption>none</encryption>
        <useOneX>false</useOneX>
    </authEncryption></security></MSM>
</WLANProfile>
"""


def _add_open_profile(ssid: str) -> bool:
    """为开放网络写临时 profile(netsh add profile),返回是否成功。"""
    xml = _OPEN_PROFILE_TMPL.replace("{name}", ssid)
    tmp: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", suffix=".xml", delete=False, encoding="utf-8") as f:
            f.write(xml)
            tmp = f.name
        r = _run(["wlan", "add", "profile", f"filename={tmp}", "user=all"])
        return r.returncode == 0
    except Exception as e:
        log.warning("wifictl: 建开放 profile 失败: %s", e)
        return False
    finally:
        if tmp:
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass


def connect(ssid: str, timeout: int = CONNECT_TIMEOUT,
            progress=None) -> bool:
    """连接指定 SSID(v1 wifi.connect 移植 + 开放 profile 兜底)。

    Returns:
        True 已连上(含本来就连着);False 超时。
    Raises:
        WifiConnectError: 无法发起连接(如加密网络无 profile)。
    """
    if not ssid:
        raise WifiConnectError("没有指定要连的网络")
    if current_ssid() == ssid:
        return True

    profile = ssid if ssid in _profiles() else None
    if profile is None:
        # 无已保存 profile:尝试按开放网络建临时 profile(校园 Web 认证网通常开放)。
        # 若目标其实是加密网络,profile 加得上但 connect 会一直失败 → 超时返回 False。
        if _add_open_profile(ssid):
            profile = ssid
            log.info("wifictl: 已为开放网络 '%s' 创建临时 profile", ssid)
        else:
            raise WifiConnectError(
                "这个网络需要密码,请先在系统 WiFi 列表里连一次,桂桂才能接管它")

    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            r = _run(["wlan", "connect", f"ssid={ssid}", f"name={profile}"])
            if r.returncode != 0:
                log.warning("wifictl: connect 返回非零: %s",
                            (r.stderr or r.stdout or "").strip()[:80])
        except Exception as e:
            log.warning("wifictl: connect 异常: %s", e)
        # 每 3s 轮询是否已切上
        poll_deadline = min(time.time() + 3 * 5, deadline)
        while time.time() < poll_deadline:
            time.sleep(3)
            if progress:
                progress()
            if current_ssid() == ssid:
                log.info("wifictl: 已连上 '%s'(第 %d 次尝试)", ssid, attempt)
                return True
        if progress:
            progress()
    return False
