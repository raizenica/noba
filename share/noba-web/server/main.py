# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Entry-point alias – allows both invocation styles:

    uvicorn server.app:app   (direct)
    uvicorn server.main:app  (legacy-friendly alias)
"""
from __future__ import annotations

from .app import app  # noqa: F401 – re-export for uvicorn

__all__ = ["app"]
