"""SchoolAutoLogin — 主窗口。"""

import logging
import threading

import customtkinter as ctk

log = logging.getLogger(__name__)

from . import autostart, config, wifi
from . import login as login_mod
from . import notify, scheduler
from .ui import theme as T
from .ui.components import BrutalButton, GlassCard, StatusDot


class App(ctk.CTk):
    def __init__(self):
        """初始化主窗口：加载配置、构建界面、填充表单字段。"""
        super().__init__()
        self.title("SchoolAutoLogin")
        self.geometry(f"{T.WIN_W}x{T.WIN_H}")
        self.configure(fg_color=T.BG)
        self.minsize(T.WIN_W, T.WIN_H)
        self.resizable(True, True)

        self._cfg = config.load()
        self._poll_thread: threading.Thread | None = None
        self._poll_stop = threading.Event()
        self._build()
        self._fill_fields()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 界面构建 ────────────────────────────────────

    def _build(self):
        """构建完整 UI：品牌条 → 卡片 → 标签页 → 状态栏。"""
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=20, pady=20)

        # 品牌条 — 3px 紫色条纹
        ctk.CTkFrame(outer, fg_color=T.ACCENT, height=3).pack(fill="x")

        # 卡片容器
        card = GlassCard(outer)
        card.pack(fill="both", expand=True)

        # ── 装饰：四角 L 形标记 ──
        self._place_corner_marks(card)

        # ── 装饰：版本号（右下角） ──
        ctk.CTkLabel(
            card, text=f"v{T.VERSION}", font=(T.FF_EN, 9),
            text_color=T.TEXT_MUTED,
        ).pack(side="bottom", anchor="e", padx=T.SPACE_XL, pady=(0, T.SPACE_MD))

        # ── 装饰：系统状态文字（右上角） ──
        ctk.CTkLabel(
            card, text="SYS:// ACTIVE", font=(T.FF_EN, 9),
            text_color=T.TEXT_MUTED,
        ).place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)

        # 主内容区
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=T.SPACE_XL, pady=T.SPACE_XL)
        self._inner = inner

        # ── 标题区 ──
        ctk.CTkLabel(
            inner, text="SCHOOL", font=T.F_BRAND,
            text_color=T.TEXT, anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            inner, text="// AUTOLOGIN", font=T.F_SUB,
            text_color=T.ACCENT, anchor="w",
        ).pack(fill="x", pady=(0, T.SPACE_MD))

        # 紫色分割线
        ctk.CTkFrame(inner, fg_color=T.ACCENT, height=2).pack(fill="x")

        # ── 标签页导航 ──
        self._build_tabs(inner)

        # ── 内容区 ──
        self._content = ctk.CTkFrame(inner, fg_color="transparent")
        self._content.pack(fill="both", expand=True, pady=(T.SPACE_SM, 0))

        self._login_panel = self._build_login(self._content)
        self._settings_panel = self._build_settings(self._content)
        self._show_tab("login")

        # ── 状态栏 ──
        self._status = StatusDot(card, state="idle")
        self._status.pack(side="bottom", anchor="w",
                          padx=T.SPACE_XL, pady=(0, T.SPACE_MD))

    @staticmethod
    def _place_corner_marks(card: ctk.CTkFrame):
        """在卡片四角绘制 L 形装饰标记。"""
        color = "#2a2a2a"
        length = 16
        offset = 6
        specs = [
            # (relx, rely, anchor, dx, dy)
            (0.0, 0.0, "nw",  offset,  offset),
            (1.0, 0.0, "ne", -offset,  offset),
            (0.0, 1.0, "sw",  offset, -offset),
            (1.0, 1.0, "se", -offset, -offset),
        ]
        for relx, rely, anchor, dx, dy in specs:
            ctk.CTkFrame(card, fg_color=color, width=length,
                         height=1, corner_radius=0).place(
                relx=relx, rely=rely, anchor=anchor, x=dx, y=dy)
            ctk.CTkFrame(card, fg_color=color, width=1,
                         height=length, corner_radius=0).place(
                relx=relx, rely=rely, anchor=anchor, x=dx, y=dy)

    def _build_tabs(self, parent):
        """构建「01 登录 / 02 设置」标签页导航栏。"""
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", pady=(T.SPACE_MD, 0))

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

        # 当前激活标签的紫色下划线指示器
        self._indicator = ctk.CTkFrame(
            bar, fg_color=T.ACCENT, height=3, width=50, corner_radius=0)
        self._indicator.place(in_=self._tab_login, rely=1.0, relx=0.0)

        # 灰色分割线
        ctk.CTkFrame(parent, fg_color=T.BORDER, height=1).pack(fill="x")

    def _move_indicator(self, target):
        """将标签页指示器移动到 *target* 按钮下方。"""
        self._indicator.place_forget()
        self._indicator.place(in_=target, rely=1.0, relx=0.0)

    # ── 登录面板 ──────────────────────────────────

    def _build_login(self, parent):
        """构建登录面板：运营商选择、学号、密码、登录/保存按钮。"""
        p = ctk.CTkFrame(parent, fg_color="transparent")

        self._section(p, "// 运营商")
        op_border = ctk.CTkFrame(
            p, fg_color=T.BORDER, height=40, corner_radius=T.R)
        op_border.pack(fill="x", pady=(0, T.SPACE_SM))
        self._op = ctk.CTkOptionMenu(
            op_border, values=list(T.OPERATORS),
            fg_color=T.BG, button_color=T.ACCENT,
            button_hover_color=T.ACCENT_DARK,
            text_color=T.TEXT, font=T.F_INPUT, height=38,
            corner_radius=T.R)
        self._op.pack(padx=T.BW_INPUT, pady=T.BW_INPUT,
                       fill="both", expand=True)

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

    # ── 设置面板 ───────────────────────────────────

    def _build_settings(self, parent):
        """构建设置面板：WiFi 名称、断网重连、定时登录、开机自启、通知开关。"""
        p = ctk.CTkFrame(parent, fg_color="transparent")

        self._section(p, "// WiFi 名称")
        ctk.CTkLabel(
            p,
            text="用 WiFi 连校园网的填名称，电脑睡眠后会自动切回。用网线的不用填。",
            font=T.F_SMALL, text_color=T.TEXT_MUTED, anchor="w",
            wraplength=380,
        ).pack(fill="x", pady=(0, T.SPACE_XS))
        self._wifi_entry = self._entry(p, placeholder="留空跳过 WiFi 切换")

        self._section(p, "// 重连")
        self._sw_poll = self._switch(p, "断网自动重连")
        r1 = ctk.CTkFrame(p, fg_color="transparent")
        r1.pack(fill="x", pady=(T.SPACE_SM, T.SPACE_SM))
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
        r2.pack(fill="x", pady=(T.SPACE_SM, T.SPACE_SM))
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

    # ── 控件辅助方法 ───────────────────────────────

    def _section(self, parent, text: str):
        """带 // 前缀的段落标签。"""
        ctk.CTkLabel(parent, text=text, font=T.F_LABEL,
                     text_color=T.TEXT_DIM, anchor="w").pack(
            fill="x", pady=(T.SEC_ABOVE, T.SEC_BELOW))

    def _entry_kw(self) -> dict:
        """输入框通用样式配置字典。"""
        return dict(fg_color=T.BG, border_color=T.BORDER,
                    text_color=T.TEXT, placeholder_text_color=T.TEXT_MUTED,
                    font=T.F_INPUT, corner_radius=T.R)

    def _entry(self, parent, placeholder: str = "") -> ctk.CTkEntry:
        """创建带焦点高亮的输入框并添加到 *parent*。"""
        e = ctk.CTkEntry(parent, placeholder_text=placeholder,
                         **self._entry_kw(), height=38)
        e.pack(fill="x", pady=(0, T.SPACE_SM))
        self._focus_border(e)
        return e

    def _switch(self, parent, label: str) -> ctk.CTkSwitch:
        """创建带标签的开关控件。"""
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
        """为输入框绑定焦点高亮：获取焦点时紫色边框，失去焦点时灰色边框。"""
        entry.bind("<FocusIn>",
                    lambda _: entry.configure(border_color=T.ACCENT,
                                              border_width=2))
        entry.bind("<FocusOut>",
                    lambda _: entry.configure(border_color=T.BORDER,
                                              border_width=T.BW_INPUT))

    # ── 标签页切换 ────────────────────────────────

    def _show_tab(self, name: str):
        """切换显示 *name* 对应的面板（"login" 或 "settings"）。"""
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

    # ── 表单 ─────────────────────────────────────

    def _fill_fields(self):
        """将配置文件中的值填充到表单控件。"""
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
        """读取表单值到新的 dict（不可变模式，不修改 self._cfg）。"""
        c = {**self._cfg}
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

    # ── 操作 ──────────────────────────────────────

    def _toggle_pw(self):
        """切换密码框的显示/隐藏状态。"""
        if self._pw.cget("show"):
            self._pw.configure(show="")
            self._pw_toggle.configure(text="隐藏")
        else:
            self._pw.configure(show="●")
            self._pw_toggle.configure(text="显示")

    def _save(self):
        """验证表单 → 更新配置 → 写盘 → 反馈。"""
        self._cfg = config.validate(self._read_form())
        config.save(self._cfg)
        self._btn_save.show_feedback("✓ 已保存", "保存配置")

    def _apply_settings(self):
        """应用设置：保存配置 + 联动轮询/定时任务/开机自启三个子系统。"""
        new_cfg = config.validate(self._read_form())
        self._cfg = new_cfg
        config.save(self._cfg)

        messages: list[str] = []

        # ── 轮询（断网自动重连） ──
        if new_cfg.get("polling_enabled"):
            self._start_polling()
            messages.append("轮询已开启")
        else:
            self._stop_polling()

        # ── 定时任务 ──
        if new_cfg.get("scheduled_login_enabled"):
            time_str = new_cfg.get("scheduled_login_time", "06:55")
            if scheduler.create_scheduled_task(time_str):
                messages.append(f"定时任务 {time_str}")
            else:
                messages.append("定时任务创建失败")
        else:
            scheduler.remove_scheduled_task()

        # ── 开机自启 ──
        if new_cfg.get("auto_start"):
            if autostart.enable():
                messages.append("自启已开启")
            else:
                messages.append("自启设置失败")
        else:
            autostart.disable()

        feedback = "✓ " + "、".join(messages) if messages else "✓ 已应用"
        self._btn_apply.show_feedback(feedback, "应用设置")

    # ── 轮询（断网自动重连） ─────────────────────

    def _start_polling(self):
        """启动或重启轮询守护线程。"""
        self._stop_polling()
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_worker, daemon=True)
        self._poll_thread.start()
        log.info("Polling thread started")

    def _stop_polling(self):
        """停止轮询线程（等待最多 5 秒）。"""
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_stop.set()
            self._poll_thread.join(timeout=5)
            if self._poll_thread.is_alive():
                log.warning("Polling thread did not stop within timeout")
            else:
                log.info("Polling thread stopped")
        self._poll_thread = None

    def _poll_worker(self):
        """后台轮询循环：检查登录状态，断网时自动重连。

        使用 ``threading.Event.wait(timeout=...)`` 实现可中断等待，
        避免线程无法响应停止信号。所有 UI 更新通过 ``self.after(0, ...)``
        调度到主线程执行（customtkinter 非线程安全）。
        """
        import time

        while not self._poll_stop.wait(
            timeout=self._cfg.get("polling_interval_seconds", 30)
        ):
            try:
                cfg = self._cfg
                status = login_mod.check_auth_status()

                if status == "logged_in":
                    self.after(0, lambda: self._status.set_state("connected"))
                    continue

                # 网络不可达 → 尝试 WiFi 切换恢复（可中断等待）
                if status == "unreachable" and cfg.get("wifi_ssid"):
                    if self._poll_stop.is_set():
                        return
                    wifi.connect(cfg["wifi_ssid"])
                    # 可中断的网络等待：每 3 秒检查一次，随时可停止
                    deadline = time.time() + 30
                    while time.time() < deadline:
                        if self._poll_stop.is_set():
                            return
                        if login_mod.check_auth_status() != "unreachable":
                            break
                        self._poll_stop.wait(timeout=3)
                    status = login_mod.check_auth_status()

                if status == "logged_in":
                    self.after(0, lambda: self._status.set_state("connected"))
                    continue

                if status == "unreachable":
                    self.after(0, lambda: self._status.set_state("disconnected"))
                    continue

                # status == "not_logged_in" → 尝试登录
                log.info("Poll: disconnected, attempting reconnect...")
                for _ in range(cfg.get("max_retries", 3)):
                    if self._poll_stop.is_set():
                        return
                    if login_mod.do_login(cfg):
                        log.info("Poll: reconnected successfully")
                        self.after(0, lambda: self._status.set_state("connected"))
                        if cfg.get("notification_enabled", True):
                            notify.send("校园网自动重连", "已重新连接网络")
                        break
                else:
                    log.warning("Poll: reconnect failed")
                    self.after(0, lambda: self._status.set_state("disconnected"))
            except Exception as e:
                log.error("Poll worker error: %s", e)

    # ── 登录 ────────────────────────────────────

    def _on_close(self):
        """窗口关闭时优雅退出：先停止轮询线程再销毁窗口。"""
        self._stop_polling()
        self.destroy()

    def _do_login(self):
        """验证表单 → 保存 → 禁用按钮 → 在后台线程执行登录。"""
        self._cfg = config.validate(self._read_form())
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
        """后台登录线程：调用 attempt_login 并通过 ``self.after`` 回调 UI。

        Args:
            cfg: 配置字典的副本（线程安全）。
        """
        try:
            result = login_mod.attempt_login(cfg)
            if result == "already_logged_in":
                self.after(0, lambda: self._done(True, "已登录"))
            elif result == "success":
                self.after(0, lambda: self._done(True, "登录成功"))
            elif result == "unreachable":
                self.after(0, lambda: self._done(False, "网络不可用"))
            else:  # "failed"
                self.after(0, lambda: self._done(False, "登录失败"))
        except Exception as e:
            log.error("Login worker error: %s", e)
            self.after(0, lambda: self._done(False, str(e)))

    def _done(self, ok: bool, msg: str):
        """登录完成回调：恢复按钮、更新状态指示器、发送桌面通知。

        Args:
            ok: 登录是否成功。
            msg: 展示给用户的结果文本。
        """
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
