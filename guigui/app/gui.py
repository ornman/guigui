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
# 无边框方案(2026-08-31 二次拍板:原生窗口试用后回到无边框自绘):
# SetWindowRgn 裁圆角,半径 8 CSS px × DPI —— 对齐 Win11 系统圆角观感(原 22px 已弃)。
# WinForms+WebView2 做不到真透明(transparent=True 四角露白),配方详见契约「集成待办」。
CORNER_CSS_PX = 8                  # Win11 系统窗口圆角规格(非 CSS 卡片 token)
SHELL_BG = "#2b2740"               # ≈ 前端 --ink,兜圆角弧线与 CSS 间的亚像素缝隙

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


def _apply_rounded_region(window):
    """窗口裁成圆角:半径 = 8 CSS px × DPI 缩放(devshell._apply_rounded_region 同款)。

    shadow 必须为 False —— pywebview 的 DWM 阴影 hack 会在圆角外铺白边(前端实测);
    任一步失败只记日志,窗口退化为直角(不影响功能)。
    """
    try:
        import ctypes

        form = window.native
        hwnd = form.Handle.ToInt64()
        user32 = ctypes.windll.user32
        scale = (user32.GetDpiForWindow(hwnd) or 96) / 96.0
        r = int(round(CORNER_CSS_PX * scale))
        hrgn = ctypes.windll.gdi32.CreateRoundRectRgn(
            0, 0, form.ClientSize.Width + 1, form.ClientSize.Height + 1, r * 2, r * 2)
        user32.SetWindowRgn(hwnd, hrgn, True)
    except Exception as e:
        log.warning("gui: 圆角裁剪失败(退化为直角): %s", e)


def _missing_static_dialog() -> None:
    """前端资源缺失时的原生提示(正常发布不该走到这里)。"""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0, "前端资源缺失(app/static),请重新安装桂桂。", "桂桂", 0x10)
    except Exception:
        pass


def _reconcile_on_start() -> None:
    """启动后台对齐:上次会话任务若缺失/失配(如曾被安全软件拦),打开即补。

    挂后台延迟跑,不挡首屏;失败时与保存路径同款 toast 指引。
    --ensure 定时路径不做对齐(它本身靠已存在的任务触发,补建有鸡生蛋问题)。"""
    import time

    from guigui.core import selfheal

    time.sleep(1.5)
    try:
        cfg = config_mod.load()
        _, misaligned = selfheal.reconcile(cfg)
    except Exception:
        log.exception("gui: 启动对齐失败")
        return
    if misaligned and cfg.get("master", True):
        notify_mod.task_blocked()


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
            "桂桂 / GuiGui", str(index), js_api=api,
            width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], min_size=WINDOW_SIZE,
            frameless=True, resizable=False,
            shadow=False,               # DWM 阴影 hack 在圆角外铺白边,禁用(契约集成票)
            background_color=SHELL_BG)
    except TypeError:  # 旧版 pywebview 参数差异兜底
        window = webview.create_window(
            "桂桂 / GuiGui", str(index), js_api=api,
            width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], resizable=False)
    api.attach_window(window)
    window.events.before_show += lambda: _apply_rounded_region(window)
    window.events.restored += lambda: _apply_rounded_region(window)  # 最小化还原后重挂,保险

    if view:
        window.events.loaded += lambda: _inject_launch(window, view)

    watcher = FileWatcher(api)
    watcher.start()
    threading.Thread(target=_reconcile_on_start, daemon=True).start()
    try:
        webview.start()
    finally:
        watcher.stop()
        lock.release()
    return 0
