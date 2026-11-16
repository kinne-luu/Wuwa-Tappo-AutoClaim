@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: 1. Uu tien chay truc tiep file exe neu da build (dong cmd launcher ngay de chi co 1 icon duy nhat)
if exist "WuwaTappoAutoClaim.exe" (
    start "" "WuwaTappoAutoClaim.exe" %*
    exit /b 0
)

:: 2. Fallback sang python neu chua build exe
where py >nul 2>&1
if %errorlevel% equ 0 (
    py app.py %*
    if errorlevel 1 pause
    exit /b
)

if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
    "%LOCALAPPDATA%\Python\bin\python.exe" app.py %*
    if errorlevel 1 pause
    exit /b
)

python app.py %*
if errorlevel 1 pause
