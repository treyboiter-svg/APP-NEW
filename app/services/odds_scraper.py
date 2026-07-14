# app/services/odds_scraper.py — compatibility shim
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from odds_scraper import scrape_sport  # noqa: F401
