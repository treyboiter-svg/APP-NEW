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
    echo.
    echo ERROR: Python not found!
    echo Install from https://www.python.org/downloads/
    echo Make sure "Add Python to PATH" is checked.
    pause
    exit /b 1
)

echo.
echo [Step 0/3] Upgrading pip to latest...
python -m pip install --upgrade pip --quiet

echo.
echo [Step 1/3] Installing Python dependencies...
echo NOTE: All packages have pre-built wheels for Python 3.14 on Windows.
echo       No C compiler required. If anything fails, see error above.
echo.
python -m pip install -r requirements.txt --prefer-binary --only-binary=:all: --upgrade
if errorlevel 1 (
    echo.
    echo ============================================================
    echo  INSTALL FAILED. Trying fallback (allow source builds)...
    echo ============================================================
    python -m pip install -r requirements.txt --prefer-binary
    if errorlevel 1 (
        echo.
        echo FAILED: pip install failed even with fallback.
        echo Please copy this window and report it.
        pause
        exit /b 1
    )
)

echo.
echo [Step 2/3] Installing Playwright Chromium browser (first run only, ~100MB)...
python -m playwright install chromium
if errorlevel 1 (echo WARN: Playwright browser install issue - scraping may be limited.)

echo.
echo =============================================
echo  DONE - Starting server now.
echo.
echo  Open in Chrome or Edge after server starts:
echo    Double-click: odds_dashboard_v8.html
echo.
echo  Health check:  http://127.0.0.1:8000/api/health
echo  Live trace:    http://127.0.0.1:8000/api/diagnostics/live
echo  Diag summary:  http://127.0.0.1:8000/api/diagnostics/run
echo  Diag download: http://127.0.0.1:8000/api/diagnostics/download
echo  Export CSV:    http://127.0.0.1:8000/api/export/all
echo =============================================
echo.
echo [Step 3/3] Starting server...
python -m uvicorn main:app --reload --port 8000
pause
