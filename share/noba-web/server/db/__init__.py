"""Noba – db package. Re-exports Database and singleton for backward compatibility."""
from __future__ import annotations

from .core import Database

db = Database()

__all__ = ["Database", "db"]
