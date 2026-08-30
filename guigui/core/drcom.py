"""Dr.COM 协议 — 登录(GET /drcom/login JSONP)、chkstatus 学号识别、学号打码。

参数集移植自 v1 src/login.py:91-128(生产验证);v2 变化:
- 返回结构化结果(success/rejected/unexpected/unreachable),供契约区分 AUTH_REJECTED;
- 学号不再写工程日志明文(打码版走 logstore)。
"""

from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

LOGIN_PATH = "/drcom/login"
CHKSTATUS_PATH = "/drcom/chkstatus"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
LOGIN_TIMEOUT = 10
CHKSTATUS_TIMEOUT = 5

SUCCESS = "success"
REJECTED = "rejected"      # 服务器应答 result!=1(密码被拒等)
UNEXPECTED = "unexpected"  # 响应不是 JSONP(维护页/劫持页)
UNREACHABLE = "unreachable"

# PRD §4.1.1 实测记录的门户后缀表(默认校园用户=裸学号,v1 生产验证)。
# 运行时从门户拉取列为增强(技术方案 §14.8),先按实测值落地。
OPERATOR_TABLE: dict[str, str] = {
    "校园用户": "",
    "校园电信": "@dx",
    "校园联通": "@lt",
}
DEFAULT_OPERATOR = "校园用户"


def operator_suffix(operator: str | None) -> str:
    return OPERATOR_TABLE.get(operator or DEFAULT_OPERATOR, "")


def build_login_url(base: str, uid: str, password: str,
                    operator: str = DEFAULT_OPERATOR, now: float | None = None) -> str:
    username = uid + operator_suffix(operator)
    params = (
        f"callback=dr1003"
        f"&DDDDD={quote(username, safe='@')}"
        f"&upass={quote(password)}"
        f"&0MKKey=123456&R1=0&R2=&R3=1&R6=0"
        f"&para=00&v6ip=&terminal_type=1"
        f"&lang=zh-cn&jsVersion=4.2.1"
        f"&v={int(now if now is not None else time.time())}&lang=zh"
    )
    return f"{base}{LOGIN_PATH}?{params}"


def login(base: str, uid: str, password: str,
          operator: str = DEFAULT_OPERATOR, timeout: int = LOGIN_TIMEOUT) -> tuple[str, str]:
    """执行一次登录请求。

    Returns:
        (result, msg):result ∈ success | rejected | unexpected | unreachable。
        网络异常归为 unreachable(不抛出,调用方据此映射 NET_UNREACHABLE)。
    """
    url = build_login_url(base, uid, password, operator)
    req = Request(url, headers={"User-Agent": UA, "Referer": f"{base}/"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("gbk", errors="replace")
    except Exception as e:
        log.info("drcom: 登录请求失败(%s)", type(e).__name__)
        return UNREACHABLE, "够不着认证服务器"
    m = re.search(r"\((\{.*\})\)", body)
    if not m:
        log.warning("drcom: 非 JSONP 响应: %r", body[:80])
        return UNEXPECTED, "认证服务器返回了不认识的格式"
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return UNEXPECTED, "认证服务器返回了不认识的格式"
    if data.get("result") == 1:
        return SUCCESS, ""
    msg = str(data.get("msga") or "").strip()
    return REJECTED, msg or "密码可能改过了"


def chkstatus_uid(base: str, timeout: int = CHKSTATUS_TIMEOUT) -> str | None:
    """登录态下抓当前会话学号(PRD §4.1.1:uid/AC 即账号,按源 IP 识别)。

    失败/未登录/不可达一律返回 None(不区分原因,调用方有 config 兜底)。
    """
    url = f"{base}{CHKSTATUS_PATH}?callback=dr1003"
    req = Request(url, headers={"User-Agent": UA, "Referer": f"{base}/"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("gbk", errors="replace")
    except Exception:
        return None
    m = re.search(r"\((\{.*\})\)", body)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    uid = data.get("uid")
    if uid is None:  # 某些固件把账号放 DDDDD
        uid = data.get("DDDDD")
    uid = str(uid or "").strip()
    return uid or None


def mask_uid(uid: str | None) -> str:
    """学号打码:长度>8 → 前4…后4(契约 §2.3/§2.9 示例格式)。"""
    uid = str(uid or "").strip()
    if len(uid) > 8:
        return f"{uid[:4]}…{uid[-4:]}"
    return uid
