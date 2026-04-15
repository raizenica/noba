# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – DB user dashboard layout functions."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

logger = logging.getLogger("noba")


def save_user_dashboard(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
    card_order: list | None = None,
    card_vis: dict | None = None,
    card_theme: dict | None = None,
) -> None:
    """Save or update a user's dashboard layout preferences.

    Only overwrites columns where a non-None value is provided;
    existing values are preserved for any column left as None.
    """
    now = int(time.time())
    order_json = json.dumps(card_order) if card_order is not None else None
    vis_json = json.dumps(card_vis) if card_vis is not None else None
    theme_json = json.dumps(card_theme) if card_theme is not None else None
    try:
        with lock:
            conn.execute(
                "INSERT INTO user_dashboards "
                "(username, card_order, card_vis, card_theme, updated_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(username) DO UPDATE SET "
                "card_order = COALESCE(excluded.card_order, card_order), "
                "card_vis   = COALESCE(excluded.card_vis,   card_vis), "
                "card_theme = COALESCE(excluded.card_theme, card_theme), "
                "updated_at = excluded.updated_at",
                (username, order_json, vis_json, theme_json, now),
            )
            conn.commit()
    except Exception as e:
        logger.error("save_user_dashboard failed: %s", e)


def get_user_dashboard(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
) -> dict | None:
    """Retrieve a user's dashboard layout preferences."""
    try:
        with lock:
            r = conn.execute(
                "SELECT username, card_order, card_vis, card_theme, updated_at "
                "FROM user_dashboards WHERE username = ?",
                (username,),
            ).fetchone()
        if not r:
            return None
        return {
            "username": r[0],
            "card_order": json.loads(r[1]) if r[1] else None,
            "card_vis": json.loads(r[2]) if r[2] else None,
            "card_theme": json.loads(r[3]) if r[3] else None,
            "updated_at": r[4],
        }
    except Exception as e:
        logger.error("get_user_dashboard failed: %s", e)
        return None


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_dashboards (
            username    TEXT PRIMARY KEY,
            card_order  TEXT,
            card_vis    TEXT,
            card_theme  TEXT,
            updated_at  INTEGER NOT NULL
        );
    """)


class _UserDashboardsMixin:
    def save_user_dashboard(self, username: str, card_order: list | None = None,
                            card_vis: dict | None = None,
                            card_theme: dict | None = None) -> None:
        save_user_dashboard(self._get_conn(), self._lock, username,
                            card_order=card_order, card_vis=card_vis, card_theme=card_theme)

    def get_user_dashboard(self, username: str) -> dict | None:
        return get_user_dashboard(self._get_read_conn(), self._read_lock, username)
