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
from typing import NamedTuple
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

# 拒绝四态(PRD §5 实测表:三态 2026-09-06 + limit_users 2026-09-07 测试床):
# error1=账号+运营商组合不存在;error2=密码不对(唯一置 cred_verified 假的态);
# bind=密码正确但绑定/接入区域被拦;limit_users=已在别处登录(不冤枉密码)。
REJ_WRONG_PASSWORD = "wrong_password"
REJ_WRONG_ACCOUNT = "wrong_account"
REJ_BOUND = "bound"
REJ_LIMIT_USERS = "limit_users"
REJ_THROTTLED = "throttled"  # 服务器节流(让等 N 秒再试,QA P1-6);不算密码错

# 诊断包/日志 data.rej 用的服务器码(§4.1/§5;与契约 §2.3 reason 枚举不同源)
REJ_CODE = {
    REJ_WRONG_ACCOUNT: "error1",
    REJ_WRONG_PASSWORD: "error2",
    REJ_BOUND: "bind",
    REJ_LIMIT_USERS: "limit_users",
    REJ_THROTTLED: "throttled",
}

# waitsec 节流秒数上限(QA P1-6 经验值,实测后校准):服务器给的秒数过大时
# 客户端按 30s 封顶等,剩余时间透传信封让前端「稍后再试」;防止一次 waitsec
# 把交互/静默重试循环卡死分钟级
WAITSEC_CAP = 30

# 学号形数字串(≥10 位)→ 打码;诊断红线「打码在采集时完成」的工具面
_UID_RUN = re.compile(r"\d{10,14}")

# waitsec 节流秒数解析(QA P1-6 实测后校准):实测前先按经验写两种形态 —
# 1) JSON 字段 {"waitsec": N} 或 "waittime" 同义(Dr.COM 系列常见键名);
# 2) msga 文本中的数字(中文「请等待 30 秒」类)+ wait/秒 关键词辅助;
# 节流判定:关键词命中即按节流处理,数字解析失败则按最小保守值 1 秒,
# 关键词也靠 regex 模糊匹配(实测响应文案可能含多余空格/标点)。
_WAIT_HINT = re.compile(
    r"wait\s*sec|waitsec|wait\s*time|wait\s*\d|秒|请\s*等|稍后再试|稍候|等待|too\s*fast|太\s*快",
    re.I)
_WAIT_NUM = re.compile(r"\d+")


def parse_waitsec(payload: dict | None, msg: str | None) -> int | None:
    """从响应里抽「让等几秒」的整数;抽不到返回 None(调用方按无节流处理)。

    优先级:JSON 字段("waitsec"/"waittime"/"wait") → msga 文本 + 关键词命中。
    JSON 字段疑似 0/负数按 None(节流秒数不能是 0)。"""
    if isinstance(payload, dict):
        for k in ("waitsec", "waittime", "wait"):
            v = payload.get(k)
            try:
                n = int(v)
                if n > 0:
                    return n
            except (TypeError, ValueError):
                pass
    msg = str(msg or "")
    if not msg:
        return None
    if not _WAIT_HINT.search(msg):
        return None
    m = _WAIT_NUM.search(msg)
    if not m:
        return 1   # 命中关键词但抽不到数字,按 1s 保守等
    n = int(m.group(0))
    return n if n > 0 else 1


def scrub_uids(text: str) -> str:
    """任何含学号的字符串出机器前过一遍(崩溃堆栈/服务器响应原文等)。"""
    return _UID_RUN.sub(lambda m: mask_uid(m.group(0)), str(text or ""))


def classify_rejection(msg: str | None, *,
                       waitsec: int | None = None,
                       payload: dict | None = None) -> str | None:
    """把服务器拒绝文案归类为四态之一;不认识返回 None(原文展示,不猜)。

    节流优先(QA P1-6):waitsec 命中即返 REJ_THROTTLED,绝不让节流文案误诊成
    密码错(error2 msga 可能混着节流说明)。节流检测先看参数 waitsec,再看
    payload/msga 自行 parse — 调用方若已知道 waitsec 直接传省一次解析。"""
    if waitsec is not None or parse_waitsec(payload, msg) is not None:
        return REJ_THROTTLED
    msg = str(msg or "")
    if "bind userid error" in msg:
        return REJ_BOUND
    if "userid error2" in msg:
        return REJ_WRONG_PASSWORD
    if "userid error1" in msg:
        return REJ_WRONG_ACCOUNT
    if "limit users err" in msg.lower():
        return REJ_LIMIT_USERS
    return None


def rejection_text(kind: str | None, fallback: str) -> str:
    """四态人话文案单一来源(信封 message 直显用)。None → fallback 原样。"""
    if kind == REJ_WRONG_ACCOUNT:
        return "学号或运营商选错了,核对一下再试"
    if kind == REJ_WRONG_PASSWORD:
        return "密码不对,改一下再试"
    if kind == REJ_BOUND:
        return "密码是对的,但这个账号被绑在别处/受限 — 去自助服务平台看看绑定"
    if kind == REJ_LIMIT_USERS:
        return ("这个学号已在别的设备上登录(比如在别处登过没下线),"
                "那边下线后桂桂会自动登好")
    if kind == REJ_THROTTLED:
        return "校园网侧说太快了,先等等再来(QA P1-6 节流)"
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


class LoginResult(NamedTuple):
    """login_ex 的返回:result 同 login();payload=拒绝响应的 JSONP 原文
    (limit_users 现场四件 ss5/ss1/ss4/aolno/ubind 从这取,§5);
    http=HTTP 状态码(不可达 None);waitsec=服务器节流秒数(QA P1-6,None=不限速)。
    请求 URL(含 upass=)永不进这里。"""

    result: str
    msg: str
    payload: dict | None
    http: int | None
    waitsec: int | None = None


def _parse_jsonp(body: str) -> dict | None:
    m = re.search(r"\((\{.*\})\)", body)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def login(base: str, uid: str, password: str,
          operator: str = DEFAULT_OPERATOR, timeout: int = LOGIN_TIMEOUT) -> tuple[str, str]:
    """执行一次登录请求(两元组兼容壳)。

    Returns:
        (result, msg):result ∈ success | rejected | unexpected | unreachable。
        网络异常归为 unreachable(不抛出,调用方据此映射 NET_UNREACHABLE)。
    """
    r = login_ex(base, uid, password, operator, timeout)
    return r.result, r.msg


def login_ex(base: str, uid: str, password: str,
             operator: str = DEFAULT_OPERATOR,
             timeout: int = LOGIN_TIMEOUT) -> LoginResult:
    """登录的完整结果形态(拒绝现场入日志 data 用,PRD §4.1/§5)。"""
    url = build_login_url(base, uid, password, operator)
    req = Request(url, headers={"User-Agent": UA, "Referer": f"{base}/"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("gbk", errors="replace")
            status = resp.status
    except Exception as e:
        log.info("drcom: 登录请求失败(%s)", type(e).__name__)
        return LoginResult(UNREACHABLE, "够不着认证服务器", None, None, None)
    data = _parse_jsonp(body)
    if data is None:
        log.warning("drcom: 非 JSONP 响应: %r", body[:80])
        return LoginResult(UNEXPECTED, "认证服务器返回了不认识的格式", None, status, None)
    if data.get("result") == 1:
        return LoginResult(SUCCESS, "", data, status, None)
    msg = str(data.get("msga") or "").strip()
    waitsec = parse_waitsec(data, msg)
    return LoginResult(REJECTED, msg or "密码可能改过了", data, status, waitsec)


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
    data = _parse_jsonp(body)
    if data is None:
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
