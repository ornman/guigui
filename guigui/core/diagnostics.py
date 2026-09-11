"""反馈诊断包 — collect(kind) 七区采集 + render(bundle) 预览文本(PRD §7.1)。

两渲染器分工:预览渲染数据(本模块 render),issue 渲染版式(边缘端 fb.js)。

红线(§7.3,任何改动不得违反):
- 绝不发起真实登录/注销(全屋共享会话);只做只读/被动探测;
- 登录 URL(含 upass=)永不入包;data 只存服务器响应字段;
- 打码在采集时完成(scrub_uids 对任何 ≥10 位数字串生效),出机器即净数据;
- 所见即所发:预览与发送渲染自同一份 bundle;sender_uid 由 feedback 模块
  在信封直附,不进本模块产物。

瘦身规则住在这里(调用方不过滤):仅纯建议不带 net/server/logs/summary/crashes。
7 个采集器是内部 seam:各自 try/except,失败写该区 errors 字段(in-band),不传染。
"""

from __future__ import annotations

import datetime as dt
import email.utils
import json
import platform
import re
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import guigui
from . import config, crashlog, detect, logstore, paths, scheduler, sysinfo, wifictl
from .drcom import UA, mask_uid, scrub_uids

LOG_DAYS = 7            # logs 区回看天数(PRD §4.1)
LOG_DAY_CAP = 80        # 单日条数上限:超了保头保尾(决策记录 8)
LOG_HEAD, LOG_TAIL = 20, 40
PROBE_TIMEOUT = 4       # 单个探测超时
VERSION_URL = "https://guigui-guat.pages.dev/version.json"

# 进程起点(供 self.proc_uptime_s;import 即记,gui/ensure 启动即 import 链上)
_PROC_STARTED = time.monotonic()

_state_zh = {"logged_in": "已登录", "not_logged_in": "未登录",
             "unreachable": "不可达", "waiting": "网络未就绪"}


def _scrub(value):
    """递归打码:字符串/列表/字典全走一遍(防御性,采集源头已尽量净)。"""
    if isinstance(value, str):
        return scrub_uids(value)
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    return value


def _region(errors: list, name: str, fn, *args):
    """单采集器 seam:异常 → 该区 errors 一行,其余照发(AC-F5)。"""
    try:
        return fn(*args)
    except Exception as e:
        errors.append(f"{name}: {type(e).__name__}")
        return None


# ── env 区采集器 ────────────────────────────────

def _env_os() -> str:
    build = 0
    try:
        build = sys_build()
    except Exception:
        build = int(re.search(r"\d+", platform.version() or "0").group(0))
    major = "11" if build >= 22000 else "10"
    return f"Windows {major} {build} {platform.machine()}"


def sys_build() -> int:
    import sys as _sys
    v = _sys.getwindowsversion()
    return int(getattr(v, "build", 0) or 0)


def _env_clock_skew(cfg: dict) -> float | None:
    """用户时钟 vs 认证服务器时钟(秒)— 定时全乱的元凶。只读探测。"""
    base = cfg.get("url") or "http://10.1.2.3"
    req = Request(base + "/", headers={"User-Agent": UA})
    with urlopen(req, timeout=PROBE_TIMEOUT) as resp:
        date_hdr = resp.headers.get("Date")
    if not date_hdr:
        return None
    server = email.utils.parsedate_to_datetime(date_hdr)
    return round((server - dt.datetime.now(dt.timezone.utc)).total_seconds(), 1)


_IPV4 = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
# kind 分类关键词(name+description 命中即归类;顺序:先专后泛)— 口径与旧
# ipconfig 通道一致,ADR-0003 只换采集方式不动分类
_KIND_RULES = [
    ("tun", ("tap", "tun", "clash", "wireguard", "openvpn", "vpn", "tailscale", "sing-box", "v2ray")),
    ("vm", ("virtualbox", "vmware", "hyper-v", "vethernet", "loopback", "bluetooth")),
]
_WIFI_RULES = ("wireless", "wi-fi", "wifi", "wlan", "802.11", "无线")


