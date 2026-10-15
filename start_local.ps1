param([switch]$OpenBrowser, [switch]$Restart)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# Offline startup: dependencies and model weights must already be provisioned.
# Never kill unrelated processes, install packages, or download model weights.
# -Restart is the ONE exception, and even then a process is stopped only after
# a live HTTP health check on that exact port confirms it is THIS app
# (service: expo-design-ai, status: ready) -- never "whatever is on the port".
# That HTTP identity check is the authority here, not a Win32_Process command-
# line match: CommandLine is frequently returned as $null by WMI for another
# user/session's process (a Windows permission quirk, not a security check we
# can rely on), so requiring it would make -Restart silently never work rather
# than failing safe in a way anyone would notice.
# Resolve the Python this project was actually built/locked against (3.12)
# via the `py` launcher, which is immune to PATH ordering. If the launcher has
# no registered runtimes, check the standard per-user/per-machine Python 3.12
# install locations before a generic PATH fallback. A bare
# `Get-Command python.exe` picks up WHATEVER python.exe is first on PATH --
# this broke startup on 2026-10-08 when a separate tool's Python 3.10 landed
# ahead of this project's 3.12, silently selecting an interpreter without the
# project's dependencies. The fallback remains for older installations, but
# emits a warning when it cannot select Python 3.12.
$python = $null
try {
    $pyLauncherPath = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null)
    if ($pyLauncherPath) { $pyLauncherPath = $pyLauncherPath.Trim() }
    if ($pyLauncherPath -and (Test-Path $pyLauncherPath)) { $python = $pyLauncherPath }
} catch { }
if (-not $python) {
    $python312Candidates = @()
    if ($env:LOCALAPPDATA) {
        $python312Candidates += Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    }
    if ($env:USERPROFILE) {
        $python312Candidates += Join-Path $env:USERPROFILE 'AppData\Local\Programs\Python\Python312\python.exe'
    }
    if ($env:ProgramFiles) {
        $python312Candidates += Join-Path $env:ProgramFiles 'Python312\python.exe'
    }
    foreach ($candidate in $python312Candidates) {
        if (-not (Test-Path $candidate)) { continue }
        try {
            $candidateVersion = (& $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null)
            if ($LASTEXITCODE -eq 0 -and $candidateVersion.Trim() -eq '3.12') {
                $python = $candidate
                break
            }
        } catch { }
    }
}
if (-not $python) {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
    Write-Warning "py -3.12 launcher unavailable; falling back to PATH python.exe ($python). If this project needs 3.12 specifically, verify this interpreter has its dependencies installed."
}

