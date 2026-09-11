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


# ── 1.6.0 open_route 深链(契约 §4)────────────────────────


def _write_pending_route(open_route, age=0.0):
    p = paths.data_dir() / PENDING_VIEW_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"open_route": open_route, "ts": time.time() - age}),
                 encoding="utf-8")
    return p


def test_forward_deep_link_writes_open_route(monkeypatch):
    monkeypatch.setattr(gui_mod, "_activate_existing_window", lambda: None)
    _forward_deep_link(None, "v-feedback")
    item = json.loads((paths.data_dir() / PENDING_VIEW_NAME)
                      .read_text(encoding="utf-8"))
    assert item["open_route"] == "v-feedback"
    assert "view" not in item                     # 纯 open_route 不占 view 字段


def test_forward_deep_link_writes_view_and_route(monkeypatch):
    monkeypatch.setattr(gui_mod, "_activate_existing_window", lambda: None)
    _forward_deep_link("creds", "v-form")
    item = json.loads((paths.data_dir() / PENDING_VIEW_NAME)
                      .read_text(encoding="utf-8"))
    assert item["view"] == "creds" and item["open_route"] == "v-form"


def test_watcher_consumes_pending_open_route():
    api = StubApi()
    w = FileWatcher(api)
    _write_pending_route("v-form")
    w._check_pending_view()
    assert not (paths.data_dir() / PENDING_VIEW_NAME).exists()
    assert any(kind == "eval" and "v-form" in js and "applyLaunch" in js
               for kind, js in api.js)


def test_watcher_drops_unknown_open_route():
    api = StubApi()
    w = FileWatcher(api)
    _write_pending_route("v-hack")            # 白名单外
    w._check_pending_view()
    assert api.js == []
    assert not (paths.data_dir() / PENDING_VIEW_NAME).exists()


def test_inject_launch_object_shape():
    captured = []

    class W:
        def evaluate_js(self, js):
            captured.append(js)

    gui_mod._inject_launch(W(), "creds", "v-status")
    assert captured == ['window.__guigui_launch = {"view": "creds",'
                        ' "open_route": "v-status"}']
    gui_mod._inject_launch(W(), None, "v-status")
    assert captured[-1] == 'window.__guigui_launch = {"open_route": "v-status"}'
    gui_mod._inject_launch(W(), None, None)   # 两项皆空:不注入
    assert len(captured) == 2


# ── __main__ 启动参数解析(open_route 透传)────────────────


def _patch_gui_run(monkeypatch, called):
    from guigui.app import gui
    monkeypatch.setattr(
        gui, "run",
        lambda view=None, open_route=None:
            called.update(view=view, open_route=open_route) or 0)


def test_main_deep_link_v_route_becomes_open_route(monkeypatch):
    import guigui.__main__ as m
    called = {}
    _patch_gui_run(monkeypatch, called)
    m.main(["guigui://v-form"])
    assert called == {"view": None, "open_route": "v-form"}


def test_main_open_route_flag(monkeypatch):
    import guigui.__main__ as m
    called = {}
    _patch_gui_run(monkeypatch, called)
    m.main(["--open-route", "v-success"])
    assert called == {"view": None, "open_route": "v-success"}


def test_main_legacy_view_still_works(monkeypatch):
    import guigui.__main__ as m
    called = {}
    _patch_gui_run(monkeypatch, called)
    m.main(["guigui://creds"])
    assert called == {"view": "creds", "open_route": None}
    m.main([])                                  # 无深链:两者皆空
    assert called == {"view": None, "open_route": None}


def test_main_unknown_deep_link_dropped(monkeypatch):
    import guigui.__main__ as m
    called = {}
    _patch_gui_run(monkeypatch, called)
    m.main(["guigui://evil"])
    assert called == {"view": None, "open_route": None}
