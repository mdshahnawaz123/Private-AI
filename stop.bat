@echo off
setlocal
cd /d "%~dp0"
echo ========================================================
echo Stopping Expo Design AI & AI Studio Engine...
echo ========================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_all.ps1"
echo.
timeout /t 3 >nul
