# app/services/venue_resolver.py — shim re-exporting from root venue_resolver.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from venue_resolver import *  # noqa: F401, F403
from venue_resolver import VenueResolver, default_workbook_path  # noqa: F401
