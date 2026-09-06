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

# 拒绝三态(PRD 4.1.2 实测表,2026-09-06 隔离测试床):
# error1=账号+运营商组合不存在;error2=密码不对;bind=密码正确但绑定/接入区域被拦。
REJ_WRONG_PASSWORD = "wrong_password"
REJ_WRONG_ACCOUNT = "wrong_account"
REJ_BOUND = "bound"


def classify_rejection(msg: str | None) -> str | None:
    """把服务器拒绝文案归类为三态之一;不认识返回 None(原文展示,不猜)。"""
    msg = str(msg or "")
    if "bind userid error" in msg:
        return REJ_BOUND
    if "userid error2" in msg:
        return REJ_WRONG_PASSWORD
    if "userid error1" in msg:
        return REJ_WRONG_ACCOUNT
    return None


def rejection_text(kind: str | None, fallback: str) -> str:
    """三态人话文案单一来源(信封 message 直显用)。None → fallback 原样。"""
    if kind == REJ_WRONG_ACCOUNT:
        return "学号或运营商选错了,核对一下再试"
    if kind == REJ_WRONG_PASSWORD:
        return "密码不对,改一下再试"
    if kind == REJ_BOUND:
        return "密码是对的,但这个账号被绑在别处/受限 — 去自助服务平台看看绑定"
    return fallback

# 门户后缀表(2026-08-31 从注销页 carrier 配置实测抓全,共 4 项;
# 默认校园用户=裸学号)。运行时从门户拉取列为增强(技术方案 §14.8)。
OPERATOR_TABLE: dict[str, str] = {
    "校园用户": "",
    "校园电信": "@dx",
    "校园联通": "@lt",
    "校园其他": "",
}
DEFAULT_OPERATOR = "校园用户"

# 展示别名(2026-09-06 用户拍板):办了移动/广电套餐的学生按习惯选自家运营商,
# 协议侧归一到「校园其他」(空后缀)— 移动/广电不在门户 carrier 配置里(双页实测,
# 门户渲染器由 a41/a40.js 从 carrier 配置生成选项,无第五项),属套餐口径非登录后缀。
OPERATOR_ALIASES: dict[str, str] = {
    "中国移动": "校园其他",
    "中国广电": "校园其他",
}


def canonical_operator(operator: str | None) -> str:
    """展示名 → 协议名(别名归一);协议名/未知值原样返回。"""
    return OPERATOR_ALIASES.get(operator or "", operator or DEFAULT_OPERATOR)


def parse_operators(portal_html: str) -> dict[str, str]:
    """从门户页 carrier 配置解析运营商表(name → suffix)。

    实测载体(注销页 JS,哆点参数):carrier='{"yys":{…,"data":[
    {"id":"1","name":"校园用户","suffix":""},…]}}';解析不到/损坏返回
    空 dict(调用方沿用内置表)。TE 用它断言内置表与门户一致。"""
    m = re.search(r"carrier\s*=\s*'(.*?)'\s*;", portal_html or "", re.DOTALL)
    if not m:
        return {}
    try:
        items = json.loads(m.group(1))["yys"]["data"]
        return {str(i["name"]): str(i.get("suffix", "")) for i in items if i.get("name")}
    except (ValueError, KeyError, TypeError):
        return {}


def operator_suffix(operator: str | None) -> str:
    return OPERATOR_TABLE.get(canonical_operator(operator), "")


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


def parse_logout_endpoint(portal_html: str, base: str) -> str | None:
    """从门户页的 JS 配置解析注销端点(实测:authlogoutport=801;authlogoutpath='/eportal/…')。

    authlogoutIP 为空表示与认证服务器同主机;解析不到返回 None(调用方降级,
    不做验证)。"""
    import re as _re
    from urllib.parse import urlsplit

    m_port = _re.search(r"authlogoutport\s*=\s*(\d+)", portal_html or "")
    m_path = _re.search(r"authlogoutpath\s*=\s*'([^']*)'", portal_html or "")
    if not (m_port and m_path):
        return None
    host = (urlsplit(base).hostname or "").strip()
    if not host:
        return None
    return f"http://{host}:{m_port.group(1)}{m_path.group(1)}"


def logout(portal_html: str, base: str, timeout: int = 5) -> str | None:
    """发起注销:按门户页配置 GET 注销端点。返回所用 URL(None=门户页没给配置)。

    不解析注销响应(格式不稳定),是否真登出由调用方探测状态翻转判定;
    任何网络异常按已发起处理(交给探测收线),永不抛出。"""
    url = parse_logout_endpoint(portal_html, base)
    if url is None:
        return None
    try:
        req = Request(url, headers={"User-Agent": UA, "Referer": f"{base}/"})
        with urlopen(req, timeout=timeout) as resp:
            resp.read(256)
    except Exception as e:
        log.info("drcom: 注销请求异常(%s,交由探测判定)", type(e).__name__)
    return url


def mask_uid(uid: str | None) -> str:
    """学号打码:长度>8 → 前4…后4(契约 §2.3/§2.9 示例格式)。"""
    uid = str(uid or "").strip()
    if len(uid) > 8:
        return f"{uid[:4]}…{uid[-4:]}"
    return uid
