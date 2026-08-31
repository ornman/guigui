"""桂桂前端开发壳(仅开发用,不进打包)。

以 pywebview(WebView2)加载 guigui/app/static,验证无边框窗口下的
圆角/字体/拖拽保真;数据走 dev/mock.js(?dev=1 开发开关),窗口控制为真。

窗口圆角:SetWindowRgn 裁剪(实测 WinForms+WebView2 做不到真透明,
transparent=True 只透到窗体底色,四角露白;配方详见契约「集成待办」)。
用法:python devshell.py [scene]   scene ∈ ok|out|down|waiting|daily|rejected(默认 ok)
"""
import ctypes
import functools
import http.server
import pathlib
import socketserver
import sys
import threading

import webview

ROOT = pathlib.Path(__file__).parent / "guigui" / "app" / "static"
CORNER_CSS_PX = 22  # 设计 token:卡片圆角(PRD 原型 .window border-radius)


class _NoCache(http.server.SimpleHTTPRequestHandler):
    """开发壳禁缓存 —— 改前端文件刷新即生效(生产不走 HTTP,无此问题)"""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, *args):
        pass


def _apply_rounded_region():
    """窗口裁成圆角:半径 = 22 CSS px × DPI 缩放。
    注意 shadow 必须为 False —— pywebview 的 DWM 阴影 hack 会在圆角外铺白边(实测);
    background_color 取 --ink 深色,兜圆角弧线与 CSS 卡片弧线间的亚像素缝隙。"""
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
        background_color="#2b2740",  # ≈ --ink,兜圆角弧线亚像素缝隙
    )
    win.events.before_show += _apply_rounded_region
    win.events.restored += _apply_rounded_region  # 最小化还原后重挂,保险
    webview.start()
    srv.shutdown()


if __name__ == "__main__":
    main()
