"""crashlog:install 双钩子 / recent / 封顶轮转 / 学号不出堆栈。"""

from guigui.core import crashlog, paths


def _files():
    d = paths.data_dir() / "crashes"
    return sorted(d.glob("crash-*.json")) if d.exists() else []


def test_sys_hook_writes_record_with_proc_identity(monkeypatch):
    import json

    monkeypatch.setattr(crashlog.sys, "__excepthook__",
                        lambda *a: None)   # 静音原生输出
    crashlog.install("ensure")
    try:
        raise RuntimeError("炸了,学号 2025000000001 别落盘")
    except RuntimeError:
        crashlog._sys_hook(*crashlog.sys.exc_info())

    recs = crashlog.recent(1)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["proc"] == "ensure"
    assert "RuntimeError" in rec["trace"] and "炸了" in rec["trace"]
    assert "2025000000001" not in rec["trace"]        # scrub:学号打码
    assert "2025…0001" in rec["trace"]
    # 落盘的就是 recent 读到的(坏文件容错由 read 侧兜)
    assert len(_files()) >= 1
    assert json.loads(_files()[-1].read_text(encoding="utf-8"))["proc"] == "ensure"


def test_recent_orders_newest_first_and_caps(monkeypatch):
    monkeypatch.setattr(crashlog.sys, "__excepthook__", lambda *a: None)
    crashlog.install("gui")
    for i in range(crashlog.KEEP + 2):
        try:
            raise ValueError(f"crash-{i}")
        except ValueError:
            crashlog._sys_hook(*crashlog.sys.exc_info())
    assert len(_files()) == crashlog.KEEP              # 封顶轮转
    recs = crashlog.recent(3)
    assert len(recs) == 3 and recs[0]["proc"] == "gui"
    traces = " ".join(r["trace"] for r in recs)
    assert "crash-11" in traces and "crash-1;" not in traces   # 新的在前


def test_write_never_raises(monkeypatch):
    # 目录不可写/盘满等:_write 吞掉一切(崩溃处理器不能自己崩)
    crashlog._write("trace")                            # 正常路径先走一遍
    def boom():
        raise PermissionError("x")
    monkeypatch.setattr(crashlog.paths, "data_dir", boom)
    crashlog._write("trace")                            # 不抛即通过
