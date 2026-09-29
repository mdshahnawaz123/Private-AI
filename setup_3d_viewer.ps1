# ============================================================
#  Expo Design AI - 3D Viewer engine setup (run ONCE)
#  Downloads the open BIM engine (web-ifc + three.js) into
#  ui\vendor so the 3D Review tab works 100% offline afterwards.
#  Your PC needs internet only for this one-time download.
# ============================================================
$ErrorActionPreference = "Stop"
$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$vendor = Join-Path $root "ui\vendor"
New-Item -ItemType Directory -Force -Path $vendor | Out-Null

$THREE = "0.160.1"
$WEBIFC = "0.0.57"

# name  ->  list of candidate URLs (tries each until one works)
$files = @(
  @{ name="three.module.js";   urls=@("https://cdn.jsdelivr.net/npm/three@$THREE/build/three.module.js","https://unpkg.com/three@$THREE/build/three.module.js") },
  @{ name="OrbitControls.js";  urls=@("https://cdn.jsdelivr.net/npm/three@$THREE/examples/jsm/controls/OrbitControls.js","https://unpkg.com/three@$THREE/examples/jsm/controls/OrbitControls.js") },
  @{ name="web-ifc-api.js";    urls=@("https://cdn.jsdelivr.net/npm/web-ifc@$WEBIFC/web-ifc-api.js","https://unpkg.com/web-ifc@$WEBIFC/web-ifc-api.js") },
  @{ name="web-ifc.wasm";      urls=@("https://cdn.jsdelivr.net/npm/web-ifc@$WEBIFC/web-ifc.wasm","https://unpkg.com/web-ifc@$WEBIFC/web-ifc.wasm") }
)

Write-Host ""
Write-Host "  Expo Design AI - downloading 3D engine into ui\vendor ..." -ForegroundColor Cyan
Write-Host ""
$ok = $true
foreach ($f in $files) {
  $out = Join-Path $vendor $f.name
  $done = $false
  foreach ($u in $f.urls) {
    try {
      Write-Host ("  [..] " + $f.name + "  <-  " + $u)
      Invoke-WebRequest -Uri $u -OutFile $out -UseBasicParsing -TimeoutSec 120
      $sz = [math]::Round((Get-Item $out).Length/1KB,0)
      Write-Host ("  [OK] " + $f.name + "  (" + $sz + " KB)") -ForegroundColor Green
      $done = $true; break
    } catch {
      Write-Host ("  [--] failed from that source, trying next...") -ForegroundColor DarkYellow
    }
  }
  if (-not $done) { Write-Host ("  [ERROR] Could not download " + $f.name) -ForegroundColor Red; $ok = $false }
}

Write-Host ""
if ($ok) {
  Write-Host "  DONE. The 3D engine is now installed locally." -ForegroundColor Green
  Write-Host "  From now on the 3D Review tab runs fully offline." -ForegroundColor Green
  Write-Host "  Restart the app (start.bat) and open the 3D Review tab." -ForegroundColor Green
} else {
  Write-Host "  Some files did not download. Check your internet and re-run this script," -ForegroundColor Red
  Write-Host "  or tell Claude which file failed and we will adjust the version." -ForegroundColor Red
}
Write-Host ""
