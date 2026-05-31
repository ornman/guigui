"""SchoolAutoLogin — campus network auto-login."""

import logging
import sys
import time

log = logging.getLogger(__name__)


def run_silent():
    """Headless login for scheduled tasks."""
    from src import config, wifi
    from src import login as login_mod
    from src import notify

    cfg = config.load()
    log.info("=== Auto-login started ===")

    # Step 1: Ensure Wi-Fi
    if cfg.get("wifi_ssid"):
        if not wifi.connect(cfg["wifi_ssid"]):
            log.warning("Wi-Fi connect failed, will still try login...")

    # Step 2: Wait for network (up to 120s)
    if not login_mod.wait_for_network():
        log.error("Network unavailable after waiting 120s")
        notify.send("校园网登录失败", "网络不可用，请检查连接")
        sys.exit(1)

    # Step 3: Check if already logged in
    try:
        if login_mod.is_logged_in():
            log.info("Already logged in, nothing to do.")
            log.info("=== Done ===")
            notify.send("校园网", "已登录，无需操作")
            return
    except Exception as e:
        log.error("Cannot check login status: %s", e)

    # Step 4: Login with retries
    retries = cfg.get("max_retries", 3)
    interval = cfg.get("retry_interval_seconds", 5)
    for i in range(1, retries + 1):
        try:
            log.info("Attempt %d/%d", i, retries)
            if login_mod.do_login(cfg):
                log.info("=== Done (success) ===")
                notify.send("校园网登录成功", "已连接网络")
                return
        except Exception as e:
            log.error("Attempt %d error: %s", i, e)
        if i < retries:
            log.info("Retrying in %ds...", interval)
            time.sleep(interval)

    log.error("=== Auto-login failed after all retries ===")
    notify.send("校园网登录失败", "重试次数已用完")
    sys.exit(1)


def main():
    if "--silent" in sys.argv:
        run_silent()
        return

    import customtkinter as ctk
    ctk.set_appearance_mode("dark")

    from src.app import App
    App().mainloop()


if __name__ == "__main__":
    main()
