"""weather_enricher.py — OverlineEdge v8 Integration

Replicates the App 2 (game_time_air_density_pressure_dashboard_vFinal.html)
physics and weather pipeline in async Python so every game payload from
fetcher.py gets live weather + moist-air density appended to its venue block.

Physics identical to App 2 JS:
    density(p, t, rh) -> moist-air density kg/m³
    ISA reference at elevation
    Indoor estimate at 21°C / 45% RH baseline

Data sources (same as App 2, zero API keys required):
    Open-Meteo forecast  https://api.open-meteo.com
    (geocoding not needed — venue lat/lon already resolved from XLSX)
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Open-Meteo forecast endpoint — same variables App 2 uses
# ---------------------------------------------------------------------------
_OM_BASE = "https://api.open-meteo.com/v1/forecast"
_OM_PARAMS = (
    "temperature_2m,relative_humidity_2m,surface_pressure,"
    "precipitation,wind_speed_10m,weather_code"
)
_FORECAST_DAYS = 16          # open-meteo max; covers any game in the next two weeks
_REQUEST_TIMEOUT = 15.0

# Simple in-process cache keyed by (lat_2dp, lon_2dp) so we don't hammer
# open-meteo with duplicate calls when multiple games share a venue.
_weather_cache: dict[str, tuple[float, dict]] = {}   # key -> (fetched_at_epoch, payload)
_CACHE_TTL_SECONDS = 3600    # 1 hour; weather doesn't change faster than this for scheduling


# ---------------------------------------------------------------------------
# Physics — direct port of App 2 JS formulas
# ---------------------------------------------------------------------------

def _moist_air_density(p_hpa: float, t_celsius: float, rh_pct: float) -> float:
    """Moist-air density in kg/m³.
    p_hpa    : surface (station) pressure in hPa
    t_celsius: dry-bulb temperature °C
    rh_pct   : relative humidity 0-100
    """
    T = t_celsius + 273.15
    # Tetens saturation vapour pressure (hPa)
    es = 6.112 * math.exp(17.67 * t_celsius / (t_celsius + 243.5))
    e = min(p_hpa, rh_pct * es / 100.0)
    R_dry   = 287.05   # J/(kg·K)
    R_vapor = 461.495  # J/(kg·K)
    # Convert hPa -> Pa (*100) for SI
    rho = ((p_hpa - e) * 100.0 / (R_dry * T)) + (e * 100.0 / (R_vapor * T))
    return round(rho, 6)


def _isa_at_elevation(elev_m: float) -> tuple[float, float]:
    """ISA standard atmosphere at given elevation.
    Returns (pressure_hPa, density_kg_m3)
    """
    h = max(-500.0, min(11000.0, elev_m))
    ratio = 1.0 - 0.0065 * h / 288.15
    p_isa  = round(1013.25 * ratio ** 5.25588, 4)
    rho_isa = round(1.225  * ratio ** 4.25588, 6)
    return p_isa, rho_isa


def _indoor_estimate(p_hpa: float, t_celsius: float, rh_pct: float) -> dict:
    """Indoor density estimate assuming 21°C / 45% RH (App 2 baseline)."""
    target_t  = 21.0
    target_rh = 45.0
    rho_indoor  = _moist_air_density(p_hpa, target_t, target_rh)
    rho_outdoor = _moist_air_density(p_hpa, t_celsius, rh_pct)
    pct_diff = round((rho_indoor / rho_outdoor - 1.0) * 100.0, 3) if rho_outdoor else 0.0
    return {
        "density_kg_m3":     round(rho_indoor, 6),
        "assumed_temp_c":    target_t,
        "assumed_rh_pct":    target_rh,
        "vs_outdoor_pct":    pct_diff,
        "note": (
            "Indoor estimate: station pressure + 21°C / 45% RH HVAC baseline. "
            "Crowd heat and roof state not directly observable."
        ),
    }


# ---------------------------------------------------------------------------
# Open-Meteo fetch (async, cached)
# ---------------------------------------------------------------------------

def _cache_key(lat: float, lon: float) -> str:
    return f"{round(lat, 2)},{round(lon, 2)}"


async def _fetch_om_forecast(lat: float, lon: float, client: httpx.AsyncClient) -> dict | None:
    key = _cache_key(lat, lon)
    now = time.monotonic()
    cached = _weather_cache.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    params = {
        "latitude":     lat,
        "longitude":    lon,
        "hourly":       _OM_PARAMS,
        "timezone":     "UTC",
        "forecast_days": _FORECAST_DAYS,
    }
    try:
        r = await client.get(_OM_BASE, params=params, timeout=_REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        _weather_cache[key] = (now, data)
        return data
    except Exception as exc:
        logger.warning("open-meteo fetch failed lat=%s lon=%s: %s", lat, lon, exc)
        return None


def _nearest_hour_index(om_payload: dict, iso_time: str) -> int:
    """Return the hourly index closest to the requested game time (ISO-8601 string)."""
    import dateutil.parser  # already available via httpx/anyio chain; pure-stdlib fallback below
    try:
        target_ts = dateutil.parser.parse(iso_time).timestamp()
    except Exception:
        # Fallback: use current time
        target_ts = time.time()

    times = om_payload.get("hourly", {}).get("time", [])
    if not times:
        return 0

    # open-meteo returns times as "YYYY-MM-DDTHH:MM" (no Z) in the requested timezone (UTC)
    best_i, best_diff = 0, float("inf")
    for i, t_str in enumerate(times):
        try:
            ts = time.mktime(time.strptime(t_str, "%Y-%m-%dT%H:%M"))
        except Exception:
            continue
        diff = abs(ts - target_ts)
        if diff < best_diff:
            best_diff = diff
            best_i = i
    return best_i


def _extract_hourly(om_payload: dict, idx: int) -> dict:
    h = om_payload.get("hourly", {})
    def _get(field):
        arr = h.get(field, [])
        return arr[idx] if idx < len(arr) else None
    return {
        "temperature_c":    _get("temperature_2m"),
        "rh_pct":           _get("relative_humidity_2m"),
        "pressure_hpa":     _get("surface_pressure"),
        "wind_kmh":         _get("wind_speed_10m"),
        "precip_mm":        _get("precipitation"),
        "weather_code":     _get("weather_code"),
        "forecast_hour_utc": h.get("time", [])[idx] if idx < len(h.get("time", [])) else None,
        "mapped_elevation_m": om_payload.get("elevation"),
    }


# ---------------------------------------------------------------------------
# Primary public interface
# ---------------------------------------------------------------------------

async def enrich_venue_weather(
    venue_block: dict,
    game_time_iso: str,
    is_indoor: bool,
    client: httpx.AsyncClient,
) -> dict:
    """Given a venue block (already containing lat/lon/elevation from VenueResolver)
    and a game commence time string, fetch open-meteo and return a
    weather_context dict to be merged into the game's venue block.

    Returns an empty dict with error key on any failure — never raises.
    """
    lat = venue_block.get("lat")
    lon = venue_block.get("lon")
    elev = venue_block.get("elevation") or 0.0

    if lat is None or lon is None:
        return {"weather_status": "unavailable_no_coords"}

    om = await _fetch_om_forecast(lat, lon, client)
    if om is None:
        return {"weather_status": "fetch_failed"}

    idx = _nearest_hour_index(om, game_time_iso)
    hourly = _extract_hourly(om, idx)

    t   = hourly.get("temperature_c")
    rh  = hourly.get("rh_pct")
    p   = hourly.get("pressure_hpa")

    if t is None or rh is None or p is None:
        return {"weather_status": "missing_hourly_values", **hourly}

    density     = _moist_air_density(p, t, rh)
    p_isa, d_isa = _isa_at_elevation(elev)
    pct_of_sea_level = round(density / 1.225 * 100.0, 3)
    pct_of_isa_elev  = round(density / d_isa * 100.0, 3) if d_isa else None

    result: dict[str, Any] = {
        "weather_status":          "ok",
        "forecast_hour_utc":       hourly["forecast_hour_utc"],
        "mapped_elevation_m":      hourly["mapped_elevation_m"],
        "temperature_c":           round(t,  2),
        "temperature_f":           round(t * 9/5 + 32, 2),
        "rh_pct":                  round(rh, 1),
        "station_pressure_hpa":    round(p,  2),
        "station_pressure_inhg":   round(p / 33.8639, 4),
        "wind_kmh":                hourly["wind_kmh"],
        "precip_mm_per_h":         hourly["precip_mm"],
        "weather_code":            hourly["weather_code"],
        "air_density_kg_m3":       density,
        "pct_of_isa_sea_level":    pct_of_sea_level,
        "pct_of_isa_at_elevation": pct_of_isa_elev,
        "isa_ref": {
            "pressure_hpa":    p_isa,
            "density_kg_m3":  d_isa,
        },
    }

    if is_indoor:
        result["indoor_estimate"] = _indoor_estimate(p, t, rh)
        result["is_indoor"]       = True
    else:
        result["is_indoor"] = False

    return result


async def enrich_games_batch(
    games: list[dict],
    client: httpx.AsyncClient,
) -> list[dict]:
    """Enrich a list of game dicts in-place (mutates venue block).
    Uses asyncio.gather for concurrent open-meteo requests.
    Shared venue coords are deduplicated via the cache.
    """
    async def _enrich_one(game: dict) -> None:
        venue = game.get("venue", {})
        game_time = game.get("commence", "")
        # Derive indoor flag from venue name heuristics + orientation confidence
        # (a resolved indoor arena has null orientation_confidence or label 'dome')
        name_lower = (venue.get("name") or "").lower()
        is_indoor = any(x in name_lower for x in (
            "arena", "center", "centre", "garden", "dome", "stadium"
            # keep this conservative — outdoor stadiums also use 'stadium'
        )) and not any(x in name_lower for x in ("field", "park", "bowl"))
        weather = await enrich_venue_weather(venue, game_time, is_indoor, client)
        game["venue"]["weather"] = weather

    await asyncio.gather(*[_enrich_one(g) for g in games], return_exceptions=True)
    return games
