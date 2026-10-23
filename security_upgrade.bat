@echo off
REM Security upgrade (2026-10-21): patched versions of Pillow, aiohttp, urllib3, certifi.
REM Run with the server stopped, then start it again with restart.bat.
py -3.12 -m pip install "pillow==13.0.0" "aiohttp==3.14.4" "urllib3==2.8.0" "certifi==2026.10.19"
if errorlevel 1 (echo Upgrade failed - see the message above. & pause & exit /b 1)
py -3.12 -c "import PIL, aiohttp, urllib3, certifi; print('OK Pillow', PIL.__version__, 'aiohttp', aiohttp.__version__, 'urllib3', urllib3.__version__)"
pause
