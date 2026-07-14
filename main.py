"""main.py — OverlineEdge v8 entry point.
Direct imports from root-level modules. No app.* prefix needed.
"""
import logging
import logging.handlers
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── logging setup (file + console) ──────────────────────────────────────────
LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = LOG_DIR / "server.log"

_fh = logging.handlers.RotatingFileHandler(
    _LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_ch, _fh])

# ── import router directly from root routes.py ───────────────────────────────
from routes import router  # noqa: E402

app = FastAPI(title="OverlineEdge v8")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

@app.get("/")
async def root():
    return {"service": "overlineedge_v8", "status": "running"}
