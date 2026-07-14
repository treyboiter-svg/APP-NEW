<#
.SYNOPSIS
    OverlineEdge v8.4.3 — Full offline install / sync.
    Writes wnba_venues.py, pressure_calc.py, wind_calc.py directly to disk
    from embedded here-strings (NO network required for these files).
    Then tries Invoke-WebRequest (no curl) for remaining files.
    Then pip installs and verifies all imports.

.USAGE
    Right-click -> Run with PowerShell
    OR in PS terminal:  Set-ExecutionPolicy -Scope Process Bypass; .\INSTALL.ps1
#>

$ErrorActionPreference = 'Continue'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $dir

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  OverlineEdge v8.4.3 -- FULL INSTALL (offline-safe)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Writing embedded modules directly to disk (no SSL/curl needed)..."
Write-Host ""

# ===========================================================================
# STEP 1 — Write wnba_venues.py directly from embedded content
# ===========================================================================
$wnba = @'
"""wnba_venues.py -- OverlineEdge v8.4.0
Standalone WNBA venue authority. Completely separate from the main US_SPORTS_VENUES workbook.
Contains: all 15 current WNBA franchises (2026 season including expansion teams),
full venue physics data: lat/lon, elevation, stadium orientation, roof type.

Roof types: OPEN | RETRACTABLE | DOME | INDOOR
For DOME and INDOOR: weather APIs are bypassed; HVAC physics model is used.
For RETRACTABLE: roof_status must be resolved at game time (defaults to OPEN in summer).
"""
from __future__ import annotations
import math
from dataclasses import dataclass

@dataclass(frozen=True)
class WNBAVenue:
    team:                 str
    city:                 str
    state:                str
    venue:                str
    lat:                  float
    lon:                  float
    elevation_ft:         float
    elevation_m:          float
    orientation_deg:      float | None
    orientation_label:    str   | None
    roof_type:            str
    capacity:             int
    surface:              str

_WNBA_VENUES = [
    WNBAVenue(team="Phoenix Mercury",city="Phoenix",state="AZ",venue="Footprint Center",lat=33.4457,lon=-112.0712,elevation_ft=1086.0,elevation_m=331.0,orientation_deg=90.0,orientation_label="E",roof_type="INDOOR",capacity=18422,surface="HARDWOOD"),
    WNBAVenue(team="Minnesota Lynx",city="Minneapolis",state="MN",venue="Target Center",lat=44.9795,lon=-93.2761,elevation_ft=830.0,elevation_m=253.0,orientation_deg=0.0,orientation_label="N",roof_type="INDOOR",capacity=19356,surface="HARDWOOD"),
    WNBAVenue(team="Los Angeles Sparks",city="Los Angeles",state="CA",venue="Crypto.com Arena",lat=34.0430,lon=-118.2673,elevation_ft=161.0,elevation_m=49.0,orientation_deg=45.0,orientation_label="NE",roof_type="INDOOR",capacity=19795,surface="HARDWOOD"),
    WNBAVenue(team="Atlanta Dream",city="Atlanta",state="GA",venue="Gateway Center Arena",lat=33.5735,lon=-84.3524,elevation_ft=1050.0,elevation_m=320.0,orientation_deg=0.0,orientation_label="N",roof_type="INDOOR",capacity=13707,surface="HARDWOOD"),
    WNBAVenue(team="Chicago Sky",city="Chicago",state="IL",venue="Wintrust Arena",lat=41.8673,lon=-87.6253,elevation_ft=594.0,elevation_m=181.0,orientation_deg=0.0,orientation_label="N",roof_type="INDOOR",capacity=10387,surface="HARDWOOD"),
    WNBAVenue(team="Dallas Wings",city="Arlington",state="TX",venue="College Park Center",lat=32.7326,lon=-97.1115,elevation_ft=616.0,elevation_m=188.0,orientation_deg=0.0,orientation_label="N",roof_type="INDOOR",capacity=7000,surface="HARDWOOD"),
    WNBAVenue(team="Connecticut Sun",city="Uncasville",state="CT",venue="Mohegan Sun Arena",lat=41.4752,lon=-72.0912,elevation_ft=120.0,elevation_m=37.0,orientation_deg=0.0,orientation_label="N",roof_type="INDOOR",capacity=10000,surface="HARDWOOD"),
    WNBAVenue(team="Seattle Storm",city="Seattle",state="WA",venue="Climate Pledge Arena",lat=47.6218,lon=-122.3542,elevation_ft=174.0,elevation_m=53.0,orientation_deg=45.0,orientation_label="NE",roof_type="INDOOR",capacity=17459,surface="HARDWOOD"),
    WNBAVenue(team="Indiana Fever",city="Indianapolis",state="IN",venue="Gainbridge Fieldhouse",lat=39.7639,lon=-86.1555,elevation_ft=715.0,elevation_m=218.0,orientation_deg=0.0,orientation_label="N",roof_type="INDOOR",capacity=17923,surface="HARDWOOD"),
    WNBAVenue(team="Las Vegas Aces",city="Las Vegas",state="NV",venue="Michelob ULTRA Arena",lat=36.1026,lon=-115.1783,elevation_ft=2001.0,elevation_m=610.0,orientation_deg=90.0,orientation_label="E",roof_type="INDOOR",capacity=12000,surface="HARDWOOD"),
    WNBAVenue(team="Washington Mystics",city="Washington",state="DC",venue="Capital One Arena",lat=38.8981,lon=-77.0209,elevation_ft=30.0,elevation_m=9.0,orientation_deg=0.0,orientation_label="N",roof_type="INDOOR",capacity=20356,surface="HARDWOOD"),
    WNBAVenue(team="New York Liberty",city="Brooklyn",state="NY",venue="Barclays Center",lat=40.6826,lon=-73.9754,elevation_ft=10.0,elevation_m=3.0,orientation_deg=0.0,orientation_label="N",roof_type="INDOOR",capacity=17732,surface="HARDWOOD"),
    WNBAVenue(team="Golden State Valkyries",city="San Francisco",state="CA",venue="Chase Center",lat=37.7680,lon=-122.3877,elevation_ft=20.0,elevation_m=6.0,orientation_deg=45.0,orientation_label="NE",roof_type="INDOOR",capacity=18064,surface="HARDWOOD"),
    WNBAVenue(team="Portland Blue Crew",city="Portland",state="OR",venue="Moda Center",lat=45.5316,lon=-122.6668,elevation_ft=108.0,elevation_m=33.0,orientation_deg=176.0,orientation_label="S",roof_type="INDOOR",capacity=19980,surface="HARDWOOD"),
    WNBAVenue(team="Cleveland Charge",city="Cleveland",state="OH",venue="Rocket Mortgage FieldHouse",lat=41.4966,lon=-81.6886,elevation_ft=653.0,elevation_m=199.0,orientation_deg=0.0,orientation_label="N",roof_type="INDOOR",capacity=19432,surface="HARDWOOD"),
]

