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
PAD = 24
PAD_SM = 12
PAD_XS = 8

# Corner radius
R_CARD = 12
R_BTN = 8
R_INPUT = 6

# Border width
BW_CARD = 2
BW_BTN = 3
BW_INPUT = 2

# Shadow offset (y only)
SY_NORMAL = 4
SY_HOVER = 6
SY_ACTIVE = 2
BTN_H = 44
BTN_BOX_H = BTN_H + SY_HOVER  # 50

# Fonts
FF = "Microsoft YaHei"
F_TITLE = (FF, 24, "bold")
F_SECTION = (FF, 18, "bold")
F_LABEL = (FF, 13, "bold")
F_BODY = (FF, 14)
F_SMALL = (FF, 12)
F_BTN = (FF, 14, "bold")

# Animation (ms)
T_FEEDBACK = 100
T_STATE = 300
T_REVERT = 1500

# Window
WIN_W = 420
WIN_H = 580

# Operators
OPERATORS = ("中国电信", "中国联通", "校园用户")
