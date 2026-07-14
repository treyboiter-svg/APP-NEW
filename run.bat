@echo off
SETLOCAL ENABLEDELAYEDEXPANSION
title OverlineEdge v8
cd /d "%~dp0"

echo.
echo ============================================================
echo  OverlineEdge v8  —  Starting ...
echo ============================================================
echo.

REM ── Check for new required modules (v8.4) ───────────────────
set MISSING=0
for %%F in (wnba_venues.py pressure_calc.py wind_calc.py) do (
    if not exist "%%F" (
        echo [WARN] Missing required module: %%F
        set MISSING=1
    )
)

if !MISSING! EQU 1 (
    echo.
    echo [ACTION REQUIRED] One or more v8.4 modules are missing.
    echo Run INSTALL.bat first to download all required files.
    echo Or run: curl -o wnba_venues.py https://raw.githubusercontent.com/treyboiter-svg/APP-NEW/main/wnba_venues.py
    echo          curl -o pressure_calc.py https://raw.githubusercontent.com/treyboiter-svg/APP-NEW/main/pressure_calc.py
    echo          curl -o wind_calc.py https://raw.githubusercontent.com/treyboiter-svg/APP-NEW/main/wind_calc.py
    echo.
    pause
    exit /b 1
)

REM ── Load .env ────────────────────────────────────────────────
if not exist ".env" (
    echo [ERROR] .env not found. Copy .env.example to .env and fill in your API keys.
    pause
    exit /b 1
)

echo [OverlineEdge] Loading .env ...
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    set "line=%%A"
    if not "!line:~0,1!" == "#" (
        set "%%A=%%B"
    )
)
echo [OverlineEdge] .env loaded.

echo [OverlineEdge] API key status:
echo   OPENWEATHER_API_KEY  = %OPENWEATHER_API_KEY:~0,3%...
echo   GOOGLE_ELEV_KEY      = %GOOGLE_ELEV_KEY:~0,3%...
echo   GOOGLE_MAPS_KEY      = %GOOGLE_MAPS_KEY:~0,3%...
echo   OPENCAGEAPIKEY       = %OPENCAGEAPIKEY:~0,3%...

echo.
echo [OverlineEdge] Installing/verifying dependencies ...
python -m pip install -r requirements.txt --quiet

echo [OverlineEdge] Starting server on http://127.0.0.1:8000
echo [OverlineEdge] Open odds_dashboard_v8.html in your browser.
echo.

python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

pause