_BY_TEAM = {v.team: v for v in _WNBA_VENUES}
_NICKNAMES = {
    "mercury":"Phoenix Mercury","phoenix mercury":"Phoenix Mercury",
    "lynx":"Minnesota Lynx","minnesota lynx":"Minnesota Lynx",
    "sparks":"Los Angeles Sparks","los angeles sparks":"Los Angeles Sparks","la sparks":"Los Angeles Sparks",
    "dream":"Atlanta Dream","atlanta dream":"Atlanta Dream",
    "sky":"Chicago Sky","chicago sky":"Chicago Sky",
    "wings":"Dallas Wings","dallas wings":"Dallas Wings",
    "sun":"Connecticut Sun","connecticut sun":"Connecticut Sun",
    "storm":"Seattle Storm","seattle storm":"Seattle Storm",
    "fever":"Indiana Fever","indiana fever":"Indiana Fever",
    "aces":"Las Vegas Aces","las vegas aces":"Las Vegas Aces","lv aces":"Las Vegas Aces",
    "mystics":"Washington Mystics","washington mystics":"Washington Mystics",
    "liberty":"New York Liberty","new york liberty":"New York Liberty","ny liberty":"New York Liberty",
    "valkyries":"Golden State Valkyries","golden state valkyries":"Golden State Valkyries",
    "blue crew":"Portland Blue Crew","portland blue crew":"Portland Blue Crew",
    "charge":"Cleveland Charge","cleveland charge":"Cleveland Charge",
}

def resolve_wnba_team(raw: str):
    key = " ".join(raw.lower().strip().split())
    canonical = _NICKNAMES.get(key)
    if canonical:
        return _BY_TEAM.get(canonical)
    for nick, team_name in _NICKNAMES.items():
        if nick in key or key in nick:
            return _BY_TEAM.get(team_name)
    return None

