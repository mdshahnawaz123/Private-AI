@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -File "%~dp0start_local.ps1" -OpenBrowser
set "launch_result=%ERRORLEVEL%"
if not "%launch_result%"=="0" (
    echo.
    echo Startup failed. Read the message above before closing this window.
    pause
)
exit /b %launch_result%
