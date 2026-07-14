# app/services/normalizer.py — shim re-exporting from root normalizer.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from normalizer import *  # noqa: F401, F403
from normalizer import normalize_team, team_id, match_teams, clean_raw  # noqa: F401
