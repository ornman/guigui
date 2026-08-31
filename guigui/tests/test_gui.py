"""gui:深链转发落盘 + FileWatcher pending 消费(纯文件/JS 层)。

窗口激活(_activate_existing_window)是 Win32 实操,不入单测,
由 Task 7 实机清单第 3 项覆盖。"""

import json
import time

from guigui.app import gui as gui_mod
from guigui.app.gui import FileWatcher, PENDING_VIEW_NAME, _forward_deep_link
from guigui.core import paths


class StubApi:
    def __init__(self):
        self.js = []

    def _emit(self, type_, payload):
        self.js.append(("emit", type_, payload))

    def _eval(self, js):
        self.js.append(("eval", js))


def _write_pending(view, age=0.0):
    p = paths.data_dir() / PENDING_VIEW_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"view": view, "ts": time.time() - age}),
                 encoding="utf-8")
    return p


def test_forward_deep_link_writes_pending_file(monkeypatch):
    monkeypatch.setattr(gui_mod, "_activate_existing_window", lambda: None)
    _forward_deep_link("creds")
    item = json.loads((paths.data_dir() / PENDING_VIEW_NAME)
                      .read_text(encoding="utf-8"))
    assert item["view"] == "creds"
    assert time.time() - item["ts"] < 5


def test_watcher_consumes_pending_view():
    api = StubApi()
    w = FileWatcher(api)
    _write_pending("creds")
    w._check_pending_view()
    assert not (paths.data_dir() / PENDING_VIEW_NAME).exists()   # 消费即删
    assert any(kind == "eval" and "creds" in js and "applyLaunch" in js
               for kind, js in api.js)


def test_watcher_drops_stale_pending_view():
    api = StubApi()
    w = FileWatcher(api)
    _write_pending("creds", age=gui_mod.PENDING_VIEW_TTL + 10)
    w._check_pending_view()
    assert api.js == []
    assert not (paths.data_dir() / PENDING_VIEW_NAME).exists()


def test_watcher_drops_invalid_view():
    api = StubApi()
    w = FileWatcher(api)
    _write_pending("evil")                    # 白名单外
    w._check_pending_view()
    assert api.js == []
    assert not (paths.data_dir() / PENDING_VIEW_NAME).exists()


def test_watcher_drops_nondict_json():
    api = StubApi()
    w = FileWatcher(api)
    p = paths.data_dir() / PENDING_VIEW_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("42", encoding="utf-8")     # 合法 JSON 但不是对象
    w._check_pending_view()
    assert api.js == []
    assert not p.exists()
