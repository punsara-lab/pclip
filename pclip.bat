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

set "HOST=0.0.0.0"
if not defined PORT set "PORT=8899"

echo.
echo   PClip starting...
echo   (auto-opening browser; remote access control is in the web UI)
echo.

"venv\Scripts\python.exe" app.py
echo.
echo   PClip stopped.
pause
