# PClip remote tunnel launcher
# Starts the app locally and exposes it via a free Cloudflare tunnel
# (no account, no credit card). Gives you a public https URL.
#
# Usage:  .\pclip-tunnel.bat
#
# Note: the random URL changes every time you run this. For a stable URL
# use Tailscale Funnel (free account) instead.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$port = if ($env:PORT) { [int]$env:PORT } else { 8899 }

# --- 1. Ensure venv + deps -------------------------------------------------
if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "Setting up virtual environment..."
    python -m venv venv
}
& "venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if (-not $env:PCLIP_NO_UPDATE) {
    & "venv\Scripts\python.exe" -m pip install -q -U yt-dlp 2>$null
}

# --- 2. Download cloudflared if missing -----------------------------------
$cf = Join-Path $PSScriptRoot "cloudflared.exe"
if (-not (Test-Path $cf)) {
    Write-Host "Downloading cloudflared (one-time)..."
    $url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Invoke-WebRequest -Uri $url -OutFile $cf -UseBasicParsing
}

# --- 3. Start the app in the background -----------------------------------
$env:HOST = "127.0.0.1"
$env:PCLIP_AUTO_OPEN = "0"
$appProc = Start-Process -FilePath "venv\Scripts\python.exe" `
    -ArgumentList "app.py" -PassThru -WindowStyle Hidden
Write-Host ""
Write-Host "  App started (PID $($appProc.Id)) on http://localhost:$port"

# --- 4. Start cloudflared tunnel and print the public URL -----------------
$logFile = Join-Path $env:TEMP "pclip-cloudflared.log"
$tunnelProc = Start-Process -FilePath $cf `
    -ArgumentList "tunnel","--url","http://localhost:$port","--no-autoupdate" `
    -PassThru -WindowStyle Hidden -RedirectStandardError $logFile

Write-Host "  Waiting for public URL..."
$publicUrl = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Path $logFile) {
        $content = Get-Content $logFile -Raw -ErrorAction SilentlyContinue
        if ($content -match "https://[a-zA-Z0-9-]+\.trycloudflare\.com") {
            $publicUrl = $Matches[0]
            break
        }
    }
}

Write-Host ""
if ($publicUrl) {
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host "   PClip is live at:  $publicUrl" -ForegroundColor Green
    Write-Host "   Open this URL on ANY device (phone, laptop, anywhere)." -ForegroundColor Green
    Write-Host "  ============================================================" -ForegroundColor Cyan
} else {
    Write-Host "  Could not detect the public URL. Check the log: $logFile" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  Keep this window open. Press Ctrl+C to stop."
Write-Host ""

# Cleanup on exit
try {
    while (-not $appProc.HasExited) { Start-Sleep -Seconds 2 }
} finally {
    if (-not $tunnelProc.HasExited) { Stop-Process -Id $tunnelProc.Id -Force -ErrorAction SilentlyContinue }
    if (-not $appProc.HasExited)    { Stop-Process -Id $appProc.Id -Force -ErrorAction SilentlyContinue }
}
