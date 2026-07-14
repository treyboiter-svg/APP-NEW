# OverlineEdge v8 — Repository Manifest

All files that must be present in your local working directory (`C:\OverlineEdge\APP-NEW-OVERLINE-EDGE\` or wherever you run `run.bat` from).

## Core Application Files

| File | Version | Description |
|------|---------|-------------|
| `main.py` | v8 | FastAPI app entry point |
| `routes.py` | v8 | API route handlers (`/api/dashboard`) |
| `fetcher.py` | **v8.4.2** | Main data pipeline — WNBA uses standalone DB |
| `config.py` | v8 | API keys, sport slugs, Kalshi/Poly series config |
| `run.bat` | v8.4 | Windows startup script |
| `run.ps1` | v8 | PowerShell startup script |
| `requirements.txt` | v8 | Python dependency list |

## Venue & Physics Modules ← **NEW in v8.4**

| File | Version | Description |
|------|---------|-------------|
| `wnba_venues.py` | **v8.4.0** | ⭐ NEW — WNBA standalone venue DB (15 teams, 2026) |
| `pressure_calc.py` | **v8.4.0** | ⭐ NEW — True absolute pressure physics, ISA model, density altitude, HVAC indoor model |
| `wind_calc.py` | **v8.4.0** | ⭐ NEW — Wind vs stadium orientation: headwind/crosswind decomposition |
| `venue_resolver.py` | v8 | Main US Sports venue authority (all sports except WNBA) |
| `weather_enricher.py` | v8.4 | OpenWeather enrichment, calls pressure_calc + wind_calc |

## Calculation Modules

| File | Version | Description |
|------|---------|-------------|
| `odds_calc.py` | v8 | American odds ↔ implied probability, vig removal, power method |
| `normalizer.py` | v8 | Team name normalization |
| `odds_scraper.py` | v8 | Sportsbook DOM scraper wrapper |
| `_scrape_worker.py` | v8 | Worker process for scraping |

## Dashboard & Diagnostics

| File | Version | Description |
|------|---------|-------------|
| `odds_dashboard_v8.html` | **v8.4.2** | ⭐ UPDATED — Full Weather tab: pressure block, wind vs stadium, ISA ref, HVAC indoor |
| `diagnostics.py` | v8 | Diagnostics endpoint |
| `US_SPORTS_VENUES_MASTER_CORRECTED_V2.xlsx` | v2 | Venue master workbook (all sports except WNBA) |

## How to Sync

### If your folder IS a git repo:
```
git pull origin main
```

### If your folder is NOT a git repo (most likely your case):
Double-click **`INSTALL.bat`** — it downloads every file above from GitHub automatically, then installs all dependencies and verifies imports.

### Manual download of new v8.4 files only:
```powershell
$base = "https://raw.githubusercontent.com/treyboiter-svg/APP-NEW/main"
curl -o wnba_venues.py    "$base/wnba_venues.py"
curl -o pressure_calc.py  "$base/pressure_calc.py"
curl -o wind_calc.py      "$base/wind_calc.py"
curl -o fetcher.py        "$base/fetcher.py"
curl -o odds_dashboard_v8.html "$base/odds_dashboard_v8.html"
```

## Import Dependency Graph

```
main.py
  └── routes.py
        └── fetcher.py
              ├── wnba_venues.py          ← NEW v8.4
              ├── venue_resolver.py
              ├── weather_enricher.py
              │     ├── pressure_calc.py  ← NEW v8.4
              │     └── wind_calc.py     ← NEW v8.4
              ├── odds_calc.py
              ├── odds_scraper.py
              ├── normalizer.py
              └── config.py
```
