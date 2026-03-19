#!/usr/bin/env python3
"""Noba Command Center – server launcher.

Tries FastAPI/uvicorn first; falls back to the legacy http.server if
uvicorn or fastapi are not installed on the system.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
HOST  = os.environ.get("HOST", "0.0.0.0")
PORT  = int(os.environ.get("PORT", 8080))


def _run_fastapi() -> None:
    import uvicorn  # noqa: F401  (ImportError propagates to caller)
    from server.app import app  # noqa: F401

    import uvicorn as _uv
    os.chdir(_HERE)
    _uv.run(app, host=HOST, port=PORT, log_config=None, access_log=False)


def _run_legacy() -> None:
    """Import and run the monolithic http.server fallback."""
    import importlib.util, pathlib

    legacy = pathlib.Path(_HERE) / "server_legacy.py"
    if not legacy.exists():
        sys.exit("server_legacy.py not found and FastAPI is unavailable. "
                 "Run: pip install fastapi uvicorn[standard] psutil")

    spec = importlib.util.spec_from_file_location("server_legacy", legacy)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)


if __name__ == "__main__":
    # Ensure the package directory is on sys.path so `from server.app import app` works
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)

    try:
        _run_fastapi()
    except ImportError:
        print("[noba] FastAPI/uvicorn not found – falling back to legacy server.", flush=True)
        print("[noba] Install with:  pip install fastapi 'uvicorn[standard]' psutil", flush=True)
        _run_legacy()
