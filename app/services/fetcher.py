# app/services/fetcher.py — shim re-exporting from root fetcher.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from fetcher import *  # noqa: F401, F403
from fetcher import build_all_sports, build_sport  # noqa: F401
