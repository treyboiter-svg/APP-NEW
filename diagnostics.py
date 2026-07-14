"""diagnostics.py — OverlineEdge v8 Full System Diagnostic Engine
Imports from root-level config only. No app.* prefix.
"""
from __future__ import annotations
import json, logging, os, platform, shutil, subprocess, sys, time, zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from config import LOG_DIR
except ImportError:
    LOG_DIR = "data/logs"

logger = logging.getLogger(__name__)


class RunTrace:
    def __init__(self): self.reset()
    def reset(self):
        self.run_start_utc  = datetime.now(timezone.utc).isoformat()
        self.run_start_ts   = time.monotonic()
        self.source_calls:  list = []
        self.weather_calls: list = []
        self.phase_times:   dict = {}
        self.norm_events:   list = []
        self.match_events:  list = []
        self._phase_starts: dict = {}
    def phase_start(self, name: str):
        self._phase_starts[name] = time.monotonic()
        logger.info("[DIAG] ► Phase START: %s", name)
    def phase_end(self, name: str):
        start = self._phase_starts.pop(name, None)
        elapsed = round((time.monotonic() - start) * 1000, 2) if start else None
        self.phase_times[name] = elapsed
        logger.info("[DIAG] ◄ Phase END:   %s  →  %s ms", name, elapsed)
    def log_source_call(self, source, url, status, latency_ms, bytes_recv=0, error=""):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "source": source, "url": url, "status": status, "latency_ms": round(latency_ms, 2), "bytes_recv": bytes_recv, "error": error}
        self.source_calls.append(entry)
        logger.log(logging.WARNING if error else logging.INFO, "[DIAG][SOURCE] %s  %s  %s  %.1f ms  %s bytes  %s", source, status, url[:90], latency_ms, bytes_recv, error or "OK")
    def log_weather_call(self, venue, lat, lon, elev_m, status, latency_ms, density_kgm3=None, pct_isa=None, error="", cached=False):
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "venue": venue, "lat": lat, "lon": lon, "elevation_m": elev_m, "status": status, "latency_ms": round(latency_ms, 2), "density_kgm3": density_kgm3, "pct_isa": pct_isa, "cached": cached, "error": error}
        self.weather_calls.append(entry)
        logger.info("[DIAG][WEATHER] %s  status=%s  %.1f ms  rho=%s  cached=%s  %s", venue[:40], status, latency_ms, density_kgm3 or "N/A", cached, error or "OK")
    def log_norm(self, sport, raw, canonical, method, confidence):
        self.norm_events.append({"sport": sport, "raw": raw, "canonical": canonical, "method": method, "confidence": round(confidence, 4)})
    def log_match(self, sport, game, source, method, confidence, accepted, detail=""):
        self.match_events.append({"sport": sport, "game": game, "source": source, "method": method, "confidence": round(confidence, 4), "accepted": accepted, "detail": detail})
        logger.info("[DIAG][MATCH] %s  %s | %s | %s | conf=%.2f  %s", "✅ MATCH" if accepted else "❌ REJECT", sport, game[:40], source, confidence, detail)
    def total_elapsed_ms(self) -> float:
        return round((time.monotonic() - self.run_start_ts) * 1000, 2)

RUN_TRACE = RunTrace()


def _build_startup_report() -> dict:
    pip_out = ""
    try:
        result = subprocess.run([sys.executable, "-m", "pip", "list", "--format=columns"], capture_output=True, text=True, timeout=30)
        pip_out = result.stdout.strip()
    except Exception as e:
        pip_out = f"pip list failed: {e}"
    safe_keys = ["PATH", "PYTHONPATH", "VIRTUAL_ENV", "COMPUTERNAME", "USERNAME", "OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS"]
    env = {k: os.environ.get(k, "(not set)") for k in safe_keys}
    return {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "python_version": sys.version, "python_executable": sys.executable, "platform": platform.platform(), "cpu_count": os.cpu_count(), "cwd": str(Path.cwd()), "installed_packages": pip_out, "env_vars": env}