def _env_adapters() -> list[dict]:
    """全部网卡(含虚拟):进程内 NetworkInformation 枚举(ADR-0003,免
    ipconfig /all 的 GBK 表头解析);kind ∈ wifi/ethernet/tun/vm。"""
    ssid = None
    try:
        ssid = wifictl.current_ssid()
    except Exception:
        pass
    adapters: list[dict] = []
    for ni in sysinfo.net_interfaces():
        hay = f"{ni['name']} {ni['description']}".lower()
        kind = "ethernet"
        for want, kws in _KIND_RULES:
            if any(k in hay for k in kws):
                kind = want
                break
        if kind == "ethernet" and (ni["is_wireless"]
                                   or any(k in hay for k in _WIFI_RULES)):
            kind = "wifi"
        entry = {"name": ni["name"], "kind": kind, "ip": ni["ipv4"],
                 "up": ni["is_up"]}
        if kind == "wifi" and ni["is_up"] and ssid:
            entry["ssid"] = ssid
        adapters.append(entry)
    return adapters


def _env_dns() -> list[str]:
    """DNS 服务器:进程内 NetworkInformation(ADR-0003);IPv4、去重、保序。"""
    servers: list[str] = []
    for ni in sysinfo.net_interfaces():
        for s in ni["dns"]:
            if _IPV4.fullmatch(s) and not s.startswith("127.") and s not in servers:
                servers.append(s)
    return servers


def _env_proxy() -> dict:
    system = False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            enable, _ = winreg.QueryValueEx(k, "ProxyEnable")
            server = ""
            try:
                server, _ = winreg.QueryValueEx(k, "ProxyServer")
            except OSError:
                pass
            system = bool(enable) and bool(str(server or "").strip())
    except Exception:
        pass
    import os
    env_flag = any(os.environ.get(k) for k in
                   ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                    "http_proxy", "https_proxy", "all_proxy"))
    return {"system": system, "env": env_flag}


# SecurityCenter2 displayName(厂商在安全中心自报名)→ 三家布尔;只报布尔,
# 不列产品清单(PRD §4.1 口径延续)
_AV_PRODUCT_RULES = {
    "huorong": ("huorong", "火绒"),
    "qihoo360": ("360",),
    "defender": ("defender",),
}


def _env_av() -> dict:
    """杀软识别 — WMI root\\SecurityCenter2 AntiVirusProduct.displayName(ADR-0003:
    撤 tasklist 进程名匹配 — 未签名程序枚举进程并匹配 AV 厂商名是教科书级侦察特征)。

    SecurityCenter2 缺失/查询失败/无产品 → 空对象(宁缺勿侦察,不回退 tasklist);
    有产品但都不认识 → 全 False(信息:装了未知杀软)。"""
    try:
        rows = sysinfo.wmi_rows("SELECT displayName FROM AntiVirusProduct",
                                scope=r"root\SecurityCenter2")
    except Exception:
        return {}
    if not rows:
        return {}
    names = [str(r.get("displayName") or "").lower() for r in rows]
    return {av: any(any(k in n for n in names) for k in kws)
            for av, kws in _AV_PRODUCT_RULES.items()}


_WEBVIEW2_KEY = (r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
                 r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")


def _env_webview2() -> str | None:
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, _WEBVIEW2_KEY) as k:
                    pv, _ = winreg.QueryValueEx(k, "pv")
                    if pv:
                        return str(pv)
            except OSError:
                continue
    except Exception:
        pass
    return None


def _collect_env(cfg: dict) -> dict:
    errors: list[str] = []
    out: dict = {"errors": errors}
    out["os"] = _region(errors, "os", _env_os) or ""
    out["clock_skew_s"] = _region(errors, "clock_skew", _env_clock_skew, cfg)
    out["adapters"] = _region(errors, "adapters", _env_adapters) or []
    out["dns"] = _region(errors, "dns", _env_dns) or []
    out["proxy"] = _region(errors, "proxy", _env_proxy) or {"system": False, "env": False}
    out["av"] = _region(errors, "av", _env_av) or {}
    out["webview2"] = _region(errors, "webview2", _env_webview2)
    out["python"] = platform.python_version()
    return out


# ── self 区采集器 ───────────────────────────────

def _self_installed_at() -> str | None:
    try:
        d = paths.data_dir()
        if not d.exists():
            return None
        ts = d.stat().st_ctime
        return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return None