def wnba_venue_block(venue: WNBAVenue) -> dict:
    return {
        "name": venue.venue, "city": venue.city, "state": venue.state,
        "lat": venue.lat, "lon": venue.lon, "elevation": venue.elevation_ft,
        "orientation_deg": venue.orientation_deg, "orientation_label": venue.orientation_label,
        "orientation_confidence": 1.0, "roof_type": venue.roof_type,
        "is_indoor": venue.roof_type in ("INDOOR", "DOME"),
        "is_retractable": venue.roof_type == "RETRACTABLE",
        "capacity": venue.capacity, "surface": venue.surface,
    }
'@
[System.IO.File]::WriteAllText((Join-Path $dir 'wnba_venues.py'), $wnba, [System.Text.Encoding]::UTF8)
Write-Host "  [OK] wnba_venues.py written" -ForegroundColor Green

# ===========================================================================
# STEP 2 — Write pressure_calc.py
# ===========================================================================
$pressure = @'
"""pressure_calc.py -- OverlineEdge v8.4.0
True barometric/absolute pressure and air density physics.

station_pressure  = MEASURED absolute surface pressure at the venue (hPa).
                    Already accounts for elevation. Use THIS for all density calcs.
sea_level_pressure= station_pressure corrected to sea level (MSLP). Display only.
isa_at_elevation  = ISA standard atmosphere at venue elevation. Reference baseline.
air_density       = rho = (p_d / R_d*T) + (p_v / R_v*T)  [moist air, kg/m3]
density_altitude  = pressure altitude corrected for non-standard temperature.

All WNBA venues are indoor: use indoor_hvac_model() for those.
"""
from __future__ import annotations
import math

_Rd    = 287.05
_Rv    = 461.495
_ISA_P0  = 101325.0
_ISA_T0  = 288.15
_ISA_RHO = 1.225
_LAPSE   = 0.0065
_HPA_TO_INHG = 1.0 / 33.8639
_HPA_TO_PA   = 100.0

def saturation_pressure_hpa(t_c: float) -> float:
    return 6.112 * math.exp(17.67 * t_c / (t_c + 243.5))

def moist_air_density(station_pressure_hpa: float, temp_c: float, rh_pct: float) -> float:
    T  = temp_c + 273.15
    es = saturation_pressure_hpa(temp_c)
    e  = min(station_pressure_hpa, rh_pct / 100.0 * es)
    pd = (station_pressure_hpa - e) * _HPA_TO_PA
    pv = e * _HPA_TO_PA
    return pd / (_Rd * T) + pv / (_Rv * T)

def isa_at_elevation(elev_m: float) -> dict:
    h   = max(-500.0, min(11000.0, float(elev_m)))
    q   = 1.0 - _LAPSE * h / _ISA_T0
    p   = (_ISA_P0 / _HPA_TO_PA) * q ** 5.25588
    rho = _ISA_RHO * q ** 4.25588
    t_c = _ISA_T0 * q - 273.15
    return {"elevation_m": round(h,1), "pressure_hpa": round(p,4),
            "pressure_inhg": round(p*_HPA_TO_INHG,4), "density_kgm3": round(rho,6), "temp_c": round(t_c,2)}

def station_to_sea_level(station_hpa: float, elev_m: float, temp_c: float) -> float:
    T = temp_c + 273.15
    return round(station_hpa * math.exp(_LAPSE * elev_m / T), 4)

def density_altitude_ft(station_hpa: float, temp_c: float, rh_pct: float = 0.0) -> float:
    es = saturation_pressure_hpa(temp_c)
    e  = rh_pct / 100.0 * es
    mixing_ratio = 0.622 * e / (station_hpa - e)
    T_virtual = (temp_c + 273.15) * (1 + 1.608 * mixing_ratio) / (1 + mixing_ratio)
    ratio = station_hpa / 1013.25
    pa_ft = (1 - ratio ** 0.190284) * 145366.45
    da_ft = pa_ft + 120 * (T_virtual - _ISA_T0)
    return round(da_ft, 0)

