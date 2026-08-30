# -*- mode: python ; coding: utf-8 -*-
"""桂桂 v2 PyInstaller spec — onedir / windowed,单 exe 双模式(GUI / --ensure)。

构建(在仓库根执行,或直接跑 guigui\\build_guigui.bat):
    pyinstaller guigui/guigui.spec --noconfirm --distpath dist --workpath build
"""

from pathlib import Path

GUIGUI_DIR = Path(SPECPATH)            # .../guigui
PROJECT_ROOT = GUIGUI_DIR.parent       # 仓库根(保证 `import guigui` 可解析)

static = GUIGUI_DIR / "app" / "static"


def _static_datas():
    """static 全量打包,但排除 dev/ 目录(契约 1.0.1:mock 只许活在开发目录)。"""
    if not static.exists():
        return []
    out = []
    for p in static.rglob("*"):
        rel = p.relative_to(static)
        if p.is_file() and "dev" not in rel.parts:
            out.append((str(p), "guigui/app/static/" + str(rel.parent)))
    return out


datas = _static_datas()

a = Analysis(
    [str(GUIGUI_DIR / "__main__.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "webview.platforms.edgechromium",   # WebView2 后端
        "keyring.backends.Windows",         # 凭据管理器后端
    ],
    excludes=["tkinter", "pytest", "pywebview.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="guigui",
    debug=False,
    strip=False,
    upx=False,
    console=False,     # windowed;--ensure 同一无窗入口
    icon=None,         # TODO 图标资产定稿后补
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="guigui")
