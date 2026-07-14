"""weather_enricher.py — OverlineEdge v8.3.1

API PRIORITY CHAIN — Weather:
  Tier 1 (primary)  : OpenWeatherMap /weather + /forecast  (OPENWEATHER_API_KEY)
  Tier 2 (fallback) : Open-Meteo free hourly forecast      (no key)

API PRIORITY CHAIN — Elevation:
  Tier 1 : Venue workbook (feet) — convert to metres here
  Tier 2 : Google Elevation API  (GOOGLE_ELEV_KEY)
  Tier 3 : Open-Meteo terrain elevation embedded in wx payload

FIX v8.3.1:
  - asyncio.Lock objects created lazily (NOT at module level) to prevent
    ImportError on Python 3.10+ / 3.14 when the event loop is not yet running.
  - All module-level state uses plain dicts; Locks are instantiated on first use.
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
# State → IANA timezone map
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
    "AK": "America/Anchorage",  "HI": "Pacific/Honolulu",
}

# ---------------------------------------------------------------------------
# API keys from environment
# ---------------------------------------------------------------------------
OWM_KEY    = os.environ.get("OPENWEATHER_API_KEY", "")
GELEV_KEY  = os.environ.get("GOOGLE_ELEV_KEY",     "")

# ---------------------------------------------------------------------------
# Physical constants — ISA / moist-air
# ---------------------------------------------------------------------------
_Rd        = 287.05
_Rv        = 461.495
_ISA_SLP   = 1013.25
_ISA_RHO   = 1.225
_ISA_T0    = 288.15
_LAPSE     = 0.0065
_INDOOR_TC = 21.0
_INDOOR_RH = 45.0

# ---------------------------------------------------------------------------
# Module-level plain dicts (NO asyncio.Lock at module level — see Python 3.10 deprecation)
# ---------------------------------------------------------------------------
_WX_CACHE:   dict = {}
_ELEV_CACHE: dict = {}

# Locks are created lazily on first async call
_wx_lock:   asyncio.Lock | None = None
_elev_lock: asyncio.Lock | None = None


def _get_wx_lock() -> asyncio.Lock:
    global _wx_lock
    if _wx_lock is None:
        _wx_lock = asyncio.Lock()
    return _wx_lock


def _get_elev_lock() -> asyncio.Lock:
    global _elev_lock
    if _elev_lock is None:
        _elev_lock = asyncio.Lock()
    return _elev_lock


# ---------------------------------------------------------------------------
# Physics helpers
# ---------------------------------------------------------------------------

def _sat_pressure_hpa(t_c: float) -> float:
    return 6.112 * math.exp(17.67 * t_c / (t_c + 243.5))


def _moist_density(p_hpa: float, t_c: float, rh_pct: float) -> float:
    T  = t_c + 273.15
    es = _sat_pressure_hpa(t_c)
    e  = min(p_hpa, rh_pct / 100.0 * es)
    pd = (p_hpa - e) * 100.0
    pv = e * 100.0
    return pd / (_Rd * T) + pv / (_Rv * T)


def _isa_at_elev(elev_m: float) -> tuple[float, float]:
    h = max(-500.0, min(11_000.0, float(elev_m)))
    q = 1.0 - _LAPSE * h / _ISA_T0
    p = _ISA_SLP  * q ** 5.25588
    r = _ISA_RHO  * q ** 4.25588
    return p, r


def _indoor_estimate(p_hpa: float, t_c_outdoor: float, rh_pct_outdoor: float) -> dict:
    rho_in  = _moist_density(p_hpa, _INDOOR_TC, _INDOOR_RH)
    rho_out = _moist_density(p_hpa, t_c_outdoor, rh_pct_outdoor)
    pct_vs  = round((rho_in / rho_out - 1.0) * 100.0, 4)
    return {
        "density_kgm3":     round(rho_in, 6),
        "assumed_temp_f":   round(_INDOOR_TC * 9 / 5 + 32, 1),
        "assumed_temp_c":   _INDOOR_TC,
        "assumed_rh_pct":   _INDOOR_RH,
        "pct_vs_outdoor":   pct_vs,
        "note": "HVAC baseline 70 F (21 C) / 45 % RH.",
    }


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _get_tz(state: str | None) -> pytz.BaseTzInfo:
    if state:
        tz_name = _STATE_TZ.get(state.strip().upper())
        if tz_name:
            try:
                return pytz.timezone(tz_name)
            except Exception:
                pass
    return ET_TZ


def _ts_to_et_str(ts: float) -> str:
    try:
        dt_et = datetime.fromtimestamp(ts, tz=ET_TZ)
        try:
            return dt_et.strftime("%-I:%M %p ET")
        except ValueError:
            return dt_et.strftime("%I:%M %p ET").lstrip("0")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Game-time parser
# ---------------------------------------------------------------------------
_SCRAPER_RE  = re.compile(r"^(\d{1,2})/(\d{1,2})\s+(\d{1,2}:\d{2})\s*(AM|PM)$", re.IGNORECASE)
_TIME_ONLY_RE = re.compile(r"^(\d{1,2}:\d{2})\s*(AM|PM)", re.IGNORECASE)


def _parse_game_time(raw: str) -> float:
    if not raw:
        return datetime.now(timezone.utc).timestamp()
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
                dt_et = ET_TZ.localize(dt_naive)
                if (dt_et.timestamp() - now_et.timestamp()) >= -43_200:
                    return dt_et.timestamp()
            except Exception:
                pass

    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass

    stripped = raw.replace(" ET", "").replace(" PT", "").replace(" CT", "").replace(" MT", "")
    m2 = _TIME_ONLY_RE.match(stripped)
    if m2:
        try:
            today = now_et.strftime("%Y-%m-%d")
            dt_naive = datetime.strptime(f"{today} {m2.group(1)} {m2.group(2).upper()}", "%Y-%m-%d %I:%M %p")
            return ET_TZ.localize(dt_naive).timestamp()
        except Exception:
            pass

    logger.warning("_parse_game_time: unparseable %r — using now()", raw)
    return datetime.now(timezone.utc).timestamp()


# ---------------------------------------------------------------------------
# Elevation lookup — Google Elevation API (Tier 2)
# ---------------------------------------------------------------------------

async def _google_elevation(lat: float, lon: float, client: httpx.AsyncClient) -> float | None:
    if not GELEV_KEY:
        return None
    key = (round(lat, 4), round(lon, 4))
    async with _get_elev_lock():
        if key in _ELEV_CACHE:
            return _ELEV_CACHE[key]
    try:
        r = await client.get(
            "https://maps.googleapis.com/maps/api/elevation/json",
            params={"locations": f"{lat},{lon}", "key": GELEV_KEY},
            timeout=10,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if results:
            elev_m = float(results[0]["elevation"])
            async with _get_elev_lock():
                _ELEV_CACHE[key] = elev_m
            return elev_m
    except Exception as exc:
        logger.warning("Google Elevation failed (%.4f, %.4f): %s", lat, lon, exc)
    return None


# ---------------------------------------------------------------------------
# Weather fetch — Tier 1: OpenWeatherMap
# ---------------------------------------------------------------------------

async def _fetch_owm(lat: float, lon: float, client: httpx.AsyncClient) -> dict | None:
    if not OWM_KEY:
        return None
    try:
        fc_url  = (f"https://api.openweathermap.org/data/2.5/forecast"
                   f"?lat={lat}&lon={lon}&appid={OWM_KEY}&units=imperial&cnt=40")
        cur_url = (f"https://api.openweathermap.org/data/2.5/weather"
                   f"?lat={lat}&lon={lon}&appid={OWM_KEY}&units=imperial")
        fc_res, cur_res = await asyncio.gather(
            client.get(fc_url,  timeout=15),
            client.get(cur_url, timeout=15),
        )
        fc_res.raise_for_status()
        cur_res.raise_for_status()
        fc  = fc_res.json()
        cur = cur_res.json()

        times, t_f_list, t_c_list, rh_list, pres_list, wmph_list, wkmh_list, precip_list = \
            [], [], [], [], [], [], [], []

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
        cm  = cur.get("main", {})
        tf0 = cm.get("temp")
        tc0 = round((tf0 - 32) * 5 / 9, 2) if tf0 is not None else 0.0
        ws0 = round((cur.get("wind") or {}).get("speed", 0.0), 2)
        times.append(now_iso); t_f_list.append(tf0); t_c_list.append(tc0)
        rh_list.append(cm.get("humidity")); pres_list.append(cm.get("pressure"))
        wmph_list.append(ws0); wkmh_list.append(round(ws0 * 1.60934, 2))
        precip_list.append((cur.get("rain") or {}).get("1h", 0.0))

        for slot in fc.get("list", []):
            dt_txt = slot.get("dt_txt", "")
            iso    = dt_txt.replace(" ", "T")[:16]
            sm     = slot.get("main", {})
            tf     = sm.get("temp")
            tc     = round((tf - 32) * 5 / 9, 2) if tf is not None else 0.0
            ws_mph = round((slot.get("wind") or {}).get("speed", 0.0), 2)
            rain   = (slot.get("rain") or {}).get("3h", 0.0)
            times.append(iso); t_f_list.append(tf); t_c_list.append(tc)
            rh_list.append(sm.get("humidity")); pres_list.append(sm.get("pressure"))
            wmph_list.append(ws_mph); wkmh_list.append(round(ws_mph * 1.60934, 2))
            precip_list.append(round(rain / 3.0, 4))

        return {
            "source": "openweathermap",
            "elevation": None,
            "hourly": {
                "time":                 times,
                "temperature_2m":       t_c_list,
                "temperature_2m_f":     t_f_list,
                "relative_humidity_2m": rh_list,
                "surface_pressure":     pres_list,
                "wind_speed_10m_mph":   wmph_list,
                "wind_speed_10m":       wkmh_list,
                "precipitation":        precip_list,
            },
        }
    except Exception as exc:
        logger.warning("OWM fetch failed (%.4f, %.4f): %s", lat, lon, exc)
        return None


# ---------------------------------------------------------------------------
# Weather fetch — Tier 2: Open-Meteo (free, no key)
# ---------------------------------------------------------------------------

async def _fetch_open_meteo(lat: float, lon: float, client: httpx.AsyncClient) -> dict | None:
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,relative_humidity_2m,surface_pressure,"
            f"precipitation,wind_speed_10m,weather_code"
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
        logger.warning("open-meteo fetch failed (%.4f, %.4f): %s", lat, lon, exc)
        return None


# ---------------------------------------------------------------------------
# Dispatcher + cache
# ---------------------------------------------------------------------------

async def _fetch_wx(lat: float, lon: float, client: httpx.AsyncClient) -> dict | None:
    key = (round(lat, 3), round(lon, 3))
    async with _get_wx_lock():
        if key in _WX_CACHE:
            return _WX_CACHE[key]
    result = await _fetch_owm(lat, lon, client)
    if result is None:
        result = await _fetch_open_meteo(lat, lon, client)
    if result is not None:
        async with _get_wx_lock():
            _WX_CACHE[key] = result
    return result


# ---------------------------------------------------------------------------
# Find closest hourly slot to game time
# ---------------------------------------------------------------------------

def _closest_slot(wx: dict, target_ts: float) -> dict | None:
    try:
        times = wx["hourly"]["time"]
        parsed: list[float] = []
        for t in times:
            try:
                t2 = t.replace("Z", "+00:00")
                if len(t2) == 16:
                    t2 += ":00+00:00"
                dt = datetime.fromisoformat(t2)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                parsed.append(dt.timestamp())
            except Exception:
                parsed.append(0.0)

        best = min(range(len(parsed)), key=lambda i: abs(parsed[i] - target_ts))
        h    = wx["hourly"]

        t_c  = h["temperature_2m"][best]
        t_f_l = h.get("temperature_2m_f") or []
        t_f  = t_f_l[best] if best < len(t_f_l) else None
        if t_f is None and t_c is not None:
            t_f = round(t_c * 9 / 5 + 32, 1)

        wmph_l = h.get("wind_speed_10m_mph") or []
        wkmh_l = h.get("wind_speed_10m")     or []
        w_mph  = wmph_l[best] if best < len(wmph_l) else None
        w_kmh  = wkmh_l[best] if best < len(wkmh_l) else None
        if w_mph is None and w_kmh is not None:
            w_mph = round(w_kmh * 0.621371, 2)
        if w_kmh is None and w_mph is not None:
            w_kmh = round(w_mph * 1.60934, 2)

        return {
            "temperature_c":         t_c,
            "temperature_f":         t_f,
            "relative_humidity_pct": h["relative_humidity_2m"][best],
            "station_pressure_hpa":  h["surface_pressure"][best],
            "wind_speed_mph":        w_mph,
            "wind_speed_kmh":        w_kmh,
            "precipitation_mmh":     h["precipitation"][best],
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
    Append weather + air-density context to a venue dict.
    venue_block keys expected: lat, lon, elevation (FEET), state, is_indoor.
    Returns venue_block with 'weather_context' key added.
    """
    lat        = venue_block.get("lat")
    lon        = venue_block.get("lon")
    elev_ft_wb = float(venue_block.get("elevation") or 0.0)
    state      = venue_block.get("state")
    is_indoor  = venue_block.get("is_indoor", False)

    if lat is None or lon is None:
        venue_block["weather_context"] = {"status": "unavailable_no_coordinates"}
        return venue_block

    game_ts      = _parse_game_time(game_time)
    game_et      = _ts_to_et_str(game_ts)
    dt_game_et   = datetime.fromtimestamp(game_ts, tz=ET_TZ)
    game_et_full = dt_game_et.strftime("%m/%d") + " " + game_et

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

    p_inhg  = round(p_hpa / 33.8639, 4)
    w_mph   = slot["wind_speed_mph"]
    w_kmh   = slot["wind_speed_kmh"]
    prec_mm = slot["precipitation_mmh"] or 0.0
    prec_in = round(prec_mm / 25.4, 4)

    rho          = _moist_density(p_hpa, t_c, rh)
    pct_isa_sl   = round(rho / _ISA_RHO * 100.0, 4)
    isa_p, isa_r = _isa_at_elev(elev_m)
    pct_isa_elev = round(rho / isa_r * 100.0, 4)
    isa_p_inhg   = round(isa_p / 33.8639, 4)

    fts           = slot["forecast_slot_ts"]
    forecast_et   = _ts_to_et_str(fts)
    dt_fc_et      = datetime.fromtimestamp(fts, tz=ET_TZ)
    forecast_et_full = dt_fc_et.strftime("%m/%d") + " " + forecast_et
    tz_local      = _get_tz(state)
    dt_fc_local   = datetime.fromtimestamp(fts, tz=tz_local)
    try:
        forecast_local = dt_fc_local.strftime("%-I:%M %p ") + dt_fc_local.strftime("%Z")
    except ValueError:
        forecast_local = dt_fc_local.strftime("%I:%M %p ").lstrip("0") + dt_fc_local.strftime("%Z")

    ctx: dict[str, Any] = {
        "status":                      "ok",
        "wx_source":                   slot["wx_source"],
        "elev_source":                 elev_src,
        "temperature_f":               round(t_f, 1),
        "temperature_c":               round(t_c, 2),
        "relative_humidity_pct":       round(rh, 1),
        "station_pressure_inhg":       p_inhg,
        "station_pressure_hpa":        round(p_hpa, 2),
        "wind_speed_mph":              round(w_mph, 1) if w_mph is not None else None,
        "wind_speed_kmh":              round(w_kmh, 1) if w_kmh is not None else None,
        "precipitation_inh":           prec_in,
        "precipitation_mmh":           round(prec_mm, 3),
        "air_density_kgm3":            round(rho, 6),
        "density_pct_of_isa_sealevel": pct_isa_sl,
        "density_pct_of_isa_elevation":pct_isa_elev,
        "isa_at_elevation": {
            "elevation_ft":  elev_ft,
            "elevation_m":   elev_m,
            "pressure_inhg": isa_p_inhg,
            "pressure_hpa":  round(isa_p, 4),
            "density_kgm3":  round(isa_r, 6),
        },
        "elevation_ft":                elev_ft,
        "elevation_m":                 elev_m,
        "mapped_elevation_ft":         elev_ft,
        "mapped_elevation_m":          elev_m,
        "game_time_raw":               game_time,
        "game_time_et":                game_et,
        "game_time_et_full":           game_et_full,
        "forecast_hour_et":            forecast_et,
        "forecast_hour_et_full":       forecast_et_full,
        "forecast_hour_local":         forecast_local,
        "forecast_hour_utc":           slot["forecast_slot_utc"],
        "forecast_hour_ts":            fts,
        "is_indoor":                   is_indoor,
    }

    if is_indoor:
        ctx["indoor_estimate"] = _indoor_estimate(p_hpa, t_c, rh)

    venue_block["weather_context"] = ctx
    return venue_block


def clear_cache() -> None:
    """Clear all weather and elevation caches. Call between test runs."""
    _WX_CACHE.clear()
    _ELEV_CACHE.clear()
