@echo off
chcp 65001 >nul
rem 桂桂 v2 构建脚本:venv + 依赖 + 测试 + PyInstaller(+ 可选 Inno 安装器)
rem 在仓库根生成 dist\guigui\guigui.exe(必须 CRLF 行尾,cmd 不认 LF-only 批处理)
setlocal
cd /d %~dp0..

if not exist .venv-guigui python -m venv .venv-guigui
call .venv-guigui\Scripts\activate.bat

python -m pip install -q -r guigui\requirements.txt pyinstaller pytest
if errorlevel 1 goto :err

python -m pytest guigui\tests -q
if errorlevel 1 goto :err_test

pyinstaller guigui\guigui.spec --noconfirm --distpath dist --workpath build
if errorlevel 1 goto :err

echo.
echo === BUILD OK: dist\guigui\guigui.exe ===

if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" guigui\setup.iss
    echo installer: guigui\Output\guigui-setup-*.exe
) else (
    echo [hint] Inno Setup 6 not found, skip installer; run dist\guigui\guigui.exe directly
)
goto :eof

:err_test
echo TESTS FAILED
exit /b 1

:err
echo BUILD FAILED
exit /b 1
