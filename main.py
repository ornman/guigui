"""SchoolAutoLogin — campus network auto-login."""

import sys


def run_silent():
    """Headless login for scheduled tasks."""
    from src import config, wifi
    from src import login as login_mod
    from src import notify

    cfg = config.load()

    if cfg.get("wifi_ssid"):
        wifi.connect(cfg["wifi_ssid"])

    if login_mod.is_logged_in():
        notify.send("校园网", "已登录，无需操作")
        return

    retries = cfg.get("max_retries", 3)
    interval = cfg.get("retry_interval_seconds", 5)
    import time
    for i in range(1, retries + 1):
        if login_mod.do_login(cfg):
            notify.send("校园网登录成功", "已连接网络")
            return
        if i < retries:
            time.sleep(interval)

    notify.send("校园网登录失败", "重试次数已用完")


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
