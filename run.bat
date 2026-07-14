@echo off
REM ============================================================
REM  OverlineEdge v8.3 — run.bat
REM  Loads .env file (if present) then starts the FastAPI server
REM ============================================================

cd /d "%~dp0"

REM ---- Load .env (key=value lines, # comments ignored) -----
if exist .env (
    echo [OverlineEdge] Loading .env ...
    for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%B"=="" (
            set "%%A=%%B"
        )
    )
    echo [OverlineEdge] .env loaded.
) else (
    echo [OverlineEdge] No .env file found - using existing environment variables.
)

REM ---- Diagnostic: show which keys are set (values hidden) --
echo.
echo [OverlineEdge] API key status:
if defined OPENWEATHER_API_KEY  (echo   OPENWEATHER_API_KEY  = SET) else (echo   OPENWEATHER_API_KEY  = NOT SET  ^(open-meteo fallback will be used^))
if defined GOOGLE_ELEV_KEY      (echo   GOOGLE_ELEV_KEY      = SET) else (echo   GOOGLE_ELEV_KEY      = NOT SET  ^(open-meteo terrain fallback^))
if defined GOOGLE_MAPS_KEY      (echo   GOOGLE_MAPS_KEY      = SET) else (echo   GOOGLE_MAPS_KEY      = NOT SET  ^(geocoding fallback disabled^))
if defined OPENCAGEAPIKEY       (echo   OPENCAGEAPIKEY        = SET) else (echo   OPENCAGEAPIKEY        = NOT SET  ^(geocoding fallback disabled^))
echo.

REM ---- Ensure dependencies are up to date ------------------
echo [OverlineEdge] Installing/verifying dependencies ...
pip install -r requirements.txt -q

REM ---- Start the server -------------------------------------
echo [OverlineEdge] Starting server on http://127.0.0.1:8000
echo [OverlineEdge] Open odds_dashboard_v8.html in your browser.
echo.
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