def _self_config(cfg: dict) -> dict:
    """配置摘要(敏感项不入:uid 由信封 sender_uid 承担,密码从不进 config)。"""
    return {
        "trigger_time": cfg.get("trigger_time"),
        "operator": cfg.get("operator"),
        "heartbeat_minutes": cfg.get("heartbeat_minutes"),
        "boot_login": cfg.get("boot_login"),
        "wake_login": cfg.get("wake_login"),
        "patrol_enabled": cfg.get("patrol_enabled"),
        "patrol_interval_minutes": cfg.get("patrol_minutes"),
        "wifi_fallback_enabled": cfg.get("wifi_fallback_enabled"),
        "wifi_fallback_ssid": cfg.get("wifi_fallback_ssid"),
        "vacation_silence": cfg.get("vacation_silence"),
        "notifications": cfg.get("notifications"),
        "master": cfg.get("master"),
    }


def _self_state() -> dict:
    from . import ensure
    st = ensure.load_state()
    lr = st.get("last_result") or {}
    return {
        "cred_verified": bool(st.get("cred_verified")),
        "unreachable_streak": st.get("unreachable_streak", 0),
        "maintenance_streak": st.get("maintenance_streak", 0),
        "last_result": lr.get("outcome"),
        "last_settle_date": _mmdd(st.get("last_settle_date")),
    }


def _mmdd(iso_date: str | None) -> str | None:
    if not iso_date:
        return None
    try:
        d = dt.date.fromisoformat(str(iso_date))
        return f"{d.month:02d}-{d.day:02d}"
    except ValueError:
        return str(iso_date)


def _self_tasks() -> list[dict]:
    """任务在岗 + 最近运行:registered 走 scheduler.query_xml(COM 主/schtasks
    兜底);last_run/last_result 走 scheduler.task_runtime_info(COM 读
    RegisteredTask 属性,ADR-0001:撤 powershell Get-ScheduledTaskInfo 通道)。
    COM 不可用 → last_run 允许缺失,registered 判定不受损。"""
    tasks: list[dict] = []
    for name in (scheduler.TASK_MAIN, scheduler.TASK_PATROL):
        info = scheduler.task_runtime_info(name) or {}
        tasks.append({
            "name": name,
            "registered": scheduler.query_xml(name) is not None,
            "last_run": info.get("last_run"),
            "last_result": info.get("last_result"),
        })
    return tasks


def _collect_self(cfg: dict) -> dict:
    errors: list[str] = []
    out: dict = {"errors": errors}
    out["installed_at"] = _region(errors, "installed_at", _self_installed_at)
    out["config"] = _region(errors, "config", _self_config, cfg) or {}
    out["state"] = _region(errors, "state", _self_state) or {}
    out["tasks"] = _region(errors, "tasks", _self_tasks) or []
    out["proc_uptime_s"] = int(time.monotonic() - _PROC_STARTED)
    return out


# ── net 区采集器(problem scope)────────────────

def _net_host_port(cfg: dict) -> tuple[str, int]:
    u = urlsplit(cfg.get("url") or "http://10.1.2.3")
    return u.hostname or "10.1.2.3", u.port or 80


def _collect_net(cfg: dict) -> dict:
    errors: list[str] = []
    host, port = _net_host_port(cfg)

    def dns_resolved():
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        return str(infos[0][4][0])

    def tcp():
        with socket.create_connection((host, port), timeout=3):
            return True

    def http():
        base = cfg.get("url") or "http://10.1.2.3"
        t0 = time.monotonic()
        try:
            req = Request(base + "/", headers={"User-Agent": UA})
            with urlopen(req, timeout=PROBE_TIMEOUT) as resp:
                status = resp.status
                resp.read(256)
        except HTTPError as e:
            status = e.code
        latency = round((time.monotonic() - t0) * 1000)
        return status, latency

    out: dict = {"errors": errors}
    out["dns_resolved"] = _region(errors, "dns", dns_resolved)
    out["tcp"] = _region(errors, "tcp", tcp)
    status_latency = _region(errors, "http", http)
    out["http"], out["latency_ms"] = status_latency if status_latency else (None, None)
    out["route_iface"] = _region(errors, "route", lambda: _route_iface(host, cfg))
    return out


