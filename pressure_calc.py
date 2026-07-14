"""pressure_calc.py — OverlineEdge v8.4.0
True barometric / absolute pressure and air density physics.

Definitions used throughout OverlineEdge:
  station_pressure    = MEASURED absolute surface pressure at the venue (hPa / inHg)
                        This is what weather APIs return as 'surface_pressure' or 'pressure'.
                        It already accounts for elevation — no altitude correction needed.

  sea_level_pressure  = station_pressure corrected UP to sea level using the hypsometric formula.
                        This is what weather services publish as 'barometric pressure' (MSLP).
                        NEVER use this for density calculations — it's a normalised reference only.

  ISA_at_elevation    = International Standard Atmosphere pressure at the venue's elevation.
                        Used as a reference baseline for that elevation.

  air_density         = ρ = (p_d / R_d·T) + (p_v / R_v·T)   [moist air, kg/m³]
                        where p_d = dry air partial pressure, p_v = water vapour pressure

  density_altitude    = pressure altitude corrected for non-standard temperature.
                        Pilots use this — relevant for ball flight physics.

All WNBA venues are indoor; use indoor_hvac_model() instead of this for those.
"""
from __future__ import annotations
import math

# Gas constants
_Rd    = 287.05    # dry air, J/(kg·K)
_Rv    = 461.495   # water vapour, J/(kg·K)

# ISA sea-level constants
_ISA_P0  = 101325.0  # Pa  (1013.25 hPa)
_ISA_T0  = 288.15    # K   (15 °C)
_ISA_RHO = 1.225     # kg/m³
_LAPSE   = 0.0065    # K/m (troposphere)

# Conversion
_HPA_TO_INHG = 1.0 / 33.8639
_HPA_TO_PA   = 100.0


def saturation_pressure_hpa(t_c: float) -> float:
    """Magnus formula — saturation vapour pressure in hPa."""
    return 6.112 * math.exp(17.67 * t_c / (t_c + 243.5))


def moist_air_density(
    station_pressure_hpa: float,
    temp_c:               float,
    rh_pct:               float,
) -> float:
    """True moist-air density ρ in kg/m³ from station (absolute) pressure."""
    T   = temp_c + 273.15
    es  = saturation_pressure_hpa(temp_c)
    e   = min(station_pressure_hpa, rh_pct / 100.0 * es)   # actual vapour pressure [hPa]
    pd  = (station_pressure_hpa - e) * _HPA_TO_PA           # dry air partial pressure [Pa]
    pv  = e * _HPA_TO_PA                                    # vapour partial pressure [Pa]
    return pd / (_Rd * T) + pv / (_Rv * T)


def isa_at_elevation(elev_m: float) -> dict:
    """ISA standard atmosphere values at a given elevation."""
    h   = max(-500.0, min(11_000.0, float(elev_m)))
    q   = 1.0 - _LAPSE * h / _ISA_T0
    p   = (_ISA_P0 / _HPA_TO_PA) * q ** 5.25588   # hPa
    rho = _ISA_RHO * q ** 4.25588
    t_c = _ISA_T0 * q - 273.15
    return {
        "elevation_m":   round(h, 1),
        "pressure_hpa":  round(p, 4),
        "pressure_inhg": round(p * _HPA_TO_INHG, 4),
        "density_kgm3":  round(rho, 6),
        "temp_c":        round(t_c, 2),
    }


def station_to_sea_level(station_hpa: float, elev_m: float, temp_c: float) -> float:
    """Hypsometric formula: convert station pressure → MSLP (hPa).
    This is for display / reference only — do NOT use for density calcs."""
    T = temp_c + 273.15
    return round(station_hpa * math.exp(_LAPSE * elev_m / T), 4)


def density_altitude_ft(station_hpa: float, temp_c: float, rh_pct: float = 0.0) -> float:
    """Density altitude in feet (pilot standard). Accounts for temperature and humidity."""
    # Virtual temperature corrects for humidity
    es  = saturation_pressure_hpa(temp_c)
    e   = rh_pct / 100.0 * es
    mixing_ratio = 0.622 * e / (station_hpa - e)
    T_virtual = (temp_c + 273.15) * (1 + 1.608 * mixing_ratio) / (1 + mixing_ratio)
    # Pressure altitude from ISA
    ratio = station_hpa / 1013.25
    pa_ft = (1 - ratio ** 0.190284) * 145366.45
    # Density altitude
    da_ft = pa_ft + 120 * (T_virtual - _ISA_T0)
    return round(da_ft, 0)


