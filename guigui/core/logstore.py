"""按天日志 — logs/YYYY-MM-DD.jsonl,每行 {"ts","level","text"}。

level ∈ ok|note|fail|silent;查询组装契约 §2.9 的 label
(今天 / 昨天 · 8月29日 / 8月28日,全 silent 天追加「 · 假期静默」)。
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from . import paths

log = logging.getLogger(__name__)

LEVELS = ("ok", "note", "fail", "silent")
MAX_DAYS = 90
DEFAULT_DAYS = 14


def _day_path(date: dt.date):
    return paths.logs_dir() / f"{date:%Y-%m-%d}.jsonl"


def append(level: str, text: str, when: dt.datetime | None = None) -> dict:
    """追加一行(就地返回该 entry,供事件推送复用)。"""
    if level not in LEVELS:
        raise ValueError(f"unknown level: {level}")
    when = when or dt.datetime.now()
    entry = {"ts": when.strftime("%H:%M:%S"), "level": level, "text": text}
    p = _day_path(when.date())
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_day(date: dt.date) -> list[dict]:
    """读某天全部 entry;坏行跳过(日志永远不该把 GUI 打挂)。"""
    p = _day_path(date)
    if not p.exists():
        return []
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("logstore: 跳过坏行 %r", line[:60])
    except OSError as e:
        log.warning("logstore: 读取 %s 失败: %s", p, e)
    return out


def _day_label(date: dt.date, today: dt.date) -> str:
    delta = (today - date).days
    base = f"{date.month}月{date.day}日"
    if delta == 0:
        return "今天"
    if delta == 1:
        return f"昨天 · {base}"
    return base


def query(days: int = DEFAULT_DAYS, level: str | None = None) -> list[dict]:
    """契约 §2.9 形状:新→旧,跳过空天;level 过滤为 AC-07 预留。"""
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = DEFAULT_DAYS
    days = max(1, min(days, MAX_DAYS))
    if level and level not in LEVELS:
        level = None
    today = dt.date.today()
    out = []
    for i in range(days):
        date = today - dt.timedelta(days=i)
        entries = read_day(date)
        if level:
            entries = [e for e in entries if e.get("level") == level]
        if not entries:
            continue
        label = _day_label(date, today)
        if all(e.get("level") == "silent" for e in entries):
            label += " · 假期静默"
        out.append({"label": label, "entries": entries})
    return out
