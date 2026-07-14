# app/services/odds_scraper.py — shim re-exporting from root odds_scraper.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from odds_scraper import *  # noqa: F401, F403
from odds_scraper import scrape_sport  # noqa: F401
