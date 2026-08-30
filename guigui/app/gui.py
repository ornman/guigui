"""pywebview 壳 — 窗口 / js_api / deep link / 文件监视器 / 单实例。

- 560×640 无边框;拖拽交给前端 ``pywebview-drag`` 类(easy_drag=False)。
- FileWatcher:2s mtime 轮询数据目录三个文件,把外部 --ensure 进程的落盘
  翻译成契约事件(net:state / log:appended / schedule:changed),诚实边界
  为 ≤2s 延迟(技术方案 §6)。
- deep link:启动参数 guigui://view → loaded 后注入 window.__guigui_launch
  (形状未入契约,已登记集成待办)。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading

from guigui.core import ensure, logstore, paths
from guigui.core import config as config_mod
from guigui.core import notify as notify_mod

from .api import GuiGuiApi

log = logging.getLogger(__name__)

WINDOW_SIZE = (560, 640)
WATCH_INTERVAL = 2.0
BG_COLOR = "#f4f2f7"   # 接近前端底色;真透明 WebView2 不稳定,伪透明按前端烘焙

_STATE2NET = {"up": "logged_in", "down": "unreachable", "failed": "not_logged_in"}


class FileWatcher(threading.Thread):
    """数据目录 mtime 监视 → 契约事件(外部 ensure 与 GUI 的唯一会话通道)。"""

    def __init__(self, api: GuiGuiApi):
        super().__init__(daemon=True, name="guigui-filewatcher")
        self.api = api
        self._stop = threading.Event()
        self._seen: dict[str, object] = {}
        self._today_lines = 0

    def run(self) -> None:
        self._prime()
        while not self._stop.wait(WATCH_INTERVAL):
            try:
                self._check_config()
                self._check_state()
                self._check_today_log()
            except Exception:
                log.exception("FileWatcher 轮询异常(继续)")

    def stop(self) -> None:
        self._stop.set()

    # ── 内部 ──────────────────────────────────────

    def _mtime(self, path):
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return None

    def _prime(self) -> None:
        """首圈只记基线,不回放历史事件。"""
        self._seen["config"] = self._mtime(paths.config_path())
        self._seen["state"] = self._mtime(paths.state_path())
        today = logstore.read_day(dt.date.today())
        self._today_lines = len(today)

    def _check_config(self) -> None:
        m = self._mtime(paths.config_path())
        if m is not None and m != self._seen.get("config"):
            self._seen["config"] = m
            cfg = config_mod.load()
            self.api._emit("schedule:changed",
                           {"master": cfg.get("master", True),
                            "trigger_time": cfg.get("trigger_time", "07:00")})

    def _check_state(self) -> None:
        m = self._mtime(paths.state_path())
        if m is not None and m != self._seen.get("state"):
            self._seen["state"] = m
            state = ensure.load_state()
            net_state = _STATE2NET.get(state.get("last_net_state"))
            if net_state:
                from guigui.core import wifictl
                self.api._emit("net:state", {"state": net_state,
                                             "ssid": wifictl.current_ssid()})

    def _check_today_log(self) -> None:
        entries = logstore.read_day(dt.date.today())
        if len(entries) > self._today_lines:
            for entry in entries[self._today_lines:]:
                self.api._emit("log:appended", {"day_label": "今天", "entry": entry})
        self._today_lines = len(entries)


def _inject_launch(window, view: str) -> None:
    try:
        window.evaluate_js(f"window.__guigui_launch = {json.dumps(view)}")
    except Exception as e:
        log.warning("deep link 注入失败: %s", e)


def _missing_static_dialog() -> None:
    """前端资源缺失时的原生提示(正常发布不该走到这里)。"""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0, "前端资源缺失(app/static),请重新安装桂桂。", "桂桂", 0x10)
    except Exception:
        pass


def run(view: str | None = None) -> int:
    """启动 GUI;返回进程退出码。重复启动直接退出(单实例)。"""
    import webview

    from . import instance

    lock = instance.SingleInstance()
    if not lock.acquire():
        log.info("gui: 已有实例在跑,本次启动退出")
        return 0
    notify_mod.register_protocol()   # 幂等:guigui:// 唤回通道

    index = paths.static_dir() / "index.html"
    if not index.exists():
        log.error("gui: 找不到前端 %s", index)
        _missing_static_dialog()
        lock.release()
        return 1

    api = GuiGuiApi()
    try:
        window = webview.create_window(
            "桂桂", str(index), js_api=api,
            width=WINDOW_SIZE[0], height=WINDOW_SIZE[1],
            resizable=False, frameless=True, easy_drag=False,
            background_color=BG_COLOR)
    except TypeError:  # 旧版 pywebview 参数差异兜底
        window = webview.create_window(
            "桂桂", str(index), js_api=api,
            width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], resizable=False)
    api.attach_window(window)

    if view:
        window.events.loaded += lambda: _inject_launch(window, view)

    watcher = FileWatcher(api)
    watcher.start()
    try:
        webview.start()
    finally:
        watcher.stop()
        lock.release()
    return 0
