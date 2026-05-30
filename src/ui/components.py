"""Custom widgets: glass card, brutal button, status dot."""

import customtkinter as ctk

from . import theme as T


class GlassCard(ctk.CTkFrame):
    """Frosted glass card — lighter surface + top highlight for refraction."""

    # Top highlight — simulates light hitting glass edge
    _HL_COLOR = "#2e2e2e"  # 1px lighter strip, barely visible

    def __init__(self, master, **kw):
        super().__init__(
            master,
            fg_color=T.SURFACE,
            border_width=T.BW_CARD,
            border_color=T.BORDER,
            corner_radius=T.R_CARD,
            **kw,
        )
        # Glass refraction line — top edge
        self._hl = ctk.CTkFrame(
            self, fg_color=self._HL_COLOR, height=1, corner_radius=0)
        self._hl.place(relx=0, rely=0, relwidth=1.0, height=1)


class BrutalButton(ctk.CTkFrame):
    """Neo-brutalist button with hard-offset bottom shadow.

    Shadow is a black frame placed behind the button face.
    Hover → shadow deepens; Active → shadow shrinks.
    """

    def __init__(self, master, text: str = "", command=None,
                 variant: str = "primary", **kw):
        super().__init__(master, fg_color="transparent",
                         height=T.BTN_BOX_H, **kw)
        self._cmd = command
        self._variant = variant
        self._enabled = True
        self._text = text

        # Shadow (black, offset below)
        self._shadow = ctk.CTkFrame(
            self, fg_color=T.SHADOW,
            corner_radius=T.R_BTN, height=T.BTN_H, width=10,
        )
        self._shadow.place(relx=0, y=T.SY_NORMAL, relwidth=1.0)
        self._shadow.lower()

        # Button face
        fg = T.ACCENT if variant == "primary" else "transparent"
        bw = T.BW_BTN if variant == "primary" else 2
        bc = T.ACCENT_DARK if variant == "primary" else T.ACCENT
        tc = T.TEXT if variant == "primary" else T.ACCENT
        self._face = ctk.CTkButton(
            self, text=text, command=self._on_click,
            fg_color=fg, corner_radius=T.R_BTN,
            text_color=tc, font=T.F_BTN,
            border_width=bw, border_color=bc,
            hover=False, height=T.BTN_H,
        )
        self._face.place(relx=0, y=0, relwidth=1.0)
        self._face.lift()

        # Hover / press
        for w in (self._face, self):
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)
        self._face.bind("<ButtonPress-1>", self._press)
        self._face.bind("<ButtonRelease-1>", self._release)

    # ── Geometry helpers ────────────────────────

    def _place_shadow(self, y: int):
        self._shadow.place(relx=0, y=y, relwidth=1.0)
        self._shadow.lower()
        self._face.lift()

    # ── Events ──────────────────────────────────

    def _on_click(self):
        if self._enabled and self._cmd:
            self._cmd()

    def _enter(self, _=None):
        if not self._enabled:
            return
        self._place_shadow(T.SY_HOVER)

    def _leave(self, _=None):
        self._place_shadow(T.SY_NORMAL)

    def _press(self, _=None):
        if not self._enabled:
            return
        self._place_shadow(T.SY_ACTIVE)

    def _release(self, _=None):
        self._enter()

    # ── Public API ──────────────────────────────

    def configure_text(self, text: str):
        self._face.configure(text=text)

    def set_state(self, enabled: bool):
        self._enabled = enabled
        self._face.configure(text=self._text)
        if enabled:
            self._place_shadow(T.SY_NORMAL)

    def show_feedback(self, text: str, revert_to: str,
                      ms: int = T.T_REVERT):
        """Temporarily change button text, then revert."""
        self._face.configure(text=text)
        self.after(ms, lambda: self._face.configure(text=revert_to))


class StatusDot(ctk.CTkFrame):
    """Colored dot + label for connection status."""

    _COLORS = {
        "connected": T.ACCENT,
        "busy": T.ACCENT,
        "disconnected": T.TEXT_DIM,
        "idle": T.TEXT_DIM,
    }
    _LABELS = {
        "connected": "已连接",
        "busy": "登录中…",
        "disconnected": "断网",
        "idle": "未配置",
    }

    def __init__(self, master, state: str = "idle"):
        super().__init__(master, fg_color="transparent")
        self._dot = ctk.CTkLabel(
            self, text="●", font=(T.FF, 14),
            text_color=self._COLORS[state],
        )
        self._dot.pack(side="left")
        self._label = ctk.CTkLabel(
            self, text=self._LABELS[state],
            font=T.F_SMALL, text_color=T.TEXT_DIM,
        )
        self._label.pack(side="left", padx=(6, 0))

    def set_state(self, state: str):
        self._dot.configure(text_color=self._COLORS.get(state, T.TEXT_DIM))
        self._label.configure(text=self._LABELS.get(state, "未配置"))
