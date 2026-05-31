"""SchoolAutoLogin — main window."""

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
        self.minsize(T.WIN_W, T.WIN_H)
        self.resizable(True, True)

        self._cfg = config.load()
        self._build()
        self._fill_fields()

    # ── Build ────────────────────────────────────

    def _build(self):
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=20, pady=20)

        # Brand bar — 3px purple strip
        ctk.CTkFrame(outer, fg_color=T.ACCENT, height=3).pack(fill="x")

        # Card
        card = GlassCard(outer)
        card.pack(fill="both", expand=True)

        # ── Decorative: corner marks ──
        corner_color = "#2a2a2a"
        corner_len = 16
        for relx, rely, orient in [
            (0.0, 0.0, "tl"), (1.0, 0.0, "tr"),
            (0.0, 1.0, "bl"), (1.0, 1.0, "br"),
        ]:
            if orient in ("tl", "bl"):
                ctk.CTkFrame(card, fg_color=corner_color, width=corner_len,
                             height=1, corner_radius=0).place(
                    relx=relx, rely=rely, anchor="nw" if orient == "tl" else "sw",
                    x=6 if relx == 0.0 else -6,
                    y=6 if rely == 0.0 else -6)
                ctk.CTkFrame(card, fg_color=corner_color, width=1,
                             height=corner_len, corner_radius=0).place(
                    relx=relx, rely=rely, anchor="nw" if orient == "tl" else "sw",
                    x=6 if relx == 0.0 else -6,
                    y=6 if rely == 0.0 else -6)
            else:
                ctk.CTkFrame(card, fg_color=corner_color, width=corner_len,
                             height=1, corner_radius=0).place(
                    relx=relx, rely=rely, anchor="ne" if orient == "tr" else "se",
                    x=-6 if relx == 1.0 else 6,
                    y=6 if rely == 0.0 else -6)
                ctk.CTkFrame(card, fg_color=corner_color, width=1,
                             height=corner_len, corner_radius=0).place(
                    relx=relx, rely=rely, anchor="ne" if orient == "tr" else "se",
                    x=-6 if relx == 1.0 else 6,
                    y=6 if rely == 0.0 else -6)

        # ── Decorative: version text (bottom-right) ──
        ctk.CTkLabel(
            card, text=f"v{T.VERSION}", font=(T.FF_EN, 9),
            text_color=T.TEXT_MUTED,
        ).pack(side="bottom", anchor="e", padx=T.PAD, pady=(0, T.PAD_SM))

        # ── Decorative: system readout (top-right) ──
        ctk.CTkLabel(
            card, text="SYS:// ACTIVE", font=(T.FF_EN, 9),
            text_color=T.TEXT_MUTED,
        ).place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)

        # Inner content
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=T.PAD, pady=T.PAD)
        self._inner = inner

        # ── Title block ──
        ctk.CTkLabel(
            inner, text="SCHOOL", font=T.F_BRAND,
            text_color=T.TEXT, anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            inner, text="// AUTOLOGIN", font=T.F_SUB,
            text_color=T.ACCENT, anchor="w",
        ).pack(fill="x", pady=(0, T.PAD_SM))

        # Purple divider
        ctk.CTkFrame(inner, fg_color=T.ACCENT, height=2).pack(fill="x")

        # ── Tabs ──
        self._build_tabs(inner)

        # ── Content ──
        self._content = ctk.CTkFrame(inner, fg_color="transparent")
        self._content.pack(fill="both", expand=True, pady=(T.SPACE_SM, 0))

        self._login_panel = self._build_login(self._content)
        self._settings_panel = self._build_settings(self._content)
        self._show_tab("login")

        # ── Status ──
        self._status = StatusDot(card, state="idle")
        self._status.pack(side="bottom", anchor="w",
                          padx=T.PAD, pady=(0, T.PAD_SM))

    def _build_tabs(self, parent):
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", pady=(T.PAD_SM, 0))

        self._tab_login = ctk.CTkButton(
            bar, text="01 登录", font=T.F_TAB, width=100,
            fg_color="transparent", text_color=T.TEXT,
            hover=False, corner_radius=0,
            command=lambda: self._show_tab("login"))
        self._tab_login.pack(side="left")

        self._tab_settings = ctk.CTkButton(
            bar, text="02 设置", font=T.F_TAB, width=100,
            fg_color="transparent", text_color=T.TEXT_DIM,
            hover=False, corner_radius=0,
            command=lambda: self._show_tab("settings"))
        self._tab_settings.pack(side="left", padx=(16, 0))

        # Active indicator
        self._indicator = ctk.CTkFrame(
            bar, fg_color=T.ACCENT, height=3, width=50, corner_radius=0)
        self._indicator.place(in_=self._tab_login, rely=1.0, relx=0.0)

        # Gray divider
        ctk.CTkFrame(parent, fg_color=T.BORDER, height=1).pack(fill="x")

    def _move_indicator(self, target):
        self._indicator.place_forget()
        self._indicator.place(in_=target, rely=1.0, relx=0.0)

    # ── Login panel ──────────────────────────────

    def _build_login(self, parent):
        p = ctk.CTkFrame(parent, fg_color="transparent")

        self._section(p, "// 运营商")
        self._op = ctk.CTkOptionMenu(
            p, values=list(T.OPERATORS),
            fg_color=T.BG, button_color=T.ACCENT,
            button_hover_color=T.ACCENT_DARK,
            text_color=T.TEXT, font=T.F_INPUT, height=38,
            corner_radius=T.R)
        self._op.pack(fill="x", pady=(0, T.SPACE_SM))

        self._section(p, "// 学号")
        self._user = self._entry(p)

        self._section(p, "// 密码")
        pw_row = ctk.CTkFrame(p, fg_color="transparent")
        pw_row.pack(fill="x", pady=(0, T.SPACE_SM))
        self._pw = ctk.CTkEntry(
            pw_row, placeholder_text="", show="●",
            **self._entry_kw(), height=38)
        self._pw.pack(side="left", fill="x", expand=True)
        self._focus_border(self._pw)
        self._pw_toggle = ctk.CTkButton(
            pw_row, text="显示", width=48, height=38,
            fg_color=T.SURFACE, text_color=T.TEXT_DIM,
            font=T.F_SMALL, hover_color=T.BORDER,
            corner_radius=T.R, command=self._toggle_pw)
        self._pw_toggle.pack(side="right", padx=(8, 0))

        self._btn_login = BrutalButton(p, text="立即登录",
                                        command=self._do_login)
        self._btn_login.pack(fill="x", pady=(T.SPACE_LG, T.SPACE_SM))

        self._btn_save = BrutalButton(p, text="保存配置",
                                        command=self._save, variant="secondary")
        self._btn_save.pack(fill="x")

        return p

    # ── Settings panel ───────────────────────────

    def _build_settings(self, parent):
        p = ctk.CTkFrame(parent, fg_color="transparent")

        self._section(p, "// 网络")
        self._wifi_entry = self._entry(p, placeholder="校园网 WiFi 名称，留空跳过")

        self._section(p, "// 重连")
        self._sw_poll = self._switch(p, "断网自动重连")
        r1 = ctk.CTkFrame(p, fg_color="transparent")
        r1.pack(fill="x", pady=(T.SPACE_SM, T.SPACE_SM), padx=(20, 0))
        ctk.CTkLabel(r1, text="检测间隔（秒）", font=T.F_SWITCH_VAL,
                     text_color=T.TEXT_DIM).pack(side="left")
        self._poll_interval = ctk.CTkEntry(
            r1, width=72, height=28, fg_color=T.BG,
            border_color=T.BORDER, text_color=T.TEXT,
            font=T.F_SWITCH_VAL, corner_radius=T.R)
        self._poll_interval.pack(side="right")

        self._section(p, "// 定时")
        self._sw_sched = self._switch(p, "定时登录")
        r2 = ctk.CTkFrame(p, fg_color="transparent")
        r2.pack(fill="x", pady=(T.SPACE_SM, T.SPACE_SM), padx=(20, 0))
        ctk.CTkLabel(r2, text="执行时间 HH:MM", font=T.F_SWITCH_VAL,
                     text_color=T.TEXT_DIM).pack(side="left")
        self._sched_time = ctk.CTkEntry(
            r2, width=72, height=28, fg_color=T.BG,
            border_color=T.BORDER, text_color=T.TEXT,
            font=T.F_SWITCH_VAL, corner_radius=T.R)
        self._sched_time.pack(side="right")

        self._section(p, "// 系统")
        self._sw_autostart = self._switch(p, "开机自启")
        self._sw_notify = self._switch(p, "桌面通知")

        self._btn_apply = BrutalButton(p, text="应用设置",
                                        command=self._apply_settings)
        self._btn_apply.pack(fill="x", pady=(T.SPACE_LG, 0))

        return p

    # ── Widget helpers ───────────────────────────

    def _section(self, parent, text: str):
        """Section label with // prefix."""
        ctk.CTkLabel(parent, text=text, font=T.F_LABEL,
                     text_color=T.TEXT_DIM, anchor="w").pack(
            fill="x", pady=(T.SEC_ABOVE, T.SEC_BELOW))

    def _entry_kw(self) -> dict:
        return dict(fg_color=T.BG, border_color=T.BORDER,
                    text_color=T.TEXT, placeholder_text_color=T.TEXT_MUTED,
                    font=T.F_INPUT, corner_radius=T.R)

    def _entry(self, parent, placeholder: str = "") -> ctk.CTkEntry:
        e = ctk.CTkEntry(parent, placeholder_text=placeholder,
                         **self._entry_kw(), height=38)
        e.pack(fill="x", pady=(0, T.SPACE_SM))
        self._focus_border(e)
        return e

    def _switch(self, parent, label: str) -> ctk.CTkSwitch:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(T.SPACE_SM, 0))
        ctk.CTkLabel(row, text=label, font=T.F_SWITCH_LABEL,
                     text_color=T.TEXT).pack(side="left")
        sw = ctk.CTkSwitch(
            row, text="",
            button_color=T.ACCENT, button_hover_color=T.ACCENT_DARK,
            progress_color=T.ACCENT, fg_color=T.BORDER)
        sw.pack(side="right")
        return sw

    def _focus_border(self, entry: ctk.CTkEntry):
        entry.bind("<FocusIn>",
                    lambda _: entry.configure(border_color=T.ACCENT,
                                              border_width=2))
        entry.bind("<FocusOut>",
                    lambda _: entry.configure(border_color=T.BORDER,
                                              border_width=T.BW_INPUT))

    # ── Tab switching ────────────────────────────

    def _show_tab(self, name: str):
        self._login_panel.pack_forget()
        self._settings_panel.pack_forget()

        if name == "login":
            self._login_panel.pack(fill="both", expand=True)
            self._tab_login.configure(text_color=T.TEXT)
            self._tab_settings.configure(text_color=T.TEXT_DIM)
            self._move_indicator(self._tab_login)
        else:
            self._settings_panel.pack(fill="both", expand=True)
            self._tab_login.configure(text_color=T.TEXT_DIM)
            self._tab_settings.configure(text_color=T.TEXT)
            self._move_indicator(self._tab_settings)

    # ── Form ─────────────────────────────────────

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

        if not self._cfg["username"] or not self._cfg["password"]:
            self._btn_login.show_feedback("请填写学号和密码", "立即登录")
            return

        self._btn_login.set_state(False)
        self._btn_login.configure_text("登录中…")
        self._status.set_state("busy")

        threading.Thread(
            target=self._login_worker,
            args=(self._cfg.copy(),), daemon=True).start()

    def _login_worker(self, cfg: dict):
        try:
            if cfg.get("wifi_ssid"):
                wifi.connect(cfg["wifi_ssid"])
            if login_mod.is_logged_in():
                self.after(0, lambda: self._done(True, "已登录"))
                return
            for _ in range(cfg.get("max_retries", 3)):
                if login_mod.do_login(cfg):
                    self.after(0, lambda: self._done(True, "登录成功"))
                    return
            self.after(0, lambda: self._done(False, "登录失败"))
        except Exception as e:
            self.after(0, lambda: self._done(False, str(e)))

    def _done(self, ok: bool, msg: str):
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
