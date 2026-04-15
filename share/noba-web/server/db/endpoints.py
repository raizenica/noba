# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Endpoint monitor CRUD and check-result persistence."""
from __future__ import annotations

import logging
import sqlite3
import time

logger = logging.getLogger("noba")


def create_monitor(conn, lock, name: str, url: str, *,
                   method: str = "GET", expected_status: int = 200,
                   check_interval: int = 300, timeout: int = 10,
                   agent_hostname: str | None = None, enabled: bool = True,
                   notify_cert_days: int = 14) -> int | None:
    """Insert a new endpoint monitor and return its id."""
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "INSERT INTO endpoint_monitors "
                "(name, url, method, expected_status, check_interval, timeout, "
                " agent_hostname, enabled, created_at, notify_cert_days) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (name, url, method, expected_status, check_interval, timeout,
                 agent_hostname, 1 if enabled else 0, now, notify_cert_days),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error("create_monitor failed: %s", e)
        return None


def get_monitors(conn, lock, *, enabled_only: bool = False) -> list[dict]:
    """Return all endpoint monitors, optionally filtered to enabled ones."""
    try:
        clause = " WHERE enabled = 1" if enabled_only else ""
        with lock:
            rows = conn.execute(
                "SELECT id, name, url, method, expected_status, check_interval, "
                "timeout, agent_hostname, enabled, created_at, last_checked, "
                "last_status, last_response_ms, cert_expiry_days, notify_cert_days "
                f"FROM endpoint_monitors{clause} ORDER BY name"
            ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "url": r[2], "method": r[3],
                "expected_status": r[4], "check_interval": r[5],
                "timeout": r[6], "agent_hostname": r[7],
                "enabled": bool(r[8]), "created_at": r[9],
                "last_checked": r[10], "last_status": r[11],
                "last_response_ms": r[12], "cert_expiry_days": r[13],
                "notify_cert_days": r[14],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("get_monitors failed: %s", e)
        return []


def get_monitor(conn, lock, monitor_id: int) -> dict | None:
    """Return a single monitor by id."""
    try:
        with lock:
            row = conn.execute(
                "SELECT id, name, url, method, expected_status, check_interval, "
                "timeout, agent_hostname, enabled, created_at, last_checked, "
                "last_status, last_response_ms, cert_expiry_days, notify_cert_days "
                "FROM endpoint_monitors WHERE id = ?",
                (monitor_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "name": row[1], "url": row[2], "method": row[3],
            "expected_status": row[4], "check_interval": row[5],
            "timeout": row[6], "agent_hostname": row[7],
            "enabled": bool(row[8]), "created_at": row[9],
            "last_checked": row[10], "last_status": row[11],
            "last_response_ms": row[12], "cert_expiry_days": row[13],
            "notify_cert_days": row[14],
        }
    except Exception as e:
        logger.error("get_monitor failed: %s", e)
        return None


def update_monitor(conn, lock, monitor_id: int, **kwargs) -> bool:
    """Update fields on an existing monitor."""
    allowed = {
        "name", "url", "method", "expected_status", "check_interval",
        "timeout", "agent_hostname", "enabled", "notify_cert_days",
    }
    sets = []
    vals: list = []
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        if k == "enabled":
            v = 1 if v else 0
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return False
    vals.append(monitor_id)
    try:
        with lock:
            conn.execute(
                f"UPDATE endpoint_monitors SET {', '.join(sets)} WHERE id = ?",
                vals,
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("update_monitor failed: %s", e)
        return False


def delete_monitor(conn, lock, monitor_id: int) -> bool:
    """Delete an endpoint monitor."""
    try:
        with lock:
            cur = conn.execute(
                "DELETE FROM endpoint_monitors WHERE id = ?", (monitor_id,)
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_monitor failed: %s", e)
        return False


def record_check_result(conn, lock, monitor_id: int, *,
                        status: str, response_ms: int | None = None,
                        status_code: int | None = None,
                        cert_expiry_days: int | None = None,
                        error: str | None = None) -> None:
    """Update a monitor with the latest check result."""
    now = int(time.time())
    try:
        with lock:
            conn.execute(
                "UPDATE endpoint_monitors SET last_checked = ?, last_status = ?, "
                "last_response_ms = ?, cert_expiry_days = ? WHERE id = ?",
                (now, status, response_ms, cert_expiry_days, monitor_id),
            )
            conn.commit()
    except Exception as e:
        logger.error("record_check_result failed: %s", e)


def record_endpoint_check_history(conn, lock, monitor_id: int, status: str,
                                   response_ms: int | None = None,
                                   error: str | None = None) -> None:
    """Record a single endpoint check result into history."""
    now = int(time.time())
    try:
        with lock:
            conn.execute(
                "INSERT INTO endpoint_check_history (monitor_id, timestamp, status, response_ms, error) "
                "VALUES (?,?,?,?,?)",
                (monitor_id, now, status, response_ms, error),
            )
            conn.commit()
    except Exception as e:
        logger.error("record_endpoint_check_history failed: %s", e)


def get_endpoint_check_history(conn, lock, monitor_id: int, hours: int = 720) -> list[dict]:
    """Get check history for a monitor within the last N hours."""
    cutoff = int(time.time()) - hours * 3600
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, monitor_id, timestamp, status, response_ms, error "
                "FROM endpoint_check_history "
                "WHERE monitor_id = ? AND timestamp >= ? "
                "ORDER BY timestamp DESC",
                (monitor_id, cutoff),
            ).fetchall()
        return [
            {
                "id": r[0], "monitor_id": r[1], "timestamp": r[2],
                "status": r[3], "response_ms": r[4], "error": r[5],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("get_endpoint_check_history failed: %s", e)
        return []


def get_endpoint_uptime(conn, lock, monitor_id: int, hours: int = 720) -> float | None:
    """Calculate uptime percentage from check history (returns 0-100 or None).

    Honesty contract: a monitor with zero history rows in the window returns
    ``None`` (unknown), NOT a fake 100% "assume OK". The caller decides how
    to surface unknown uptime — typically by skipping the monitor from any
    aggregated score. Same applies to DB failures: exception → None, not a
    silent fake-100.
    """
    cutoff = int(time.time()) - hours * 3600
    try:
        with lock:
            row = conn.execute(
                "SELECT COUNT(*), SUM(CASE WHEN status = 'up' THEN 1 ELSE 0 END) "
                "FROM endpoint_check_history "
                "WHERE monitor_id = ? AND timestamp >= ?",
                (monitor_id, cutoff),
            ).fetchone()
        total = row[0] or 0
        up_count = row[1] or 0
        if total == 0:
            return None  # No data yet — unknown, not a free A
        return round((up_count / total) * 100, 2)
    except Exception as e:
        logger.error("get_endpoint_uptime failed: %s", e)
        return None


def get_endpoint_avg_latency(conn, lock, monitor_id: int, hours: int = 720) -> float | None:
    """Calculate average response time (ms) from successful checks."""
    cutoff = int(time.time()) - hours * 3600
    try:
        with lock:
            row = conn.execute(
                "SELECT AVG(response_ms) "
                "FROM endpoint_check_history "
                "WHERE monitor_id = ? AND timestamp >= ? AND status = 'up' AND response_ms IS NOT NULL",
                (monitor_id, cutoff),
            ).fetchone()
        avg = row[0] if row else None
        return round(avg, 2) if avg is not None else None
    except Exception as e:
        logger.error("get_endpoint_avg_latency failed: %s", e)
        return None


def prune_endpoint_check_history(conn, lock, days: int = 90) -> None:
    """Delete check history older than N days."""
    cutoff = int(time.time()) - days * 86400
    try:
        with lock:
            conn.execute(
                "DELETE FROM endpoint_check_history WHERE timestamp < ?",
                (cutoff,),
            )
            conn.commit()
    except Exception as e:
        logger.error("prune_endpoint_check_history failed: %s", e)


def get_due_monitors(conn, lock) -> list[dict]:
    """Return enabled monitors whose next check is due (last_checked + interval < now)."""
    now = int(time.time())
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, name, url, method, expected_status, check_interval, "
                "timeout, agent_hostname, enabled, created_at, last_checked, "
                "last_status, last_response_ms, cert_expiry_days, notify_cert_days "
                "FROM endpoint_monitors "
                "WHERE enabled = 1 AND (last_checked IS NULL OR last_checked + check_interval < ?)",
                (now,),
            ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "url": r[2], "method": r[3],
                "expected_status": r[4], "check_interval": r[5],
                "timeout": r[6], "agent_hostname": r[7],
                "enabled": bool(r[8]), "created_at": r[9],
                "last_checked": r[10], "last_status": r[11],
                "last_response_ms": r[12], "cert_expiry_days": r[13],
                "notify_cert_days": r[14],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("get_due_monitors failed: %s", e)
        return []



def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS endpoint_monitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            method TEXT DEFAULT 'GET',
            expected_status INTEGER DEFAULT 200,
            check_interval INTEGER DEFAULT 300,
            timeout INTEGER DEFAULT 10,
            agent_hostname TEXT,
            enabled INTEGER DEFAULT 1,
            created_at INTEGER,
            last_checked INTEGER,
            last_status TEXT,
            last_response_ms INTEGER,
            cert_expiry_days INTEGER,
            notify_cert_days INTEGER DEFAULT 14
        );
        CREATE INDEX IF NOT EXISTS idx_endpoint_monitors_enabled
            ON endpoint_monitors(enabled);

        CREATE TABLE IF NOT EXISTS endpoint_check_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id  INTEGER NOT NULL,
            timestamp   INTEGER NOT NULL,
            status      TEXT NOT NULL,
            response_ms INTEGER,
            error       TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ech_monitor_ts
            ON endpoint_check_history(monitor_id, timestamp);
    """)


class _EndpointsMixin:
    def create_endpoint_monitor(self, name: str, url: str, **kwargs) -> int | None:
        return create_monitor(self._get_conn(), self._lock, name, url, **kwargs)

    def get_endpoint_monitors(self, *, enabled_only: bool = False) -> list[dict]:
        return get_monitors(self._get_read_conn(), self._read_lock, enabled_only=enabled_only)

    def get_endpoint_monitor(self, monitor_id: int) -> dict | None:
        return get_monitor(self._get_read_conn(), self._read_lock, monitor_id)

    def update_endpoint_monitor(self, monitor_id: int, **kwargs) -> bool:
        return update_monitor(self._get_conn(), self._lock, monitor_id, **kwargs)

    def delete_endpoint_monitor(self, monitor_id: int) -> bool:
        return delete_monitor(self._get_conn(), self._lock, monitor_id)

    def record_endpoint_check(self, monitor_id: int, **kwargs) -> None:
        record_check_result(self._get_conn(), self._lock, monitor_id, **kwargs)

    def get_due_endpoint_monitors(self) -> list[dict]:
        return get_due_monitors(self._get_read_conn(), self._read_lock)

    def record_endpoint_check_history(self, monitor_id: int, status: str,
                                       response_ms: int | None = None,
                                       error: str | None = None) -> None:
        record_endpoint_check_history(self._get_conn(), self._lock,
                                      monitor_id, status,
                                      response_ms=response_ms, error=error)

    def get_endpoint_check_history(self, monitor_id: int,
                                    hours: int = 720) -> list[dict]:
        return get_endpoint_check_history(self._get_read_conn(), self._read_lock,
                                          monitor_id, hours=hours)

    def get_endpoint_uptime(self, monitor_id: int, hours: int = 720) -> float | None:
        return get_endpoint_uptime(self._get_read_conn(), self._read_lock,
                                   monitor_id, hours=hours)

    def get_endpoint_avg_latency(self, monitor_id: int,
                                  hours: int = 720) -> float | None:
        return get_endpoint_avg_latency(self._get_read_conn(), self._read_lock,
                                        monitor_id, hours=hours)

    def prune_endpoint_check_history(self, days: int = 90) -> None:
        prune_endpoint_check_history(self._get_conn(), self._lock, days=days)
