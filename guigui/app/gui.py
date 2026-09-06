"""pywebview 壳 — 窗口 / js_api / deep link / 文件监视器 / 单实例。

- 560×640 无边框;拖拽只认前端 ``pywebview-drag-region`` 类(标题行,create_window
  传 easy_drag=False;pywebview 默认 True = 整窗任意位置可拖,2026-08-31 实测踩坑)。
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
PENDING_VIEW_NAME = "pending_view.json"   # 深链二实例 → 主实例的接力文件
PENDING_VIEW_TTL = 120.0                  # 超龄视为残留,静默丢弃
# 无边框方案(2026-08-31 二次拍板:原生窗口试用后回到无边框自绘):
# SetWindowRgn 裁圆角,半径 8 CSS px × DPI —— 对齐 Win11 系统圆角观感(原 22px 已弃)。
# WinForms+WebView2 做不到真透明(transparent=True 四角露白),配方详见契约「集成待办」。
CORNER_CSS_PX = 8                  # Win11 系统窗口圆角规格(非 CSS 卡片 token)
# 取卡片浅底(≈ .window 渐变的浅紫),兜首帧闪色与弧线亚像素缝隙;
# 深色会在浅色卡片的角落露楔形(2026-08-31 实机踩坑)
SHELL_BG = "#e9e7f2"
WINDOW_TITLE = "桂桂 / GuiGui"

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
                self._check_pending_view()
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

    def _check_pending_view(self) -> None:
        """深链转发文件:消费即删;过期/白名单外静默丢弃。"""
        import time as _time

        p = paths.data_dir() / PENDING_VIEW_NAME
        try:
            if not p.exists():
                return
            raw = p.read_text(encoding="utf-8")
            p.unlink()
        except OSError:
            return
        try:
            item = json.loads(raw)
            view = item.get("view")
            fresh = _time.time() - float(item.get("ts") or 0) <= PENDING_VIEW_TTL
        except (ValueError, TypeError, AttributeError):
            return
        if fresh and view in ("main", "creds", "settings"):
            # 与冷启动同一条路:壳注入 __guigui_launch → applyLaunch 消费
            self.api._eval(
                f"window.__guigui_launch={json.dumps(view)};"
                "applyLaunch&&applyLaunch()")


def _inject_launch(window, view: str) -> None:
    try:
        window.evaluate_js(f"window.__guigui_launch = {json.dumps(view)}")
    except Exception as e:
        log.warning("deep link 注入失败: %s", e)


def _activate_existing_window() -> None:
    """把已在跑的桂桂窗口拉到前台(深链二实例用);失败只记日志。"""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if hwnd:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)          # SW_RESTORE
            if not user32.SetForegroundWindow(hwnd):
                log.info("gui: 前台切换被系统拒绝(仅任务栏闪烁),视图仍会经深链生效")
    except Exception as e:
        log.warning("gui: 激活已有窗口失败: %s", e)


def _forward_deep_link(view: str) -> None:
    """单实例抢锁失败时的深链转发:pending 文件 + 激活旧窗口。

    主实例 FileWatcher 2s 轮询消费 pending 文件并注入 applyLaunch;
    带 ts 是为了丢弃「GUI 关闭前没消费完」的隔夜残留。"""
    import time as _time

    try:
        p = paths.data_dir() / PENDING_VIEW_NAME
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"view": view, "ts": _time.time()}),
                     encoding="utf-8")
    except OSError as e:
        log.warning("gui: 深链转发落盘失败: %s", e)
    _activate_existing_window()


def _apply_rounded_region(window):
    """窗口裁成圆角:半径 = 8 CSS px × DPI 缩放(devshell._apply_rounded_region 同款)。

    shadow 必须为 False —— pywebview 的 DWM 阴影 hack 会在圆角外铺白边(前端实测);
    任一步失败只记日志,窗口退化为直角(不影响功能)。
    同参短路:窗口区域只由宽高/DPI 决定,与位置无关;SetWindowRgn(bRedraw=True)
    是全窗强制重绘 + DWM 重算,而拖动时 LocationChanged 每帧触发,不短路就
    每帧全窗重绘 —— WebView2 大表面上就是拖动卡顿的根因(2026-09-06 定位)。
    """
    try:
        import ctypes

        form = window.native
        hwnd = form.Handle.ToInt64()
        user32 = ctypes.windll.user32
        scale = (user32.GetDpiForWindow(hwnd) or 96) / 96.0
        r = int(round(CORNER_CSS_PX * scale))
        w, h = form.ClientSize.Width, form.ClientSize.Height
        if getattr(_apply_rounded_region, "_last", None) == (w, h, r):
            return
        hrgn = ctypes.windll.gdi32.CreateRoundRectRgn(
            0, 0, w + 1, h + 1, r * 2, r * 2)
        if user32.SetWindowRgn(hwnd, hrgn, True):
            _apply_rounded_region._last = (w, h, r)  # 只记成功,失败留给 keeper 下轮
        else:
            # 成功后 region 归系统;失败必须自删,keeper 每 1.5s 重贴会累积泄漏
            ctypes.windll.gdi32.DeleteObject(hrgn)
    except Exception as e:
        log.warning("gui: 圆角裁剪失败(退化为直角): %s", e)


def _hook_region_trackers(window) -> None:
    """把圆角重贴挂到 WinForms 窗体的 Resize / LocationChanged 上。

    跨屏拖动变 DPI 时系统会重算 ClientSize(125%↔150%),只在 before_show
    贴一次的圆角区会和客户区脱节 —— 底部露一条壳底色带,页面卡片像被
    裁掉一截(2026-08-31 像素采样实测:WebView2 比窗口短 50px)。
    """
    try:
        form = window.native
        handler = lambda sender, args: _apply_rounded_region(window)
        form.Resize += handler
        form.LocationChanged += handler
    except Exception as e:
        log.warning("gui: 圆角跟踪事件挂载失败: %s", e)


def _start_region_keeper(window) -> None:
    """圆角区定时重贴(1.5s):窗体 DPI 定型的时序在 WinForms/WebView2 里
    不可靠(实测 before_show 时 ClientSize 还是中间值 682x752,定型到
    700x800 后 Resize 并不触发),事件挂钩只是加速,这道定时是收敛保证,
    兼容用户日后跨屏拖动变 DPI。"""
    stop = threading.Event()

    def keeper():
        import time

        while not stop.wait(1.5):
            try:
                _apply_rounded_region(window)
            except Exception:
                break  # 窗口销毁后退出

    threading.Thread(target=keeper, daemon=True, name="guigui-region-keeper").start()
    window.events.closed += stop.set


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
    --ensure 定时路径不做对齐(它本身靠已存在的任务触发,补建有鸡生蛋问题)。
    未完成首装(无学号或密码)时不建 —— 任务属于「开启每日自动登录」
    那一步(契约 §4 单行道),启动对齐只服务已配置用户。"""
    import time

    from guigui.core import selfheal, vault

    time.sleep(1.5)
    try:
        cfg = config_mod.load()
        if not cfg.get("uid") or not vault.has_password(cfg["uid"]):
            return
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
        if view:
            _forward_deep_link(view)   # 通知点击落到已开的 GUI 时不再石沉大海
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
            WINDOW_TITLE, str(index), js_api=api,
            width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], min_size=WINDOW_SIZE,
            frameless=True, resizable=False,
            shadow=False,               # DWM 阴影 hack 在圆角外铺白边,禁用(契约集成票)
            background_color=SHELL_BG,
            easy_drag=False)            # 只许标题行拖窗(.pywebview-drag-region);默认 True 是全局拖
    except TypeError:  # 旧版 pywebview 参数差异兜底
        window = webview.create_window(
            WINDOW_TITLE, str(index), js_api=api,
            width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], resizable=False,
            easy_drag=False)
    api.attach_window(window)

    def _on_before_show():
        _apply_rounded_region(window)
        # native 在 webview.start() 后才存在,事件挂钩必须等窗体诞生(挂早了
        # window.native=None,Resize 永远追不上 DPI 定型后的最终尺寸)
        _hook_region_trackers(window)
        _start_region_keeper(window)

    window.events.before_show += _on_before_show
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
