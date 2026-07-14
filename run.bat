@echo off
title OverlineEdge v8
color 0A
echo =============================================
echo  OverlineEdge Odds Dashboard v8
echo  (No Docker. No compiler. No API keys.)
echo =============================================
echo.

REM ---- Stay in the folder where run.bat lives (flat layout) ----
cd /d "%~dp0"

echo [Checking Python version...]
python --version 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Python not found!
    echo Install from https://www.python.org/downloads/
    echo Check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo.
echo [Step 1/3] Installing Python dependencies (Python 3.14 compatible)...
python -m pip install -r requirements.txt --prefer-binary
if errorlevel 1 (
    echo.
    echo FAILED: pip install failed.
    echo Try running: python -m pip install --upgrade pip
    pause
    exit /b 1
)

echo.
echo [Step 2/3] Installing Playwright Chromium browser (first run only)...
python -m playwright install chromium
if errorlevel 1 (echo WARN: Playwright browser install issue, scraping may be limited.)

echo.
echo =============================================
echo  DONE - Server starting now.
echo.
echo  Open in Chrome or Edge:
echo    odds_dashboard_v8.html  (double-click it)
echo.
echo  API Health: http://127.0.0.1:8000/api/health
echo  Export All: http://127.0.0.1:8000/api/export/all
echo =============================================
echo.
echo [Step 3/3] Starting server...
python -m uvicorn main:app --reload --port 8000
pause
