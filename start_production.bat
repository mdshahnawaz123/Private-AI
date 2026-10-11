@echo off
setlocal enabledelayedexpansion
title Expo Design AI - Production Server
cd /d "%~dp0"

echo ======================================================================
echo                 Expo Design AI - Production Launcher
echo ======================================================================
echo.

:: Check if Ollama is running
curl -s http://127.0.0.1:11434/api/version >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Ollama does not appear to be running on http://127.0.0.1:11434.
    echo Please make sure Ollama is started with required models (qwen, bge-m3).
    echo.
)

:: Check if data folder exists, if not create default structure
if not exist "data" (
    echo [SETUP] Initializing data directory structure...
    mkdir "data"
    mkdir "data\docs"
    mkdir "data\projects"
    mkdir "data\faiss_index"
    mkdir "data\recovery"
)

:: Run the compiled binary
echo [START] Launching Expo Design AI production server on port 8090...
echo Access UI at: http://127.0.0.1:8090/ui/classic.html
echo.

start "" "http://127.0.0.1:8090/ui/classic.html"
"dist\ExpoDesignAI\ExpoDesignAI.exe"

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Server terminated with error code %errorlevel%.
    pause
)
