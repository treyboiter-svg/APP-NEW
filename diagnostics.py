"""
diagnostics.py — OverlineEdge v8 FULL SYSTEM DIAGNOSTIC ENGINE

Every build_all_sports() pass produces:
  1. STARTUP REPORT      — Python version, OS, cwd, installed packages, env vars (redacted)
  2. SOURCE TRACE        — Every API call: URL, status, latency_ms, bytes_received, error (if any)
  3. WEATHER TRACE       — Per-venue: lat/lon/elevation, open-meteo fetch status, latency_ms, density result
  4. MATCH AUDIT         — Per-game: how each Kalshi/Poly market was matched or rejected, confidence score
  5. DATA QUALITY MATRIX — Per-sport/game: which books returned prices, which were missing, vig per book
  6. PIPELINE TIMING     — Total wall-clock ms for each phase: fetch, normalize, match, weather, render
  7. FULL SNAPSHOT       — Complete dashboard JSON at time of run
  8. SERVER LOG          — Full server.log tail (last 2000 lines)

All artifacts zipped to: data/diagnostics/OverlineEdge_RunDiagnostic_YYYYMMDD_HHMMSS.zip

Download via: http://127.0.0.1:8000/api/diagnostics/download
View summary: http://127.0.0.1:8000/api/diagnostics/run
"""
from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from app.core.config import LOG_DIR
except ImportError:
    LOG_DIR = "data/logs"

logger = logging.getLogger(__name__)

# ============================================================
# GLOBAL TRACE ACCUMULATOR — populated by fetcher + weather_enricher
# Reset at the start of every build_all_sports() call
# ============================================================

