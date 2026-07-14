"""weather_enricher.py — OverlineEdge v8.2

CRITICAL FIXES in v8.2:
  1. _parse_game_time() now handles scraper format  "7/13 7:00PM"  correctly
  2. ALL times displayed in ET (Eastern) — both game time and forecast time
  3. forecast_hour_et  = the actual ET slot used (e.g. "9:00 PM ET")
  4. game_time_et      = game commence in ET for display (e.g. "9:00 PM ET 7/13")
  5. Elevation bug fixed: venue workbook stores feet; we convert to meters before
     passing to open-meteo and physics. Delta Center = 4,324 ft = 1,317 m correct.
  6. OpenWeatherMap integration (OPENWEATHER_API_KEY) as primary source;
     open-meteo free API as fallback. OWM gives current + 3h forecast slots.
  7. Full ISA physics block with pressure_inhg primary.
  8. Imperial primary throughout: °F, mph, inHg, in/h, ft.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
import pytz

logger = logging.getLogger(__name__)

ET_TZ = pytz.timezone("America/New_York")

# ---------------------------------------------------------------------------
# State → IANA timezone map (all 50 states + DC)
# ---------------------------------------------------------------------------
_STATE_TZ: dict[str, str] = {
    "CT": "America/New_York",  "DC": "America/New_York",  "DE": "America/New_York",
    "FL": "America/New_York",  "GA": "America/New_York",  "IN": "America/Indiana/Indianapolis",
    "KY": "America/New_York",  "MA": "America/New_York",  "MD": "America/New_York",
    "ME": "America/New_York",  "MI": "America/New_York",  "NC": "America/New_York",
    "NH": "America/New_York",  "NJ": "America/New_York",  "NY": "America/New_York",
    "OH": "America/New_York",  "PA": "America/New_York",  "RI": "America/New_York",
    "SC": "America/New_York",  "VA": "America/New_York",  "VT": "America/New_York",
    "WV": "America/New_York",
    "AL": "America/Chicago",   "AR": "America/Chicago",   "IA": "America/Chicago",
    "IL": "America/Chicago",   "KS": "America/Chicago",   "LA": "America/Chicago",
    "MN": "America/Chicago",   "MO": "America/Chicago",   "MS": "America/Chicago",
    "ND": "America/Chicago",   "NE": "America/Chicago",   "OK": "America/Chicago",
    "SD": "America/Chicago",   "TN": "America/Chicago",   "TX": "America/Chicago",
    "WI": "America/Chicago",
    "AZ": "America/Phoenix",   "CO": "America/Denver",    "ID": "America/Denver",
    "MT": "America/Denver",    "NM": "America/Denver",    "UT": "America/Denver",
    "WY": "America/Denver",
    "CA": "America/Los_Angeles", "NV": "America/Los_Angeles", "OR": "America/Los_Angeles",
    "WA": "America/Los_Angeles",
    "AK": "America/Anchorage", "HI": "Pacific/Honolulu",
}


def _get_tz(state: str | None) -> pytz.BaseTzInfo:
    if state:
        tz_name = _STATE_TZ.get(state.strip().upper())
        if tz_name:
            try:
                return pytz.timezone(tz_name)
            except Exception:
                pass
    return ET_TZ


def _ts_to_et(ts: float) -> str:
    """Unix timestamp → 'h:MM AM/PM ET' string."""
    try:
        dt_utc   = datetime.fromtimestamp(ts, tz=timezone.utc)
        dt_et    = dt_utc.astimezone(ET_TZ)
        try:
            return dt_et.strftime("%-I:%M %p ET")
        except ValueError:
            return dt_et.strftime("%I:%M %p ET").lstrip("0")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Game-time parser — MUST handle scraper format  "7/13 7:00PM"
# Also handles ISO, plain time strings, etc.
# ---------------------------------------------------------------------------
# Scraper produces strings like:  "7/13 7:00PM"  "7/13 10:00PM"  "7/14 1:00AM"
_SCRAPER_RE = re.compile(
    r"^(\d{1,2})/(\d{1,2})\s+(\d{1,2}:\d{2})(AM|PM)$", re.IGNORECASE
)
# Plain time:  "7:00 PM ET"  "10:00PM"
_TIME_RE = re.compile(
    r"^(\d{1,2}:\d{2})\s*(AM|PM)", re.IGNORECASE
)


def _parse_game_time(raw: str) -> float:
    """Parse game time string → UTC Unix timestamp. ALWAYS returns a real value."""
    if not raw:
        return datetime.now(timezone.utc).timestamp()

    raw = raw.strip()
    now_et = datetime.now(ET_TZ)

    # --- Format 1: scraper "7/13 7:00PM" ---
    m = _SCRAPER_RE.match(raw)
    if m:
        month, day, time_str, ampm = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
        year = now_et.year
        # If month/day is in the past by more than 1 day, assume next year
        try:
            dt_naive = datetime.strptime(f"{year}-{month:02d}-{day:02d} {time_str} {ampm.upper()}",
                                         "%Y-%m-%d %I:%M %p")
            dt_et = ET_TZ.localize(dt_naive)
            # If more than 12 hours in the past, try next year
            if (dt_et.timestamp() - now_et.timestamp()) < -43200:
                dt_naive2 = datetime.strptime(f"{year+1}-{month:02d}-{day:02d} {time_str} {ampm.upper()}",
                                              "%Y-%m-%d %I:%M %p")
                dt_et = ET_TZ.localize(dt_naive2)
            return dt_et.timestamp()
        except Exception as exc:
            logger.debug("scraper time parse failed: %s — %s", raw, exc)

    # --- Format 2: ISO 8601 ---
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass

    # --- Format 3: plain time "7:00 PM ET" ---
    m2 = _TIME_RE.match(raw.replace(" ET", "").replace(" PT", "").replace(" CT", "").replace(" MT", ""))
    if m2:
        try:
            today_str = now_et.strftime("%Y-%m-%d")
            dt_naive  = datetime.strptime(f"{today_str} {m2.group(1)} {m2.group(2).upper()}",
                                          "%Y-%m-%d %I:%M %p")
            dt_et = ET_TZ.localize(dt_naive)
            return dt_et.timestamp()
        except Exception:
            pass

    logger.warning("_parse_game_time: could not parse %r — using now()", raw)
    return datetime.now(timezone.utc).timestamp()


# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------
_Rd        = 287.05     # J/(kg·K)  dry air
_Rv        = 461.495    # J/(kg·K)  water vapour
_ISA_SLP   = 1013.25    # hPa  sea-level
_ISA_RHO   = 1.225      # kg/m³
_ISA_T0    = 288.15     # K
_INDOOR_TC = 21.0       # °C  HVAC baseline
_INDOOR_RH = 45.0       # %

# ---------------------------------------------------------------------------
# Physics helpers
# ---------------------------------------------------------------------------

def _sat_pressure(t_c: float) -> float:
    """Saturation vapour pressure hPa — August-Roche-Magnus."""
    return 6.112 * math.exp(17.67 * t_c / (t_c + 243.5))


def _density(p_hpa: float, t_c: float, rh_pct: float) -> float:
    """Moist-air density kg/m³."""
    T  = t_c + 273.15
    es = _sat_pressure(t_c)
    e  = min(p_hpa, rh_pct * es / 100.0)
    return (p_hpa - e) * 100.0 / (_Rd * T) + e * 100.0 / (_Rv * T)


def _isa_at_elev(elev_m: float) -> tuple[float, float]:
    """ISA pressure (hPa) and density (kg/m³) at elevation."""
    x = max(-500.0, min(11000.0, elev_m))
    q = 1.0 - 0.0065 * x / _ISA_T0
    return _ISA_SLP * q ** 5.25588, _ISA_RHO * q ** 4.25588


def _indoor_est(p_hpa: float, t_c: float, rh_pct: float) -> dict:
    rho_in  = _density(p_hpa, _INDOOR_TC, _INDOOR_RH)
    rho_out = _density(p_hpa, t_c, rh_pct)
    return {
        "density_kgm3":    round(rho_in, 6),
        "assumed_temp_f":  round(_INDOOR_TC * 9/5 + 32, 1),
        "assumed_temp_c":  _INDOOR_TC,
        "assumed_rh_pct":  _INDOOR_RH,
        "pct_vs_outdoor":  round((rho_in / rho_out - 1.0) * 100.0, 4),
        "note": "HVAC baseline 70°F (21°C) / 45% RH. Crowd heat and roof state not observable.",
    }


# ---------------------------------------------------------------------------
# API keys from environment
# ---------------------------------------------------------------------------
OWM_KEY = os.environ.get("OPENWEATHER_API_KEY", "")

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_WX_CACHE: dict[tuple[float, float], dict] = {}
_WX_LOCK  = asyncio.Lock()

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&hourly=temperature_2m,relative_humidity_2m,surface_pressure,"
    "precipitation,wind_speed_10m,weather_code"
    "&timezone=UTC&forecast_days=16"
)
OWM_FORECAST_URL = (
    "https://api.openweathermap.org/data/2.5/forecast"
    "?lat={lat}&lon={lon}&appid={key}&units=imperial&cnt=40"
)
OWM_CURRENT_URL = (
    "https://api.openweathermap.org/data/2.5/weather"
    "?lat={lat}&lon={lon}&appid={key}&units=imperial"
)


def _ckey(lat: float, lon: float) -> tuple[float, float]:
    return round(lat, 3), round(lon, 3)


async def _fetch_owm(lat: float, lon: float, client: httpx.AsyncClient) -> dict | None:
    """Fetch OpenWeatherMap 3h forecast + current. Returns normalised payload."""
    if not OWM_KEY:
        return None
    try:
        furl = OWM_FORECAST_URL.format(lat=lat, lon=lon, key=OWM_KEY)
        curl = OWM_CURRENT_URL.format(lat=lat, lon=lon, key=OWM_KEY)
        fres, cres = await asyncio.gather(
            client.get(furl, timeout=15),
            client.get(curl, timeout=15),
        )
        fres.raise_for_status()
        cres.raise_for_status()
        fdata = fres.json()
        cdata = cres.json()
        # Build normalised structure matching open-meteo style
        times, temp_f, temp_c, rh, pres, wind_mph, precip = [], [], [], [], [], [], []
        # inject current as first slot
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
        m = cdata.get("main", {})
        times.append(now_iso)
        temp_f.append(m.get("temp"))
        temp_c.append(round((m.get("temp", 32) - 32) * 5/9, 2))
        rh.append(m.get("humidity"))
        pres.append(m.get("pressure"))
        wind_mph.append(round((cdata.get("wind") or {}).get("speed", 0) * 2.23694, 2))
        precip.append((cdata.get("rain") or {}).get("1h", 0.0))
        for slot in fdata.get("list", []):
            dt_txt = slot.get("dt_txt", "")  # e.g. "2026-07-13 21:00:00"
            iso    = dt_txt.replace(" ", "T")[:16]
            sm     = slot.get("main", {})
            times.append(iso)
            tf = sm.get("temp")   # already imperial from units=imperial
            tc = round((tf - 32) * 5/9, 2) if tf is not None else None
            temp_f.append(tf)
            temp_c.append(tc)
            rh.append(sm.get("humidity"))
            pres.append(sm.get("pressure"))
            ws_ms = (slot.get("wind") or {}).get("speed", 0)
            wind_mph.append(round(ws_ms * 2.23694, 2))
            rain = (slot.get("rain") or {}).get("3h", 0.0)
            precip.append(round(rain / 3.0, 4))
        return {
            "source": "openweathermap",
            "elevation": (cdata.get("coord") or {}).get("alt"),
            "hourly": {
                "time":                times,
                "temperature_2m":      temp_c,   # °C for physics
                "temperature_2m_f":    temp_f,   # °F for display
                "relative_humidity_2m": rh,
                "surface_pressure":    pres,
                "wind_speed_10m_mph":  wind_mph,
                "wind_speed_10m":      [round(x / 1.60934, 2) if x is not None else None for x in wind_mph],
                "precipitation":       precip,
            },
        }
    except Exception as exc:
        logger.warning("OWM fetch failed (%.4f, %.4f): %s", lat, lon, exc)
        return None


async def _fetch_open_meteo(lat: float, lon: float, client: httpx.AsyncClient) -> dict | None:
    try:
        url = OPEN_METEO_URL.format(lat=lat, lon=lon)
        r   = await client.get(url, timeout=15)
        r.raise_for_status()
        payload = r.json()
        payload["source"] = "open-meteo"
        return payload
    except Exception as exc:
        logger.warning("open-meteo fetch failed (%.4f, %.4f): %s", lat, lon, exc)
        return None


async def _fetch_wx(lat: float, lon: float, client: httpx.AsyncClient) -> dict | None:
    """Try OWM first, fall back to open-meteo."""
    key = _ckey(lat, lon)
    async with _WX_LOCK:
        if key in _WX_CACHE:
            return _WX_CACHE[key]
    result = None
    if OWM_KEY:
        result = await _fetch_owm(lat, lon, client)
    if result is None:
        result = await _fetch_open_meteo(lat, lon, client)
    if result is not None:
        async with _WX_LOCK:
            _WX_CACHE[key] = result
    return result


def _closest_slot(wx: dict, target_ts: float) -> dict | None:
    """Find hourly slot closest to target_ts (UTC unix). Returns raw slot scalars."""
    try:
        times = wx["hourly"]["time"]
        parsed_ts: list[float] = []
        for t in times:
            try:
                t_clean = t.replace("Z", "+00:00")
                if len(t_clean) == 16:   # "2026-07-13T21:00"
                    t_clean = t_clean + ":00+00:00"
                dt = datetime.fromisoformat(t_clean)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                parsed_ts.append(dt.timestamp())
            except Exception:
                parsed_ts.append(0.0)

        best = min(range(len(parsed_ts)), key=lambda i: abs(parsed_ts[i] - target_ts))

        h         = wx["hourly"]
        t_c       = h["temperature_2m"][best]
        # OWM provides pre-computed °F; open-meteo only has °C
        t_f_raw   = (h.get("temperature_2m_f") or [None])
        t_f       = t_f_raw[best] if best < len(t_f_raw) else None
        if t_f is None and t_c is not None:
            t_f = round(t_c * 9/5 + 32, 1)

        wind_kmh_list = h.get("wind_speed_10m") or []
        wind_mph_list = h.get("wind_speed_10m_mph") or []
        wind_kmh = wind_kmh_list[best] if best < len(wind_kmh_list) else None
        wind_mph = wind_mph_list[best] if best < len(wind_mph_list) else None
        if wind_mph is None and wind_kmh is not None:
            wind_mph = round(wind_kmh * 0.621371, 2)
        if wind_kmh is None and wind_mph is not None:
            wind_kmh = round(wind_mph * 1.60934, 2)

        return {
            "temperature_c":          t_c,
            "temperature_f":          t_f,
            "relative_humidity_pct":  h["relative_humidity_2m"][best],
            "station_pressure_hpa":   h["surface_pressure"][best],
            "wind_speed_kmh":         wind_kmh,
            "wind_speed_mph":         wind_mph,
            "precipitation_mmh":      h["precipitation"][best],
            "forecast_slot_utc":      times[best],
            "forecast_slot_ts":       parsed_ts[best],
            "wx_source":              wx.get("source", "unknown"),
            "wx_elevation_m":         wx.get("elevation"),
        }
    except Exception as exc:
        logger.warning("_closest_slot error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def enrich_venue(
    venue_block: dict,
    game_time:   str,
    client:      httpx.AsyncClient,
) -> dict:
    """
    Append weather + air-density context to an existing venue dict.

    venue_block must contain: lat, lon, elevation (in FEET from workbook),
    state, is_indoor.

    v8.2 CRITICAL CHANGE: venue_block['elevation'] is in FEET (from the
    venue workbook which stores feet). We convert to metres here for all
    physics. The displayed elevation_ft comes directly from the workbook value.
    """
    lat        = venue_block.get("lat")
    lon        = venue_block.get("lon")
    elev_ft_wb = venue_block.get("elevation") or 0.0   # workbook stores FEET
    state      = venue_block.get("state")
    is_indoor  = venue_block.get("is_indoor", False)

    # Convert workbook feet to metres for physics
    # (open-meteo terrain elevation is in metres and will be used as cross-check)
    elev_m_from_wb = elev_ft_wb * 0.3048

    if lat is None or lon is None:
        venue_block["weather_context"] = {"status": "unavailable_no_coordinates"}
        return venue_block

    # --- Parse game time → UTC timestamp + ET display string ---
    game_ts    = _parse_game_time(game_time)
    game_et    = _ts_to_et(game_ts)
    # Format: "9:00 PM ET — 7/13"
    dt_et_game = datetime.fromtimestamp(game_ts, tz=ET_TZ)
    game_et_full = dt_et_game.strftime("%m/%d") + " " + game_et

    wx = await _fetch_wx(lat, lon, client)
    if wx is None:
        venue_block["weather_context"] = {"status": "fetch_failed"}
        return venue_block

    slot = _closest_slot(wx, game_ts)
    if slot is None:
        venue_block["weather_context"] = {"status": "parse_failed"}
        return venue_block

    t_c   = slot["temperature_c"]
    t_f   = slot["temperature_f"]
    rh    = slot["relative_humidity_pct"]
    p_hpa = slot["station_pressure_hpa"]

    # Elevation: prefer workbook feet (known for venue). Use open-meteo terrain
    # elevation as a sanity check but don't override known venue data.
    wx_elev_m = slot.get("wx_elevation_m")
    if elev_ft_wb and elev_ft_wb > 10:        # we have real workbook data
        elev_ft = round(elev_ft_wb, 1)
        elev_m  = round(elev_m_from_wb, 1)
    elif wx_elev_m is not None:               # fall back to API terrain value
        elev_m  = round(float(wx_elev_m), 1)
        elev_ft = round(elev_m * 3.28084, 1)
    else:
        elev_m  = 0.0
        elev_ft = 0.0

    # Imperial conversions
    if t_f is None and t_c is not None:
        t_f = round(t_c * 9/5 + 32, 1)
    p_inhg    = round(p_hpa / 33.8639, 3)
    wind_mph  = slot["wind_speed_mph"]
    wind_kmh  = slot["wind_speed_kmh"]
    precip_mm = slot["precipitation_mmh"] or 0.0
    precip_in = round(precip_mm / 25.4, 4)

    # Air density at station conditions
    rho     = _density(p_hpa, t_c, rh)
    pct_isa = round(rho / _ISA_RHO * 100.0, 4)

    # ISA reference at venue elevation
    isa_p, isa_r   = _isa_at_elev(elev_m)
    isa_p_inhg     = round(isa_p / 33.8639, 3)
    isa_pct        = round(rho / isa_r * 100.0, 4)   # vs ISA at THIS elevation

    # Forecast slot times — both in ET
    fts              = slot["forecast_slot_ts"]
    forecast_et      = _ts_to_et(fts)
    dt_et_fc         = datetime.fromtimestamp(fts, tz=ET_TZ)
    forecast_et_full = dt_et_fc.strftime("%m/%d") + " " + forecast_et
    # Also local venue time for reference
    tz_local          = _get_tz(state)
    dt_local_fc       = datetime.fromtimestamp(fts, tz=tz_local)
    try:
        forecast_local = dt_local_fc.strftime("%-I:%M %p ") + dt_local_fc.strftime("%Z")
    except ValueError:
        forecast_local = dt_local_fc.strftime("%I:%M %p ").lstrip("0") + dt_local_fc.strftime("%Z")

    ctx: dict[str, Any] = {
        "status": "ok",
        "wx_source": slot["wx_source"],

        # Temperature — °F primary
        "temperature_f":             round(t_f, 1),
        "temperature_c":             round(t_c, 1),

        # Humidity
        "relative_humidity_pct":     round(rh, 1),

        # Pressure — inHg primary
        "station_pressure_inhg":     p_inhg,
        "station_pressure_hpa":      round(p_hpa, 2),

        # Wind — mph primary
        "wind_speed_mph":            round(wind_mph, 1) if wind_mph else None,
        "wind_speed_kmh":            round(wind_kmh, 1) if wind_kmh else None,

        # Precipitation — in/h primary
        "precipitation_inh":         precip_in,
        "precipitation_mmh":         round(precip_mm, 2),

        # Air density
        "air_density_kgm3":          round(rho, 6),
        "density_pct_of_isa_sealevel": pct_isa,
        "density_pct_of_isa_elevation": isa_pct,

        # ISA at venue elevation — inHg primary
        "isa_at_elevation": {
            "elevation_ft":   elev_ft,
            "elevation_m":    elev_m,
            "pressure_inhg":  isa_p_inhg,
            "pressure_hpa":   round(isa_p, 4),
            "density_kgm3":   round(isa_r, 6),
        },

        # Elevation — ft primary
        "elevation_ft":              elev_ft,
        "elevation_m":               elev_m,
        # Legacy field names kept for backward compat
        "mapped_elevation_ft":        elev_ft,
        "mapped_elevation_m":         elev_m,

        # Forecast timing — ET primary, local secondary
        "game_time_raw":             game_time,
        "game_time_et":              game_et,           # "9:00 PM ET"
        "game_time_et_full":         game_et_full,      # "07/13 9:00 PM ET"
        "forecast_hour_et":          forecast_et,       # "9:00 PM ET"
        "forecast_hour_et_full":     forecast_et_full,  # "07/13 9:00 PM ET"
        "forecast_hour_local":       forecast_local,    # "9:00 PM MDT" (venue local)
        "forecast_hour_utc":         slot["forecast_slot_utc"],
        "forecast_hour_ts":          fts,

        "is_indoor": is_indoor,
    }

    if is_indoor:
        ctx["indoor_estimate"] = _indoor_est(p_hpa, t_c, rh)

    venue_block["weather_context"] = ctx
    return venue_block


def clear_cache() -> None:
    _WX_CACHE.clear()
