"""Custom widgets — glass card, brutal button, status dot."""

import customtkinter as ctk

from . import theme as T


class GlassCard(ctk.CTkFrame):
    """Frosted glass via color layering + top highlight."""

    def __init__(self, master, **kw):
        super().__init__(
            master,
            fg_color=T.SURFACE,
            border_width=T.BW_CARD,
            border_color=T.BORDER,
            corner_radius=T.R,
            **kw,
        )
        # Glass refraction line
        self._hl = ctk.CTkFrame(
            self, fg_color="#2a2a2a", height=1, width=10, corner_radius=0)
        self._hl.place(relx=0, rely=0, relwidth=1.0)


class BrutalButton(ctk.CTkFrame):
    """Neo-brutalist button — hard offset shadow, zero radius."""

    def __init__(self, master, text: str = "", command=None,
                 variant: str = "primary", **kw):
        super().__init__(master, fg_color="transparent",
                         height=T.BTN_BOX, **kw)
        self._cmd = command
        self._enabled = True
        self._text = text

        # Shadow
        self._shadow = ctk.CTkFrame(
            self, fg_color=T.SHADOW, corner_radius=T.R,
            height=T.BTN_H, width=10)
        self._shadow.place(relx=0, y=T.SY_NORM, relwidth=1.0)
        self._shadow.lower()

        # Face
        fg = T.ACCENT if variant == "primary" else "transparent"
        bc = T.ACCENT_DARK if variant == "primary" else T.ACCENT
        tc = T.TEXT if variant == "primary" else T.ACCENT
        bw = T.BW_BTN if variant == "primary" else 2

        self._face = ctk.CTkButton(
            self, text=text, command=self._click,
            fg_color=fg, corner_radius=T.R,
            text_color=tc, font=T.F_BTN,
            border_width=bw, border_color=bc,
            hover=False, height=T.BTN_H)
        self._face.place(relx=0, y=0, relwidth=1.0)
        self._face.lift()

        for w in (self._face, self):
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)
        self._face.bind("<ButtonPress-1>", self._press)
        self._face.bind("<ButtonRelease-1>", self._release)

    def _place_shadow(self, y: int):
        self._shadow.place(relx=0, y=y, relwidth=1.0)
        self._shadow.lower()
        self._face.lift()

    def _click(self):
        if self._enabled and self._cmd:
            self._cmd()

    def _enter(self, _=None):
        if self._enabled:
            self._place_shadow(T.SY_HOVER)

    def _leave(self, _=None):
        self._place_shadow(T.SY_NORM)

    def _press(self, _=None):
        if self._enabled:
            self._place_shadow(T.SY_ACTIVE)

    def _release(self, _=None):
        self._enter()

    def configure_text(self, text: str):
        self._face.configure(text=text)

    def set_state(self, enabled: bool):
        self._enabled = enabled
        self._face.configure(text=self._text)
        if enabled:
            self._place_shadow(T.SY_NORM)

    def show_feedback(self, text: str, revert_to: str, ms: int = 1500):
        self._face.configure(text=text)
        self.after(ms, lambda: self._face.configure(text=revert_to))


class StatusDot(ctk.CTkFrame):
    """Connection status — purple dot = ok, gray dot = no."""

    def __init__(self, master, state: str = "idle"):
        super().__init__(master, fg_color="transparent")
        color = T.ACCENT if state == "connected" else T.TEXT_MUTED
        label = {"connected": "已连接", "busy": "登录中…",
                 "disconnected": "断网", "idle": "未配置"}.get(state, "未配置")
        self._dot = ctk.CTkLabel(self, text="●", font=(T.FF_CN, 10),
                                  text_color=color)
        self._dot.pack(side="left")
        self._label = ctk.CTkLabel(self, text=label, font=T.F_SMALL,
                                    text_color=T.TEXT_DIM)
        self._label.pack(side="left", padx=(6, 0))

    def set_state(self, state: str):
        c = T.ACCENT if state in ("connected", "busy") else T.TEXT_MUTED
        t = {"connected": "已连接", "busy": "登录中…",
             "disconnected": "断网", "idle": "未配置"}.get(state, "未配置")
        self._dot.configure(text_color=c)
        self._label.configure(text=t)