def _build_quality_matrix(dashboard: dict) -> dict:
    matrix = {}
    for sport, payload in dashboard.items():
        games = payload.get("games", [])
        sport_row = {"game_count": len(games), "games": []}
        for g in games:
            dq = g.get("data_quality", {})
            missing = dq.get("missing_prices", {})
            per_book = g.get("per_book", {})
            vigs = {bk: round(bd.get("vig_pct", 0), 4) for bk, bd in per_book.items() if bd.get("vig_pct") is not None}
            wx = g.get("venue", {}).get("weather_context", {})
            sport_row["games"].append({
                "title": g.get("title", ""), "commence": g.get("commence", ""),
                "books_total": len(per_book),
                "books_with_ml":     [bk for bk, bd in per_book.items() if bd.get("home_american") or bd.get("away_american")],
                "missing_ml":        missing.get("moneyline", []),
                "missing_spread":    missing.get("spread", []),
                "missing_total":     missing.get("total", []),
                "vig_per_book":      vigs,
                "avg_vig":           round(sum(vigs.values()) / len(vigs), 4) if vigs else None,
                "kalshi_matched":    g.get("match_audit", {}).get("kalshi_method", "none"),
                "poly_matched":      g.get("match_audit", {}).get("polymarket_method", "none"),
                "weather_status":    wx.get("status", "not_run"),
                "air_density_kgm3": wx.get("air_density_kgm3"),
            })
        matrix[sport] = sport_row
    return matrix


def _build_pipeline_summary(dashboard: dict, trace: RunTrace) -> dict:
    total_games = sum(len(v.get("games", [])) for v in dashboard.values())
    src_by_source: dict = defaultdict(list)
    for c in trace.source_calls: src_by_source[c["source"]].append(c)
    source_summary = {src: {"calls": len(calls), "ok": sum(1 for c in calls if not c["error"]), "errors": sum(1 for c in calls if c["error"]), "avg_latency_ms": round(sum(c["latency_ms"] for c in calls) / len(calls), 2) if calls else 0, "total_bytes": sum(c["bytes_recv"] for c in calls)} for src, calls in src_by_source.items()}
    return {"run_at_utc": trace.run_start_utc, "total_wall_ms": trace.total_elapsed_ms(), "phase_times_ms": trace.phase_times, "total_games": total_games, "sports": list(dashboard.keys()), "source_calls_total": len(trace.source_calls), "source_summary": source_summary, "weather": {"total_venues": len(trace.weather_calls), "ok": sum(1 for c in trace.weather_calls if c["status"] == "ok"), "cached": sum(1 for c in trace.weather_calls if c["cached"]), "failed": sum(1 for c in trace.weather_calls if c["error"])}, "match_events": len(trace.match_events), "match_accepted": sum(1 for m in trace.match_events if m["accepted"]), "match_rejected": sum(1 for m in trace.match_events if not m["accepted"])}


def write_run_diagnostic(dashboard: dict) -> str | None:
    trace = RUN_TRACE
    try:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root  = Path("data/diagnostics")
        stage = root / f"run_{stamp}"
        stage.mkdir(parents=True, exist_ok=True)
        logger.info("[DIAG] Writing full run diagnostic: %s", stamp)
        (stage / "startup_report.json").write_text(json.dumps(_build_startup_report(), indent=2, default=str), encoding="utf-8")
        summary = _build_pipeline_summary(dashboard, trace)
        (stage / "pipeline_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        (stage / "source_call_trace.json").write_text(json.dumps(trace.source_calls, indent=2, default=str), encoding="utf-8")
        (stage / "weather_trace.json").write_text(json.dumps(trace.weather_calls, indent=2, default=str), encoding="utf-8")
        (stage / "normalization_trace.json").write_text(json.dumps(trace.norm_events, indent=2, default=str), encoding="utf-8")
        (stage / "match_trace.json").write_text(json.dumps(trace.match_events, indent=2, default=str), encoding="utf-8")
        (stage / "data_quality_matrix.json").write_text(json.dumps(_build_quality_matrix(dashboard), indent=2, default=str), encoding="utf-8")
        (stage / "dashboard_snapshot.json").write_text(json.dumps(dashboard, indent=2, default=str), encoding="utf-8")
        log_src = Path(LOG_DIR) / "server.log"
        if log_src.exists():
            lines = log_src.read_text(encoding="utf-8", errors="replace").splitlines()
            (stage / "server.log").write_text("\n".join(lines[-2000:]), encoding="utf-8")
        target = root / f"OverlineEdge_RunDiagnostic_{stamp}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for f in stage.rglob("*"):
                if f.is_file(): archive.write(f, f.relative_to(stage))
        shutil.rmtree(stage, ignore_errors=True)
        for old in sorted(root.glob("OverlineEdge_RunDiagnostic_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)[10:]:
            try: old.unlink()
            except Exception: pass
        logger.info("[DIAG] ✅ Diagnostic complete: %s  (%d bytes)", target.name, target.stat().st_size)
        return str(target)
    except Exception:
        logger.exception("[DIAG] ❌ Unable to write run diagnostic")
        return None
