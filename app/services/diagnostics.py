# app/services/diagnostics.py — shim re-exporting from root diagnostics.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from diagnostics import write_run_diagnostic, RUN_TRACE  # noqa: F401
