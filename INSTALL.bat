@echo off
SETLOCAL ENABLEDELAYEDEXPANSION
title OverlineEdge v8 — Full Sync + Install
cd /d "%~dp0"

echo.
echo ============================================================
echo  OverlineEdge v8  —  FULL SYNC + INSTALL
echo ============================================================
echo.
echo This script pulls ALL latest files from GitHub and installs
echo every Python dependency. Run this whenever you see a
echo ModuleNotFoundError or after any GitHub push.
echo.
pause

REM ── Step 1: Git pull if this is a git repo ──────────────────
where git >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [1/4] Git found — pulling latest from origin/main ...
    git pull origin main
    if !ERRORLEVEL! NEQ 0 (
        echo [WARN] git pull failed. Falling back to manual curl download.
        goto :CURL_FALLBACK
    )
    echo [OK] Git pull complete.
    goto :INSTALL_DEPS
) else (
    echo [WARN] Git not found. Falling back to manual curl download.
    goto :CURL_FALLBACK
)

REM ── Step 2a: Curl fallback — download every core module ─────
:CURL_FALLBACK
echo [2/4] Downloading all core modules from GitHub raw ...
set BASE=https://raw.githubusercontent.com/treyboiter-svg/APP-NEW/main

for %%F in (
    main.py
    routes.py
    fetcher.py
    config.py
    normalizer.py
    odds_calc.py
    odds_scraper.py
    pressure_calc.py
    wind_calc.py
    weather_enricher.py
    venue_resolver.py
    wnba_venues.py
    diagnostics.py
    _scrape_worker.py
    odds_dashboard_v8.html
    run.bat
    run.ps1
    requirements.txt
) do (
    echo   Downloading %%F ...
    curl -fsSL -o "%%F" "%BASE%/%%F"
    if !ERRORLEVEL! NEQ 0 (
        echo   [ERROR] Failed to download %%F
    ) else (
        echo   [OK] %%F
    )
)
echo [OK] All files downloaded.

REM ── Step 3: Install / verify Python dependencies ────────────
:INSTALL_DEPS
echo [3/4] Installing Python dependencies ...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] pip install failed. Check Python installation.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.

REM ── Step 4: Verify all imports load cleanly ──────────────────
echo [4/4] Verifying all module imports ...
python -c "import main; print('[OK] main')"
python -c "from fetcher import build_all_sports; print('[OK] fetcher')"
python -c "from wnba_venues import resolve_wnba_team; print('[OK] wnba_venues')"
python -c "from pressure_calc import full_pressure_block; print('[OK] pressure_calc')"
python -c "from wind_calc import wind_vs_stadium; print('[OK] wind_calc')"
python -c "from weather_enricher import enrich_venue; print('[OK] weather_enricher')"
python -c "from venue_resolver import VenueResolver; print('[OK] venue_resolver')"

echo.
echo ============================================================
echo  SYNC COMPLETE.  Run run.bat to start the server.
echo ============================================================
echo.
pause
