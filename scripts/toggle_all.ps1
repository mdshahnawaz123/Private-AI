# Toggle Expo Design AI Server: starts if stopped, stops if running
$port = 8090
$isRunning = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)

if ($isRunning) {
    Write-Host "========================================================" -ForegroundColor Yellow
    Write-Host " Expo Design AI is currently RUNNING." -ForegroundColor Yellow
    Write-Host " Stopping all services now..." -ForegroundColor Yellow
    Write-Host "========================================================" -ForegroundColor Yellow
    & "$PSScriptRoot\stop_all.ps1"
    Start-Sleep -Seconds 2
} else {
    Write-Host "========================================================" -ForegroundColor Green
    Write-Host " Expo Design AI is STOPPED." -ForegroundColor Green
    Write-Host " Starting Expo Design AI server & opening browser..." -ForegroundColor Green
    Write-Host "========================================================" -ForegroundColor Green
    $projectRoot = Split-Path -Parent $PSScriptRoot
    & "$projectRoot\start_local.ps1" -OpenBrowser -Restart
}
