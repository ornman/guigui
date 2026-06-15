# -*- mode: python ; coding: utf-8 -*-
import customtkinter as ctk
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

# Collect customtkinter data files (themes, assets)
ctk_data = Path(ctk.__file__).parent

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        (str(ctk_data), 'customtkinter'),
    ] + collect_data_files('PIL'),
    hiddenimports=[
        'src',
        'src.config',
        'src.login',
        'src.notify',
        'src.wifi',
        'src.app',
        'src.ui',
        'src.ui.components',
        'src.ui.theme',
        'src.scheduler',
        'src.autostart',
        'src.instance',
        'src.selfheal',
        'src.ensure',
        'src.tray',
        'customtkinter',
        'pystray._win32',
        'PIL',
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SchoolAutoLogin',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
