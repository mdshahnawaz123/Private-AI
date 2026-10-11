param([int]$Port = 11435)
$ErrorActionPreference = 'Stop'

# Pilot architecture blueprint Sec 6.2: a SECOND Ollama process, bound to its
# own port, dedicated to the vision/ingestion workload (per-page PDF vision
# extraction at upload, plus table/drawing extraction in
# services/vision_adapter.py). This is what keeps a heavy admin upload from
# ever starving a concurrent user's chat request on the main Ollama instance --
# today both share one process and one OLLAMA_MAX_LOADED_MODELS=1 slot, which
# is what caused the ingestion stall observed during a question-batch test.
#
# This is OPTIONAL infrastructure. The app runs fine today on a single Ollama
# instance without this script -- config.resolve_role('vision') only points
# here once EXPO_VISION_OLLAMA_HOST is set (see the instructions this script
# prints below). Nothing else changes.
#
# Same spirit as start_local.ps1: this script does not install anything or
# download model weights. It assumes `ollama` is already installed and the
# vision model is already pulled (or you pull it into this instance the first
# time, per the instructions printed below).

$ollama = (Get-Command ollama.exe -ErrorAction Stop).Source

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Something is already listening on port $Port."
    Write-Host "If that's already this vision Ollama instance, you don't need to run this again."
    Write-Host "Otherwise, stop whatever owns port $Port first, or pass a different -Port."
    exit 1
}

$env:OLLAMA_HOST = "127.0.0.1:$Port"
$env:OLLAMA_MAX_LOADED_MODELS = '1'

Write-Host "Starting a second, dedicated Ollama instance for vision on port $Port..."
Write-Host ""
Write-Host "One-time setup, in a SEPARATE shell (leave this window running the server):"
Write-Host "  `$env:OLLAMA_HOST = '127.0.0.1:$Port'"
Write-Host "  ollama pull qwen2.5vl:7b"
Write-Host ""
Write-Host "Then point the app at this instance before starting it (start.bat / restart.bat):"
Write-Host "  `$env:EXPO_VISION_OLLAMA_HOST = 'http://127.0.0.1:$Port'"
Write-Host ""
Write-Host "Press Ctrl+C to stop this vision Ollama instance."
Write-Host ""

& $ollama serve
