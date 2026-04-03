# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – DB alert and incident functions."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

logger = logging.getLogger("noba")


# ── Alert History ─────────────────────────────────────────────────────────────

def insert_alert_history(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    rule_id: str,
    severity: str,
    message: str,
) -> None:
    """Insert an alert event with the current timestamp."""
    try:
        with lock:
            conn.execute(
                "INSERT INTO alert_history (rule_id, timestamp, severity, message) "
                "VALUES (?,?,?,?)",
                (rule_id, int(time.time()), severity, message),
            )
            conn.commit()
    except Exception as e:
        logger.error("insert_alert_history failed: %s", e)


def get_alert_history(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    limit: int = 100,
    rule_id: str | None = None,
    from_ts: int = 0,
    to_ts: int = 0,
) -> list[dict]:
    """Query alert history with optional filters."""
    try:
        clauses: list[str] = []
        params: list = []
        if rule_id:
            clauses.append("rule_id = ?")
            params.append(rule_id)
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
                "SELECT id, rule_id, timestamp, severity, message, resolved_at "
                f"FROM alert_history{where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            {
                "id": r[0], "rule_id": r[1], "timestamp": r[2],
                "severity": r[3], "message": r[4], "resolved_at": r[5],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("get_alert_history failed: %s", e)
        return []


def resolve_alert(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    rule_id: str,
) -> None:
    """Mark all unresolved alerts for a rule as resolved now."""
    try:
        with lock:
            conn.execute(
                "UPDATE alert_history SET resolved_at = ? "
                "WHERE rule_id = ? AND resolved_at IS NULL",
                (int(time.time()), rule_id),
            )
            conn.commit()
    except Exception as e:
        logger.error("resolve_alert failed: %s", e)


def get_sla(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    rule_id: str,
    window_hours: int = 720,
) -> float:
    """Calculate uptime percentage for a rule over the given window.

    Counts total seconds in the window minus seconds where an alert was
    active (timestamp to resolved_at or now if still open).  Returns the
    uptime as a percentage (0-100).
    """
    try:
        now = int(time.time())
        window_start = now - window_hours * 3600
        window_seconds = window_hours * 3600
        with lock:
            rows = conn.execute(
                "SELECT timestamp, resolved_at FROM alert_history "
                "WHERE rule_id = ? AND "
                "(resolved_at IS NULL OR resolved_at >= ?) AND timestamp <= ?",
                (rule_id, window_start, now),
            ).fetchall()
        downtime = 0
        for alert_start, resolved_at in rows:
            start = max(alert_start, window_start)
            end = resolved_at if resolved_at else now
            end = min(end, now)
            if end > start:
                downtime += end - start
        if window_seconds == 0:
            return 100.0
        uptime = max(0.0, (window_seconds - downtime) / window_seconds * 100)
        return round(uptime, 4)
    except Exception as e:
        logger.error("get_sla failed: %s", e)
        return 100.0


# ── Incidents ─────────────────────────────────────────────────────────────────

def insert_incident(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    severity: str,
    source: str,
    title: str,
    details: str = "",
) -> int:
    try:
        with lock:
            c = conn.execute(
                "INSERT INTO incidents (timestamp, severity, source, title, details) VALUES (?,?,?,?,?)",
                (int(time.time()), severity, source, title, details),
            )
            conn.commit()
            return c.lastrowid or 0
    except Exception as e:
        logger.error("insert_incident failed: %s", e)
        return 0


def get_incidents(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    limit: int = 100,
    hours: int = 24,
) -> list[dict]:
    try:
        cutoff = int(time.time()) - hours * 3600
        with lock:
            rows = conn.execute(
                "SELECT id, timestamp, severity, source, title, details, resolved_at FROM incidents "
                "WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
        return [
            {
                "id": r[0], "timestamp": r[1], "severity": r[2], "source": r[3],
                "title": r[4], "details": r[5], "resolved_at": r[6],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("get_incidents failed: %s", e)
        return []


def resolve_incident(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    incident_id: int,
) -> bool:
    try:
        with lock:
            conn.execute(
                "UPDATE incidents SET resolved_at = ? WHERE id = ?",
                (int(time.time()), incident_id),
            )
            conn.commit()
        return True
    except Exception:
        return False


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS alert_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id     TEXT NOT NULL,
            timestamp   INTEGER NOT NULL,
            severity    TEXT NOT NULL,
            message     TEXT,
            resolved_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_alert_hist ON alert_history(rule_id, timestamp);

        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            source TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            details TEXT DEFAULT '',
            resolved_at INTEGER DEFAULT 0,
            auto_generated INTEGER DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_incidents_time ON incidents(timestamp DESC);
    """)


class _AlertsMixin:
    def insert_alert_history(self, rule_id: str, severity: str, message: str) -> None:
        insert_alert_history(self._get_conn(), self._lock, rule_id, severity, message)

    def get_alert_history(self, limit: int = 100, rule_id: str | None = None,
                          from_ts: int = 0, to_ts: int = 0) -> list[dict]:
        return get_alert_history(self._get_read_conn(), self._read_lock, limit=limit,
                                 rule_id=rule_id, from_ts=from_ts, to_ts=to_ts)

    def resolve_alert(self, rule_id: str) -> None:
        resolve_alert(self._get_conn(), self._lock, rule_id)

    def get_sla(self, rule_id: str, window_hours: int = 720) -> float:
        return get_sla(self._get_read_conn(), self._read_lock, rule_id, window_hours=window_hours)

    def insert_incident(self, severity: str, source: str, title: str, details: str = "") -> int:
        return insert_incident(self._get_conn(), self._lock, severity, source, title,
                               details=details)

    def get_incidents(self, limit: int = 100, hours: int = 24) -> list[dict]:
        return get_incidents(self._get_read_conn(), self._read_lock, limit=limit, hours=hours)

    def resolve_incident(self, incident_id: int) -> bool:
        return resolve_incident(self._get_conn(), self._lock, incident_id)
