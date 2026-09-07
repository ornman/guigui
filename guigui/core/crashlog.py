"""崩溃捕获 — install()(双 excepthook)+ recent(n)(供诊断采集)。

PRD §7.1 微接口模块:GUI 与 ensure 两进程启动各调一次 install(proc);
记录进程身份;封顶轮转。红线:崩溃文件只随用户主动反馈出门,永不静默上传;
堆栈经 scrub_uids(异常消息里可能带学号);Python 堆栈本就不含实参。
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import logging
import os
import sys
import threading
import traceback

from . import paths
from .drcom import scrub_uids

log = logging.getLogger(__name__)

KEEP = 10            # 封顶轮转:磁盘上最多保留的崩溃文件数
RECENT_FOR_DIAG = 3  # 诊断包携带的份数(PRD §4.1 crashes 区)

_proc = {"name": "gui"}
_seq = itertools.count(1)    # 同秒多崩不互覆(文件名带序号)


def install(proc: str = "gui") -> None:
    """挂全局异常钩子(sys 主线程 + threading 子线程);幂等。"""
    _proc["name"] = proc
    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook


def _sys_hook(tp, val, tb) -> None:
    _write("".join(traceback.format_exception(tp, val, tb)))
    sys.__excepthook__(tp, val, tb)     # 原生输出不丢(工程日志/控制台)


def _thread_hook(args) -> None:
    _write("".join(traceback.format_exception(
        args.exc_type, args.exc_value, args.exc_traceback)))


def _crashes_dir():
    return paths.data_dir() / "crashes"


def _write(trace: str) -> None:
    """落盘一份;任何失败不再抛(崩溃处理器自己不能崩)。"""
    try:
        d = _crashes_dir()
        d.mkdir(parents=True, exist_ok=True)
        now = dt.datetime.now()
        rec = {
            "ts": now.strftime("%m-%d %H:%M:%S"),
            "proc": _proc["name"],
            "trace": scrub_uids(trace[-16384:]),   # 超长保尾部(异常链顶在下)
        }
        name = f"crash-{now:%Y%m%d-%H%M%S}-{os.getpid()}-{next(_seq):03d}.json"
        p = d / name
        p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        _rotate(d)
    except Exception:
        pass


def _rotate(d) -> None:
    files = sorted(d.glob("crash-*.json"))
    for p in files[:-KEEP] if len(files) > KEEP else []:
        try:
            p.unlink()
        except OSError:
            pass


def recent(n: int = RECENT_FOR_DIAG) -> list[dict]:
    """最近 n 份崩溃记录(新→旧);坏文件跳过。"""
    d = _crashes_dir()
    try:
        files = sorted(d.glob("crash-*.json"), reverse=True)
    except OSError:
        return []
    out = []
    for p in files[:n]:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out
