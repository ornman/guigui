"""工程运行日志初始化(RotatingFileHandler)。

与 v1 不同,日志初始化不再藏在协议模块的 import 副作用里:
由入口(__main__ / gui)显式调用,幂等。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from . import paths


def setup() -> None:
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) and h.baseFilename.endswith("guigui.log")
           for h in root.handlers):
        return
    root.setLevel(logging.INFO)
    p = paths.run_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(str(p), maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    root.addHandler(fh)
