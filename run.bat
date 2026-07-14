@echo off
title OverlineEdge v8
color 0A
echo =============================================
echo  OverlineEdge Odds Dashboard v8
echo  (No Docker. No compiler. No API keys.)
echo =============================================
echo.

REM ---- Stay in the folder where run.bat lives ----
cd /d "%~dp0"

echo [Checking Python version...]
python --version 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from https://www.python.org/downloads/
    echo Make sure "Add Python to PATH" is checked during install.
    pause
    exit /b 1
)

echo.
echo [Step 0] Upgrading pip...
python -m pip install --upgrade pip --quiet

echo.
echo [Step 1/3] Installing Python dependencies (pre-built wheels only)...
python -m pip install -r requirements.txt --prefer-binary --upgrade
if errorlevel 1 (
    echo.
    echo ============================================================
    echo  INSTALL FAILED. See error above. Copy this window and
    echo  report the full text.
    echo ============================================================
    pause
    exit /b 1
)

echo.
echo [Step 2/3] Installing Playwright Chromium (~100MB one-time)...
python -m playwright install chromium
if errorlevel 1 (
    echo WARN: Playwright browser install issue. Scraping may be limited.
)

echo.
echo =============================================
echo  DONE. Starting OverlineEdge server...
echo.
echo  After the server starts, open in Chrome or Edge:
echo    Double-click odds_dashboard_v8.html
echo.
echo  Health check : http://127.0.0.1:8000/api/health
echo  Live trace   : http://127.0.0.1:8000/api/diagnostics/live
echo  Diag summary : http://127.0.0.1:8000/api/diagnostics/run
echo  Diag download: http://127.0.0.1:8000/api/diagnostics/download
echo  Export CSV   : http://127.0.0.1:8000/api/export/all
echo =============================================
echo.

echo [Step 3/3] Starting server...
python -m uvicorn main:app --reload --port 8000

echo.
echo SERVER EXITED. See error above if unexpected.
pause