def _route_iface(host: str, cfg: dict) -> str | None:
    """最长前缀匹配路由 → 出口网卡名(WMI Win32_IP4RouteTable,ADR-0003:
    免 route print 文本解析;InterfaceIndex 直接反查网卡名,不再绕 IP 二次匹配)。"""
    try:
        ip = socket.inet_aton(host)
    except OSError:
        return None
    target = int.from_bytes(ip, "big")
    best_prefix, best_idx = -1, None
    for row in sysinfo.wmi_rows(
            "SELECT Destination, Mask, InterfaceIndex FROM Win32_IP4RouteTable"):
        try:
            dest = int.from_bytes(socket.inet_aton(str(row["Destination"])), "big")
            mask = int.from_bytes(socket.inet_aton(str(row["Mask"])), "big")
            idx = int(row["InterfaceIndex"])
        except (OSError, TypeError, ValueError):
            continue
        prefix = bin(mask).count("1")
        # mask=0(默认路由)也参与:prefix 0 是兜底命中(旧 route print 通道
        # 因 `if mask` 守卫从未匹配过 0/0,属通道重写修正)
        if (dest & mask) == (target & mask) and prefix > best_prefix:
            best_prefix, best_idx = prefix, idx
    if best_idx is None:
        return None
    for ni in sysinfo.net_interfaces():
        if ni["index"] == best_idx:
            return ni["name"]
    return str(best_idx)


# ── server 区(problem scope)──────────────────

def _server_chkstatus(cfg: dict) -> dict:
    """只读探测,三形态(§8,实测 2026-09-07):uid_online / no_session(HTTP 400)
    / unreachable。AC-F9:HTTP 400 是正常形态,不产生异常日志。"""
    from .drcom import CHKSTATUS_PATH
    base = cfg.get("url") or "http://10.1.2.3"
    url = f"{base}{CHKSTATUS_PATH}?callback=dr1003"
    req = Request(url, headers={"User-Agent": UA, "Referer": f"{base}/"})
    try:
        with urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            body = resp.read(1024).decode("gbk", errors="replace")
            status = resp.status
    except HTTPError as e:
        if e.code == 400:
            head = ""
            try:
                head = e.read(1024).decode("gbk", errors="replace")
            except Exception:
                pass
            return {"state": "no_session", "raw_head": scrub_uids(head[:120])}
        return {"state": "unreachable", "raw_head": ""}
    except Exception:
        return {"state": "unreachable", "raw_head": ""}
    data = _parse_jsonp(body)
    uid = (data or {}).get("uid") or (data or {}).get("DDDDD")
    state = "uid_online" if str(uid or "").strip() else "no_session"
    return {"state": state, "raw_head": scrub_uids(body[:120])}


def _parse_jsonp(body: str) -> dict | None:
    m = re.search(r"\((\{.*\})\)", body)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _server_last_verdict() -> dict | None:
    """最近一次真实登录尝试的服务器判定 — 取自日志 data(§7.3 红线:
    绝不诊断重放登录),七天窗口内最新的带 rej 的失败行。"""
    today = dt.date.today()
    for i in range(LOG_DAYS):
        date = today - dt.timedelta(days=i)
        for e in reversed(logstore.read_day(date)):
            d = e.get("data") or {}
            if d.get("rej"):
                out = {
                    "ts": f"{date.month:02d}-{date.day:02d} {e.get('ts', '')}",
                    "rej": d["rej"],
                    "msga": d.get("body_head"),
                    "server_view_ip": d.get("server_view_ip"),
                    "mac_hint": d.get("mac_hint"),
                    "aolno": d.get("aolno"),
                    "ubind": d.get("ubind"),
                }
                return {k: v for k, v in out.items() if v is not None}
    return None


def _collect_server(cfg: dict) -> dict:
    errors: list[str] = []
    out: dict = {"errors": errors}
    out["chkstatus"] = _region(errors, "chkstatus", _server_chkstatus, cfg) \
        or {"state": "unreachable", "raw_head": ""}
    out["last_verdict"] = _region(errors, "last_verdict", _server_last_verdict)
    return out


# ── logs / summary 区(problem scope)────────────

