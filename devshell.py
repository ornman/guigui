"""桂桂前端开发壳(仅开发用,不进打包)。

以 pywebview(WebView2)加载 guigui/app/static,验证无边框透明窗口下的
圆角/阴影/字体/拖拽保真;数据走 dev/mock.js(?dev=1 开发开关),窗口控制为真。

用法:python devshell.py [scene]   scene ∈ ok|out|down|waiting|daily|rejected(默认 ok)
"""
import functools
import http.server
import pathlib
import socketserver
import sys
import threading

import webview

ROOT = pathlib.Path(__file__).parent / "guigui" / "app" / "static"


class _NoCache(http.server.SimpleHTTPRequestHandler):
    """开发壳禁缓存 —— 改前端文件刷新即生效(生产不走 HTTP,无此问题)"""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, *args):
        pass


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
    webview.create_window(
        "桂桂 / GuiGui",
        url,
        js_api=Shell(),
        width=560,
        height=640,
        min_size=(560, 640),
        frameless=True,
        transparent=True,
        resizable=False,
    )
    webview.start()
    srv.shutdown()


if __name__ == "__main__":
    main()
