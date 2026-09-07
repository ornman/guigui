"""logstore:追加/按天查询/label 规则/days 上限/过滤预留。"""

import datetime as dt

from guigui.core import logstore


def _at(day_offset: int, hhmmss: str):
    base = dt.date.today() - dt.timedelta(days=day_offset)
    h, m, s = (int(x) for x in hhmmss.split(":"))
    return dt.datetime.combine(base, dt.time(h, m, s))


def test_append_and_query_today():
    logstore.append("ok", "网络可达", when=_at(0, "07:00:01"))
    logstore.append("ok", "已登录 · 2025…7209", when=_at(0, "07:00:02"))
    logstore.append("note", "今天到这就下班啦 ☕", when=_at(0, "07:00:03"))
    days = logstore.query()
    assert days[0]["label"] == "今天"
    assert [e["ts"] for e in days[0]["entries"]] == ["07:00:01", "07:00:02", "07:00:03"]
    assert days[0]["entries"][0]["level"] == "ok"


def test_yesterday_label_with_date():
    logstore.append("ok", "开门即试,一次登好 ✓", when=_at(1, "06:55:02"))
    d = dt.date.today() - dt.timedelta(days=1)
    label = logstore.query()[0]["label"]
    assert label == f"昨天 · {d.month}月{d.day}日"


def test_older_label_plain():
    logstore.append("ok", "x", when=_at(5, "07:00:00"))
    d = dt.date.today() - dt.timedelta(days=5)
    assert logstore.query()[0]["label"] == f"{d.month}月{d.day}日"


def test_all_silent_day_gets_vacation_suffix():
    logstore.append("silent", "连不上,今天先不打扰,明天再试一次", when=_at(2, "07:00:01"))
    label = logstore.query()[0]["label"]
    assert label.endswith(" · 假期静默")


def test_mixed_day_no_vacation_suffix():
    logstore.append("silent", "连不上", when=_at(2, "07:00:01"))
    logstore.append("ok", "后来又通了", when=_at(2, "08:00:00"))
    assert "假期静默" not in logstore.query()[0]["label"]


def test_empty_days_skipped_and_order_newest_first():
    logstore.append("ok", "today", when=_at(0, "09:00:00"))
    logstore.append("ok", "3d ago", when=_at(3, "09:00:00"))
    days = logstore.query()
    assert [d["entries"][0]["text"] for d in days] == ["today", "3d ago"]


def test_days_capped_at_90():
    assert len(logstore.query(500)) <= 90


def test_level_filter_reserved_for_ac07():
    logstore.append("ok", "a", when=_at(0, "01:00:00"))
    logstore.append("fail", "b", when=_at(0, "02:00:00"))
    only_fail = logstore.query(level="fail")
    assert [e["text"] for e in only_fail[0]["entries"]] == ["b"]


def test_bad_lines_skipped():
    p = logstore.paths.logs_dir() / f"{dt.date.today():%Y-%m-%d}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json\n" + '{"ts":"07:00:00","level":"ok","text":"好行"}\n', encoding="utf-8")
    entries = logstore.read_day(dt.date.today())
    assert len(entries) == 1 and entries[0]["text"] == "好行"


# ── >90 天清理(AC-18)────────────────────────────────────


def test_cleanup_old_removes_only_our_old_files():
    logs = logstore.paths.logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    old = logs / "2026-06-01.jsonl"          # 97 天前(> 90)
    edge = logs / "2026-06-08.jsonl"         # 90 天整(保留,cutoff 语义为「早于」)
    fresh = logs / "2026-09-06.jsonl"
    foreign = logs / "2026-01-01.txt"        # 不是桂桂命名 → 一律不碰
    for p in (old, edge, fresh, foreign):
        p.write_text('{"ts":"07:00:00","level":"ok","text":"x"}\n', encoding="utf-8")
    removed = logstore.cleanup_old(keep_days=90, today=dt.date(2026, 9, 6))
    assert removed == 1
    assert not old.exists()
    assert edge.exists() and fresh.exists() and foreign.exists()


def test_cleanup_old_survives_garbage_names():
    logs = logstore.paths.logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "not-a-date.jsonl").write_text("x", encoding="utf-8")
    assert logstore.cleanup_old(keep_days=90, today=dt.date(2026, 9, 6)) == 0
    assert (logs / "not-a-date.jsonl").exists()


def test_append_with_data_roundtrip():
    import datetime as dt
    logstore.append("fail", "登录被拒",
                    data={"rej": "limit_users", "tries": 2, "http": 200})
    e = logstore.read_day(dt.date.today())[-1]
    assert e["data"] == {"rej": "limit_users", "tries": 2, "http": 200}


def test_append_without_data_keeps_old_shape():
    import datetime as dt
    logstore.append("ok", "网络可达")
    e = logstore.read_day(dt.date.today())[-1]
    assert set(e) == {"ts", "level", "text"}      # 日常界面形状不变
