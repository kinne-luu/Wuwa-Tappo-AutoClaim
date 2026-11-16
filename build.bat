@echo off
chcp 65001 >nul
title Building Wuwa Tappo Auto Claim - PyInstaller
cd /d "%~dp0"

echo ===================================================
echo   Building WuwaTappoAutoClaim.exe (Pure Console)
echo ===================================================

taskkill /F /IM WuwaTappoAutoClaim.exe >nul 2>nul

py -m PyInstaller --clean --noconfirm --onefile --console ^
    --icon="assets\Zani-Icon.ico" ^
    --add-data="assets;assets" ^
    --collect-data certifi ^
    --name="WuwaTappoAutoClaim" ^
    app.py

if errorlevel 1 (
    echo.
    echo [!] Build failed! Please check errors above.
    exit /b 1
)

echo.
echo Copying executable to workspace root...
if exist "dist\WuwaTappoAutoClaim.exe" (
    copy /y "dist\WuwaTappoAutoClaim.exe" "WuwaTappoAutoClaim.exe" >nul
    echo [+] Success: WuwaTappoAutoClaim.exe is ready!
)

echo ===================================================
echo   Build Complete!
echo ===================================================
