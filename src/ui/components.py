"""自定义组件 —— 玻璃卡片、新粗野按钮、状态指示点。"""

import customtkinter as ctk

from . import theme as T


class GlassCard(ctk.CTkFrame):
    """毛玻璃卡片：颜色叠加 + 顶部高光线。"""

    def __init__(self, master, **kw):
        """创建带边框和顶部高光的毛玻璃卡片。"""
        super().__init__(
            master,
            fg_color=T.SURFACE,
            border_width=T.BW_CARD,
            border_color=T.BORDER,
            corner_radius=T.R,
            **kw,
        )
        # 玻璃折射线 —— 模拟玻璃边缘高光
        self._hl = ctk.CTkFrame(
            self, fg_color="#2a2a2a", height=1, width=10, corner_radius=0)
        self._hl.place(relx=0, rely=0, relwidth=1.0)


class BrutalButton(ctk.CTkFrame):
    """新粗野主义按钮 —— 硬偏移阴影、零圆角。"""

    def __init__(self, master, text: str = "", command=None,
                 variant: str = "primary", **kw):
        """创建带硬偏移阴影的粗野按钮。

        Args:
            master: 父级控件。
            text: 按钮标签文本。
            command: 点击时触发的回调（仅在按钮启用时生效）。
            variant: ``"primary"``（实心填充）或 ``"secondary"``（描边镂空）。
        """
        super().__init__(master, fg_color="transparent",
                         height=T.BTN_BOX, **kw)
        self._cmd = command
        self._enabled = True
        self._text = text

        # 阴影层
        self._shadow = ctk.CTkFrame(
            self, fg_color=T.SHADOW, corner_radius=T.R,
            height=T.BTN_H, width=10)
        self._shadow.place(relx=0, y=T.SY_NORM, relwidth=1.0)
        self._shadow.lower()

        # 按钮面层
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
        """将阴影层移动到 *y* 像素位置，保持在按钮面层下方。"""
        self._shadow.place(relx=0, y=y, relwidth=1.0)
        self._shadow.lower()
        self._face.lift()

    def _click(self):
        """按钮启用时执行回调。"""
        if self._enabled and self._cmd:
            self._cmd()

    def _enter(self, _=None):
        """鼠标移入 —— 阴影上浮到悬停位置（启用时）。"""
        if self._enabled:
            self._place_shadow(T.SY_HOVER)

    def _leave(self, _=None):
        """鼠标移出 —— 阴影复位到默认位置。"""
        self._place_shadow(T.SY_NORM)

    def _press(self, _=None):
        """鼠标按下 —— 阴影压到最低（激活态）。"""
        if self._enabled:
            self._place_shadow(T.SY_ACTIVE)

    def _release(self, _=None):
        """鼠标松开 —— 恢复悬停态。"""
        self._enter()

    def configure_text(self, text: str):
        """更新按钮标签文本。"""
        self._face.configure(text=text)

    def set_state(self, enabled: bool):
        """启用或禁用按钮并重置视觉状态。

        禁用时阴影复位到默认位置，避免视觉上暗示可交互。
        """
        self._enabled = enabled
        self._face.configure(text=self._text)
        if enabled:
            self._place_shadow(T.SY_NORM)

    def show_feedback(self, text: str, revert_to: str, ms: int = 1500):
        """在按钮上闪烁显示 *text*，*ms* 毫秒后恢复为 *revert_to*。

        用于展示短暂操作结果（如 "✓ 已保存" → "保存配置"）。
        """
        self._face.configure(text=text)
        self.after(ms, lambda: self._face.configure(text=revert_to))


class StatusDot(ctk.CTkFrame):
    """连接状态指示器 —— 紫色圆点 = 正常，灰色圆点 = 异常。"""

    def __init__(self, master, state: str = "idle"):
        """创建带标签的状态指示圆点。

        Args:
            state: 初始状态 —— ``"connected"``、``"busy"``、
                ``"disconnected"`` 或 ``"idle"``。
        """
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
        """根据连接 *state* 更新圆点颜色和标签文本。

        可选值：``"connected"`` / ``"busy"`` → 紫色高亮；
        其他 → 灰色弱化。
        """
        c = T.ACCENT if state in ("connected", "busy") else T.TEXT_MUTED
        t = {"connected": "已连接", "busy": "登录中…",
             "disconnected": "断网", "idle": "未配置"}.get(state, "未配置")
        self._dot.configure(text_color=c)
        self._label.configure(text=t)
