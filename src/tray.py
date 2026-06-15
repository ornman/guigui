"""系统托盘：pystray + Pillow。状态驱动图标 + 右键菜单。

UI 更新由调用方驱动（update_state）；本模块不直接访问 GUI 线程。
"""

import logging

from PIL import Image, ImageDraw
import pystray

log = logging.getLogger(__name__)

ACCENT = (124, 58, 237, 255)   # #7c3aed
MUTED = (68, 68, 68, 255)      # #444444

_LABELS = {"connected": "已连接", "disconnected": "断网", "busy": "登录中…", "idle": "待命"}


def state_label(state: str) -> str:
    return _LABELS.get(state, "未知")


def icon_color(state: str):
    return MUTED if state == "disconnected" else ACCENT


def _make_icon(color) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle([10, 10, 54, 54], fill=color)
    return img


class Tray:
    """托盘控制器。回调：on_show / on_login / on_quit；get_state 返回当前状态字符串。"""

    def __init__(self, on_show, on_login, on_quit, get_state):
        self._on_show = on_show
        self._on_login = on_login
        self._on_quit = on_quit
        self._get_state = get_state
        self._icon: pystray.Icon | None = None

    def _menu(self):
        return pystray.Menu(
            pystray.MenuItem("打开主界面", lambda *_: self._on_show(), default=True),
            pystray.MenuItem("立即登录", lambda *_: self._on_login()),
            pystray.MenuItem(lambda _: f"状态：{state_label(self._get_state())}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda *_: self._on_quit()),
        )

    def start(self):
        """阻塞运行（请在 daemon 线程里调用）。"""
        self._icon = pystray.Icon("SchoolAutoLogin", _make_icon(ACCENT),
                                  "SchoolAutoLogin", self._menu())
        self._icon.run()

    def stop(self):
        if self._icon:
            self._icon.stop()
            self._icon = None

    def update_state(self, state: str):
        if self._icon:
            self._icon.icon = _make_icon(icon_color(state))
            self._icon.update_menu()
