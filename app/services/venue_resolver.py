# app/services/venue_resolver.py — compatibility shim
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from venue_resolver import VenueResolver, default_workbook_path, _fold, _tokens  # noqa: F401
