# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Linked social provider persistence."""
from __future__ import annotations

import time
import sqlite3


def _ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS linked_providers (
            username TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_email TEXT NOT NULL,
            provider_name TEXT DEFAULT '',
            linked_at REAL NOT NULL,
            PRIMARY KEY (username, provider)
        )
    """)
    conn.commit()


def get_linked_providers(conn, lock, username: str) -> dict:
    """Get all linked providers for a user. Returns {provider: {email, name, linked_at}}."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT provider, provider_email, provider_name, linked_at FROM linked_providers WHERE username = ?",
                (username,)
            ).fetchall()
    except Exception:
        return {}
    return {
        row[0]: {"email": row[1], "name": row[2], "linked_at": row[3]}
        for row in rows
    }


def link_provider(conn, lock, username: str, provider: str, email: str, name: str = "") -> None:
    """Link a social provider to a user account."""
    _ensure_table(conn)
    with lock:
        conn.execute(
            "INSERT OR REPLACE INTO linked_providers (username, provider, provider_email, provider_name, linked_at) VALUES (?, ?, ?, ?, ?)",
            (username, provider, email, name, time.time())
        )
        conn.commit()


def unlink_provider(conn, lock, username: str, provider: str) -> bool:
    """Unlink a social provider. Returns True if it existed."""
    _ensure_table(conn)
    with lock:
        cur = conn.execute(
            "DELETE FROM linked_providers WHERE username = ? AND provider = ?",
            (username, provider)
        )
        conn.commit()
        return cur.rowcount > 0


def find_user_by_provider(conn, lock, provider: str, email: str) -> str | None:
    """Find a NOBA username by their linked provider email. Used for social login."""
    try:
        with lock:
            row = conn.execute(
                "SELECT username FROM linked_providers WHERE provider = ? AND provider_email = ?",
                (provider, email)
            ).fetchone()
    except Exception:
        return None
    return row[0] if row else None



def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS linked_providers (
            username TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_email TEXT NOT NULL,
            provider_name TEXT DEFAULT '',
            linked_at REAL NOT NULL,
            PRIMARY KEY (username, provider)
        );
    """)


class _LinkedProvidersMixin:
    def get_linked_providers(self, username: str) -> dict:
        return get_linked_providers(self._get_read_conn(), self._read_lock, username)

    def link_provider(self, username: str, provider: str, email: str,
                      name: str = "") -> None:
        link_provider(self._get_conn(), self._lock, username, provider,
                      email, name)

    def unlink_provider(self, username: str, provider: str) -> bool:
        return unlink_provider(self._get_conn(), self._lock, username,
                               provider)

    def find_user_by_provider(self, provider: str, email: str) -> str | None:
        return find_user_by_provider(self._get_read_conn(), self._read_lock, provider,
                                     email)
