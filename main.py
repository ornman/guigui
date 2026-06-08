"""SchoolAutoLogin — campus network auto-login."""

import logging
import subprocess
import sys

log = logging.getLogger(__name__)


def run_silent():
    """Headless login for scheduled tasks."""
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
    if "--silent" in sys.argv:
        try:
            run_silent()
        except SystemExit:
            raise
        except Exception as e:
            log.exception("Silent mode crashed")
            # Strip PowerShell metacharacters to prevent injection
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
