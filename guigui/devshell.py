"""桂桂前端开发壳(仅开发用,不进打包)。

以 pywebview(WebView2)加载 app/static,验证无边框窗口下的
圆角/字体/拖拽保真;数据走 dev/mock.js(?dev=1 开发开关),窗口控制为真。

窗口圆角/SetWindowRgn 裁剪/壳底色三者必须与正式壳 gui.py 同参 —— devshell 带
js_api,app.js 会挂 html.in-app(CSS 卡片弧随之变 9px);曾停留在原型配方
(裁剪 22px + 深墨紫底色)时,in-app 卡片弧 9px 远小于裁剪弧 22px,四角
露出深底色月牙 = 黑角(2026-09-06 实码定位,db6947f 引入 9px 后失配)。
用法:python guigui/devshell.py [scene]   scene 见 static/dev/mock.js 头部(默认 ok);
      状态画廊(9 视图×全状态陈列+故事流程)走浏览器:
      cd guigui/app/static && python -m http.server 8000 → /dev/state-gallery.html
"""
import ctypes
import functools
import http.server
import pathlib
import socketserver
import sys
import threading

import webview

ROOT = pathlib.Path(__file__).parent / "app" / "static"
CORNER_CSS_PX = 8   # 与 gui.py 同款:Win11 系统窗口圆角;CSS 卡片 9px 必须盖过此弧


class _NoCache(http.server.SimpleHTTPRequestHandler):
    """开发壳禁缓存 —— 改前端文件刷新即生效(生产不走 HTTP,无此问题)"""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, *args):
        pass


def _apply_rounded_region():
    """Win10 兜底:窗口裁成圆角,半径 = 8 CSS px × DPI 缩放(gui.py 同款;in-app 卡片弧 9px 盖过此弧)。
    注意 shadow 必须为 False —— pywebview 的 DWM 阴影 hack 会在圆角外铺白边(实测);
    background_color 取卡片浅底,兜圆角弧线与 CSS 卡片弧线间的亚像素缝隙。"""
    w = webview.windows[0]
    form = w.native
    hwnd = form.Handle.ToInt64()
    user32 = ctypes.windll.user32
    scale = (user32.GetDpiForWindow(hwnd) or 96) / 96.0
    r = int(round(CORNER_CSS_PX * scale))
    hrgn = ctypes.windll.gdi32.CreateRoundRectRgn(
        0, 0, form.ClientSize.Width + 1, form.ClientSize.Height + 1, r * 2, r * 2
    )
    user32.SetWindowRgn(hwnd, hrgn, True)


def _apply_rounded_corners() -> bool:
    """Win11+:DWM 系统圆角(抗锯齿、DPI 自适应,gui.py 同款);失败(Win10)回退 rgn 裁剪。"""
    w = webview.windows[0]
    try:
        from ctypes import wintypes

        v = ctypes.c_int(2)  # DWMWCP_ROUND
        hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(w.native.Handle.ToInt64()),
            33, ctypes.byref(v), ctypes.sizeof(v))  # DWMWA_WINDOW_CORNER_PREFERENCE
        return hr == 0
    except Exception:
        return False


def apply_corners():
    """before_show/restored 共用入口:DWM 成功即免维护,失败走 rgn(rgn 重贴幂等)。"""
    if not _apply_rounded_corners():
        _apply_rounded_region()


class Shell:
    """js_api:只提供窗口控制(契约 2.11);数据方法缺失时适配器按 dev 规则回落 mock"""

    def winMinimize(self):
        webview.windows[0].minimize()

    def winClose(self):
        webview.windows[0].destroy()


def main():
    scene = sys.argv[1] if len(sys.argv) > 1 else "ok"
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(
        ("127.0.0.1", 0), functools.partial(_NoCache, directory=str(ROOT))
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:{}/index.html?dev=1&scene={}".format(
        srv.server_address[1], scene
    )
    win = webview.create_window(
        "桂桂 / GuiGui",
        url,
        js_api=Shell(),
        width=560,
        height=640,
        min_size=(560, 640),
        frameless=True,
        resizable=False,
        shadow=False,                # DWM 阴影 hack 会铺白边,禁用(见 _apply_rounded_region 注释)
        background_color="#e9e7f2",  # gui.py SHELL_BG 同款:卡片浅紫,兜弧线亚像素缝隙(深色会在四角露黑月牙)
        easy_drag=False,             # 与正式壳同款:只许标题行拖窗(.pywebview-drag-region)
    )
    win.events.before_show += apply_corners
    win.events.restored += apply_corners  # rgn 兜底路径需要;DWM 路径幂等无害
    webview.start()
    srv.shutdown()


if __name__ == "__main__":
    main()
