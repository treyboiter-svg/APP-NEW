# app/api/routes.py — compatibility shim only
# main.py no longer uses this file. It now imports directly from root routes.py.
# This file is kept so any legacy import does not cause an AttributeError.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from routes import router  # noqa: F401
