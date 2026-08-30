"""桂桂入口 — 三种形态:

- ``guigui --ensure``       静默短进程(任务计划触发,不加载 GUI 依赖)
- ``guigui guigui://view``  通知/快捷方式 deep link → GUI 并跳指定视图
- ``guigui``                GUI

兼容「作为脚本直接启动」(协议命令把本文件当入口):补 sys.path 后再导入包。
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # python guigui\__main__.py 场景
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from guigui.core import logsetup


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logsetup.setup()

    if "--ensure" in argv:
        from guigui.core import ensure
        return ensure.run()

    deep = next((a for a in argv if a.startswith("guigui://")), None)
    view = deep.split("guigui://", 1)[1].strip("/ ").lower() or None if deep else None
    if view not in (None, "main", "creds", "settings"):
        view = None
    from guigui.app import gui  # 延迟导入:--ensure 路径不碰 GUI 依赖
    return gui.run(view)


if __name__ == "__main__":
    raise SystemExit(main())
