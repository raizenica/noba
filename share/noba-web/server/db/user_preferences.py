# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- DB functions for per-user dashboard preferences."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

logger = logging.getLogger("noba")


def get_user_preferences(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
) -> dict | None:
    """Retrieve a user's preferences JSON blob, or None if not set."""
    try:
        with lock:
            r = conn.execute(
                "SELECT username, preferences_json, updated_at "
                "FROM user_preferences WHERE username = ?",
                (username,),
            ).fetchone()
        if not r:
            return None
        return {
            "username": r[0],
            "preferences": json.loads(r[1]) if r[1] else {},
            "updated_at": r[2],
        }
    except Exception as e:
        logger.error("get_user_preferences failed: %s", e)
        return None


def save_user_preferences(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
    preferences: dict,
) -> bool:
    """Save or update a user's preferences. Returns True on success."""
    try:
        with lock:
            conn.execute(
                "INSERT OR REPLACE INTO user_preferences "
                "(username, preferences_json, updated_at) VALUES (?,?,?)",
                (username, json.dumps(preferences), int(time.time())),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("save_user_preferences failed: %s", e)
        return False


def delete_user_preferences(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
) -> bool:
    """Delete a user's preferences (reset to defaults). Returns True if deleted."""
    try:
        with lock:
            cur = conn.execute(
                "DELETE FROM user_preferences WHERE username = ?",
                (username,),
            )
            conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_user_preferences failed: %s", e)
        return False


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            username TEXT PRIMARY KEY,
            preferences_json TEXT DEFAULT '{}',
            updated_at INTEGER
        );
    """)


class _UserPreferencesMixin:
    def get_user_preferences(self, username: str) -> dict | None:
        return get_user_preferences(self._get_read_conn(), self._read_lock, username)

    def save_user_preferences(self, username: str, preferences: dict) -> bool:
        return save_user_preferences(self._get_conn(), self._lock, username, preferences)

    def delete_user_preferences(self, username: str) -> bool:
        return delete_user_preferences(self._get_conn(), self._lock, username)