def full_pressure_block(
    station_hpa:  float,
    temp_c:       float,
    rh_pct:       float,
    elev_m:       float,
) -> dict:
    """
    Complete pressure and density analysis block.
    Returns all values needed for dashboard display and bet-type physics calcs.
    """
    rho   = moist_air_density(station_hpa, temp_c, rh_pct)
    isa   = isa_at_elevation(elev_m)
    mslp  = station_to_sea_level(station_hpa, elev_m, temp_c)
    da_ft = density_altitude_ft(station_hpa, temp_c, rh_pct)

    return {
        # ── True Absolute Pressure ────────────────────────────────────────
        "station_pressure_hpa":   round(station_hpa, 2),
        "station_pressure_inhg":  round(station_hpa * _HPA_TO_INHG, 4),
        "station_pressure_pa":    round(station_hpa * _HPA_TO_PA, 1),

        # ── Sea-Level Reference (display only) ───────────────────────────
        "sea_level_pressure_hpa":  mslp,
        "sea_level_pressure_inhg": round(mslp * _HPA_TO_INHG, 4),

        # ── Air Density ───────────────────────────────────────────────────
        "air_density_kgm3":         round(rho, 6),
        "air_density_lbft3":        round(rho * 0.0624279606, 6),
        "density_pct_of_isa_sealevel": round(rho / _ISA_RHO * 100.0, 4),
        "density_pct_of_isa_elevation": round(rho / isa["density_kgm3"] * 100.0, 4),

        # ── ISA Reference at Venue Elevation ─────────────────────────────
        "isa_at_elevation": isa,

        # ── Density Altitude ─────────────────────────────────────────────
        "density_altitude_ft": da_ft,
        "density_altitude_m":  round(da_ft * 0.3048, 0),

        # ── Inputs (echoed for transparency) ─────────────────────────────
        "inputs": {
            "temp_c":       round(temp_c, 2),
            "temp_f":       round(temp_c * 9/5 + 32, 1),
            "rh_pct":       round(rh_pct, 1),
            "elev_m":       round(elev_m, 1),
            "elev_ft":      round(elev_m * 3.28084, 1),
        },
    }


# ---------------------------------------------------------------------------
# INDOOR / DOME physics model
# ---------------------------------------------------------------------------
_HVAC_TEMP_C  = 21.0   # 70 °F baseline
_HVAC_RH_PCT  = 45.0   # 45% RH baseline
_HVAC_TEMP_F  = 70.0

def indoor_hvac_model(
    station_hpa_outdoor: float,
    temp_c_outdoor:      float,
    rh_pct_outdoor:      float,
    elev_m:              float,
    roof_type:           str = "INDOOR",
) -> dict:
    """
    For INDOOR / DOME venues: compute density using HVAC baseline conditions
    at the venue's elevation and outdoor station pressure.

    The outdoor pressure drives the absolute pressure inside the building
    (buildings are not hermetically sealed — indoor = outdoor pressure).
    Only temperature and humidity differ.

    For RETRACTABLE: call this only when roof is confirmed CLOSED;
    otherwise call full_pressure_block().
    """
    rho_indoor  = moist_air_density(station_hpa_outdoor, _HVAC_TEMP_C, _HVAC_RH_PCT)
    rho_outdoor = moist_air_density(station_hpa_outdoor, temp_c_outdoor, rh_pct_outdoor)
    isa         = isa_at_elevation(elev_m)
    da_ft       = density_altitude_ft(station_hpa_outdoor, _HVAC_TEMP_C, _HVAC_RH_PCT)

    return {
        "roof_type":          roof_type,
        "status":             "indoor_hvac_model",
        "note":               f"HVAC baseline {_HVAC_TEMP_F} °F / {_HVAC_RH_PCT}% RH. "
                              "Outdoor pressure drives absolute pressure inside.",

        # ── Indoor conditions ─────────────────────────────────────────────
        "indoor_temp_f":      _HVAC_TEMP_F,
        "indoor_temp_c":      _HVAC_TEMP_C,
        "indoor_rh_pct":      _HVAC_RH_PCT,

        # ── True Absolute Pressure (same as outdoors) ─────────────────────
        "station_pressure_hpa":  round(station_hpa_outdoor, 2),
        "station_pressure_inhg": round(station_hpa_outdoor / 33.8639, 4),

        # ── Air Density ───────────────────────────────────────────────────
        "air_density_kgm3":          round(rho_indoor, 6),
        "air_density_lbft3":         round(rho_indoor * 0.0624279606, 6),
        "density_pct_of_isa_sealevel": round(rho_indoor / _ISA_RHO * 100.0, 4),
        "density_pct_of_isa_elevation": round(rho_indoor / isa["density_kgm3"] * 100.0, 4),
        "density_pct_vs_outdoor":    round((rho_indoor / rho_outdoor - 1.0) * 100.0, 4),

        # ── Density Altitude ─────────────────────────────────────────────
        "density_altitude_ft": da_ft,

        # ── ISA Reference ─────────────────────────────────────────────────
        "isa_at_elevation": isa,

        # ── Outdoor conditions (for reference) ───────────────────────────
        "outdoor_temp_c":        round(temp_c_outdoor, 2),
        "outdoor_temp_f":        round(temp_c_outdoor * 9/5 + 32, 1),
        "outdoor_rh_pct":        round(rh_pct_outdoor, 1),
        "outdoor_density_kgm3":  round(rho_outdoor, 6),
    }
