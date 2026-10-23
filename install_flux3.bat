@echo off
setlocal EnableExtensions
title Install FLUX 3 Image Klein for Expo Design AI
set "COMFY=C:\3EH\ComfyUI"
set "PY=%COMFY%\venv\Scripts\python.exe"
set "HF=%COMFY%\venv\Scripts\hf.exe"
set "REPO=black-forest-labs/flux-3-image-klein-comfy"
set "DL=%COMFY%\models\_flux3_download"

echo.
echo ================================================================
echo  FLUX 3 Image Klein installer  (nothing is deleted by this script)
echo ================================================================
echo  BEFORE CONTINUING: open this page in your browser, log in to
echo  Hugging Face and click "Agree" on the FLUX Kommunity License:
echo     https://huggingface.co/%REPO%
echo.
pause

echo.
echo [1/5] Stopping ComfyUI (port 8188) if it is running...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8188" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1

echo [2/5] Checking ComfyUI version (needs v0.41.0 or newer for FLUX 3)...
"%PY%" -c "import sys; sys.path.insert(0, r'%COMFY%'); import comfyui_version as v; p=tuple(int(x) for x in v.__version__.split('.')[:2]); sys.exit(0 if p>=(0,41) else 1)" && goto :step3
git -C "%COMFY%" checkout -- . || goto :fail
git -C "%COMFY%" pull --ff-only || goto :fail
"%PY%" -m pip install --upgrade -r "%COMFY%\requirements.txt" || goto :fail
"%PY%" -c "import sys; sys.path.insert(0, r'%COMFY%'); import comfyui_version as v; print('ComfyUI version', v.__version__)"

:step3
echo [3/5] Hugging Face login (you type your own token if asked)...
"%HF%" auth whoami >nul 2>&1 || "%HF%" auth login || goto :fail

echo [4/5] Downloading FLUX 3 Image Klein (distilled, int8) + text encoder (several GB)...
"%HF%" download %REPO% diffusion_models/flux3-image-klein-int8-convrot.safetensors text_encoders/qwen3vl_4b_int8_convrot.safetensors --local-dir "%DL%" || goto :fail

echo [5/5] Moving files into ComfyUI model folders...
if exist "%DL%\diffusion_models\flux3-image-klein-int8-convrot.safetensors" move /Y "%DL%\diffusion_models\flux3-image-klein-int8-convrot.safetensors" "%COMFY%\models\diffusion_models\" >nul
if exist "%DL%\text_encoders\qwen3vl_4b_int8_convrot.safetensors" move /Y "%DL%\text_encoders\qwen3vl_4b_int8_convrot.safetensors" "%COMFY%\models\text_encoders\" >nul
if not exist "%COMFY%\models\diffusion_models\flux3-image-klein-int8-convrot.safetensors" goto :fail
if not exist "%COMFY%\models\text_encoders\qwen3vl_4b_int8_convrot.safetensors" goto :fail
if not exist "%COMFY%\models\vae\flux2-vae.safetensors" echo WARNING: flux2-vae.safetensors is missing - FLUX 3 needs it.
dir "%COMFY%\models\diffusion_models\flux3*" "%COMFY%\models\text_encoders\qwen3vl*"

echo.
echo DONE. FLUX 3 files are installed. Now run restart.bat, then tell Claude "flux3 installed".
pause
exit /b 0

:fail
echo.
echo *** Something failed above. Nothing was deleted. Copy the error text and send it to Claude. ***
pause
exit /b 1
