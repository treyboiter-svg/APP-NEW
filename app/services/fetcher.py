# app/services/fetcher.py — compatibility shim
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from fetcher import build_all_sports, build_sport  # noqa: F401
