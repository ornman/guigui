"""数据目录解析。

- 生产:%LOCALAPPDATA%\\GuiGui(Inno 装进 Program Files 后 exe 目录不可写)。
- 测试/便携:环境变量 GUIGUI_DATA_DIR 覆盖(每次调用时读取,便于注入)。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_APP_DIR_NAME = "GuiGui"
_STATIC_OVERRIDE_ENV = "GUIGUI_STATIC_DIR"


def data_dir() -> Path:
    override = os.environ.get("GUIGUI_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / _APP_DIR_NAME


def config_path() -> Path:
    return data_dir() / "config_v2.json"


def state_path() -> Path:
    return data_dir() / "ensure_state.json"


def logs_dir() -> Path:
    return data_dir() / "logs"


def run_log_path() -> Path:
    """工程运行日志(排查用,不进 GUI)。"""
    return data_dir() / "guigui.log"


def static_dir() -> Path:
    """前端静态目录(app/static 由前端拥有,后端只读)。

    dev:包内源码目录;frozen:PyInstaller datas 落在 _MEIPASS 同相对位置。
    GUIGUI_STATIC_DIR 可覆盖(联调指向别处)。
    """
    override = os.environ.get(_STATIC_OVERRIDE_ENV)
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return meipass / "guigui" / "app" / "static"
    return Path(__file__).resolve().parent.parent / "app" / "static"
