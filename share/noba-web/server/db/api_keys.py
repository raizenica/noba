# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – DB API key functions."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

logger = logging.getLogger("noba")


def insert_api_key(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    key_id: str,
    name: str,
    key_hash: str,
    role: str,
    expires_at: int | None = None,
) -> None:
    """Insert a new API key."""
    try:
        with lock:
            conn.execute(
                "INSERT INTO api_keys (id, name, key_hash, role, created_at, expires_at) "
                "VALUES (?,?,?,?,?,?)",
                (key_id, name, key_hash, role, int(time.time()), expires_at),
            )
            conn.commit()
    except Exception as e:
        logger.error("insert_api_key failed: %s", e)


def get_api_key(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    key_hash: str,
) -> dict | None:
    """Look up an API key by its hash and update last_used timestamp."""
    try:
        now = int(time.time())
        with lock:
            r = conn.execute(
                "SELECT id, name, key_hash, role, created_at, expires_at, last_used "
                "FROM api_keys WHERE key_hash = ? AND (expires_at IS NULL OR expires_at > ?)",
                (key_hash, now),
            ).fetchone()
            if not r:
                return None
            conn.execute(
                "UPDATE api_keys SET last_used = ? WHERE key_hash = ?",
                (int(time.time()), key_hash),
            )
            conn.commit()
        return {
            "id": r[0], "name": r[1], "key_hash": r[2], "role": r[3],
            "created_at": r[4], "expires_at": r[5], "last_used": r[6],
        }
    except Exception as e:
        logger.error("get_api_key failed: %s", e)
        return None


def list_api_keys(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> list[dict]:
    """List all API keys (excluding key_hash from results)."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, name, role, created_at, expires_at, last_used "
                "FROM api_keys ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "role": r[2],
                "created_at": r[3], "expires_at": r[4], "last_used": r[5],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("list_api_keys failed: %s", e)
        return []


def delete_api_key(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    key_id: str,
) -> bool:
    """Delete an API key by its id."""
    try:
        with lock:
            cur = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
            conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_api_key failed: %s", e)
        return False


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            key_hash   TEXT NOT NULL,
            role       TEXT NOT NULL DEFAULT 'viewer',
            created_at INTEGER NOT NULL,
            expires_at INTEGER,
            last_used  INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_api_keys_hash
            ON api_keys(key_hash);
    """)


class _ApiKeysMixin:
    def insert_api_key(self, key_id: str, name: str, key_hash: str,
                       role: str, expires_at: int | None = None) -> None:
        insert_api_key(self._get_conn(), self._lock, key_id, name, key_hash,
                       role, expires_at=expires_at)

    def get_api_key(self, key_hash: str) -> dict | None:
        # NOTE: get_api_key updates last_used — it's a write operation
        return get_api_key(self._get_conn(), self._lock, key_hash)

    def list_api_keys(self) -> list[dict]:
        return list_api_keys(self._get_read_conn(), self._read_lock)

    def delete_api_key(self, key_id: str) -> bool:
        return delete_api_key(self._get_conn(), self._lock, key_id)
