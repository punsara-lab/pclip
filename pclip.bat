@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python is required but was not found on PATH.
    pause
    exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo FFmpeg is required but was not found on PATH.
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo Setting up virtual environment...
    python -m venv venv
    if errorlevel 1 ( pause & exit /b 1 )
)

"venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 ( pause & exit /b 1 )

if not defined PCLIP_NO_UPDATE (
    echo Updating yt-dlp...
    "venv\Scripts\python.exe" -m pip install -q -U yt-dlp || echo   (couldn't update yt-dlp - continuing)
)

:menu
echo.
echo   ============================================
echo    PClip - choose how to serve:
echo   ============================================
echo.
echo     1. Local only      - this PC only
echo     2. Same WiFi       - phone/tablet on same network
echo     3. Anywhere        - public URL via Cloudflare tunnel
echo.
choice /c 123 /n /m "  Select [1/2/3] (default 1): "
set "sel=%ERRORLEVEL%"

if %sel%==3 goto tunnel
if %sel%==2 goto wifi
goto local

:local
set "HOST=127.0.0.1"
goto run

:wifi
set "HOST=0.0.0.0"
goto run

:tunnel
echo.
echo   Starting remote tunnel (access from anywhere)...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pclip-tunnel.ps1"
echo.
echo   Tunnel stopped.
pause
goto menu

:run
set "PCLIP_AUTO_OPEN=0"
if not defined PORT set "PORT=8899"
echo.
echo   Starting PClip...
echo.
"venv\Scripts\python.exe" app.py
echo.
echo   PClip stopped.
pause
goto menu
