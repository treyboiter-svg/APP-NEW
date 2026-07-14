# app/services/odds_calc.py — shim re-exporting from root odds_calc.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from odds_calc import *  # noqa: F401, F403