def _trim_entries(entries: list[dict]) -> list[dict]:
    if len(entries) <= LOG_DAY_CAP:
        return entries
    head, tail = entries[:LOG_HEAD], entries[-LOG_TAIL:]
    omitted = len(entries) - LOG_HEAD - LOG_TAIL
    return head + [{"ts": "", "level": "note",
                    "text": f"(中间略去 {omitted} 条)"}] + tail


def _collect_logs() -> tuple[list[dict], str | None]:
    today = dt.date.today()
    days: list[dict] = []
    marks: list[str] = []
    for i in range(LOG_DAYS):
        date = today - dt.timedelta(days=i)
        entries = _trim_entries(logstore.read_day(date))
        if not entries:
            continue
        out_entries = []
        for e in entries:
            row = {"ts": e.get("ts", ""), "level": e.get("level", ""),
                   "text": e.get("text", "")}
            if e.get("data"):
                row["data"] = e["data"]
            out_entries.append(row)
        days.append({"date": f"{date.month:02d}-{date.day:02d}", "entries": out_entries})
        mark = "–"                                  # silent/纯备注天
        for e in entries:                           # 最后一个信号定当天成色
            if e.get("level") == "fail":
                mark = "✗"
            elif e.get("level") == "ok" and str(e.get("text", "")).startswith("已登录"):
                mark = "✓"
        marks.insert(0, f"{date.month:02d}-{date.day:02d} {mark}")
    return days, (" · ".join(marks) if marks else None)


def last_fail_when() -> str:
    """用户输入层 when:最近一条失败日志时间('MM-DD HH:MM');无失败 → 空串。"""
    today = dt.date.today()
    for i in range(LOG_DAYS):
        date = today - dt.timedelta(days=i)
        for e in reversed(logstore.read_day(date)):
            if e.get("level") == "fail":
                ts = str(e.get("ts", ""))
                return f"{date.month:02d}-{date.day:02d} {ts[:5]}".strip()
    return ""


# ── latest_ver(两 scope 都带)──────────────────

def _latest_ver() -> str | None:
    try:
        req = Request(VERSION_URL, headers={"User-Agent": UA})
        with urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ver = data.get("latest")
        return str(ver)[:20] if ver else None
    except Exception:
        return None


# ── 对外接口 ────────────────────────────────────

def collect(kind: list[str]) -> dict:
    """采集诊断包(打码已在采集时完成)。kind 含 problem → 全量;纯建议 → 瘦身。"""
    cfg = config.load()
    full = "problem" in (kind or [])
    errors: list[str] = []
    bundle: dict = {"env": _collect_env(cfg)}
    try:
        bundle["self"] = _collect_self(cfg)
    except Exception as e:
        bundle["self"] = {"errors": [f"self: {type(e).__name__}"]}
    if full:
        try:
            bundle["net"] = _collect_net(cfg)
        except Exception as e:
            bundle["net"] = {"errors": [f"net: {type(e).__name__}"]}
        try:
            bundle["server"] = _collect_server(cfg)
        except Exception as e:
            bundle["server"] = {"errors": [f"server: {type(e).__name__}"]}
        try:
            bundle["crashes"] = crashlog.recent(crashlog.RECENT_FOR_DIAG)
        except Exception as e:
            bundle["crashes"] = []
            errors.append(f"crashes: {type(e).__name__}")
        try:
            logs, summary = _collect_logs()
            bundle["logs"] = logs
            if summary:
                bundle["summary"] = summary
        except Exception as e:
            bundle["logs"] = []
            errors.append(f"logs: {type(e).__name__}")
    bundle["latest_ver"] = _latest_ver()
    if errors:
        bundle["self"]["errors"] = [*bundle["self"].get("errors", []), *errors]
    return _scrub(bundle)


