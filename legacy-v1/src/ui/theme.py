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

# ── Spacing — varied rhythm (tight within sections, loose between) ──
SPACE_XL = 28      # card edge padding
SPACE_LG = 20      # before action buttons
SPACE_MD = 14      # between modules (tab bar → content)
SPACE_SM = 6       # between fields within a section
SPACE_XS = 4       # label → input gap

# Section rhythm: gap above labels groups content visually
SEC_ABOVE = 12     # space above a section label (inter-section break)
SEC_BELOW = SPACE_XS  # space below a section label (tight to its field)

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

# ── Fonts — type scale with clear hierarchy ──
FF_EN = "Inter"
FF_CN = "Noto Sans SC"

F_BRAND = (FF_EN, 28, "bold")        # app title — identity
F_SUB = (FF_EN, 13)                   # subtitle — companion
F_TAB = (FF_EN, 14, "bold")          # tab navigation
F_LABEL = (FF_CN, 12, "bold")        # section labels — was 10, now readable
F_INPUT = (FF_CN, 14)                 # body / input text
F_BTN = (FF_CN, 15, "bold")          # call-to-action buttons
F_SMALL = (FF_CN, 11)                 # status, meta, captions
F_SWITCH_LABEL = (FF_CN, 13)         # toggle switch text
F_SWITCH_VAL = (FF_CN, 12)           # inline sub-input labels

# ── Window ──
WIN_W = 460
WIN_H = 780

# ── Operators ──
OPERATORS = ("中国电信", "中国联通", "校园用户")

# ── App meta ──
VERSION = "1.0.0"