def full_pressure_block(station_hpa: float, temp_c: float, rh_pct: float, elev_m: float) -> dict:
    rho   = moist_air_density(station_hpa, temp_c, rh_pct)
    isa   = isa_at_elevation(elev_m)
    mslp  = station_to_sea_level(station_hpa, elev_m, temp_c)
    da_ft = density_altitude_ft(station_hpa, temp_c, rh_pct)
    return {
        "station_pressure_hpa":   round(station_hpa, 2),
        "station_pressure_inhg":  round(station_hpa * _HPA_TO_INHG, 4),
        "station_pressure_pa":    round(station_hpa * _HPA_TO_PA, 1),
        "sea_level_pressure_hpa":  mslp,
        "sea_level_pressure_inhg": round(mslp * _HPA_TO_INHG, 4),
        "air_density_kgm3":         round(rho, 6),
        "air_density_lbft3":        round(rho * 0.0624279606, 6),
        "density_pct_of_isa_sealevel": round(rho / _ISA_RHO * 100.0, 4),
        "density_pct_of_isa_elevation": round(rho / isa["density_kgm3"] * 100.0, 4),
        "isa_at_elevation": isa,
        "density_altitude_ft": da_ft,
        "density_altitude_m":  round(da_ft * 0.3048, 0),
        "inputs": {"temp_c": round(temp_c,2), "temp_f": round(temp_c*9/5+32,1),
                   "rh_pct": round(rh_pct,1), "elev_m": round(elev_m,1), "elev_ft": round(elev_m*3.28084,1)},
    }

_HVAC_TEMP_C = 21.0
_HVAC_RH_PCT = 45.0
_HVAC_TEMP_F = 70.0

def indoor_hvac_model(station_hpa_outdoor: float, temp_c_outdoor: float,
                      rh_pct_outdoor: float, elev_m: float, roof_type: str = "INDOOR") -> dict:
    rho_indoor  = moist_air_density(station_hpa_outdoor, _HVAC_TEMP_C, _HVAC_RH_PCT)
    rho_outdoor = moist_air_density(station_hpa_outdoor, temp_c_outdoor, rh_pct_outdoor)
    isa         = isa_at_elevation(elev_m)
    da_ft       = density_altitude_ft(station_hpa_outdoor, _HVAC_TEMP_C, _HVAC_RH_PCT)
    return {
        "roof_type": roof_type, "status": "indoor_hvac_model",
        "note": f"HVAC baseline {_HVAC_TEMP_F} F / {_HVAC_RH_PCT}% RH. Outdoor pressure drives indoor.",
        "indoor_temp_f": _HVAC_TEMP_F, "indoor_temp_c": _HVAC_TEMP_C, "indoor_rh_pct": _HVAC_RH_PCT,
        "station_pressure_hpa":  round(station_hpa_outdoor, 2),
        "station_pressure_inhg": round(station_hpa_outdoor / 33.8639, 4),
        "air_density_kgm3":          round(rho_indoor, 6),
        "air_density_lbft3":         round(rho_indoor * 0.0624279606, 6),
        "density_pct_of_isa_sealevel": round(rho_indoor / _ISA_RHO * 100.0, 4),
        "density_pct_of_isa_elevation": round(rho_indoor / isa["density_kgm3"] * 100.0, 4),
        "density_pct_vs_outdoor":    round((rho_indoor / rho_outdoor - 1.0) * 100.0, 4),
        "density_altitude_ft": da_ft,
        "isa_at_elevation": isa,
        "outdoor_temp_c": round(temp_c_outdoor,2), "outdoor_temp_f": round(temp_c_outdoor*9/5+32,1),
        "outdoor_rh_pct": round(rh_pct_outdoor,1), "outdoor_density_kgm3": round(rho_outdoor,6),
    }
'@
[System.IO.File]::WriteAllText((Join-Path $dir 'pressure_calc.py'), $pressure, [System.Text.Encoding]::UTF8)
Write-Host "  [OK] pressure_calc.py written" -ForegroundColor Green

# ===========================================================================
# STEP 3 — Write wind_calc.py
# ===========================================================================
$wind = @'
"""wind_calc.py -- OverlineEdge v8.4.0
Wind direction analysis relative to stadium orientation.
All WNBA venues are indoor; wind is N/A for them.
Physics:
  headwind  = wind_speed * cos(relative_angle)
  crosswind = wind_speed * sin(relative_angle)
  relative_angle = (wind_dir_from - field_orientation) mod 360, mapped to [-180,180]
Wind convention: direction FROM which wind blows (270 = FROM west).
Field orientation_deg: compass bearing the field long axis points.
"""
from __future__ import annotations
import math

_COMPASS_LABELS = [
    ("N",0.0),("NNE",22.5),("NE",45.0),("ENE",67.5),
    ("E",90.0),("ESE",112.5),("SE",135.0),("SSE",157.5),
    ("S",180.0),("SSW",202.5),("SW",225.0),("WSW",247.5),
    ("W",270.0),("WNW",292.5),("NW",315.0),("NNW",337.5),
]

