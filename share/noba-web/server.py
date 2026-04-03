#!/usr/bin/env python3
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba Command Center – server launcher.

Requires FastAPI and uvicorn. Install with:
    pip install fastapi 'uvicorn[standard]' psutil pyyaml
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
HOST  = os.environ.get("HOST", "0.0.0.0")
PORT  = int(os.environ.get("PORT", 8080))


if __name__ == "__main__":
    # Ensure the package directory is on sys.path so `from server.app import app` works
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)

    try:
        import uvicorn  # noqa: F401
        from server.app import app  # noqa: F401
    except ImportError as e:
        print(f"[noba] Missing dependency: {e}", file=sys.stderr, flush=True)
        print("[noba] Install with:  pip install fastapi 'uvicorn[standard]' psutil pyyaml",
              file=sys.stderr, flush=True)
        sys.exit(1)

    os.chdir(_HERE)
    uvicorn.run(app, host=HOST, port=PORT, log_config=None, access_log=False)
