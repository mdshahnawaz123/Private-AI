@echo off
setlocal EnableDelayedExpansion
title Expo Design AI - Launcher
color 0B
cd /d "%~dp0"

echo.
echo  ============================================================
echo    EXPO DESIGN AI  -  Local RAG Launcher
echo  ============================================================
echo.

REM ---------- 0. Stop any previous Expo backend (frees port 8090 so NEW code loads) ----------
echo  [..] Stopping any previous Expo backend...
taskkill /F /IM python.exe >nul 2>&1
REM give the OS a moment to release port 8090
timeout /t 2 /nobreak >nul
echo  [OK] Previous backend stopped (if any was running).

REM ---------- 1. Ollama check ----------
where ollama >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Ollama not found in PATH.
    pause & exit /b 1
)
echo  [OK] Ollama detected.

REM ---------- 2. Ollama server ----------
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I "ollama.exe" >NUL
if errorlevel 1 (
    echo  [..] Starting Ollama server...
    set OLLAMA_ORIGINS=*
    start "Ollama Server" /min cmd /c "set OLLAMA_ORIGINS=* && set OLLAMA_MAX_LOADED_MODELS=1 && set OLLAMA_KEEP_ALIVE=5m && ollama serve"
    timeout /t 5 /nobreak >nul
) else (
    echo  [OK] Ollama server already running.
)

REM ---------- 3. Python check ----------
where python >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found in PATH.
    pause & exit /b 1
)
echo  [OK] Python detected.

REM ---------- 4. Install packages (uses --user to avoid admin) ----------
echo  [..] Installing required packages...
python -m pip install --upgrade pip --quiet
python -m pip install --user --quiet -r requirements.txt
if errorlevel 1 (
    echo  [ERROR] Package installation failed.
    pause & exit /b 1
)
echo  [OK] Packages installed.

REM ---------- 4b. Fragments converter deps (optional, best-effort) ----------
REM Enables lightweight .frag compression of uploaded IFC models. Never fatal:
REM if Node/npm is missing or install fails, uploads still work (raw IFC kept).
if exist "tools\fragments\node_modules" (
    echo  [OK] Fragments converter ready.
) else (
    where node >nul 2>&1 && where npm >nul 2>&1
    if errorlevel 1 (
        echo  [..] Node/npm not found - skipping IFC compression setup ^(optional^).
    ) else (
        echo  [..] Installing Fragments converter ^(one-time, enables IFC compression^)...
        pushd tools\fragments
        call npm install --no-audit --no-fund >nul 2>&1
        if errorlevel 1 ( echo  [..] Fragments converter install skipped ^(optional^). ) else ( echo  [OK] Fragments converter installed. )
        popd
    )
)

REM ---------- 5. Check models ----------
echo  [..] Checking models...
ollama list | findstr /C:"bge-m3" >nul
if errorlevel 1 (
    echo  [..] Pulling bge-m3 embedding model...
    ollama pull bge-m3
)
ollama list | findstr /C:"qwen2.5vl:32b" >nul
if errorlevel 1 (
    echo  [..] Pulling qwen2.5vl:32b vision model ^(~20 GB, this takes a while^)...
    ollama pull qwen2.5vl:32b
)
echo  [OK] Models ready.

REM ---------- 6. Start FastAPI ----------
echo  [..] Starting backend on http://127.0.0.1:8090
start "Expo RAG Backend" /min cmd /c "cd /d %~dp0 && python main.py"

REM ---------- 7. Wait, open the V2 UI ----------
timeout /t 6 /nobreak >nul
start "" "http://127.0.0.1:8090/ui/app.html"

REM ---------- 7b. Health check (confirms the LATEST build is serving) ----------
echo  [..] Opening health check ^(should return JSON if this is the latest build^)...
start "" "http://127.0.0.1:8090/health/full"

echo.
echo  ============================================================
echo    Expo Design AI is RUNNING
echo    UI:  http://127.0.0.1:8090/ui/app.html
echo    API: http://127.0.0.1:8090/docs
echo    Verify latest: http://127.0.0.1:8090/health/full  ^(404 = old folder^)
echo  ============================================================
echo.
echo  Press any key to close this launcher...
pause >nul
