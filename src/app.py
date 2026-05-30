"""SchoolAutoLogin — main application window."""

import threading

import customtkinter as ctk

from . import config, wifi
from . import login as login_mod
from . import notify
from .ui import theme as T
from .ui.components import BrutalButton, GlassCard, StatusDot


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SchoolAutoLogin")
        self.geometry(f"{T.WIN_W}x{T.WIN_H}")
        self.configure(fg_color=T.BG)
        self.resizable(False, False)

        self._cfg = config.load()
        self._build()
        self._fill_fields()

    # ── Build ────────────────────────────────────

    def _build(self):
        card = GlassCard(self)
        card.pack(fill="both", expand=True, padx=20, pady=20)
        self._card = card

        # Title
        ctk.CTkLabel(
            card, text="SchoolAutoLogin",
            font=T.F_TITLE, text_color=T.TEXT,
        ).pack(pady=(T.PAD, 2))
        ctk.CTkLabel(
            card, text="校园网自动登录",
            font=T.F_SMALL, text_color=T.TEXT_DIM,
        ).pack(pady=(0, T.PAD_SM))

        # Tabs
        self._build_tabs(card)

        # Content area
        self._content = ctk.CTkFrame(card, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=T.PAD)

        self._login_panel = self._build_login(self._content)
        self._settings_panel = self._build_settings(self._content)
        self._show_tab("login")

        # Status bar
        self._status = StatusDot(card, state="idle")
        self._status.pack(side="bottom", anchor="w",
                          padx=T.PAD, pady=(0, T.PAD))

    def _build_tabs(self, parent):
        bar = ctk.CTkFrame(parent, fg_color="transparent", height=36)
        bar.pack(fill="x", padx=T.PAD)

        self._tab_login = ctk.CTkButton(
            bar, text="登录", font=T.F_SECTION, width=80,
            fg_color="transparent", text_color=T.ACCENT,
            hover=False, corner_radius=0,
            command=lambda: self._show_tab("login"),
        )
        self._tab_login.pack(side="left", padx=(0, 8))

        self._tab_settings = ctk.CTkButton(
            bar, text="设置", font=T.F_SECTION, width=80,
            fg_color="transparent", text_color=T.TEXT_DIM,
            hover=False, corner_radius=0,
            command=lambda: self._show_tab("settings"),
        )
        self._tab_settings.pack(side="left", padx=(0, 8))

        ctk.CTkFrame(parent, fg_color=T.BORDER, height=1).pack(
            fill="x", padx=T.PAD)

    # ── Login panel ──────────────────────────────

    def _build_login(self, parent):
        p = ctk.CTkFrame(parent, fg_color="transparent")

        # Operator
        self._label(p, "运营商")
        self._op = ctk.CTkOptionMenu(
            p, values=list(T.OPERATORS),
            fg_color=T.SURFACE, button_color=T.ACCENT,
            button_hover_color=T.ACCENT_HOVER,
            text_color=T.TEXT, font=T.F_BODY, height=40,
            corner_radius=T.R_INPUT,
        )
        self._op.pack(fill="x", pady=(0, T.PAD_XS))

        # Username
        self._label(p, "学号")
        self._user = self._entry(p, placeholder="输入学号")

        # Password
        self._label(p, "密码")
        pw_row = ctk.CTkFrame(p, fg_color="transparent")
        pw_row.pack(fill="x", pady=(0, T.PAD_SM))

        self._pw = ctk.CTkEntry(
            pw_row, placeholder_text="输入密码", show="●",
            **self._entry_style(), height=40,
        )
        self._pw.pack(side="left", fill="x", expand=True)
        self._focus_border(self._pw)

        self._pw_toggle = ctk.CTkButton(
            pw_row, text="显示", width=50, height=40,
            fg_color=T.SURFACE, text_color=T.TEXT_DIM,
            font=T.F_SMALL, hover_color=T.BORDER,
            corner_radius=T.R_INPUT, command=self._toggle_pw,
        )
        self._pw_toggle.pack(side="right", padx=(8, 0))

        # Buttons
        self._btn_login = BrutalButton(
            p, text="立即登录", command=self._do_login)
        self._btn_login.pack(fill="x", pady=(T.PAD_XS, 8))

        self._btn_save = BrutalButton(
            p, text="保存配置", command=self._save, variant="secondary")
        self._btn_save.pack(fill="x")

        return p

    # ── Settings panel ───────────────────────────

    def _build_settings(self, parent):
        p = ctk.CTkFrame(parent, fg_color="transparent")

        # WiFi
        self._label(p, "校园网 WiFi 名称")
        self._wifi_entry = self._entry(p, placeholder="留空则跳过")

        # Polling
        self._sw_poll = self._switch(p, "断网自动重连")
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", pady=(0, T.PAD_SM), padx=(T.PAD, 0))
        ctk.CTkLabel(
            row, text="检测间隔（秒）",
            font=T.F_SMALL, text_color=T.TEXT_DIM,
        ).pack(side="left")
        self._poll_interval = ctk.CTkEntry(
            row, width=80, height=32,
            fg_color=T.BG, border_color=T.BORDER,
            text_color=T.TEXT, font=T.F_SMALL,
            corner_radius=T.R_INPUT,
        )
        self._poll_interval.pack(side="right")

        # Scheduled login
        self._sw_sched = self._switch(p, "定时登录")
        row2 = ctk.CTkFrame(p, fg_color="transparent")
        row2.pack(fill="x", pady=(0, T.PAD_SM), padx=(T.PAD, 0))
        ctk.CTkLabel(
            row2, text="执行时间（HH:MM）",
            font=T.F_SMALL, text_color=T.TEXT_DIM,
        ).pack(side="left")
        self._sched_time = ctk.CTkEntry(
            row2, width=80, height=32,
            fg_color=T.BG, border_color=T.BORDER,
            text_color=T.TEXT, font=T.F_SMALL,
            corner_radius=T.R_INPUT,
        )
        self._sched_time.pack(side="right")

        # Auto-start + notifications
        self._sw_autostart = self._switch(p, "开机自启")
        self._sw_notify = self._switch(p, "桌面通知")

        self._btn_apply = BrutalButton(
            p, text="应用设置", command=self._apply_settings)
        self._btn_apply.pack(fill="x", pady=(T.PAD_SM, 0))

        return p

    # ── Widget helpers ───────────────────────────

    def _label(self, parent, text: str):
        ctk.CTkLabel(
            parent, text=text,
            font=T.F_LABEL, text_color=T.TEXT_DIM,
        ).pack(anchor="w", pady=(T.PAD_XS, 4))

    def _entry_style(self) -> dict:
        return dict(
            fg_color=T.BG, border_color=T.BORDER,
            text_color=T.TEXT, placeholder_text_color=T.TEXT_DIM,
            font=T.F_BODY, corner_radius=T.R_INPUT,
        )

    def _entry(self, parent, placeholder: str = "") -> ctk.CTkEntry:
        e = ctk.CTkEntry(
            parent, placeholder_text=placeholder,
            **self._entry_style(), height=40,
        )
        e.pack(fill="x", pady=(0, T.PAD_XS))
        self._focus_border(e)
        return e

    def _switch(self, parent, label: str) -> ctk.CTkSwitch:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(
            row, text=label, font=T.F_BODY, text_color=T.TEXT,
        ).pack(side="left")
        sw = ctk.CTkSwitch(
            row, text="",
            button_color=T.ACCENT, button_hover_color=T.ACCENT_HOVER,
            progress_color=T.ACCENT, fg_color=T.BORDER,
        )
        sw.pack(side="right")
        return sw

    def _focus_border(self, entry: ctk.CTkEntry):
        entry.bind("<FocusIn>",
                    lambda _: entry.configure(border_color=T.ACCENT))
        entry.bind("<FocusOut>",
                    lambda _: entry.configure(border_color=T.BORDER))

    # ── Tab switching ────────────────────────────

    def _show_tab(self, name: str):
        self._login_panel.pack_forget()
        self._settings_panel.pack_forget()

        if name == "login":
            self._login_panel.pack(fill="both", expand=True)
            self._tab_login.configure(text_color=T.ACCENT)
            self._tab_settings.configure(text_color=T.TEXT_DIM)
        else:
            self._settings_panel.pack(fill="both", expand=True)
            self._tab_login.configure(text_color=T.TEXT_DIM)
            self._tab_settings.configure(text_color=T.ACCENT)

    # ── Form data ────────────────────────────────

    def _fill_fields(self):
        c = self._cfg
        self._op.set(c.get("operator", "中国电信"))
        self._user.insert(0, c.get("username", ""))
        self._pw.insert(0, c.get("password", ""))
        self._wifi_entry.insert(0, c.get("wifi_ssid", ""))
        self._poll_interval.insert(0,
                                    str(c.get("polling_interval_seconds", 30)))
        self._sched_time.insert(0,
                                 c.get("scheduled_login_time", "06:55"))
        if c.get("polling_enabled"):
            self._sw_poll.select()
        if c.get("scheduled_login_enabled"):
            self._sw_sched.select()
        if c.get("auto_start"):
            self._sw_autostart.select()
        if c.get("notification_enabled", True):
            self._sw_notify.select()

    def _read_form(self) -> dict:
        c = self._cfg
        c["operator"] = self._op.get()
        c["username"] = self._user.get()
        c["password"] = self._pw.get()
        c["wifi_ssid"] = self._wifi_entry.get()
        c["polling_enabled"] = self._sw_poll.get() == 1
        try:
            c["polling_interval_seconds"] = int(
                self._poll_interval.get() or "30")
        except ValueError:
            c["polling_interval_seconds"] = 30
        c["scheduled_login_enabled"] = self._sw_sched.get() == 1
        c["scheduled_login_time"] = self._sched_time.get() or "06:55"
        c["auto_start"] = self._sw_autostart.get() == 1
        c["notification_enabled"] = self._sw_notify.get() == 1
        return c

    # ── Actions ──────────────────────────────────

    def _toggle_pw(self):
        if self._pw.cget("show"):
            self._pw.configure(show="")
            self._pw_toggle.configure(text="隐藏")
        else:
            self._pw.configure(show="●")
            self._pw_toggle.configure(text="显示")

    def _save(self):
        self._read_form()
        config.save(self._cfg)
        self._btn_save.show_feedback("✓ 已保存", "保存配置")

    def _apply_settings(self):
        self._read_form()
        config.save(self._cfg)
        self._btn_apply.show_feedback("✓ 已应用", "应用设置")

    def _do_login(self):
        self._read_form()
        config.save(self._cfg)

        cfg = self._cfg
        if not cfg["username"] or not cfg["password"]:
            self._btn_login.show_feedback("请填写学号和密码", "立即登录")
            return

        self._btn_login.set_state(False)
        self._btn_login.configure_text("登录中…")
        self._status.set_state("busy")

        threading.Thread(
            target=self._login_worker, args=(cfg.copy(),), daemon=True,
        ).start()

    def _login_worker(self, cfg: dict):
        try:
            if cfg.get("wifi_ssid"):
                wifi.connect(cfg["wifi_ssid"])

            if login_mod.is_logged_in():
                self.after(0, lambda: self._login_done(True, "已登录"))
                return

            for _ in range(cfg.get("max_retries", 3)):
                if login_mod.do_login(cfg):
                    self.after(0, lambda: self._login_done(True, "登录成功"))
                    return

            self.after(0, lambda: self._login_done(False, "登录失败"))
        except Exception as e:
            self.after(0, lambda: self._login_done(False, str(e)))

    def _login_done(self, ok: bool, msg: str):
        self._btn_login.set_state(True)

        if ok:
            self._btn_login.show_feedback(f"✓ {msg}", "立即登录")
            self._status.set_state("connected")
            if self._cfg.get("notification_enabled", True):
                notify.send("校园网登录成功", msg)
        else:
            self._btn_login.show_feedback(f"✕ {msg}", "立即登录")
            self._status.set_state("disconnected")
            if self._cfg.get("notification_enabled", True):
                notify.send("校园网登录失败", msg)
