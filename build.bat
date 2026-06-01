@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   SchoolAutoLogin Build Script
echo ============================================
echo.

:: ---- Check PyInstaller ----

echo [Check] PyInstaller...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo         Installing PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo ERROR: PyInstaller install failed!
        pause
        exit /b 1
    )
) else (
    echo         OK
)

:: ---- Check / Install Inno Setup 6 ----

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo         Inno Setup 6 not found, downloading...
    powershell -Command "Invoke-WebRequest -Uri 'https://files.jrsoftware.org/is/6/innosetup-6.4.3.exe' -OutFile '%TEMP%\innosetup.exe'"
    if errorlevel 1 (
        echo ERROR: Download failed!
        pause
        exit /b 1
    )
    echo         Installing Inno Setup 6 (silent)...
    start /wait "" "%TEMP%\innosetup.exe" /VERYSILENT /NORESTART /SP-
    del "%TEMP%\innosetup.exe" >nul 2>&1
    if not exist "%ISCC%" (
        echo ERROR: Inno Setup install failed!
        pause
        exit /b 1
    )
    echo         OK
) else (
    echo         OK
)

:: ---- Clean ----

echo.
echo [1/4] Cleaning...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist installer_output rmdir /s /q installer_output

:: ---- PyInstaller ----

echo.
echo [2/4] PyInstaller...
pyinstaller main.spec
if errorlevel 1 (
    echo ERROR: PyInstaller failed!
    pause
    exit /b 1
)

:: ---- Prepare dist ----

echo.
echo [3/4] Preparing dist...
copy config.json dist\config.json >nul

:: ---- Inno Setup ----

echo.
echo [4/4] Inno Setup...
"%ISCC%" setup.iss
if errorlevel 1 (
    echo ERROR: Inno Setup compile failed!
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Done!
echo   Output: installer_output\SchoolAutoLogin_Setup_1.0.0.exe
echo ============================================
pause
