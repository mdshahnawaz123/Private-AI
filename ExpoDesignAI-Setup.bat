@echo off
setlocal EnableDelayedExpansion
title Expo Design AI — Production Setup
color 0B
cd /d "%~dp0"

echo.
echo  ==============================================================
echo        EXPO DESIGN AI  —  One-Click Production Launcher
echo       Offline RAG  ·  Dubai Engineering  ·  Typesafe AI
echo  ==============================================================
echo.
echo  This will install everything automatically for you.
echo.

REM ── Run the PowerShell installer ──
powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"
