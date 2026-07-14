# app/api/routes.py — shim that re-exports the router from root routes.py
# This satisfies main.py's `from app.api.routes import router` import
# while keeping all real logic in the flat root-level routes.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from routes import router  # noqa: F401
