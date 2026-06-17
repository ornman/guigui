"""SchoolAutoLogin — 校园网自动登录工具。"""

import logging
import sys

log = logging.getLogger(__name__)


def main():
    """程序入口：``--ensure`` 静默执行 / 否则 GUI。

    ``--ensure`` 是唯一的静默执行入口（由窗口任务/巡逻/AtLogon 调用），
    做幂等登录（含 WiFi 兜底）与状态翻转通知，绝不拉起 GUI。
    其余启动一律进入 GUI（设置前端 + 手动登录）。
    """
    if "--ensure" in sys.argv:
        from src import ensure
        try:
            sys.exit(ensure.run())
        except Exception:
            log.exception("Ensure mode crashed")
            sys.exit(1)
        return

    # GUI 模式：单实例守卫
    from src.instance import SingleInstance
    si = SingleInstance()
    if not si.acquire():
        log.info("已有实例运行，退出")
        return
    try:
        import customtkinter as ctk
        ctk.set_appearance_mode("dark")
        from src.app import App
        App().mainloop()
    finally:
        si.release()


if __name__ == "__main__":
    main()
