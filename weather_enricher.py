"""weather_enricher.py — OverlineEdge v8.4.0

API PRIORITY CHAIN:
  Tier 1 (weather): OpenWeatherMap /weather + /forecast  (OPENWEATHER_API_KEY)
  Tier 2 (weather): Open-Meteo free                       (no key)
  Tier 1 (elev):    Venue workbook feet column
  Tier 2 (elev):    Google Elevation API  (GOOGLE_ELEV_KEY)
  Tier 3 (elev):    Open-Meteo terrain elevation

FIX v8.4.0:
  - asyncio.Lock created lazily (Python 3.14 safe)
  - Wind direction added to _closest_slot output
  - Full pressure_calc + wind_calc integration
  - Indoor/dome venues bypass outdoor physics and use indoor_hvac_model
  - Retractable: summer default OPEN; winter default CLOSED
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

from pressure_calc import full_pressure_block, indoor_hvac_model
from wind_calc import wind_vs_stadium

logger = logging.getLogger(__name__)
ET_TZ  = pytz.timezone("America/New_York")

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
    "AK": "America/Anchorage",  "HI": "Pacific/Honolulu",
}

OWM_KEY   = os.environ.get("OPENWEATHER_API_KEY", "")
GELEV_KEY = os.environ.get("GOOGLE_ELEV_KEY",     "")

_WX_CACHE:   dict = {}
_ELEV_CACHE: dict = {}
_wx_lock:    asyncio.Lock | None = None
_elev_lock:  asyncio.Lock | None = None

def _get_wx_lock()   -> asyncio.Lock:
    global _wx_lock
    if _wx_lock is None:   _wx_lock   = asyncio.Lock()
    return _wx_lock

def _get_elev_lock() -> asyncio.Lock:
    global _elev_lock
    if _elev_lock is None: _elev_lock = asyncio.Lock()
    return _elev_lock


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _get_tz(state: str | None) -> pytz.BaseTzInfo:
    if state:
        tz_name = _STATE_TZ.get(state.strip().upper())
        if tz_name:
            try: return pytz.timezone(tz_name)
            except Exception: pass
    return ET_TZ

def _ts_to_et_str(ts: float) -> str:
    try:
        dt_et = datetime.fromtimestamp(ts, tz=ET_TZ)
        try:    return dt_et.strftime("%-I:%M %p ET")
        except ValueError: return dt_et.strftime("%I:%M %p ET").lstrip("0")
    except Exception: return ""

_SCRAPER_RE  = re.compile(r"^(\d{1,2})/(\d{1,2})\s+(\d{1,2}:\d{2})\s*(AM|PM)$", re.IGNORECASE)
_TIME_ONLY_RE = re.compile(r"^(\d{1,2}:\d{2})\s*(AM|PM)", re.IGNORECASE)

def _parse_game_time(raw: str) -> float:
    if not raw: return datetime.now(timezone.utc).timestamp()
    raw = raw.strip()
    now_et = datetime.now(ET_TZ)
    m = _SCRAPER_RE.match(raw)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        time_str, ampm = m.group(3), m.group(4).upper()
        year = now_et.year
        for y in (year, year + 1):
            try:
                dt_naive = datetime.strptime(f"{y}-{month:02d}-{day:02d} {time_str} {ampm}", "%Y-%m-%d %I:%M %p")
                dt_et    = ET_TZ.localize(dt_naive)
                if (dt_et.timestamp() - now_et.timestamp()) >= -43_200: return dt_et.timestamp()
            except Exception: pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try: return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError: pass
    stripped = raw.replace(" ET","").replace(" PT","").replace(" CT","").replace(" MT","")
    m2 = _TIME_ONLY_RE.match(stripped)
    if m2:
        try:
            today    = now_et.strftime("%Y-%m-%d")
            dt_naive = datetime.strptime(f"{today} {m2.group(1)} {m2.group(2).upper()}", "%Y-%m-%d %I:%M %p")
            return ET_TZ.localize(dt_naive).timestamp()
        except Exception: pass
    logger.warning("_parse_game_time: unparseable %r — using now()", raw)
    return datetime.now(timezone.utc).timestamp()


# ---------------------------------------------------------------------------
# Elevation lookup (Google Elevation, Tier 2)
# ---------------------------------------------------------------------------

async def _google_elevation(lat: float, lon: float, client: httpx.AsyncClient) -> float | None:
    if not GELEV_KEY: return None
    key = (round(lat, 4), round(lon, 4))
    async with _get_elev_lock():
        if key in _ELEV_CACHE: return _ELEV_CACHE[key]
    try:
        r = await client.get(
            "https://maps.googleapis.com/maps/api/elevation/json",
            params={"locations": f"{lat},{lon}", "key": GELEV_KEY}, timeout=10,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if results:
            elev_m = float(results[0]["elevation"])
            async with _get_elev_lock(): _ELEV_CACHE[key] = elev_m
            return elev_m
    except Exception as exc: logger.warning("Google Elevation (%.4f,%.4f): %s", lat, lon, exc)
    return None


# ---------------------------------------------------------------------------
# Weather fetch — Tier 1: OpenWeatherMap
# ---------------------------------------------------------------------------

async def _fetch_owm(lat: float, lon: float, client: httpx.AsyncClient) -> dict | None:
    if not OWM_KEY: return None
    try:
        fc_url  = (f"https://api.openweathermap.org/data/2.5/forecast"
                   f"?lat={lat}&lon={lon}&appid={OWM_KEY}&units=imperial&cnt=40")
        cur_url = (f"https://api.openweathermap.org/data/2.5/weather"
                   f"?lat={lat}&lon={lon}&appid={OWM_KEY}&units=imperial")
        fc_res, cur_res = await asyncio.gather(
            client.get(fc_url,  timeout=15),
            client.get(cur_url, timeout=15),
        )
        fc_res.raise_for_status(); cur_res.raise_for_status()
        fc = fc_res.json(); cur = cur_res.json()

        times, t_f_l, t_c_l, rh_l, pres_l, wmph_l, wkmh_l, precip_l, wdir_l = \
            [], [], [], [], [], [], [], [], []

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
        cm  = cur.get("main", {})
        tf0 = cm.get("temp")
        tc0 = round((tf0 - 32) * 5/9, 2) if tf0 is not None else 0.0
        ws0 = round((cur.get("wind") or {}).get("speed", 0.0), 2)
        wd0 = (cur.get("wind") or {}).get("deg")   # degrees from which wind blows
        times.append(now_iso); t_f_l.append(tf0); t_c_l.append(tc0)
        rh_l.append(cm.get("humidity")); pres_l.append(cm.get("pressure"))
        wmph_l.append(ws0); wkmh_l.append(round(ws0 * 1.60934, 2))
        precip_l.append((cur.get("rain") or {}).get("1h", 0.0))
        wdir_l.append(wd0)

        for slot in fc.get("list", []):
            dt_txt = slot.get("dt_txt", "")
            iso    = dt_txt.replace(" ", "T")[:16]
            sm     = slot.get("main", {})
            tf     = sm.get("temp")
            tc     = round((tf - 32) * 5/9, 2) if tf is not None else 0.0
            ws_mph = round((slot.get("wind") or {}).get("speed", 0.0), 2)
            wd     = (slot.get("wind") or {}).get("deg")
            rain   = (slot.get("rain") or {}).get("3h", 0.0)
            times.append(iso); t_f_l.append(tf); t_c_l.append(tc)
            rh_l.append(sm.get("humidity")); pres_l.append(sm.get("pressure"))
            wmph_l.append(ws_mph); wkmh_l.append(round(ws_mph * 1.60934, 2))
            precip_l.append(round(rain / 3.0, 4)); wdir_l.append(wd)

        return {
            "source": "openweathermap",
            "elevation": None,
            "hourly": {
                "time":                 times,
                "temperature_2m":       t_c_l,
                "temperature_2m_f":     t_f_l,
                "relative_humidity_2m": rh_l,
                "surface_pressure":     pres_l,
                "wind_speed_10m_mph":   wmph_l,
                "wind_speed_10m":       wkmh_l,
                "precipitation":        precip_l,
                "wind_direction_10m":   wdir_l,
            },
        }
    except Exception as exc:
        logger.warning("OWM fetch (%.4f,%.4f): %s", lat, lon, exc)
        return None


# ---------------------------------------------------------------------------
# Weather fetch — Tier 2: Open-Meteo
# ---------------------------------------------------------------------------

async def _fetch_open_meteo(lat: float, lon: float, client: httpx.AsyncClient) -> dict | None:
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,relative_humidity_2m,surface_pressure,"
            f"precipitation,wind_speed_10m,wind_direction_10m,weather_code"
            f"&timezone=UTC&forecast_days=16"
        )
        r = await client.get(url, timeout=15)
        r.raise_for_status()
        payload = r.json()
        payload["source"] = "open-meteo"
        h = payload.get("hourly", {})
        kmh = h.get("wind_speed_10m", [])
        h["wind_speed_10m_mph"] = [round(v * 0.621371, 2) if v is not None else None for v in kmh]
        h["temperature_2m_f"]   = [round(v * 9/5 + 32, 1) if v is not None else None
                                    for v in h.get("temperature_2m", [])]
        return payload
    except Exception as exc:
        logger.warning("open-meteo (%.4f,%.4f): %s", lat, lon, exc)
        return None


async def _fetch_wx(lat: float, lon: float, client: httpx.AsyncClient) -> dict | None:
    key = (round(lat, 3), round(lon, 3))
    async with _get_wx_lock():
        if key in _WX_CACHE: return _WX_CACHE[key]
    result = await _fetch_owm(lat, lon, client)
    if result is None: result = await _fetch_open_meteo(lat, lon, client)
    if result is not None:
        async with _get_wx_lock(): _WX_CACHE[key] = result
    return result


# ---------------------------------------------------------------------------
# Find closest hourly slot — now includes wind_direction_deg
# ---------------------------------------------------------------------------

def _closest_slot(wx: dict, target_ts: float) -> dict | None:
    try:
        times = wx["hourly"]["time"]
        parsed: list[float] = []
        for t in times:
            try:
                t2 = t.replace("Z", "+00:00")
                if len(t2) == 16: t2 += ":00+00:00"
                dt = datetime.fromisoformat(t2)
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                parsed.append(dt.timestamp())
            except Exception: parsed.append(0.0)

        best = min(range(len(parsed)), key=lambda i: abs(parsed[i] - target_ts))
        h    = wx["hourly"]

        def _get(key, idx): 
            lst = h.get(key) or []
            return lst[idx] if idx < len(lst) else None

        t_c  = _get("temperature_2m", best)
        t_f  = _get("temperature_2m_f", best)
        if t_f is None and t_c is not None: t_f = round(t_c * 9/5 + 32, 1)

        w_mph = _get("wind_speed_10m_mph", best)
        w_kmh = _get("wind_speed_10m",     best)
        if w_mph is None and w_kmh is not None: w_mph = round(w_kmh * 0.621371, 2)
        if w_kmh is None and w_mph is not None: w_kmh = round(w_mph * 1.60934, 2)

        w_dir = _get("wind_direction_10m", best)

        return {
            "temperature_c":         t_c,
            "temperature_f":         t_f,
            "relative_humidity_pct": _get("relative_humidity_2m", best),
            "station_pressure_hpa":  _get("surface_pressure",     best),
            "wind_speed_mph":        w_mph,
            "wind_speed_kmh":        w_kmh,
            "wind_direction_deg":    w_dir,
            "precipitation_mmh":     _get("precipitation",        best),
            "forecast_slot_utc":     times[best],
            "forecast_slot_ts":      parsed[best],
            "wx_source":             wx.get("source", "unknown"),
            "wx_elevation_m":        wx.get("elevation"),
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
    Append weather + air-density + pressure + wind-vs-stadium context to a venue dict.
    venue_block keys expected: lat, lon, elevation (FEET), state, is_indoor,
                               orientation_deg, roof_type.
    Returns venue_block with 'weather_context' key added.
    """
    lat        = venue_block.get("lat")
    lon        = venue_block.get("lon")
    elev_ft_wb = float(venue_block.get("elevation") or 0.0)
    state      = venue_block.get("state")
    is_indoor  = venue_block.get("is_indoor", False)
    is_retract = venue_block.get("is_retractable", False)
    roof_type  = venue_block.get("roof_type", "OUTDOOR" if not is_indoor else "INDOOR")
    orient_deg = venue_block.get("orientation_deg")

    if lat is None or lon is None:
        venue_block["weather_context"] = {"status": "unavailable_no_coordinates"}
        return venue_block

    game_ts      = _parse_game_time(game_time)
    game_et      = _ts_to_et_str(game_ts)
    dt_game_et   = datetime.fromtimestamp(game_ts, tz=ET_TZ)
    game_et_full = dt_game_et.strftime("%m/%d") + " " + game_et

    # Determine if roof is effectively closed for physics
    if is_retract:
        month = dt_game_et.month
        roof_closed = month in (11, 12, 1, 2, 3)  # winter default
    else:
        roof_closed = is_indoor

    wx = await _fetch_wx(lat, lon, client)
    if wx is None:
        venue_block["weather_context"] = {"status": "fetch_failed"}
        return venue_block

    slot = _closest_slot(wx, game_ts)
    if slot is None:
        venue_block["weather_context"] = {"status": "parse_failed"}
        return venue_block

    # Elevation resolution (3-tier)
    if elev_ft_wb > 10:
        elev_ft  = round(elev_ft_wb, 1)
        elev_m   = round(elev_ft_wb * 0.3048, 1)
        elev_src = "workbook"
    else:
        g_elev = await _google_elevation(lat, lon, client)
        if g_elev is not None:
            elev_m   = round(float(g_elev), 1)
            elev_ft  = round(elev_m * 3.28084, 1)
            elev_src = "google_elevation_api"
        else:
            wx_elev = slot.get("wx_elevation_m")
            if wx_elev is not None:
                elev_m   = round(float(wx_elev), 1)
                elev_ft  = round(elev_m * 3.28084, 1)
                elev_src = "open_meteo_terrain"
            else:
                elev_m   = 0.0
                elev_ft  = 0.0
                elev_src = "unknown"

    t_c   = float(slot["temperature_c"]         or 20.0)
    t_f   = float(slot["temperature_f"]         or round(t_c * 9/5 + 32, 1))
    rh    = float(slot["relative_humidity_pct"] or 50.0)
    p_hpa = float(slot["station_pressure_hpa"]  or 1013.25)
    w_mph = slot["wind_speed_mph"]
    w_kmh = slot["wind_speed_kmh"]
    w_dir = slot["wind_direction_deg"]
    prec_mm = slot["precipitation_mmh"] or 0.0
    prec_in = round(prec_mm / 25.4, 4)

    # Forecast time labels
    fts = slot["forecast_slot_ts"]
    forecast_et = _ts_to_et_str(fts)
    dt_fc_et    = datetime.fromtimestamp(fts, tz=ET_TZ)
    forecast_et_full = dt_fc_et.strftime("%m/%d") + " " + forecast_et
    tz_local = _get_tz(state)
    dt_fc_local = datetime.fromtimestamp(fts, tz=tz_local)
    try:    forecast_local = dt_fc_local.strftime("%-I:%M %p ") + dt_fc_local.strftime("%Z")
    except ValueError: forecast_local = dt_fc_local.strftime("%I:%M %p ").lstrip("0") + dt_fc_local.strftime("%Z")

    # Physics model: indoor vs outdoor
    if roof_closed:
        phys = indoor_hvac_model(p_hpa, t_c, rh, elev_m, roof_type)
        wind_analysis = {"status": "not_applicable_indoor", "note": f"Roof type: {roof_type}"}
    else:
        phys = full_pressure_block(p_hpa, t_c, rh, elev_m)
        wind_analysis = wind_vs_stadium(w_mph, w_dir, orient_deg)

    ctx: dict[str, Any] = {
        "status":               "ok",
        "wx_source":            slot["wx_source"],
        "elev_source":          elev_src,
        "roof_type":            roof_type,
        "roof_closed":          roof_closed,
        "elevation_ft":         elev_ft,
        "elevation_m":          elev_m,

        # Raw weather observations
        "temperature_f":               round(t_f, 1),
        "temperature_c":               round(t_c, 2),
        "relative_humidity_pct":       round(rh, 1),
        "wind_speed_mph":              round(w_mph, 1) if w_mph is not None else None,
        "wind_speed_kmh":              round(w_kmh, 1) if w_kmh is not None else None,
        "wind_direction_deg":          round(w_dir, 1) if w_dir is not None else None,
        "precipitation_inh":           prec_in,
        "precipitation_mmh":           round(prec_mm, 3),

        # Full pressure + density block (or indoor model)
        "pressure_density": phys,

        # Wind vs stadium orientation
        "wind_vs_stadium": wind_analysis,

        # Game/forecast time
        "game_time_raw":          game_time,
        "game_time_et":           game_et,
        "game_time_et_full":      game_et_full,
        "forecast_hour_et":       forecast_et,
        "forecast_hour_et_full":  forecast_et_full,
        "forecast_hour_local":    forecast_local,
        "forecast_hour_utc":      slot["for