"""weather_enricher.py — OverlineEdge v8 Integration

Replicates App 2 (game_time_air_density_pressure_dashboard_vFinal.html)
physics and data pipeline in pure Python/async.

For every game resolved by fetcher.py, this module:
  1. Fetches hourly forecast from open-meteo (free, no API key)
  2. Finds the closest hourly slot to game commence time
  3. Calculates moist-air density using the exact same formula as App 2
  4. Calculates ISA reference values at venue elevation
  5. Handles indoor/roofed venues with HVAC baseline (21C / 45% RH)
  6. Returns a weather_context dict that is merged into the game venue block

All results are cached per (lat, lon) coordinate to avoid redundant API calls
within a single build_all_sports() pass.

v8.1 fixes:
  - Imperial primary units: °F, mph, inHg, in/h, ft
  - forecast_hour_local: converts UTC slot to venue local timezone
  - _STATE_TZ map covers all 50 US states + DC
  - forecast_hour_ts stored for debugging
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any

import httpx
import pytz

logger = logging.getLogger(__name__)

ET_TZ = pytz.timezone("America/New_York")

# ---------------------------------------------------------------------------
# Timezone map: US state abbreviation -> IANA timezone string
# Used to convert UTC forecast slot → local game-time display
# ---------------------------------------------------------------------------
_STATE_TZ: dict[str, str] = {
    # Eastern
    "CT": "America/New_York",
    "DC": "America/New_York",
    "DE": "America/New_York",
    "FL": "America/New_York",
    "GA": "America/New_York",
    "IN": "America/Indiana/Indianapolis",
    "KY": "America/New_York",
    "MA": "America/New_York",
    "MD": "America/New_York",
    "ME": "America/New_York",
    "MI": "America/New_York",
    "NC": "America/New_York",
    "NH": "America/New_York",
    "NJ": "America/New_York",
    "NY": "America/New_York",
    "OH": "America/New_York",
    "PA": "America/New_York",
    "RI": "America/New_York",
    "SC": "America/New_York",
    "VA": "America/New_York",
    "VT": "America/New_York",
    "WV": "America/New_York",
    # Central
    "AL": "America/Chicago",
    "AR": "America/Chicago",
    "IA": "America/Chicago",
    "IL": "America/Chicago",
    "KS": "America/Chicago",
    "LA": "America/Chicago",
    "MN": "America/Chicago",
    "MO": "America/Chicago",
    "MS": "America/Chicago",
    "ND": "America/Chicago",
    "NE": "America/Chicago",
    "OK": "America/Chicago",
    "SD": "America/Chicago",
    "TN": "America/Chicago",
    "TX": "America/Chicago",
    "WI": "America/Chicago",
    # Mountain
    "AZ": "America/Phoenix",
    "CO": "America/Denver",
    "ID": "America/Denver",
    "MT": "America/Denver",
    "NM": "America/Denver",
    "UT": "America/Denver",
    "WY": "America/Denver",
    # Pacific
    "CA": "America/Los_Angeles",
    "NV": "America/Los_Angeles",
    "OR": "America/Los_Angeles",
    "WA": "America/Los_Angeles",
    # Other
    "AK": "America/Anchorage",
    "HI": "Pacific/Honolulu",
}


def _get_tz_for_state(state: str | None) -> pytz.BaseTzInfo:
    """Return pytz timezone for a US state abbreviation, default ET."""
    if state:
        tz_name = _STATE_TZ.get(state.strip().upper())
        if tz_name:
            try:
                return pytz.timezone(tz_name)
            except Exception:
                pass
    return ET_TZ


def _forecast_hour_local(forecast_ts: float, state: str | None) -> str:
    """Convert a UTC Unix timestamp to a local time string like '9:00 PM MT'."""
    try:
        tz = _get_tz_for_state(state)
        dt_utc   = datetime.fromtimestamp(forecast_ts, tz=timezone.utc)
        dt_local = dt_utc.astimezone(tz)
        # %-I strips leading zero on Linux; %I keeps it on Windows — handle both
        try:
            return dt_local.strftime("%-I:%M %p %Z")
        except ValueError:
            return dt_local.strftime("%I:%M %p %Z").lstrip("0")
    except Exception as exc:
        logger.debug("forecast_hour_local error: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Module-level cache: keyed by (lat_rounded, lon_rounded) -> raw open-meteo
# hourly payload. Rounded to 3 decimal places (~111 m grid) to allow reuse
# across teams playing at the same venue on the same build pass.
# ---------------------------------------------------------------------------
_WX_CACHE: dict[tuple[float, float], dict] = {}
_WX_LOCK = asyncio.Lock()

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&hourly=temperature_2m,relative_humidity_2m,surface_pressure,"
    "precipitation,wind_speed_10m,weather_code"
    "&timezone=UTC&forecast_days=16"
)

# Physical constants (matches App 2 exactly)
_Rd = 287.05    # J/(kg·K)  dry air gas constant
_Rv = 461.495   # J/(kg·K)  water vapour gas constant

# ISA sea-level reference
_ISA_SLP = 1013.25    # hPa
_ISA_RHO = 1.225      # kg/m³
_ISA_T0  = 288.15     # K
_ISA_L   = 0.0065     # K/m lapse rate

# Indoor HVAC baseline (matches App 2)
_INDOOR_T_C = 21.0    # °C  (69.8 °F)
_INDOOR_RH  = 45.0    # %


# ---------------------------------------------------------------------------
# Physics helpers — exact port of App 2 JS functions
# ---------------------------------------------------------------------------

def _saturation_pressure_hpa(t_c: float) -> float:
    """August-Roche-Magnus formula (matches App 2: 6.112 * exp(17.67*t/(t+243.5)))"""
    return 6.112 * math.exp(17.67 * t_c / (t_c + 243.5))


def _moist_air_density(p_hpa: float, t_c: float, rh_pct: float) -> float:
    """Moist-air density kg/m³. Exact port of App 2 density() function."""
    T  = t_c + 273.15
    es = _saturation_pressure_hpa(t_c)
    e  = min(p_hpa, rh_pct * es / 100.0)
    return (p_hpa - e) * 100.0 / (_Rd * T) + e * 100.0 / (_Rv * T)


def _isa_at_elevation(elevation_m: float) -> tuple[float, float]:
    """ISA pressure (hPa) and density (kg/m³) at a given elevation."""
    x = max(-500.0, min(11000.0, elevation_m))
    q = 1.0 - 0.0065 * x / _ISA_T0
    return _ISA_SLP * q ** 5.25588, _ISA_RHO * q ** 4.25588


def _indoor_estimate(p_hpa: float, t_c: float, rh_pct: float) -> dict:
    """Indoor density estimate using HVAC baseline (matches App 2 indoorEstimate())."""
    rho_indoor  = _moist_air_density(p_hpa, _INDOOR_T_C, _INDOOR_RH)
    rho_outdoor = _moist_air_density(p_hpa, t_c, rh_pct)
    pct_diff    = (rho_indoor / rho_outdoor - 1.0) * 100.0
    indoor_f    = round(_INDOOR_T_C * 9 / 5 + 32, 1)
    return {
        "density_kgm3":     round(rho_indoor, 6),
        "assumed_temp_c":   _INDOOR_T_C,
        "assumed_temp_f":   indoor_f,
        "assumed_rh_pct":   _INDOOR_RH,
        "pct_vs_outdoor":   round(pct_diff, 4),
        "note": (
            "HVAC baseline 70°F (21°C) / 45% RH. "
            "Crowd heat/moisture and roof state not directly observable."
        ),
    }


# ---------------------------------------------------------------------------
# Open-Meteo fetch + cache
# ---------------------------------------------------------------------------

def _cache_key(lat: float, lon: float) -> tuple[float, float]:
    return round(lat, 3), round(lon, 3)


async def _fetch_open_meteo(lat: float, lon: float, client: httpx.AsyncClient) -> dict | None:
    """Fetch hourly forecast for (lat, lon). Results cached per coordinate."""
    key = _cache_key(lat, lon)
    async with _WX_LOCK:
        if key in _WX_CACHE:
            return _WX_CACHE[key]
    try:
        url = OPEN_METEO_URL.format(lat=lat, lon=lon)
        r   = await client.get(url, timeout=15)
        r.raise_for_status()
        payload = r.json()
        async with _WX_LOCK:
            _WX_CACHE[key] = payload
        return payload
    except Exception as exc:
        logger.warning("open-meteo fetch failed (%.4f, %.4f): %s", lat, lon, exc)
        return None


def _closest_hour(wx: dict, game_time_iso: str) -> dict | None:
    """Return weather scalars for the hourly slot closest to game_time_iso.

    game_time_iso is whatever comes from the scraper/ESPN — could be
    '7:10 PM ET', '2026-07-13T19:10:00Z', or empty.  We parse best-effort
    and fall back to now() if unparseable.
    """
    try:
        times = wx["hourly"]["time"]
        if not times:
            return None

        target_ts = _parse_game_time(game_time_iso)
        target_ms = target_ts * 1000

        parsed_ms: list[int] = []
        for t in times:
            try:
                dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                parsed_ms.append(int(dt.timestamp() * 1000))
            except Exception:
                parsed_ms.append(0)

        best_idx = min(range(len(parsed_ms)), key=lambda i: abs(parsed_ms[i] - target_ms))

        h = wx["hourly"]
        return {
            "temperature_c":         h["temperature_2m"][best_idx],
            "relative_humidity_pct": h["relative_humidity_2m"][best_idx],
            "station_pressure_hpa":  h["surface_pressure"][best_idx],
            "wind_speed_kmh":        h["wind_speed_10m"][best_idx],
            "precipitation_mmh":     h["precipitation"][best_idx],
            "forecast_hour_utc":     times[best_idx],
            "forecast_hour_ts":      parsed_ms[best_idx] / 1000.0,
            "mapped_elevation_m":    wx.get("elevation"),
        }
    except Exception as exc:
        logger.warning("closest_hour parse error: %s", exc)
        return None


def _parse_game_time(raw: str) -> float:
    """Best-effort parse of game time string → Unix timestamp (seconds)."""
    if not raw:
        return datetime.now(timezone.utc).timestamp()
    # ISO 8601
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass
    # Scraper strings like "7:10 PM ET" — assume today's date in ET
    try:
        today     = datetime.now(ET_TZ).strftime("%Y-%m-%d")
        raw_clean = raw.strip().replace(" ET", "").replace(" PT", "").replace(" CT", "").replace(" MT", "")
        dt_naive  = datetime.strptime(f"{today} {raw_clean}", "%Y-%m-%d %I:%M %p")
        dt_et     = ET_TZ.localize(dt_naive)
        return dt_et.timestamp()
    except Exception:
        pass
    return datetime.now(timezone.utc).timestamp()


# ---------------------------------------------------------------------------
# Public entry point — called from fetcher.py
# ---------------------------------------------------------------------------

async def enrich_venue(
    venue_block: dict,
    game_time:   str,
    client:      httpx.AsyncClient,
) -> dict:
    """Append weather + air density context to an existing venue dict.

    Args:
        venue_block:  The existing venue dict from fetcher.py (has lat, lon,
                      elevation, orientation, state fields already populated).
        game_time:    Raw time string from the scraper / ESPN feed.
        client:       Shared httpx.AsyncClient from build_sport().

    Returns:
        The same venue_block dict with a 'weather_context' key added.
        If weather fetch fails, weather_context = {'status': 'unavailable'}.
    """
    lat       = venue_block.get("lat")
    lon       = venue_block.get("lon")
    elev      = venue_block.get("elevation") or 0.0
    state     = venue_block.get("state")        # e.g. "UT", "TX", "NY"
    is_indoor = venue_block.get("is_indoor", False)

    if lat is None or lon is None:
        venue_block["weather_context"] = {"status": "unavailable_no_coordinates"}
        return venue_block

    wx = await _fetch_open_meteo(lat, lon, client)
    if wx is None:
        venue_block["weather_context"] = {"status": "fetch_failed"}
        return venue_block

    slot = _closest_hour(wx, game_time)
    if slot is None:
        venue_block["weather_context"] = {"status": "parse_failed"}
        return venue_block

    t_c    = slot["temperature_c"]
    rh     = slot["relative_humidity_pct"]
    p      = slot["station_pressure_hpa"]
    elev_m = slot["mapped_elevation_m"] if slot["mapped_elevation_m"] is not None else elev

    # Imperial conversions
    t_f       = round(t_c * 9.0 / 5.0 + 32.0, 1)
    elev_ft   = round(elev_m * 3.28084, 1)
    p_inhg    = round(p / 33.8639, 3)
    wind_mph  = round(slot["wind_speed_kmh"] * 0.621371, 1)
    precip_in = round(slot["precipitation_mmh"] / 25.4, 4)

    # Air density + ISA
    rho              = _moist_air_density(p, t_c, rh)
    isa_p, isa_r     = _isa_at_elevation(elev_m)
    pct_isa          = round(rho / _ISA_RHO * 100.0, 4)
    isa_p_inhg       = round(isa_p / 33.8639, 3)

    # Local forecast hour string — e.g. "9:00 PM MT"
    forecast_ts    = slot.get("forecast_hour_ts") or 0.0
    forecast_local = _forecast_hour_local(forecast_ts, state)

    ctx: dict[str, Any] = {
        "status": "ok",

        # --- Temperature (Imperial primary) ---
        "temperature_f":              t_f,
        "temperature_c":              round(t_c, 1),

        # --- Humidity ---
        "relative_humidity_pct":      round(rh, 1),

        # --- Pressure (Imperial primary) ---
        "station_pressure_inhg":      p_inhg,
        "station_pressure_hpa":       round(p, 2),

        # --- Wind (Imperial primary) ---
        "wind_speed_mph":             wind_mph,
        "wind_speed_kmh":             round(slot["wind_speed_kmh"], 1),

        # --- Precipitation (Imperial primary) ---
        "precipitation_inh":          precip_in,
        "precipitation_mmh":          round(slot["precipitation_mmh"], 2),

        # --- Air density ---
        "air_density_kgm3":           round(rho, 6),
        "density_pct_of_isa_sealevel": pct_isa,

        # --- ISA at venue elevation ---
        "isa_at_elevation": {
            "pressure_inhg":  isa_p_inhg,
            "pressure_hpa":   round(isa_p, 4),
            "density_kgm3":   round(isa_r, 6),
        },

        # --- Elevation (Imperial primary) ---
        "mapped_elevation_ft":        elev_ft,
        "mapped_elevation_m":         round(elev_m, 1),

        # --- Forecast timing ---
        "forecast_hour_local":        forecast_local,   # e.g. "9:00 PM MT"
        "forecast_hour_utc":          slot["forecast_hour_utc"],
        "forecast_hour_ts":           forecast_ts,

        "is_indoor":                  is_indoor,
    }

    if is_indoor:
        ctx["indoor_estimate"] = _indoor_estimate(p, t_c, rh)

    venue_block["weather_context"] = ctx
    return venue_block


def clear_cache() -> None:
    """Clear the weather cache. Call between test runs if needed."""
    _WX_CACHE.clear()
