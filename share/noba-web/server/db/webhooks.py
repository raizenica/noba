# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Webhook endpoints database layer (Feature 8)."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

logger = logging.getLogger("noba")


def create_webhook(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    name: str,
    hook_id: str,
    secret: str,
    automation_id: str | None = None,
) -> int | None:
    """Create a new webhook endpoint. Returns the row id or None on failure."""
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "INSERT INTO webhook_endpoints "
                "(name, hook_id, secret, automation_id, enabled, last_triggered, "
                "trigger_count, created_at) VALUES (?,?,?,?,1,NULL,0,?)",
                (name, hook_id, secret, automation_id, now),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error("create_webhook failed: %s", e)
        return None


def list_webhooks(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> list[dict]:
    """Return all webhook endpoints."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, name, hook_id, automation_id, enabled, "
                "last_triggered, trigger_count, created_at "
                "FROM webhook_endpoints ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "hook_id": r[2],
                "automation_id": r[3], "enabled": bool(r[4]),
                "last_triggered": r[5], "trigger_count": r[6],
                "created_at": r[7],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("list_webhooks failed: %s", e)
        return []


def get_webhook_by_hook_id(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    hook_id: str,
) -> dict | None:
    """Look up a webhook by its public hook_id. Returns the record including secret."""
    try:
        with lock:
            r = conn.execute(
                "SELECT id, name, hook_id, secret, automation_id, enabled, "
                "last_triggered, trigger_count, created_at "
                "FROM webhook_endpoints WHERE hook_id = ?",
                (hook_id,),
            ).fetchone()
        if not r:
            return None
        return {
            "id": r[0], "name": r[1], "hook_id": r[2], "secret": r[3],
            "automation_id": r[4], "enabled": bool(r[5]),
            "last_triggered": r[6], "trigger_count": r[7],
            "created_at": r[8],
        }
    except Exception as e:
        logger.error("get_webhook_by_hook_id failed: %s", e)
        return None


def delete_webhook(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    webhook_id: int,
) -> bool:
    """Delete a webhook by its internal id."""
    try:
        with lock:
            cur = conn.execute(
                "DELETE FROM webhook_endpoints WHERE id = ?", (webhook_id,),
            )
            conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_webhook failed: %s", e)
        return False


def record_trigger(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    webhook_id: int,
) -> None:
    """Increment trigger_count and set last_triggered for a webhook."""
    now = int(time.time())
    try:
        with lock:
            conn.execute(
                "UPDATE webhook_endpoints SET trigger_count = trigger_count + 1, "
                "last_triggered = ? WHERE id = ?",
                (now, webhook_id),
            )
            conn.commit()
    except Exception as e:
        logger.error("record_trigger failed: %s", e)


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS webhook_endpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            hook_id TEXT UNIQUE NOT NULL,
            secret TEXT NOT NULL,
            automation_id TEXT,
            enabled INTEGER DEFAULT 1,
            last_triggered INTEGER,
            trigger_count INTEGER DEFAULT 0,
            created_at INTEGER
        );
    """)


class _WebhooksMixin:
    def create_webhook(self, name: str, hook_id: str, secret: str,
                       automation_id: str | None = None) -> int | None:
        return create_webhook(self._get_conn(), self._lock, name, hook_id, secret,
                              automation_id=automation_id)

    def list_webhooks(self) -> list[dict]:
        return list_webhooks(self._get_read_conn(), self._read_lock)

    def get_webhook_by_hook_id(self, hook_id: str) -> dict | None:
        return get_webhook_by_hook_id(self._get_read_conn(), self._read_lock, hook_id)

    def delete_webhook(self, webhook_id: int) -> bool:
        return delete_webhook(self._get_conn(), self._lock, webhook_id)

    def record_webhook_trigger(self, webhook_id: int) -> None:
        record_trigger(self._get_conn(), self._lock, webhook_id)
