# app/services/normalizer.py — compatibility shim
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from normalizer import normalize_team  # noqa: F401
