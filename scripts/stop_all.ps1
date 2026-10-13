# Cleanly stop Expo Design AI server (port 8090) and ComfyUI (port 8188)
$ErrorActionPreference = 'SilentlyContinue'
$ports = @(8090, 8188)
$stopped = 0

foreach ($p in $ports) {
    $connections = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $connections) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Stopping $($proc.ProcessName) (PID $($proc.Id)) on port $p..." -ForegroundColor Yellow
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            $stopped++
        }
    }
}

if ($stopped -gt 0) {
    Write-Host "Expo Design AI and AI Studio Engine stopped successfully." -ForegroundColor Green
} else {
    Write-Host "No running Expo Design AI services were detected." -ForegroundColor Cyan
}
