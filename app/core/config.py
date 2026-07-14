# app/core/config.py — shim re-exporting from root config.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import *  # noqa: F401, F403
from config import KALSHI_BASE, POLY_GAMMA, SPORT_KEYS, KALSHI_SERIES, POLY_SERIES  # noqa: F401
