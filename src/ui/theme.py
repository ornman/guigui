"""Design tokens — Endfield-inspired industrial design."""

# ── Palette: isometric gray + purple accent ──
BG = "#0a0a0a"
SURFACE = "#141414"
BORDER = "#222222"
SHADOW = "#000000"
TEXT = "#e0e0e0"
TEXT_DIM = "#666666"
TEXT_MUTED = "#444444"
ACCENT = "#7c3aed"
ACCENT_DARK = "#5b21b6"

# ── Spacing (8px grid) ──
PAD = 28
PAD_SM = 14
PAD_XS = 8
PAD_SECTION = 20  # breathing room before buttons

# ── Radius — zero, always ──
R = 0

# ── Border ──
BW_CARD = 2
BW_BTN = 2
BW_INPUT = 1

# ── Shadow ──
SY_NORM = 4
SY_HOVER = 6
SY_ACTIVE = 2
BTN_H = 44
BTN_BOX = BTN_H + SY_HOVER

# ── Fonts ──
FF_EN = "Segoe UI"
FF_CN = "DengXian"

F_BRAND = (FF_EN, 28, "bold")       # SCHOOL
F_SUB = (FF_EN, 13)                  # // AUTOLOGIN
F_TAB = (FF_EN, 14, "bold")         # 01 登录
F_LABEL = (FF_CN, 10)               # // 运营商
F_INPUT = (FF_CN, 14)               # input body
F_BTN = (FF_CN, 15, "bold")         # buttons
F_SMALL = (FF_CN, 11)               # status
F_SWITCH_LABEL = (FF_CN, 13)        # switch text
F_SWITCH_VAL = (FF_CN, 12)          # switch sub-input

# ── Window ──
WIN_W = 460
WIN_H = 680

# ── Operators ──
OPERATORS = ("中国电信", "中国联通", "校园用户")
