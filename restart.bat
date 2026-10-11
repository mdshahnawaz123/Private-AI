@echo off
setlocal
cd /d "%~dp0"
echo Stopping any running Expo Design AI server and starting a fresh one...
echo (Use this after a code change. start.bat will just reuse an already-running server.)
powershell.exe -NoProfile -File "%~dp0start_local.ps1" -OpenBrowser -Restart
set "launch_result=%ERRORLEVEL%"
if not "%launch_result%"=="0" (
    echo.
    echo Restart failed. Read the message above before closing this window.
    pause
)
exit /b %launch_result%
