# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – DB audit functions (log, query, login history, prune)."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

from ..config import AUDIT_RETENTION_DAYS

logger = logging.getLogger("noba")


def audit_log(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    action: str,
    username: str,
    details: str = "",
    ip: str = "",
) -> None:
    if len(details) > 512:
        details = details[:512] + "…"
    try:
        with lock:
            conn.execute(
                "INSERT INTO audit (timestamp, username, action, details, ip) VALUES (?,?,?,?,?)",
                (int(time.time()), username, action, details, ip),
            )
            conn.commit()
    except Exception as e:
        logger.error("audit_log failed: %s", e)


def get_audit(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    limit: int = 100,
    username_filter: str = "",
    action_filter: str = "",
    from_ts: int = 0,
    to_ts: int = 0,
) -> list[dict]:
    try:
        clauses = []
        params: list = []
        if username_filter:
            clauses.append("username = ?")
            params.append(username_filter)
        if action_filter:
            clauses.append("action = ?")
            params.append(action_filter)
        if from_ts:
            clauses.append("timestamp >= ?")
            params.append(from_ts)
        if to_ts:
            clauses.append("timestamp <= ?")
            params.append(to_ts)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with lock:
            rows = conn.execute(
                f"SELECT timestamp, username, action, details, ip FROM audit{where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            {"time": r[0], "username": r[1], "action": r[2], "details": r[3], "ip": r[4]}
            for r in rows
        ]
    except Exception as e:
        logger.error("get_audit failed: %s", e)
        return []


def get_login_history(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
    limit: int = 30,
) -> list[dict]:
    """Get login history for a specific user."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT timestamp, action, details, ip FROM audit "
                "WHERE username = ? AND action IN ('login', 'login_failed') "
                "ORDER BY timestamp DESC LIMIT ?",
                (username, limit),
            ).fetchall()
        return [{"time": r[0], "action": r[1], "details": r[2], "ip": r[3]} for r in rows]
    except Exception as e:
        logger.error("get_login_history failed: %s", e)
        return []


def prune_audit(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> None:
    cutoff = int(time.time()) - AUDIT_RETENTION_DAYS * 86400
    try:
        with lock:
            stale = conn.execute(
                "SELECT COUNT(*) FROM audit WHERE timestamp < ?", (cutoff,)
            ).fetchone()[0]
            if stale == 0:
                return
            conn.execute("DELETE FROM audit WHERE timestamp < ?", (cutoff,))
            conn.commit()
            logger.info("Audit pruned: %d rows older than %d days", stale, AUDIT_RETENTION_DAYS)
    except Exception as e:
        logger.error("prune_audit failed: %s", e)


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS audit (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            username  TEXT NOT NULL,
            action    TEXT NOT NULL,
            details   TEXT,
            ip        TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audit_ts
            ON audit(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_user_action
            ON audit(username, action);
    """)


class _AuditMixin:
    def audit_log(self, action: str, username: str, details: str = "", ip: str = "") -> None:
        audit_log(self._get_conn(), self._lock, action, username, details=details, ip=ip)

    def get_audit(self, limit: int = 100, username_filter: str = "",
                  action_filter: str = "", from_ts: int = 0, to_ts: int = 0) -> list[dict]:
        return get_audit(self._get_read_conn(), self._read_lock, limit=limit,
                         username_filter=username_filter, action_filter=action_filter,
                         from_ts=from_ts, to_ts=to_ts)

    def get_login_history(self, username: str, limit: int = 30) -> list[dict]:
        return get_login_history(self._get_read_conn(), self._read_lock, username, limit=limit)

    def prune_audit(self) -> None:
        prune_audit(self._get_conn(), self._lock)
