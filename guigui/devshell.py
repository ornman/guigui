"""桂桂前端开发壳(仅开发用,不进打包)。

以 pywebview(WebView2)加载 app/static,验证无边框窗口下的
圆角/字体/拖拽保真;数据走 dev/mock.js(?dev=1 开发开关),窗口控制为真。

窗口圆角/SetWindowRgn 裁剪/壳底色三者必须与正式壳 gui.py 同参 —— devshell 带
js_api,app.js 会挂 html.in-app(CSS 卡片弧随之变 9px);曾停留在原型配方
(裁剪 22px + 深墨紫底色)时,in-app 卡片弧 9px 远小于裁剪弧 22px,四角
露出深底色月牙 = 黑角(2026-09-06 实码定位,db6947f 引入 9px 后失配)。
用法:python guigui/devshell.py [scene]   scene ∈ ok|out|down|waiting|daily|rejected(默认 ok)
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
    """窗口裁成圆角:半径 = 8 CSS px × DPI 缩放(gui.py 同款;in-app 卡片弧 9px 盖过此弧)。
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
    win.events.before_show += _apply_rounded_region
    win.events.restored += _apply_rounded_region  # 最小化还原后重挂,保险
    webview.start()
    srv.shutdown()


if __name__ == "__main__":
    main()
