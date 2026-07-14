"""wind_calc.py — OverlineEdge v8.4.0
Wind direction analysis relative to stadium orientation.

All WNBA venues are indoor — wind direction is N/A for them.
This module is primarily used for outdoor/retractable MLB, NFL, CFB venues.

Physics model:
  headwind_component  = wind_speed * cos(relative_angle)
  crosswind_component = wind_speed * sin(relative_angle)
  relative_angle      = abs(wind_dir_from - field_orientation) mod 360, then mapped to [-180,180]

Wind meteorological convention: direction FROM which wind blows (270 = wind FROM west, blowing east).
Field orientation_deg: compass bearing the field long axis points (baseline end to CF in baseball;
  attacking direction in football; home plate end).
"""
from __future__ import annotations
import math


_COMPASS_LABELS = [
    ("N",   0.0),  ("NNE",  22.5), ("NE",  45.0), ("ENE",  67.5),
    ("E",  90.0),  ("ESE", 112.5), ("SE", 135.0), ("SSE", 157.5),
    ("S", 180.0),  ("SSW", 202.5), ("SW", 225.0), ("WSW", 247.5),
    ("W", 270.0),  ("WNW", 292.5), ("NW", 315.0), ("NNW", 337.5),
]


def _deg_label(deg: float) -> str:
    deg = deg % 360
    best = min(_COMPASS_LABELS, key=lambda x: abs((x[1] - deg + 180) % 360 - 180))
    return best[0]


def wind_vs_stadium(
    wind_speed_mph: float | None,
    wind_dir_deg:   float | None,   # meteorological: direction FROM which wind blows
    orientation_deg: float | None,  # field long-axis compass bearing
) -> dict:
    """
    Returns a dict with headwind/crosswind components and human-readable labels.
    All values are None for indoor venues (call this only for outdoor/retractable).
    """
    if wind_speed_mph is None or wind_dir_deg is None or orientation_deg is None:
        return {
            "status":             "insufficient_data",
            "wind_dir_deg":       wind_dir_deg,
            "wind_dir_label":     _deg_label(wind_dir_deg) if wind_dir_deg is not None else None,
            "field_orientation":  orientation_deg,
            "relative_angle_deg": None,
            "headwind_mph":       None,
            "crosswind_mph":      None,
            "crosswind_dir":      None,
            "wind_effect_label":  None,
        }

    # Relative angle: how much wind deviates from field long axis
    rel = (wind_dir_deg - orientation_deg) % 360
    if rel > 180:
        rel -= 360
    # headwind: positive = blowing IN to play (toward home plate / goal line)
    # crosswind: positive = blowing left-to-right from home perspective
    headwind  = round(wind_speed_mph * math.cos(math.radians(rel)),  2)
    crosswind = round(wind_speed_mph * math.sin(math.radians(rel)), 2)

    # Human label
    abs_head = abs(headwind)
    abs_cross = abs(crosswind)
    if abs_head >= abs_cross:
        direction = "blowing in" if headwind > 0 else "blowing out"
        mag_label = f"{abs_head:.1f} mph {direction}"
    else:
        side = "left-to-right" if crosswind > 0 else "right-to-left"
        mag_label = f"{abs_cross:.1f} mph crosswind ({side})"

    speed_label = "calm" if wind_speed_mph < 5 else (
                  "light" if wind_speed_mph < 10 else (
                  "moderate" if wind_speed_mph < 20 else "strong"))

    return {
        "status":             "ok",
        "wind_speed_mph":     round(wind_speed_mph, 1),
        "wind_dir_deg":       round(wind_dir_deg, 1),
        "wind_dir_label":     _deg_label(wind_dir_deg),
        "field_orientation_deg": round(orientation_deg, 1),
        "field_orientation_label": _deg_label(orientation_deg),
        "relative_angle_deg": round(rel, 2),
        "headwind_mph":       headwind,
        "crosswind_mph":      crosswind,
        "crosswind_dir":      "left_to_right" if crosswind > 0 else "right_to_left",
        "wind_effect_label":  f"{speed_label} {mag_label}",
    }
