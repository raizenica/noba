# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – db package. Re-exports Database and singleton for backward compatibility."""
from __future__ import annotations

from .core import Database

# Lazy singleton - instantiated on first use to avoid circular imports with migrations
_db_instance: Database | None = None


def _get_db() -> Database:
    """Get or create the shared database singleton."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance


# Backward compatibility: use a module-level __getattr__ for lazy instantiation
# This way `from server.db import db` works, but db is only instantiated when first accessed
def __getattr__(name: str):
    if name == "db":
        return _get_db()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["Database", "db", "_get_db"]
