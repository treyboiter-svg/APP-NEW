# app/services/weather_enricher.py — compatibility shim
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from weather_enricher import enrich_venue  # noqa: F401
