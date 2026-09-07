"""反馈深模块 — submit / pump / status 三接口(PRD §7.1,本系统的杠杆点)。

依赖单向:api → feedback → diagnostics / logstore;本模块绝不 import api/gui。

接口不变量(调用方需要知道的全部):
1. 用户提交的反馈,要么送达、要么留在本机直到送达——发送失败、入队、退避、
   补发全部在模块内,调用方永不需要「再问一次」。
2. 投递 at-least-once,服务端按 client_id exactly-once ⇒ 队列无需跨进程锁:
   pump() 可被 GUI 进程与 --ensure 进程并发调用(双发被服务端幂等吸收)。
3. client_id 在入队时生成一次、终身复用;送达 = 原子移出队列(unlink)。
4. 退避表 30s / 5min / 30min / 次日;单次尝试 timeout 8s、不原地重试——
   重试是队列的事,不是调用链的事。

队列布局:feedback_queue/<client_id>.json,每条一文件——新增=建文件、
送达=unlink,双进程并发互不覆盖(单文件重写在并发下会丢条目,禁用)。

内部 seam(不出接口):_http_post(生产 urllib / 测试 fake)、_now(退避计时)。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import socket
import ssl
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import guigui
from . import config, diagnostics, paths

log = logging.getLogger(__name__)

FB_URL = "https://guigui-guat.pages.dev/fb"
UA_PREFIX = "GuiguiDesktop"
TIMEOUT_S = 8                      # 单次尝试超时(不变量 4)
BACKOFF_S = (30, 300, 1800, 86400)  # 退避表:30s/5min/30min/次日
KINDS = ("problem", "suggestion")
MAX_WHAT = 120
MAX_CONTACT = 80

E_NET_OFFLINE = "E_NET_OFFLINE"
E_NET_DNS = "E_NET_DNS"
E_NET_TLS = "E_NET_TLS"
E_TIMEOUT = "E_TIMEOUT"
E_HTTP_5XX = "E_HTTP_5XX"
E_UNKNOWN = "E_UNKNOWN"            # 服务器回了不认识的形状(防御,不入线上枚举)

_now = dt.datetime.now             # 测试可注入(沿用 logstore 模式)


# ── Outcome(与 §4.2 线上状态码一一对应,桥层零翻译)──


@dataclass(frozen=True)
class Submitted:
    id: str


@dataclass(frozen=True)
class SubmittedDegraded:
    id: str


@dataclass(frozen=True)
class Queued:
    code: str
    next_attempt_at: str           # 展示用 "HH:MM"


@dataclass(frozen=True)
class Rejected:
    """仅 VALIDATION:字段本身不合法,重试无意义,不入队。"""

    detail: str


@dataclass(frozen=True)
class _Retry:
    """内部标记:可重试失败,入队/退避由调用方按退避表决定。"""

    code: str
    retry_after: int | None = None


def validate_input(kind, what: str, contact: str) -> str | None:
    """表单校验(人话错误);服务端仍是权威,这只是离线早拒。None=合法。"""
    if not isinstance(kind, list) or not kind or any(k not in KINDS for k in kind):
        return "至少选一个分类(问题 / 建议)"
    what = (what or "").strip()
    if not what:
        return "说说具体情况(必填)"
    if len(what) > MAX_WHAT:
        return f"具体情况限 {MAX_WHAT} 字(现在 {len(what)} 字)"
    if len((contact or "").strip()) > MAX_CONTACT:
        return f"联系方式限 {MAX_CONTACT} 字"
    return None


# ── transport seam ──────────────────────────────


@dataclass(frozen=True)
class HttpResult:
    status: int | None
    body: dict | None
    err: str | None                # E_NET_* 分类;None=拿到了 HTTP 应答


def _classify_net_error(e: Exception) -> str:
    if isinstance(e, socket.gaierror):
        return E_NET_DNS
    if isinstance(e, (socket.timeout, TimeoutError)):
        return E_TIMEOUT
    if isinstance(e, (ssl.SSLError, ssl.SSLCertVerificationError)):
        return E_NET_TLS
    return E_NET_OFFLINE


def _http_post(payload: dict) -> HttpResult:
    """单次 POST(不重试——重试是队列的事)。任何异常归 E_NET_* 分类。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        FB_URL, data=data, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": f"{UA_PREFIX}/{guigui.__version__}"})
    try:
        with urlopen(req, timeout=TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return HttpResult(resp.status, body if isinstance(body, dict) else None, None)
    except HTTPError as e:
        body = None
        try:
            parsed = json.loads(e.read().decode("utf-8"))
            body = parsed if isinstance(parsed, dict) else None
        except Exception:
            pass
        return HttpResult(e.code, body,
                          E_HTTP_5XX if e.code >= 500 else None)
    except Exception as e:                      # URLError / socket / ssl / json…
        return HttpResult(None, None, _classify_net_error(e))


# ── 响应 → Outcome(§4.2 信封表)────────────────

def _outcome(res: HttpResult):
    """终局 Outcome(Submitted/Degraded/Rejected)或 _Retry(重试是队列的事)。"""
    if res.err is not None:
        return _Retry(E_HTTP_5XX if res.err == E_HTTP_5XX else res.err)
    body = res.body or {}
    code = body.get("code")
    if res.status == 200 and code == "SUBMITTED":
        return Submitted(str(body.get("id") or ""))
    if res.status == 200 and code == "SUBMITTED_DEGRADED":
        return SubmittedDegraded(str(body.get("id") or ""))
    if res.status == 400 and code == "VALIDATION":
        return Rejected(str(body.get("message") or "内容不合法"))
    if res.status == 429:
        ra = body.get("retry_after")
        return _Retry("RATE_LIMITED", int(ra) if isinstance(ra, (int, float)) else None)
    if res.status == 503:
        return _Retry("SINK_DOWN")
    if res.status >= 500:
        return _Retry(E_HTTP_5XX)
    return _Retry(E_UNKNOWN)


# ── 队列(feedback_queue/,每条一文件)──────────


def _queue_dir() -> Path:
    return paths.data_dir() / "feedback_queue"


def _item_path(client_id: str) -> Path:
    return _queue_dir() / f"{client_id}.json"


def _enqueue(payload: dict, client_id: str, *, delay_s: int,
             attempts: int = 0, created_at: dt.datetime | None = None) -> dt.datetime:
    now = _now()
    next_at = now + dt.timedelta(seconds=delay_s)
    item = {
        "client_id": client_id,
        "created_at": (created_at or now).strftime("%Y-%m-%dT%H:%M:%S"),
        "attempts": attempts,
        "next_attempt_at": next_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "payload": payload,
    }
    d = _queue_dir()
    d.mkdir(parents=True, exist_ok=True)
    _atomic_write(_item_path(client_id), item)
    return next_at


def _atomic_write(path: Path, item: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp",
                               prefix=".fb_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _load_items() -> list[tuple[Path, dict]]:
    d = _queue_dir()
    try:
        files = sorted(d.glob("*.json"))
    except OSError:
        return []
    out = []
    for p in files:
        try:
            out.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue                              # 坏文件跳过,队列永不该挂主流程
    return out


def _parse_ts(s: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def _backoff_delay(attempts: int) -> int:
    return BACKOFF_S[min(attempts, len(BACKOFF_S) - 1)]


def _reschedule(path: Path, item: dict, retry: _Retry, *, attempts: int) -> Queued:
    """按退避表排下次尝试;429 的 retry_after 不短于退避表。"""
    delay = _backoff_delay(attempts)
    if retry.retry_after:
        delay = max(delay, int(retry.retry_after))
    next_at = _now() + dt.timedelta(seconds=delay)
    item["attempts"] = attempts
    item["next_attempt_at"] = next_at.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        _atomic_write(path, item)
    except OSError:
        log.warning("feedback: 队列重写失败(%s)", path.name)
    return Queued(retry.code, next_at.strftime("%H:%M"))


# ── 接口(就这三个)──────────────────────────────


def submit(kind: list[str], what: str, contact: str = ""):
    """用户点「发送反馈」:采集 → 组包 → 单次尝试;失败即入队(不变量 1/4)。"""
    what = (what or "").strip()
    contact = (contact or "").strip()
    client_id = str(uuid.uuid4())
    payload = _build_payload(kind, what, contact, client_id)
    result = _outcome(_http_post(payload))
    if not isinstance(result, _Retry):
        return result
    next_at = _enqueue(payload, client_id,
                       delay_s=max(_backoff_delay(0), int(result.retry_after or 0)))
    log.info("feedback: 入队(%s)", result.code)
    return Queued(result.code, next_at.strftime("%H:%M"))


def pump() -> list:
    """到期补发(GUI 打开 / 网络恢复 / ensure 拍都会调)。每条一次尝试。

    返回本次各条目的 Outcome;GUI/ensure 并发调用安全(不变量 2)。"""
    now = _now()
    results = []
    for path, item in _load_items():
        due = _parse_ts(item.get("next_attempt_at", ""))
        if due is None or due > now:
            continue
        result = _outcome(_http_post(item.get("payload") or {}))
        if isinstance(result, _Retry):
            results.append(_reschedule(
                path, item, result, attempts=int(item.get("attempts", 0)) + 1))
            continue
        _deliver(path)
        if isinstance(result, Rejected):
            # VALIDATION 永不成功:丢弃止损(队列里躺着的旧格式条目防御)
            log.warning("feedback: %s 被 VALIDATION 拒,已丢弃", item.get("client_id"))
        results.append(result)
    return results


def status() -> dict:
    """待发条数 + 最老一条年龄(供 UI 状态行)。"""
    now = _now()
    oldest: dt.datetime | None = None
    pending = 0
    for _path, item in _load_items():
        pending += 1
        created = _parse_ts(item.get("created_at", ""))
        if created and (oldest is None or created < oldest):
            oldest = created
    return {
        "pending": pending,
        "oldest_age_s": int((now - oldest).total_seconds()) if oldest else None,
    }


# ── 内部 ────────────────────────────────────────


def _deliver(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)             # 双进程并发送达:第二个 unlink 落空,无妨
    except OSError:
        log.warning("feedback: 移出队列失败(%s)", path.name)


def _build_payload(kind: list[str], what: str, contact: str,
                   client_id: str) -> dict:
    cfg = config.load()
    bundle = diagnostics.collect(kind)
    return {
        # 信封层(幂等与限频只看这一层;sender_uid 后端直附,前端不显示)
        "v": 2,
        "client_id": client_id,
        "sender_uid": cfg.get("uid") or "",
        "app": "desktop",
        "app_ver": guigui.__version__,
        # 用户输入层
        "kind": kind,
        "what": what,
        "contact": contact,
        "when": diagnostics.last_fail_when() if "problem" in kind else "",
        **bundle,
    }