class RunTrace:
    """Singleton accumulator: all instrumentation writes here during a build pass."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.run_start_utc: str  = datetime.now(timezone.utc).isoformat()
        self.run_start_ts:  float = time.monotonic()
        self.source_calls:  list  = []   # {source, url, status, latency_ms, bytes, error}
        self.weather_calls: list  = []   # {venue, lat, lon, elev, status, latency_ms, density, pct_isa, error}
        self.phase_times:   dict  = {}   # {phase_name: elapsed_ms}
        self.norm_events:   list  = []   # {sport, raw_name, canonical, method, confidence}
        self.match_events:  list  = []   # {sport, game, source, method, confidence, accepted}
        self.sport_summaries: dict = {}
        self._phase_starts: dict  = {}

    # ---- phase timing helpers ----
    def phase_start(self, name: str):
        self._phase_starts[name] = time.monotonic()
        logger.info("[DIAG] ► Phase START: %s", name)

    def phase_end(self, name: str):
        start = self._phase_starts.pop(name, None)
        elapsed = round((time.monotonic() - start) * 1000, 2) if start else None
        self.phase_times[name] = elapsed
        logger.info("[DIAG] ◄ Phase END:   %s  →  %s ms", name, elapsed)

    # ---- source call trace ----
    def log_source_call(
        self,
        source:     str,
        url:        str,
        status:     int | str,
        latency_ms: float,
        bytes_recv: int  = 0,
        error:      str  = "",
    ):
        entry = {
            "ts":         datetime.now(timezone.utc).isoformat(),
            "source":     source,
            "url":        url,
            "status":     status,
            "latency_ms": round(latency_ms, 2),
            "bytes_recv": bytes_recv,
            "error":      error,
        }
        self.source_calls.append(entry)
        level = logging.WARNING if error else logging.INFO
        logger.log(level, "[DIAG][SOURCE] %s  %s  %s  %.1f ms  %s bytes  %s",
                   source, status, url[:90], latency_ms, bytes_recv, error or "OK")

    # ---- weather trace ----
    def log_weather_call(
        self,
        venue:      str,
        lat:        float | None,
        lon:        float | None,
        elev_m:     float | None,
        status:     str,
        latency_ms: float,
        density_kgm3: float | None = None,
        pct_isa:    float | None   = None,
        error:      str            = "",
        cached:     bool           = False,
    ):
        entry = {
            "ts":           datetime.now(timezone.utc).isoformat(),
            "venue":        venue,
            "lat":          lat,
            "lon":          lon,
            "elevation_m":  elev_m,
            "status":       status,
            "latency_ms":   round(latency_ms, 2),
            "density_kgm3": density_kgm3,
            "pct_isa":      pct_isa,
            "cached":       cached,
            "error":        error,
        }
        self.weather_calls.append(entry)
        logger.info(
            "[DIAG][WEATHER] %s  status=%s  %.1f ms  ρ=%s kg/m³  (%s%%ISA)  cached=%s  %s",
            venue[:40], status, latency_ms,
            density_kgm3 or "N/A", pct_isa or "N/A", cached, error or "OK",
        )

    # ---- normalization trace ----
    def log_norm(self, sport: str, raw: str, canonical: str, method: str, confidence: float):
        self.norm_events.append({
            "sport": sport, "raw": raw, "canonical": canonical,
            "method": method, "confidence": round(confidence, 4),
        })

    # ---- market match trace ----
    def log_match(
        self,
        sport:      str,
        game:       str,
        source:     str,
        method:     str,
        confidence: float,
        accepted:   bool,
        detail:     str = "",
    ):
        self.match_events.append({
            "sport":      sport,
            "game":       game,
            "source":     source,
            "method":     method,
            "confidence": round(confidence, 4),
            "accepted":   accepted,
            "detail":     detail,
        })
        tag = "✅ MATCH" if accepted else "❌ REJECT"
        logger.info("[DIAG][MATCH] %s  %s | %s | %s | conf=%.2f  %s",
                    tag, sport, game[:40], source, confidence, detail)

    def total_elapsed_ms(self) -> float:
        return round((time.monotonic() - self.run_start_ts) * 1000, 2)


# Module-level singleton
RUN_TRACE = RunTrace()


# ============================================================
# STARTUP ENVIRONMENT REPORT
# ============================================================

def _build_startup_report() -> dict:
    """Capture full environment info: Python, OS, packages, path, relevant env vars."""
    # installed packages via pip list
    pip_out = ""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=columns"],
            capture_output=True, text=True, timeout=30
        )
        pip_out = result.stdout.strip()
    except Exception as e:
        pip_out = f"pip list failed: {e}"

    # safe env vars (no secrets)
    safe_env_keys = [
        "PATH", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV",
        "COMPUTERNAME", "USERNAME", "OS", "PROCESSOR_ARCHITECTURE",
        "USERPROFILE", "TEMP", "NUMBER_OF_PROCESSORS",
    ]
    env_snapshot = {k: os.environ.get(k, "(not set)") for k in safe_env_keys}
    # Redact anything that looks like a key/secret if it slipped in
    for k in list(env_snapshot):
        v = env_snapshot[k]
        if any(word in k.upper() for word in ["KEY", "SECRET", "TOKEN", "PASS", "PWD"]):
            env_snapshot[k] = "[REDACTED]"

    return {
        "timestamp_utc":    datetime.now(timezone.utc).isoformat(),
        "python_version":   sys.version,
        "python_executable": sys.executable,
        "platform":         platform.platform(),
        "architecture":     platform.architecture()[0],
        "processor":        platform.processor() or platform.machine(),
        "cpu_count":        os.cpu_count(),
        "cwd":              str(Path.cwd()),
        "script_dir":       str(Path(__file__).parent.resolve()),
        "sys_path":         sys.path,
        "installed_packages": pip_out,
        "env_vars":         env_snapshot,
    }


# ============================================================
# DATA QUALITY MATRIX
# ============================================================

def _build_quality_matrix(dashboard: dict) -> dict:
    matrix = {}
    for sport, payload in dashboard.items():
        games = payload.get("games", [])
        sport_row = {
            "game_count": len(games),
            "games": [],
        }
        for g in games:
            dq = g.get("data_quality", {})
            missing = dq.get("missing_prices", {})
            per_book = g.get("per_book", {})
            vigs = {bk: round(bd.get("vig_pct", 0), 4)
                    for bk, bd in per_book.items()
                    if bd.get("vig_pct") is not None}
            books_with_ml     = [bk for bk, bd in per_book.items() if bd.get("home_ml") or bd.get("away_ml")]
            books_with_spread  = [bk for bk, bd in per_book.items() if bd.get("home_spread") or bd.get("away_spread")]
            books_with_total   = [bk for bk, bd in per_book.items() if bd.get("over") or bd.get("under")]

            wx = g.get("venue", {}).get("weather_context", {})

            game_row = {
                "title":             g.get("title", ""),
                "commence":          g.get("commence", ""),
                "books_total":       len(per_book),
                "books_with_ml":     books_with_ml,
                "books_with_spread": books_with_spread,
                "books_with_total":  books_with_total,
                "missing_ml":        missing.get("moneyline", []),
                "missing_spread":    missing.get("spread", []),
                "missing_total":     missing.get("total", []),
                "vig_per_book":      vigs,
                "avg_vig":           round(sum(vigs.values()) / len(vigs), 4) if vigs else None,
                "kalshi_matched":    g.get("match_audit", {}).get("kalshi_method", "none"),
                "poly_matched":      g.get("match_audit", {}).get("polymarket_method", "none"),
                "venue_name":        g.get("venue", {}).get("name", ""),
                "venue_lat":         g.get("venue", {}).get("lat"),
                "venue_lon":         g.get("venue", {}).get("lon"),
                "weather_status":    wx.get("status", "not_run"),
                "air_density_kgm3": wx.get("air_density_kgm3"),
                "density_pct_isa":   wx.get("density_pct_of_isa_sealevel"),
                "temp_f":            wx.get("temperature_f"),
                "rh_pct":            wx.get("relative_humidity_pct"),
                "wind_mph":          wx.get("wind_speed_mph"),
            }
            sport_row["games"].append(game_row)
        matrix[sport] = sport_row
    return matrix


# ============================================================
# PIPELINE SUMMARY
# ============================================================

def _build_pipeline_summary(dashboard: dict, trace: RunTrace) -> dict:
    total_games     = sum(len(v.get("games", [])) for v in dashboard.values())
    total_wx_ok     = sum(1 for c in trace.weather_calls if c["status"] == "ok")
    total_wx_cached = sum(1 for c in trace.weather_calls if c["cached"])
    total_wx_fail   = sum(1 for c in trace.weather_calls if c["error"])
    src_by_source: dict[str, list] = defaultdict(list)
    for c in trace.source_calls:
        src_by_source[c["source"]].append(c)
    source_summary = {
        src: {
            "calls":       len(calls),
            "ok":          sum(1 for c in calls if not c["error"]),
            "errors":      sum(1 for c in calls if c["error"]),
            "avg_latency_ms": round(sum(c["latency_ms"] for c in calls) / len(calls), 2) if calls else 0,
            "total_bytes": sum(c["bytes_recv"] for c in calls),
        }
        for src, calls in src_by_source.items()
    }
    return {
        "run_at_utc":        trace.run_start_utc,
        "total_wall_ms":     trace.total_elapsed_ms(),
        "phase_times_ms":    trace.phase_times,
        "total_games":       total_games,
        "sports":            list(dashboard.keys()),
        "source_calls_total":len(trace.source_calls),
        "source_summary":    source_summary,
        "weather": {
            "total_venues":  len(trace.weather_calls),
            "ok":            total_wx_ok,
            "cached":        total_wx_cached,
            "failed":        total_wx_fail,
        },
        "normalization_events": len(trace.norm_events),
        "match_events":     len(trace.match_events),
        "match_accepted":   sum(1 for m in trace.match_events if m["accepted"]),
        "match_rejected":   sum(1 for m in trace.match_events if not m["accepted"]),
    }


# ============================================================
# MAIN ENTRY POINT — called by routes.py after every build pass
# ============================================================

def write_run_diagnostic(dashboard: dict) -> str | None:
    """
    Write full diagnostic bundle to:
      data/diagnostics/OverlineEdge_RunDiagnostic_YYYYMMDD_HHMMSS.zip

    Contents of ZIP:
      startup_report.json      — Python/OS/packages/env
      pipeline_summary.json    — timing, source call counts, weather counts
      source_call_trace.json   — every API call with URL/status/latency/bytes
      weather_trace.json       — every venue weather fetch with density result
      normalization_trace.json — every team name canonicalization
      match_trace.json         — every Kalshi/Poly market match accept/reject
      data_quality_matrix.json — per-game: books, missing prices, vig, weather
      dashboard_snapshot.json  — full dashboard JSON
      server.log               — last 2000 lines of server.log
    """
    trace = RUN_TRACE
    try:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root  = Path("data/diagnostics")
        stage = root / f"run_{stamp}"
        stage.mkdir(parents=True, exist_ok=True)

        logger.info("[DIAG] Writing full run diagnostic bundle: %s", stamp)

        # 1. Startup report
        startup = _build_startup_report()
        (stage / "startup_report.json").write_text(
            json.dumps(startup, indent=2, default=str), encoding="utf-8"
        )
        logger.info("[DIAG]   startup_report.json  →  Python %s  |  %s",
                    sys.version.split()[0], startup["platform"])

        # 2. Pipeline summary
        summary = _build_pipeline_summary(dashboard, trace)
        (stage / "pipeline_summary.json").write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8"
        )
        logger.info("[DIAG]   pipeline_summary.json  →  %d games | %d src calls | %d ms total",
                    summary["total_games"], summary["source_calls_total"], summary["total_wall_ms"])

        # 3. Source call trace
        (stage / "source_call_trace.json").write_text(
            json.dumps(trace.source_calls, indent=2, default=str), encoding="utf-8"
        )
        logger.info("[DIAG]   source_call_trace.json  →  %d calls", len(trace.source_calls))

        # 4. Weather trace
        (stage / "weather_trace.json").write_text(
            json.dumps(trace.weather_calls, indent=2, default=str), encoding="utf-8"
        )
        logger.info("[DIAG]   weather_trace.json  →  %d venues  (%d ok / %d fail)",
                    len(trace.weather_calls),
                    summary["weather"]["ok"], summary["weather"]["failed"])

        # 5. Normalization trace
        (stage / "normalization_trace.json").write_text(
            json.dumps(trace.norm_events, indent=2, default=str), encoding="utf-8"
        )

        # 6. Match trace
        (stage / "match_trace.json").write_text(
            json.dumps(trace.match_events, indent=2, default=str), encoding="utf-8"
        )
        logger.info("[DIAG]   match_trace.json  →  %d accepted / %d rejected",
                    summary["match_accepted"], summary["match_rejected"])

        # 7. Data quality matrix
        matrix = _build_quality_matrix(dashboard)
        (stage / "data_quality_matrix.json").write_text(
            json.dumps(matrix, indent=2, default=str), encoding="utf-8"
        )

        # 8. Full dashboard snapshot
        (stage / "dashboard_snapshot.json").write_text(
            json.dumps(dashboard, indent=2, default=str), encoding="utf-8"
        )

        # 9. Server log tail (last 2000 lines)
        log_src = Path(LOG_DIR) / "server.log"
        if log_src.exists():
            lines = log_src.read_text(encoding="utf-8", errors="replace").splitlines()
            tail  = "\n".join(lines[-2000:])
            (stage / "server.log").write_text(tail, encoding="utf-8")
            logger.info("[DIAG]   server.log  →  last %d lines copied", min(len(lines), 2000))

        # 10. Human-readable ASCII summary
        readable = _build_ascii_summary(summary, matrix)
        (stage / "SUMMARY.txt").write_text(readable, encoding="utf-8")

        # ZIP everything
        target = root / f"OverlineEdge_RunDiagnostic_{stamp}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for f in stage.rglob("*"):
                if f.is_file():
                    archive.write(f, f.relative_to(stage))
        shutil.rmtree(stage, ignore_errors=True)

        # Keep only last 10 diagnostic ZIPs
        _prune_old_diagnostics(root, keep=10)

        logger.info("[DIAG] ✅ Run diagnostic complete: %s  (%d bytes)",
                    target.name, target.stat().st_size)
        return str(target)

    except Exception:
        logger.exception("[DIAG] ❌ Unable to write run diagnostic")
        return None


def _build_ascii_summary(summary: dict, matrix: dict) -> str:
    lines = []
    sep   = "=" * 70
    lines += [
        sep,
        "  OVERLINEEDGE v8 — RUN DIAGNOSTIC SUMMARY",
        f"  Run at (UTC):  {summary['run_at_utc']}",
        f"  Total wall ms: {summary['total_wall_ms']}",
        sep,
        "",
        "PHASE TIMING",
        "-" * 40,
    ]
    for phase, ms in summary.get("phase_times_ms", {}).items():
        lines.append(f"  {phase:<30s}  {ms:>8} ms")

    lines += ["", "SOURCE API CALLS", "-" * 40]
    for src, s in summary.get("source_summary", {}).items():
        lines.append(
            f"  {src:<20s}  calls={s['calls']:>3}  ok={s['ok']:>3}  "
            f"err={s['errors']:>2}  avg={s['avg_latency_ms']:>7.1f}ms  "
            f"bytes={s['total_bytes']:>10,}"
        )

    wx = summary.get("weather", {})
    lines += [
        "",
        "WEATHER / AIR DENSITY",
        "-" * 40,
        f"  Venues fetched:  {wx.get('total_venues', 0)}",
        f"  OK:              {wx.get('ok', 0)}",
        f"  Cache hits:      {wx.get('cached', 0)}",
        f"  Failed:          {wx.get('failed', 0)}",
    ]

    lines += [
        "",
        "MARKET MATCHING",
        "-" * 40,
        f"  Total events:    {summary.get('match_events', 0)}",
        f"  Accepted:        {summary.get('match_accepted', 0)}",
        f"  Rejected:        {summary.get('match_rejected', 0)}",
    ]

    lines += ["", "DATA QUALITY PER SPORT", "-" * 40]
    for sport, sm in matrix.items():
        games = sm.get("games", [])
        n     = len(games)
        wx_ok = sum(1 for g in games if g["weather_status"] == "ok")
        k_ok  = sum(1 for g in games if not str(g["kalshi_matched"]).startswith("rej"))
        p_ok  = sum(1 for g in games if not str(g["poly_matched"]).startswith("rej"))
        lines.append(
            f"  {sport.upper():<8s}  games={n:>2}  "
            f"wx={wx_ok:>2}/{n:<2}  "
            f"kalshi={k_ok:>2}/{n:<2}  "
            f"poly={p_ok:>2}/{n:<2}"
        )
        for g in games:
            avg_vig = f"{g['avg_vig']:.4f}" if g["avg_vig"] else "N/A"
            rho     = f"{g['air_density_kgm3']:.5f}" if g["air_density_kgm3"] else "N/A"
            lines.append(
                f"    ├ {g['title'][:38]:<38s}  "
                f"books={g['books_total']:>2}  "
                f"vig={avg_vig}  "
                f"wx={g['weather_status']:<12s}  "
                f"rho={rho}"
            )

    lines += ["", "=" * 70,
              "  See source_call_trace.json for every API URL, status, latency, bytes.",
              "  See weather_trace.json for per-venue density calculations.",
              "  See match_trace.json for Kalshi/Poly accept/reject reasoning.",
              "  See data_quality_matrix.json for full per-game book coverage.",
              "=" * 70]
    return "\n".join(lines)


def _prune_old_diagnostics(root: Path, keep: int = 10):
    zips = sorted(root.glob("OverlineEdge_RunDiagnostic_*.zip"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for old in zips[keep:]:
        try:
            old.unlink()
            logger.info("[DIAG] Pruned old diagnostic: %s", old.name)
        except Exception:
            pass
