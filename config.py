"""OverlineEdge v8.3 — Central configuration + API key registry.

API Priority Chain (weather):
  1. OpenWeatherMap  (OPENWEATHER_API_KEY)  — best: current + 3h forecast, station pressure
  2. Open-Meteo free                        — free fallback, 1h forecast, no key needed

Elevation fallback chain (venue_resolver):
  1. Venue workbook  (xlsx, feet)           — authoritative source
  2. Google Elevation API (GOOGLE_ELEV_KEY) — per-coordinate lookup when workbook missing
  3. Open-Meteo terrain                     — last-resort embedded in wx payload

Geocoding fallback chain (venue_resolver):
  1. Venue workbook  (lat/lon)              — authoritative source
  2. OpenCage (OPENCAGEAPIKEY)              — geocode by venue name + city when workbook missing
  3. Google Maps (GOOGLE_MAPS_KEY)          — secondary geocode

NOTE: Keys are loaded from environment variables (set via .env file or shell).
NEVER hardcode key values in this file.
"""
import os

# ---------------------------------------------------------------------------
# Prediction market APIs
# ---------------------------------------------------------------------------
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
POLY_GAMMA  = "https://gamma-api.polymarket.com"

# ---------------------------------------------------------------------------
# External API keys — loaded from environment
# ---------------------------------------------------------------------------
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
GOOGLE_MAPS_KEY     = os.environ.get("GOOGLE_MAPS_KEY", "")
GOOGLE_ELEV_KEY     = os.environ.get("GOOGLE_ELEV_KEY", "")
OPENCAGE_API_KEY    = os.environ.get("OPENCAGEAPIKEY", "")

# ---------------------------------------------------------------------------
# Sport / league routing
# ---------------------------------------------------------------------------
SPORT_KEYS = {
    "mlb":   "mlb",
    "nfl":   "nfl",
    "nba":   "nba",
    "nhl":   "nhl",
    "ncaaf": "ncaaf",
    "ncaab": "ncaab",
    "wnba":  "wnba",
}

KALSHI_SERIES = {
    "mlb":   ["KXMLBGAME"],
    "nfl":   ["KXNFLGAME"],
    "nba":   ["KXNBAGAME"],
    "nhl":   ["KXNHLGAME"],
    "ncaaf": ["KXNCAAFGAME"],
    "ncaab": ["KXNCAABGAME"],
    "wnba":  ["KXWNBAGAME"],
}

POLY_SERIES = {
    "mlb":   3,
    "nfl":   10187,
    "nba":   10345,
    "nhl":   10346,
    "ncaaf": 10210,
    "ncaab": 39,
    "wnba":  10512,
}

FETCH_INTERVAL_SECONDS = 120
LOG_DIR    = "data/logs"
EXPORT_DIR = "data/exports"
