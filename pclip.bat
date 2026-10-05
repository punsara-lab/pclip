@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python is required but was not found on PATH.
    exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo FFmpeg is required but was not found on PATH.
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo Setting up virtual environment...
    python -m venv venv
    if errorlevel 1 exit /b 1
)

"venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 exit /b 1

if not defined PCLIP_NO_UPDATE (
    echo Updating yt-dlp...
    "venv\Scripts\python.exe" -m pip install -q -U yt-dlp || echo   (couldn't update yt-dlp - continuing with the installed version)
)

if not defined PORT set "PORT=8899"
echo.
echo   PClip is running at http://localhost:%PORT%
echo   Opening browser in 2 seconds...
echo.

start "" powershell -NoProfile -NonInteractive -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process http://localhost:%PORT%"

"venv\Scripts\python.exe" app.py

