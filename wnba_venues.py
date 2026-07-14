"""wnba_venues.py — OverlineEdge v8.4.0
Standalone WNBA venue authority. Completely separate from the main US_SPORTS_VENUES workbook.
Contains: all 14 current WNBA franchises (2026 season including expansion teams),
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
    elevation_ft:         float    # feet above sea level
    elevation_m:          float    # metres above sea level
    orientation_deg:      float | None   # compass bearing of playing field long axis
    orientation_label:    str   | None   # N, NE, E, SE, S, SW, W, NW
    roof_type:            str           # OPEN | RETRACTABLE | DOME | INDOOR
    capacity:             int
    surface:              str           # HARDWOOD (all WNBA)

# ---------------------------------------------------------------------------
# 2026 WNBA venue master  (12 legacy + 2 expansion)
# Orientation_deg = compass bearing the court long axis points (home basket end)
# ---------------------------------------------------------------------------
_WNBA_VENUES: list[WNBAVenue] = [
    WNBAVenue(
        team="Phoenix Mercury", city="Phoenix", state="AZ",
        venue="Footprint Center",
        lat=33.4457, lon=-112.0712,
        elevation_ft=1086.0, elevation_m=331.0,
        orientation_deg=90.0, orientation_label="E",
        roof_type="INDOOR", capacity=18422, surface="HARDWOOD",
    ),
    WNBAVenue(
        team="Minnesota Lynx", city="Minneapolis", state="MN",
        venue="Target Center",
        lat=44.9795, lon=-93.2761,
        elevation_ft=830.0, elevation_m=253.0,
        orientation_deg=0.0, orientation_label="N",
        roof_type="INDOOR", capacity=19356, surface="HARDWOOD",
    ),
    WNBAVenue(
        team="Los Angeles Sparks", city="Los Angeles", state="CA",
        venue="Crypto.com Arena",
        lat=34.0430, lon=-118.2673,
        elevation_ft=161.0, elevation_m=49.0,
        orientation_deg=45.0, orientation_label="NE",
        roof_type="INDOOR", capacity=19795, surface="HARDWOOD",
    ),
    WNBAVenue(
        team="Atlanta Dream", city="Atlanta", state="GA",
        venue="Gateway Center Arena",
        lat=33.5735, lon=-84.3524,
        elevation_ft=1050.0, elevation_m=320.0,
        orientation_deg=0.0, orientation_label="N",
        roof_type="INDOOR", capacity=13707, surface="HARDWOOD",
    ),
    WNBAVenue(
        team="Chicago Sky", city="Chicago", state="IL",
        venue="Wintrust Arena",
        lat=41.8673, lon=-87.6253,
        elevation_ft=594.0, elevation_m=181.0,
        orientation_deg=0.0, orientation_label="N",
        roof_type="INDOOR", capacity=10387, surface="HARDWOOD",
    ),
    WNBAVenue(
        team="Dallas Wings", city="Arlington", state="TX",
        venue="College Park Center",
        lat=32.7326, lon=-97.1115,
        elevation_ft=616.0, elevation_m=188.0,
        orientation_deg=0.0, orientation_label="N",
        roof_type="INDOOR", capacity=7000, surface="HARDWOOD",
    ),
    WNBAVenue(
        team="Connecticut Sun", city="Uncasville", state="CT",
        venue="Mohegan Sun Arena",
        lat=41.4752, lon=-72.0912,
        elevation_ft=120.0, elevation_m=37.0,
        orientation_deg=0.0, orientation_label="N",
        roof_type="INDOOR", capacity=10000, surface="HARDWOOD",
    ),
    WNBAVenue(
        team="Seattle Storm", city="Seattle", state="WA",
        venue="Climate Pledge Arena",
        lat=47.6218, lon=-122.3542,
        elevation_ft=174.0, elevation_m=53.0,
        orientation_deg=45.0, orientation_label="NE",
        roof_type="INDOOR", capacity=17459, surface="HARDWOOD",
    ),
    WNBAVenue(
        team="Indiana Fever", city="Indianapolis", state="IN",
        venue="Gainbridge Fieldhouse",
        lat=39.7639, lon=-86.1555,
        elevation_ft=715.0, elevation_m=218.0,
        orientation_deg=0.0, orientation_label="N",
        roof_type="INDOOR", capacity=17923, surface="HARDWOOD",
    ),
    WNBAVenue(
        team="Las Vegas Aces", city="Las Vegas", state="NV",
        venue="Michelob ULTRA Arena",
        lat=36.1026, lon=-115.1783,
        elevation_ft=2001.0, elevation_m=610.0,
        orientation_deg=90.0, orientation_label="E",
        roof_type="INDOOR", capacity=12000, surface="HARDWOOD",
    ),
    WNBAVenue(
        team="Washington Mystics", city="Washington", state="DC",
        venue="Capital One Arena",
        lat=38.8981, lon=-77.0209,
        elevation_ft=30.0, elevation_m=9.0,
        orientation_deg=0.0, orientation_label="N",
        roof_type="INDOOR", capacity=20356, surface="HARDWOOD",
    ),
    WNBAVenue(
        team="New York Liberty", city="Brooklyn", state="NY",
        venue="Barclays Center",
        lat=40.6826, lon=-73.9754,
        elevation_ft=10.0, elevation_m=3.0,
        orientation_deg=0.0, orientation_label="N",
        roof_type="INDOOR", capacity=17732, surface="HARDWOOD",
    ),
    # 2025 Expansion
    WNBAVenue(
        team="Golden State Valkyries", city="San Francisco", state="CA",
        venue="Chase Center",
        lat=37.7680, lon=-122.3877,
        elevation_ft=20.0, elevation_m=6.0,
        orientation_deg=45.0, orientation_label="NE",
        roof_type="INDOOR", capacity=18064, surface="HARDWOOD",
    ),
    WNBAVenue(
        team="Portland Blue Crew", city="Portland", state="OR",
        venue="Moda Center",
        lat=45.5316, lon=-122.6668,
        elevation_ft=108.0, elevation_m=33.0,
        orientation_deg=176.0, orientation_label="S",
        roof_type="INDOOR", capacity=19980, surface="HARDWOOD",
    ),
    WNBAVenue(
        team="Cleveland Charge", city="Cleveland", state="OH",
        venue="Rocket Mortgage FieldHouse",
        lat=41.4966, lon=-81.6886,
        elevation_ft=653.0, elevation_m=199.0,
        orientation_deg=0.0, orientation_label="N",
        roof_type="INDOOR", capacity=19432, surface="HARDWOOD",
    ),
]

# ---------------------------------------------------------------------------
# Index for fast O(1) lookup
# ---------------------------------------------------------------------------
_BY_TEAM: dict[str, WNBAVenue] = {v.team: v for v in _WNBA_VENUES}

# Nickname aliases  (folded lowercase key → canonical team name)
_NICKNAMES: dict[str, str] = {
    "mercury":                    "Phoenix Mercury",
    "phoenix mercury":            "Phoenix Mercury",
    "lynx":                       "Minnesota Lynx",
    "minnesota lynx":             "Minnesota Lynx",
    "sparks":                     "Los Angeles Sparks",
    "los angeles sparks":         "Los Angeles Sparks",
    "la sparks":                  "Los Angeles Sparks",
    "dream":                      "Atlanta Dream",
    "atlanta dream":              "Atlanta Dream",
    "sky":                        "Chicago Sky",
    "chicago sky":                "Chicago Sky",
    "wings":                      "Dallas Wings",
    "dallas wings":               "Dallas Wings",
    "sun":                        "Connecticut Sun",
    "connecticut sun":            "Connecticut Sun",
    "storm":                      "Seattle Storm",
    "seattle storm":              "Seattle Storm",
    "fever":                      "Indiana Fever",
    "indiana fever":              "Indiana Fever",
    "aces":                       "Las Vegas Aces",
    "las vegas aces":             "Las Vegas Aces",
    "lv aces":                    "Las Vegas Aces",
    "mystics":                    "Washington Mystics",
    "washington mystics":         "Washington Mystics",
    "liberty":                    "New York Liberty",
    "new york liberty":           "New York Liberty",
    "ny liberty":                 "New York Liberty",
    "valkyries":                  "Golden State Valkyries",
    "golden state valkyries":     "Golden State Valkyries",
    "blue crew":                  "Portland Blue Crew",
    "portland blue crew":         "Portland Blue Crew",
    "charge":                     "Cleveland Charge",
    "cleveland charge":           "Cleveland Charge",
}


def resolve_wnba_team(raw: str) -> WNBAVenue | None:
    """Resolve a raw sportsbook team string to a WNBAVenue. Returns None if unresolved."""
    key = " ".join(raw.lower().strip().split())
    canonical = _NICKNAMES.get(key)
    if canonical:
        return _BY_TEAM.get(canonical)
    # Partial token match fallback
    for nick, team_name in _NICKNAMES.items():
        if nick in key or key in nick:
            return _BY_TEAM.get(team_name)
    return None


def wnba_venue_block(venue: WNBAVenue) -> dict:
    """Convert a WNBAVenue into the standard venue_block dict used by enrich_venue."""
    return {
        "name":                   venue.venue,
        "city":                   venue.city,
        "state":                  venue.state,
        "lat":                    venue.lat,
        "lon":                    venue.lon,
        "elevation":              venue.elevation_ft,
        "orientation_deg":        venue.orientation_deg,
        "orientation_label":      venue.orientation_label,
        "orientation_confidence": 1.0,
        "roof_type":              venue.roof_type,
        "is_indoor":              venue.roof_type in ("INDOOR", "DOME"),
        "is_retractable":         venue.roof_type == "RETRACTABLE",
        "capacity":               venue.capacity,
        "surface":                venue.surface,
    }
