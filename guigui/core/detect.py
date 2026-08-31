"""网络状态探测 — logged_in / not_logged_in / unreachable / waiting 四态。

- waiting:网络栈未就绪(刚开机/WiFi 还在连)= 无已连接 WLAN 且无默认路由;
  此时不做 HTTP(避免 5s 空等),对应前端 bootWait 等门 UI(契约 §2.1)。
- 三态判定与 v1 login.check_auth_status 同源:title 含"注销" = 已登录。
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from urllib.request import Request, urlopen

from . import config as config_mod
from . import wifictl
from .drcom import UA

log = logging.getLogger(__name__)

LOGGED_IN = "logged_in"
NOT_LOGGED_IN = "not_logged_in"
UNREACHABLE = "unreachable"
WAITING = "waiting"

PROBE_TIMEOUT = 5
GATE_INTERVAL = 30    # 开门轮询间隔(PRD §4.6:每 30 秒看一次)
GATE_TIMEOUT = 600    # 等门上限 10min(任务时限 15min 容纳,技术方案 §3.5)


def _base_url(cfg: dict | None = None) -> str:
    cfg = cfg or config_mod.load()
    return cfg.get("url") or "http://10.1.2.3"


def _default_route_exists() -> bool:
    """route print -4 中是否存在默认路由(0.0.0.0/0)。"""
    try:
        r = subprocess.run(
            ["route", "print", "-4"], capture_output=True, text=True,
            encoding="gbk", errors="replace", timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,  # 不弹终端窗口
        )
    except Exception as e:
        log.warning("detect: route 查询失败: %s", e)
        return True  # 探测失败不拦路,交给 HTTP 判定
    for line in r.stdout.splitlines():
        tok = line.split()
        if len(tok) >= 3 and tok[0] == "0.0.0.0" and tok[1] == "0.0.0.0":
            return True
    return False


def any_network_up() -> bool:
    """有任一可用网络(WLAN 已连 或 存在默认路由)。"""
    if wifictl.current_ssid():
        return True
    return _default_route_exists()


def http_probe(base: str | None = None, timeout: int = PROBE_TIMEOUT,
               cfg: dict | None = None) -> dict:
    """探测认证服务器。返回 {"state", "detail"};不抛异常。"""
    base = base or _base_url(cfg)
    try:
        req = Request(base + "/", headers={"User-Agent": UA})
        with urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("gb2312", errors="replace")
        m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
        if m and "注销" in m.group(1):
            return {"state": LOGGED_IN, "detail": ""}
        return {"state": NOT_LOGGED_IN, "detail": ""}
    except Exception as e:
        name = type(e).__name__
        detail = "timeout" if "timeout" in name.lower() else "refused"
        log.info("detect: 不可达(%s: %s)", name, str(e)[:60])
        return {"state": UNREACHABLE, "detail": detail}


def probe(cfg: dict | None = None) -> dict:
    """契约 §2.1 net 形状:{state, ssid, server}(外加内部 detail 键)。"""
    cfg = cfg or config_mod.load()
    if not any_network_up():
        return {"state": WAITING, "ssid": None, "server": cfg.get("server_name", ""), "detail": ""}
    out = http_probe(cfg=cfg)
    out["ssid"] = wifictl.current_ssid()
    out["server"] = cfg.get("server_name", "")
    return out


def server_reachable(base: str | None = None, cfg: dict | None = None) -> bool:
    return http_probe(base, cfg=cfg)["state"] != UNREACHABLE


def wait_for_gate(base: str | None = None, timeout: int = GATE_TIMEOUT,
                  interval: int = GATE_INTERVAL, cfg: dict | None = None,
                  progress=None) -> bool:
    """开机等门:轮询直到服务器可达(开门),永不报错。返回是否等到。"""
    deadline = time.time() + timeout
    while True:
        if server_reachable(base, cfg=cfg):
            return True
        if progress:
            progress()
        if time.time() >= deadline:
            return False
        time.sleep(interval)


def portal_html(cfg: dict | None = None, timeout: int = PROBE_TIMEOUT) -> str | None:
    """取认证服务器门户页原文(验证流程解析注销端点用);失败返回 None。"""
    base = _base_url(cfg)
    try:
        req = Request(base + "/", headers={"User-Agent": UA})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("gb2312", errors="replace")
    except Exception as e:
        log.info("detect: 门户页取回失败(%s)", type(e).__name__)
        return None
