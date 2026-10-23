@echo off
setlocal
cd /d "%~dp0\.."
if exist "C:\Program Files\Docker\Docker\resources\bin" set "PATH=C:\Program Files\Docker\Docker\resources\bin;C:\Program Files\Docker\Docker;%PATH%"
echo ========================================================
echo Building Expo Design AI Container Sandbox Image (Option B)
echo Image Target: expodesignai-sandbox:latest
echo ========================================================

set ENGINE=
docker --version >nul 2>&1
if not errorlevel 1 (
    set ENGINE=docker
) else if exist "C:\Program Files\Docker\Docker\resources\bin\docker.exe" (
    set "ENGINE=C:\Program Files\Docker\Docker\resources\bin\docker.exe"
) else if exist "C:\Program Files\Docker\Docker\docker.exe" (
    set "ENGINE=C:\Program Files\Docker\Docker\docker.exe"
) else (
    podman --version >nul 2>&1
    if not errorlevel 1 (
        set ENGINE=podman
    ) else if exist "C:\Program Files\RedHat\Podman\podman.exe" (
        set "ENGINE=C:\Program Files\RedHat\Podman\podman.exe"
    )
)

if "%ENGINE%"=="" (
    echo [ERROR] Neither Docker nor Podman was found on PATH or in Program Files.
    echo Please install Docker Desktop:
    echo   winget install Docker.DockerDesktop
    echo Or install Podman:
    echo   winget install RedHat.Podman
    echo Then start the application and re-run this script.
    if "%~1"=="" pause
    exit /b 1
)

echo Using container engine: %ENGINE%
"%ENGINE%" build -f docker\Dockerfile.sandbox -t expodesignai-sandbox:latest .
if errorlevel 1 (
    echo [ERROR] Container image build failed. Verify that Docker/Podman daemon is running.
    if "%~1"=="" pause
    exit /b 1
)

echo.
echo [SUCCESS] Container sandbox image 'expodesignai-sandbox:latest' is ready!
if "%~1"=="" pause
