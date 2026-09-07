"""feedback 深模块 — 只走接口 submit/pump/status,不测内部(PRD §7.1)。

transport seam(_http_post)与 clock seam(_now)注入;不变量逐条对号:
送达或留存 / at-least-once + client_id 复用 / 退避表 / 不原地重试。
"""

import datetime as dt
import json

import pytest

from guigui.core import feedback


@pytest.fixture
def env(monkeypatch):
    """固定时钟 + 静态诊断(组包链不碰真采集器/真网络)。"""
    from guigui.core import config
    config.save(dict(config.DEFAULTS, uid="2025000000001"))
    monkeypatch.setattr(feedback.diagnostics, "collect",
                        lambda kind: {"env": {"os": "Windows 11 26200 x64"},
                                      "self": {"errors": []}, "latest_ver": "2.1.2"})
    monkeypatch.setattr(feedback.diagnostics, "last_fail_when", lambda: "09-07 06:52")

    clock = {"now": dt.datetime(2026, 9, 7, 7, 0, 0)}
    monkeypatch.setattr(feedback, "_now", lambda: clock["now"])

    posts = []          # 每次 POST 的 (client_id, payload)
    replies = []        # 队列应答,取尽后重复末条
    real_post = feedback._http_post

    def fake_post(payload):
        posts.append(payload)
        reply = replies[min(len(posts) - 1, len(replies) - 1)] if replies else OK
        return feedback.HttpResult(*reply) if isinstance(reply, tuple) else reply

    monkeypatch.setattr(feedback, "_http_post", fake_post)
    return type("Env", (), {"clock": clock, "posts": posts, "replies": replies})()


def _advance(env, seconds):
    env.clock["now"] = env.clock["now"] + dt.timedelta(seconds=seconds)


OK = (200, {"ok": True, "code": "SUBMITTED", "id": "GG-33"}, None)


def test_submit_delivered_no_queue(env):
    env.replies.append(OK)
    out = feedback.submit(["problem"], "今早没登上")
    assert isinstance(out, feedback.Submitted) and out.id == "GG-33"
    assert feedback.status() == {"pending": 0, "oldest_age_s": None}
    payload = env.posts[0]
    assert payload["v"] == 2 and payload["sender_uid"] == "2025000000001"
    assert payload["app"] == "desktop" and payload["kind"] == ["problem"]
    assert payload["when"] == "09-07 06:52"
    assert len(payload["client_id"]) >= 8


def test_submit_offline_queues_and_pump_delivers(env):
    env.replies.append(feedback.HttpResult(None, None, feedback.E_NET_OFFLINE))
    out = feedback.submit(["suggestion"], "建议加个深色模式")
    assert isinstance(out, feedback.Queued) and out.code == feedback.E_NET_OFFLINE
    assert feedback.status()["pending"] == 1

    _advance(env, 31)                       # 退避表第一档 30s
    env.replies.append(OK)
    results = feedback.pump()
    assert [type(r) for r in results] == [feedback.Submitted]
    assert feedback.status() == {"pending": 0, "oldest_age_s": None}
    # client_id 终身复用:补发的是同一条(服务端据此幂等)
    assert env.posts[0]["client_id"] == env.posts[1]["client_id"]
    assert env.posts[0]["what"] == "建议加个深色模式"


def test_submit_degraded(env):
    env.replies.append((200, {"ok": True, "code": "SUBMITTED_DEGRADED", "id": "GG-9"}, None))
    out = feedback.submit(["problem", "suggestion"], "两种都选")
    assert isinstance(out, feedback.SubmittedDegraded) and out.id == "GG-9"
    assert env.posts[0]["kind"] == ["problem", "suggestion"]


def test_backoff_schedule(env):
    env.replies.append(feedback.HttpResult(None, None, feedback.E_NET_OFFLINE))
    feedback.submit(["problem"], "x")
    first_id = env.posts[0]["client_id"]

    # 未到期:pump 不发(单次尝试、不原地重试)
    _advance(env, 10)
    assert feedback.pump() == [] and len(env.posts) == 1

    # 到期失败 → attempts=1,下次 +5min(退避表第二档)
    env.replies.append(feedback.HttpResult(None, None, feedback.E_NET_OFFLINE))
    _advance(env, 21)
    out = feedback.pump()
    assert isinstance(out[0], feedback.Queued)
    assert len(env.posts) == 2 and env.posts[1]["client_id"] == first_id
    _advance(env, 299)
    assert feedback.pump() == [] and len(env.posts) == 2
    _advance(env, 2)
    env.replies.append((503, {"ok": False, "code": "SINK_DOWN"}, None))
    assert isinstance(feedback.pump()[0], feedback.Queued)
    assert len(env.posts) == 3


def test_rate_limited_respects_retry_after(env):
    env.replies.append((429, {"ok": False, "code": "RATE_LIMITED", "retry_after": 3600}, None))
    out = feedback.submit(["problem"], "y")
    assert isinstance(out, feedback.Queued) and out.code == "RATE_LIMITED"
    _advance(env, 3601)
    env.replies.append(OK)
    assert isinstance(feedback.pump()[0], feedback.Submitted)


def test_validation_never_queues(env):
    env.replies.append((400, {"ok": False, "code": "VALIDATION", "message": "kind 不合法"}, None))
    out = feedback.submit(["problem"], "z")
    assert isinstance(out, feedback.Rejected) and "kind" in out.detail
    assert feedback.status()["pending"] == 0


def test_pump_drops_stale_validation(env):
    env.replies.append(feedback.HttpResult(None, None, feedback.E_NET_OFFLINE))
    feedback.submit(["problem"], "旧格式条目")
    _advance(env, 31)
    env.replies.append((400, {"ok": False, "code": "VALIDATION", "message": "schema 漂了"}, None))
    results = feedback.pump()
    assert isinstance(results[0], feedback.Rejected)
    assert feedback.status()["pending"] == 0     # 丢弃止损,不无限重试


def test_concurrent_pump_double_send_same_client_id(env, monkeypatch):
    """不变量 2 的桌面侧:两进程同发同一条 → 两次 POST 同 client_id,
    由服务端幂等吸收;第二unlink 落空不报错。"""
    env.replies.append(feedback.HttpResult(None, None, feedback.E_NET_OFFLINE))
    feedback.submit(["problem"], "并发场景")
    _advance(env, 31)
    env.replies.extend([OK, OK])                  # 两次都「成功」
    monkeypatch.setattr(feedback, "_deliver", lambda p: None)  # 模拟另一进程先读走
    feedback.pump()
    feedback.pump()                               # 第二进程仍在处理同一文件
    assert len(env.posts) == 3                    # 1 次入队前 + 2 次 pump
    assert env.posts[1]["client_id"] == env.posts[2]["client_id"]


def test_status_oldest_age(env):
    env.replies.append(feedback.HttpResult(None, None, feedback.E_NET_OFFLINE))
    feedback.submit(["problem"], "a")
    _advance(env, 120)
    st = feedback.status()
    assert st["pending"] == 1 and 110 <= st["oldest_age_s"] <= 130


def test_validate_input_human_errors():
    assert feedback.validate_input([], "x", "") is not None
    assert feedback.validate_input(["nope"], "x", "") is not None
    assert feedback.validate_input(["problem"], "", "") is not None
    assert feedback.validate_input(["problem"], "好" * 121, "") is not None
    assert feedback.validate_input(["problem"], "x", "c" * 81) is not None
    assert feedback.validate_input(["suggestion"], "x", "") is None
