"""Design tokens — black/white/gray + purple."""

# Palette
BG = "#0d0d0d"
SURFACE = "#171717"
BORDER = "#2a2a2a"
SHADOW = "#000000"
TEXT = "#ffffff"
TEXT_DIM = "#888888"
ACCENT = "#7c3aed"
ACCENT_DARK = "#5b21b6"
ACCENT_HOVER = "#8b5cf6"

# Spacing
PAD = 28
PAD_SM = 14
PAD_XS = 8

# Corner radius — 0 everywhere, hard edges only
R_CARD = 0
R_BTN = 0
R_INPUT = 0

# Border width
BW_CARD = 2
BW_BTN = 3
BW_INPUT = 2

# Shadow offset
SY_NORMAL = 4
SY_HOVER = 6
SY_ACTIVE = 2
BTN_H = 44
BTN_BOX_H = BTN_H + SY_HOVER  # 50

# Fonts
FF = "Microsoft YaHei"
F_TITLE = (FF, 26, "bold")
F_SUBTITLE = (FF, 12)
F_TAB = (FF, 16, "bold")
F_LABEL = (FF, 13, "bold")
F_BODY = (FF, 14)
F_SMALL = (FF, 12)
F_BTN = (FF, 15, "bold")

# Animation (ms)
T_FEEDBACK = 100
T_STATE = 300
T_REVERT = 1500

# Window
WIN_W = 460
WIN_H = 680

# Operators
OPERATORS = ("中国电信", "中国联通", "校园用户")