$settingsJson = @'
import json
from config import get_settings, resolve_role
s=get_settings()
# Pilot architecture blueprint Sec 6.2: each role resolves its own model name
# + serving endpoint; vision can live on a separate Ollama process/port from
# chat/embed without any change here.
roles={r: resolve_role(r) for r in ('vision','chat','embed')}
print(json.dumps({'port':s.port,'data':s.data_dir,'roles':roles}))
'@ | & $python -
if ($LASTEXITCODE -ne 0) { throw 'Application configuration is invalid.' }
$settings = $settingsJson | ConvertFrom-Json
$serviceUrl = "http://127.0.0.1:$($settings.port)"
function Show-LocalService {
    Write-Host "Local service ready: $serviceUrl/ui/classic.html"
    if ($OpenBrowser) {
        try { Start-Process -FilePath "$serviceUrl/ui/classic.html" }
        catch { Write-Warning "Could not open your browser. Open $serviceUrl/ui/classic.html manually." }
    }
}
if (Get-NetTCPConnection -LocalPort $settings.port -State Listen -ErrorAction SilentlyContinue) {
    $ownerPids = @(Get-NetTCPConnection -LocalPort $settings.port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)

    $isOurs = $false
    try {
        $live = Invoke-RestMethod -Uri "$serviceUrl/health/live" -TimeoutSec 5
        if ($live.service -eq 'expo-design-ai') {
            $isOurs = $true
        }
    } catch { }

    # If HTTP check did not reply (e.g. server was busy, hung, or reloading), verify if the listening process is our python server
    if (-not $isOurs) {
        foreach ($procId in $ownerPids) {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
            if ($proc -and $proc.Name -eq 'python.exe') {
                if (-not $proc.CommandLine -or $proc.CommandLine -match 'main\.py' -or $proc.CommandLine -match 'ExpoDesignAI') {
                    $isOurs = $true
                    break
                }
            }
        }
    }

    if ($isOurs -and -not $Restart) {
        Write-Host 'Expo Design AI is already running.'
        Write-Host '(Code changes on disk are NOT picked up by an already-running server.'
        Write-Host ' Run restart.bat instead of start.bat to pick up a code change.)'
        Show-LocalService
        exit 0
    }
    if ($isOurs -and $Restart) {
        $stopped = $false
        foreach ($procId in $ownerPids) {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
            if ($proc -and $proc.Name -and $proc.Name -ne 'python.exe') {
                Write-Warning "PID $procId on port $($settings.port) is '$($proc.Name)', not python.exe -- skipping it, not stopping."
                continue
            }
            try {
                Write-Host "Stopping the running Expo Design AI server (PID $procId) before restart..."
                Stop-Process -Id $procId -Force -ErrorAction Stop
                $stopped = $true
            } catch {
                Write-Warning "Could not stop PID $procId`: $($_.Exception.Message)"
            }
        }
        if (-not $stopped) {
            throw "Port $($settings.port) is serving Expo Design AI, but its process could not be stopped (see warnings above). Close it manually, then run start.bat."
        }
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            if (-not (Get-NetTCPConnection -LocalPort $settings.port -State Listen -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Seconds 1
        }
        if (Get-NetTCPConnection -LocalPort $settings.port -State Listen -ErrorAction SilentlyContinue) {
            throw "Port $($settings.port) is still in use after stopping the previous server. Close it manually and try again."
        }
    } elseif (-not $isOurs) {
        throw "Port $($settings.port) is in use, but a healthy Expo Design AI service could not be confirmed. No process was stopped."
    }
}
& $python -c 'import fastapi, sqlalchemy, faiss, fitz, httpx, pydantic_settings'
if ($LASTEXITCODE -ne 0) { throw 'Required Python dependencies are missing. Provision the environment before startup.' }
# Check each DISTINCT role endpoint once (today that's one Ollama instance;
# after standing up a second one for vision per Sec 6.2, this checks both).
$hostsToModels = @{}
foreach ($roleName in $settings.roles.PSObject.Properties.Name) {
    $role = $settings.roles.$roleName
    $exactTag = if ($role.model.Contains(':')) { $role.model } else { $role.model + ':latest' }
    if (-not $hostsToModels.ContainsKey($role.base_url)) { $hostsToModels[$role.base_url] = @() }
    $hostsToModels[$role.base_url] += $exactTag
}
# Start Ollama itself if it isn't already running on a LOCAL endpoint this
# script's own role config points at. This is not "installing packages or
# downloading model weights" (still never done automatically) -- it's just
# starting an already-installed local background service, the same way this
# script already starts/stops its own server process. Added 2026-10-08/09
# after repeated manual restarts failing here with "Unable to connect to the
# remote server" simply because Ollama's service had stopped in the
# background; `ollama serve` is idempotent/harmless to call against an
# instance that's already up (it just fails to bind and exits), so this only
# acts when the endpoint is confirmed unreachable first.
foreach ($baseUrl in @($hostsToModels.Keys)) {
    $uri = [System.Uri]$baseUrl
    if ($uri.Host -notin @('127.0.0.1', 'localhost')) { continue }
    try {
        Invoke-RestMethod -Uri ($baseUrl.TrimEnd('/') + '/api/tags') -TimeoutSec 5 | Out-Null
        continue
    } catch { }
    $ollamaCmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if (-not $ollamaCmd) { $ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue }
    if (-not $ollamaCmd) {
        throw "Ollama at $baseUrl is not reachable and the 'ollama' command was not found on PATH. Start Ollama manually, then run start.bat again."
    }
    Write-Host "Ollama at $baseUrl is not responding -- starting it..."
    Start-Process -FilePath $ollamaCmd.Source -ArgumentList 'serve' -WindowStyle Hidden
    $ollamaUp = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        try {
            Invoke-RestMethod -Uri ($baseUrl.TrimEnd('/') + '/api/tags') -TimeoutSec 5 | Out-Null
            $ollamaUp = $true
            break
        } catch { }
    }
    if (-not $ollamaUp) {
        throw "Started 'ollama serve' but $baseUrl still isn't responding after 30s. Check Ollama manually, then run start.bat again."
    }
    Write-Host "Ollama is up."
}
foreach ($baseUrl in $hostsToModels.Keys) {
    $tags = Invoke-RestMethod -Uri ($baseUrl.TrimEnd('/') + '/api/tags') -TimeoutSec 10
    $available = @($tags.models | ForEach-Object { $_.name })
    foreach ($exactTag in ($hostsToModels[$baseUrl] | Select-Object -Unique)) {
        if ($exactTag -notin $available) { throw "Required local model is missing on $baseUrl`: $exactTag. Provision it before startup." }
    }
}
$logRoot = [System.IO.Path]::GetFullPath($settings.data)
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

# Auto-start AI Studio Engine (ComfyUI) in background if not already running
$comfyDir = "C:\3EH\ComfyUI"
if (Test-Path (Join-Path $comfyDir "main.py")) {
    $comfyPortListening = (Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue)
    if (-not $comfyPortListening) {
        $comfyPy = Join-Path $comfyDir "venv\Scripts\python.exe"
        if (-not (Test-Path $comfyPy)) { $comfyPy = $python }
        Start-Process -FilePath $comfyPy -ArgumentList 'main.py --listen 127.0.0.1 --port 8188 --highvram' `
            -WorkingDirectory $comfyDir -WindowStyle Hidden
    }
}

Start-Process -FilePath $python -ArgumentList 'main.py' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logRoot 'server.stdout.log') `
    -RedirectStandardError (Join-Path $logRoot 'server.stderr.log')
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$($settings.port)/health/ready" -TimeoutSec 10
        if ($health.status -eq 'ready') {
            Show-LocalService
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 1
}
throw 'The service did not become ready. Inspect data/server.stderr.log.'