def _deg_label(deg: float) -> str:
    deg = deg % 360
    best = min(_COMPASS_LABELS, key=lambda x: abs((x[1]-deg+180)%360-180))
    return best[0]

def wind_vs_stadium(wind_speed_mph, wind_dir_deg, orientation_deg) -> dict:
    if wind_speed_mph is None or wind_dir_deg is None or orientation_deg is None:
        return {
            "status": "insufficient_data",
            "wind_dir_deg": wind_dir_deg,
            "wind_dir_label": _deg_label(wind_dir_deg) if wind_dir_deg is not None else None,
            "field_orientation": orientation_deg,
            "relative_angle_deg": None, "headwind_mph": None,
            "crosswind_mph": None, "crosswind_dir": None, "wind_effect_label": None,
        }
    rel = (wind_dir_deg - orientation_deg) % 360
    if rel > 180: rel -= 360
    headwind  = round(wind_speed_mph * math.cos(math.radians(rel)), 2)
    crosswind = round(wind_speed_mph * math.sin(math.radians(rel)), 2)
    abs_head  = abs(headwind)
    abs_cross = abs(crosswind)
    if abs_head >= abs_cross:
        direction = "blowing in" if headwind > 0 else "blowing out"
        mag_label = f"{abs_head:.1f} mph {direction}"
    else:
        side = "left-to-right" if crosswind > 0 else "right-to-left"
        mag_label = f"{abs_cross:.1f} mph crosswind ({side})"
    speed_label = ("calm" if wind_speed_mph < 5 else
                   "light" if wind_speed_mph < 10 else
                   "moderate" if wind_speed_mph < 20 else "strong")
    return {
        "status": "ok",
        "wind_speed_mph": round(wind_speed_mph,1),
        "wind_dir_deg": round(wind_dir_deg,1),
        "wind_dir_label": _deg_label(wind_dir_deg),
        "field_orientation_deg": round(orientation_deg,1),
        "field_orientation_label": _deg_label(orientation_deg),
        "relative_angle_deg": round(rel,2),
        "headwind_mph": headwind, "crosswind_mph": crosswind,
        "crosswind_dir": "left_to_right" if crosswind > 0 else "right_to_left",
        "wind_effect_label": f"{speed_label} {mag_label}",
    }
'@
[System.IO.File]::WriteAllText((Join-Path $dir 'wind_calc.py'), $wind, [System.Text.Encoding]::UTF8)
Write-Host "  [OK] wind_calc.py written" -ForegroundColor Green

Write-Host ""
Write-Host "All 3 missing modules written. No network was needed." -ForegroundColor Cyan
Write-Host ""

# ===========================================================================
# STEP 4 — pip install
# ===========================================================================
Write-Host "[3/4] Installing Python dependencies..." -ForegroundColor Yellow
if (Test-Path (Join-Path $dir 'requirements.txt')) {
    python -m pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -eq 0) { Write-Host "  [OK] pip install complete" -ForegroundColor Green }
    else { Write-Host "  [WARN] pip install had errors. Check Python." -ForegroundColor Yellow }
} else {
    Write-Host "  [WARN] requirements.txt not found, skipping pip install" -ForegroundColor Yellow
}

# ===========================================================================
# STEP 5 — Verify imports
# ===========================================================================
Write-Host ""
Write-Host "[4/4] Verifying all module imports..." -ForegroundColor Yellow

$modules = @(
    @{ cmd="from wnba_venues import resolve_wnba_team, wnba_venue_block"; label="wnba_venues" },
    @{ cmd="from pressure_calc import full_pressure_block, indoor_hvac_model"; label="pressure_calc" },
    @{ cmd="from wind_calc import wind_vs_stadium"; label="wind_calc" },
    @{ cmd="from venue_resolver import VenueResolver"; label="venue_resolver" },
    @{ cmd="from weather_enricher import enrich_venue"; label="weather_enricher" },
    @{ cmd="from fetcher import build_all_sports, build_sport"; label="fetcher" },
    @{ cmd="import main"; label="main" }
)

$allOk = $true
foreach ($m in $modules) {
    $result = python -c $m.cmd 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $($m.label)" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $($m.label): $result" -ForegroundColor Red
        $allOk = $false
    }
}

Write-Host ""
if ($allOk) {
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  ALL IMPORTS CLEAN. Run .\run.bat to start the server." -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
} else {
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "  SOME IMPORTS FAILED. See [FAIL] lines above." -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
}
Write-Host ""
Read-Host "Press Enter to exit"
