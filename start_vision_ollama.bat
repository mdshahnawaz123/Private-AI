@echo off
setlocal
cd /d "%~dp0"
echo Starting a second, dedicated Ollama instance for vision (Pilot blueprint Sec 6.2).
echo This is OPTIONAL -- the app works fine without it on the single default Ollama instance.
powershell.exe -NoProfile -File "%~dp0start_vision_ollama.ps1" %*
set "launch_result=%ERRORLEVEL%"
if not "%launch_result%"=="0" (
    echo.
    echo Could not start the vision Ollama instance. Read the message above.
    pause
)
exit /b %launch_result%
