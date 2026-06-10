"""SchoolAutoLogin — 校园网自动登录工具。"""

import logging
import subprocess
import sys

log = logging.getLogger(__name__)


def run_silent():
    """静默登录模式（无窗口），用于定时任务。

    加载配置后尝试登录，根据结果发送桌面通知。
    登录失败时以 exit code 1 退出，供任务计划程序判断状态。
    """
    from src import config
    from src import login as login_mod
    from src import notify

    cfg = config.load()
    log.info("=== Auto-login started ===")

    result = login_mod.attempt_login(cfg)

    if result == "already_logged_in":
        log.info("Already logged in, nothing to do.")
        notify.send("校园网", "已登录，无需操作")
    elif result == "success":
        log.info("=== Done (success) ===")
        notify.send("校园网登录成功", "已连接网络")
    elif result == "unreachable":
        log.error("Network unavailable")
        notify.send("校园网登录失败", "网络不可用，请检查连接")
        sys.exit(1)
    else:  # "failed"
        log.error("=== Auto-login failed after all retries ===")
        notify.send("校园网登录失败", "重试次数已用完")
        sys.exit(1)

    log.info("=== Done ===")


def main():
    """程序入口：``--silent`` 走静默登录，否则启动 GUI 主窗口。"""
    if "--silent" in sys.argv:
        try:
            run_silent()
        except SystemExit:
            raise
        except Exception as e:
            log.exception("Silent mode crashed")
            # 过滤 PowerShell 元字符，防止注入
            import re
            safe_msg = re.sub(r'''['"$`()]''', '', str(e))[:200]
            subprocess.run([
                "powershell", "-Command",
                f'[System.Windows.Forms.MessageBox]::Show('
                f'"校园网自动登录失败：{safe_msg}", "SchoolAutoLogin")',
            ], timeout=10)
        return

    import customtkinter as ctk
    ctk.set_appearance_mode("dark")

    from src.app import App
    App().mainloop()


if __name__ == "__main__":
    main()