def render(bundle: dict) -> str:
    """预览文本(折叠区展示/复制动作共用;issue 排版权在边缘端,两渲染器不重叠)。"""
    now = dt.datetime.now()
    parts = [f"桂桂 v{guigui.__version__} 诊断信息",
             f"生成时间:{now:%Y-%m-%d %H:%M:%S}(已打码,密码永不包含)", ""]

    env = bundle.get("env") or {}
    parts += ["── 环境 ──",
              f"系统:{env.get('os') or '?'} · Python {env.get('python') or '?'}"
              f" · WebView2 {env.get('webview2') or '?'}",
              f"时钟偏差:{env.get('clock_skew_s')}s · 代理:系统 {bool((env.get('proxy') or {}).get('system'))}"
              f" / 环境变量 {bool((env.get('proxy') or {}).get('env'))}",
              f"杀软:{', '.join(f'{k}={v}' for k, v in (env.get('av') or {}).items()) or '—'}"]
    for a in env.get("adapters") or []:
        line = f"网卡 {a.get('name')}({a.get('kind')}){' · ' + a['ssid'] if a.get('ssid') else ''}"
        line += f" · {a.get('ip') or '无IP'} · {'在用' if a.get('up') else '未连接'}"
        parts.append(line)
    if env.get("dns"):
        parts.append(f"DNS:{' / '.join(env['dns'])}")
    if env.get("errors"):
        parts.append(f"采集失败:{'; '.join(env['errors'])}")

    self_ = bundle.get("self") or {}
    parts += ["", "── 自身 ──", f"安装于:{self_.get('installed_at') or '?'}"
              f" · 进程已运行 {self_.get('proc_uptime_s', 0)}s"]
    cfg = self_.get("config") or {}
    if cfg:
        parts.append(f"配置:{cfg.get('trigger_time')} 触发 · {cfg.get('operator')}"
                     f" · 心跳 {cfg.get('heartbeat_minutes')} 分钟 · 巡逻 {'开' if cfg.get('patrol_enabled') else '关'}"
                     f" · WiFi兜底 {'开' if cfg.get('wifi_fallback_enabled') else '关'}"
                     f" · 总开关 {'开' if cfg.get('master') else '关'}")
    st = self_.get("state") or {}
    if st:
        parts.append(f"状态:凭据{'已验证' if st.get('cred_verified') else '未验证'}"
                     f" · 最近结果 {st.get('last_result') or '—'}"
                     f" · 最后成功 {st.get('last_settle_date') or '—'}")
    for t in self_.get("tasks") or []:
        parts.append(f"任务 {t.get('name')}:{'已注册' if t.get('registered') else '未注册'}"
                     f" · 上次 {t.get('last_run') or '—'}({t.get('last_result') or '—'})")
    if self_.get("errors"):
        parts.append(f"采集失败:{'; '.join(self_['errors'])}")

    net = bundle.get("net")
    if net is not None:
        parts += ["", "── 网络(实时)──",
                  f"解析:{net.get('dns_resolved') or '失败'} · TCP:{'通' if net.get('tcp') else '不通'}"
                  f" · HTTP:{net.get('http') or '失败'} · 延迟 {net.get('latency_ms')}ms"
                  f" · 出口网卡:{net.get('route_iface') or '—'}"]
        if net.get("errors"):
            parts.append(f"采集失败:{'; '.join(net['errors'])}")

    server = bundle.get("server")
    if server is not None:
        parts += ["", "── 服务器(怎么看待这台机器)──"]
        chk = server.get("chkstatus") or {}
        parts.append(f"会话探测:{chk.get('state') or '?'}"
                     + (f"({chk.get('raw_head')})" if chk.get('raw_head') else ""))
        verdict = server.get("last_verdict")
        if verdict:
            parts.append(f"最近判定:{verdict.get('ts')} {verdict.get('rej')}"
                         f" · {verdict.get('msga') or ''}")
            if verdict.get("server_view_ip"):
                parts.append(f"服务器视角 IP:{verdict['server_view_ip']}")
        if server.get("errors"):
            parts.append(f"采集失败:{'; '.join(server['errors'])}")

    if bundle.get("summary"):
        parts += ["", "── 最近七天 ──", bundle["summary"]]
    for day in bundle.get("logs") or []:
        parts.append(f"[{day.get('date')}]")
        for e in day.get("entries") or []:
            parts.append(f"  {e.get('ts', '')} {str(e.get('level', '')).upper():<5} {e.get('text', '')}")

    if bundle.get("crashes"):
        parts += ["", "── 崩溃(最近)──"]
        for c in bundle["crashes"]:
            parts.append(f"[{c.get('ts')} {c.get('proc')}]")
            parts.append(str(c.get("trace", "")).strip())

    parts += ["", f"── 版本对照 ──\n本机 {guigui.__version__} · 最新 {bundle.get('latest_ver') or '?'}"]
    return "\n".join(parts)
