# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- DB status page functions (components, incidents, updates, uptime)."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger("noba")


# -- Status Page Components ---------------------------------------------------

def create_status_component(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    name: str,
    group_name: str = "Default",
    service_key: str | None = None,
    display_order: int = 0,
) -> int:
    """Create a status page component and return its id."""
    try:
        with lock:
            c = conn.execute(
                "INSERT INTO status_components (name, group_name, service_key, display_order) "
                "VALUES (?,?,?,?)",
                (name, group_name, service_key, display_order),
            )
            conn.commit()
            return c.lastrowid or 0
    except Exception as e:
        logger.error("create_status_component failed: %s", e)
        return 0


def list_status_components(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> list[dict]:
    """Return all status components ordered by display_order."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, name, group_name, service_key, display_order, enabled "
                "FROM status_components ORDER BY display_order, id"
            ).fetchall()
        return [
            {"id": r[0], "name": r[1], "group_name": r[2], "service_key": r[3],
             "display_order": r[4], "enabled": bool(r[5])}
            for r in rows
        ]
    except Exception as e:
        logger.error("list_status_components failed: %s", e)
        return []


def update_status_component(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    comp_id: int,
    **kwargs,
) -> bool:
    """Update a status component. Allowed keys: name, group_name, service_key, display_order, enabled."""
    allowed = {"name", "group_name", "service_key", "display_order", "enabled"}
    sets = []
    params: list = []
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        if k == "enabled":
            v = 1 if v else 0
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        return False
    params.append(comp_id)
    try:
        with lock:
            cur = conn.execute(
                f"UPDATE status_components SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("update_status_component failed: %s", e)
        return False


def delete_status_component(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    comp_id: int,
) -> bool:
    """Delete a status component by id."""
    try:
        with lock:
            cur = conn.execute("DELETE FROM status_components WHERE id = ?", (comp_id,))
            conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_status_component failed: %s", e)
        return False


# -- Status Page Incidents ----------------------------------------------------

def create_status_incident(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    title: str,
    severity: str = "minor",
    message: str = "",
    created_by: str = "",
) -> int:
    """Create a status page incident with an optional initial update message."""
    now = int(time.time())
    try:
        with lock:
            c = conn.execute(
                "INSERT INTO status_incidents (title, severity, status, created_at, created_by) "
                "VALUES (?,?,?,?,?)",
                (title, severity, "investigating", now, created_by),
            )
            incident_id = c.lastrowid or 0
            if incident_id and message:
                conn.execute(
                    "INSERT INTO status_updates (incident_id, message, status, created_at, created_by) "
                    "VALUES (?,?,?,?,?)",
                    (incident_id, message, "investigating", now, created_by),
                )
            conn.commit()
            return incident_id
    except Exception as e:
        logger.error("create_status_incident failed: %s", e)
        return 0


def list_status_incidents(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    limit: int = 50,
    include_resolved: bool = True,
) -> list[dict]:
    """List status incidents, most recent first."""
    try:
        where = "" if include_resolved else " WHERE resolved_at IS NULL"
        with lock:
            rows = conn.execute(
                "SELECT id, title, severity, status, created_at, resolved_at, created_by, assigned_to "
                f"FROM status_incidents{where} ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": r[0], "title": r[1], "severity": r[2], "status": r[3],
             "created_at": r[4], "resolved_at": r[5], "created_by": r[6],
             "assigned_to": r[7]}
            for r in rows
        ]
    except Exception as e:
        logger.error("list_status_incidents failed: %s", e)
        return []


def get_status_incident(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    incident_id: int,
) -> dict | None:
    """Get a single status incident with its updates."""
    try:
        with lock:
            r = conn.execute(
                "SELECT id, title, severity, status, created_at, resolved_at, created_by, assigned_to "
                "FROM status_incidents WHERE id = ?",
                (incident_id,),
            ).fetchone()
            if not r:
                return None
            updates = conn.execute(
                "SELECT id, message, status, created_at, created_by "
                "FROM status_updates WHERE incident_id = ? ORDER BY created_at ASC, id ASC",
                (incident_id,),
            ).fetchall()
        return {
            "id": r[0], "title": r[1], "severity": r[2], "status": r[3],
            "created_at": r[4], "resolved_at": r[5], "created_by": r[6],
            "assigned_to": r[7],
            "updates": [
                {"id": u[0], "message": u[1], "status": u[2],
                 "created_at": u[3], "created_by": u[4]}
                for u in updates
            ],
        }
    except Exception as e:
        logger.error("get_status_incident failed: %s", e)
        return None


def update_status_incident(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    incident_id: int,
    **kwargs,
) -> bool:
    """Update a status incident. Allowed keys: title, severity, status."""
    allowed = {"title", "severity", "status"}
    sets = []
    params: list = []
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        return False
    params.append(incident_id)
    try:
        with lock:
            cur = conn.execute(
                f"UPDATE status_incidents SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("update_status_incident failed: %s", e)
        return False


def add_status_update(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    incident_id: int,
    message: str,
    status: str = "investigating",
    created_by: str = "",
) -> int:
    """Add an update to a status incident."""
    now = int(time.time())
    try:
        with lock:
            c = conn.execute(
                "INSERT INTO status_updates (incident_id, message, status, created_at, created_by) "
                "VALUES (?,?,?,?,?)",
                (incident_id, message, status, now, created_by),
            )
            # Also update the incident's status
            conn.execute(
                "UPDATE status_incidents SET status = ? WHERE id = ?",
                (status, incident_id),
            )
            conn.commit()
            return c.lastrowid or 0
    except Exception as e:
        logger.error("add_status_update failed: %s", e)
        return 0


def resolve_status_incident(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    incident_id: int,
    created_by: str = "",
) -> bool:
    """Resolve a status incident."""
    now = int(time.time())
    try:
        with lock:
            conn.execute(
                "UPDATE status_incidents SET status = 'resolved', resolved_at = ? WHERE id = ?",
                (now, incident_id),
            )
            conn.execute(
                "INSERT INTO status_updates (incident_id, message, status, created_at, created_by) "
                "VALUES (?,?,?,?,?)",
                (incident_id, "This incident has been resolved.", "resolved", now, created_by),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("resolve_status_incident failed: %s", e)
        return False


def get_status_uptime_history(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    days: int = 90,
) -> list[dict]:
    """Return per-day incident counts for the uptime bar chart.

    Each entry: {date: 'YYYY-MM-DD', incidents: N, worst_severity: 'minor'|'major'|'critical'}
    Days with no incidents get severity 'none' (operational).
    """
    try:
        cutoff = int(time.time()) - days * 86400
        with lock:
            rows = conn.execute(
                "SELECT created_at, severity FROM status_incidents WHERE created_at >= ?",
                (cutoff,),
            ).fetchall()
        # Group by date
        by_day: dict[str, list[str]] = defaultdict(list)
        for created_at, severity in rows:
            day = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d")
            by_day[day].append(severity)
        # Build result for each day
        result = []
        severity_rank = {"critical": 3, "major": 2, "minor": 1}
        for d in range(days):
            ts = int(time.time()) - (days - 1 - d) * 86400
            day_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            sevs = by_day.get(day_str, [])
            if not sevs:
                result.append({"date": day_str, "incidents": 0, "worst_severity": "none"})
            else:
                worst = max(sevs, key=lambda s: severity_rank.get(s, 0))
                result.append({"date": day_str, "incidents": len(sevs), "worst_severity": worst})
        return result
    except Exception as e:
        logger.error("get_status_uptime_history failed: %s", e)
        return []


# -- Incident War Room (messages & assignment) --------------------------------

def add_incident_message(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    incident_id: int,
    author: str,
    message: str,
    msg_type: str = "comment",
) -> int:
    """Add a message to an incident's war room thread."""
    now = int(time.time())
    try:
        with lock:
            c = conn.execute(
                "INSERT INTO incident_messages (incident_id, author, message, msg_type, created_at) "
                "VALUES (?,?,?,?,?)",
                (incident_id, author, message, msg_type, now),
            )
            conn.commit()
            return c.lastrowid or 0
    except Exception as e:
        logger.error("add_incident_message failed: %s", e)
        return 0


def get_incident_messages(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    incident_id: int,
    limit: int = 200,
) -> list[dict]:
    """Return war room messages for an incident, oldest first."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, incident_id, author, message, msg_type, created_at "
                "FROM incident_messages WHERE incident_id = ? "
                "ORDER BY created_at ASC, id ASC LIMIT ?",
                (incident_id, limit),
            ).fetchall()
        return [
            {"id": r[0], "incident_id": r[1], "author": r[2], "message": r[3],
             "msg_type": r[4], "created_at": r[5]}
            for r in rows
        ]
    except Exception as e:
        logger.error("get_incident_messages failed: %s", e)
        return []


def assign_incident(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    incident_id: int,
    assigned_to: str,
) -> bool:
    """Assign a status incident to a user."""
    try:
        with lock:
            cur = conn.execute(
                "UPDATE status_incidents SET assigned_to = ? WHERE id = ?",
                (assigned_to, incident_id),
            )
            conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("assign_incident failed: %s", e)
        return False


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS status_components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            group_name TEXT DEFAULT 'Default',
            service_key TEXT,
            display_order INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS status_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            severity TEXT DEFAULT 'minor',
            status TEXT DEFAULT 'investigating',
            created_at INTEGER,
            resolved_at INTEGER,
            created_by TEXT,
            assigned_to TEXT
        );

        CREATE TABLE IF NOT EXISTS status_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER NOT NULL REFERENCES status_incidents(id),
            message TEXT NOT NULL,
            status TEXT DEFAULT 'investigating',
            created_at INTEGER,
            created_by TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_status_updates_incident
            ON status_updates(incident_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS incident_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER NOT NULL,
            author TEXT NOT NULL,
            message TEXT NOT NULL,
            msg_type TEXT DEFAULT 'comment',
            created_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_incident_messages_incident
            ON incident_messages(incident_id, created_at ASC);
    """)


class _StatusPageMixin:
    def create_status_component(self, name: str, group_name: str = "Default",
                                service_key: str | None = None,
                                display_order: int = 0) -> int:
        return create_status_component(self._get_conn(), self._lock, name,
                                       group_name=group_name, service_key=service_key,
                                       display_order=display_order)

    def list_status_components(self) -> list[dict]:
        return list_status_components(self._get_read_conn(), self._read_lock)

    def update_status_component(self, comp_id: int, **kwargs) -> bool:
        return update_status_component(self._get_conn(), self._lock, comp_id, **kwargs)

    def delete_status_component(self, comp_id: int) -> bool:
        return delete_status_component(self._get_conn(), self._lock, comp_id)

    def create_status_incident(self, title: str, severity: str = "minor",
                               message: str = "", created_by: str = "") -> int:
        return create_status_incident(self._get_conn(), self._lock, title,
                                      severity=severity, message=message,
                                      created_by=created_by)

    def list_status_incidents(self, limit: int = 50,
                              include_resolved: bool = True) -> list[dict]:
        return list_status_incidents(self._get_read_conn(), self._read_lock, limit=limit,
                                     include_resolved=include_resolved)

    def get_status_incident(self, incident_id: int) -> dict | None:
        return get_status_incident(self._get_read_conn(), self._read_lock, incident_id)

    def update_status_incident(self, incident_id: int, **kwargs) -> bool:
        return update_status_incident(self._get_conn(), self._lock, incident_id, **kwargs)

    def add_status_update(self, incident_id: int, message: str,
                          status: str = "investigating",
                          created_by: str = "") -> int:
        return add_status_update(self._get_conn(), self._lock, incident_id,
                                 message, status=status, created_by=created_by)

    def resolve_status_incident(self, incident_id: int,
                                created_by: str = "") -> bool:
        return resolve_status_incident(self._get_conn(), self._lock, incident_id,
                                       created_by=created_by)

    def get_status_uptime_history(self, days: int = 90) -> list[dict]:
        return get_status_uptime_history(self._get_read_conn(), self._read_lock, days=days)

    def add_incident_message(self, incident_id: int, author: str,
                             message: str, msg_type: str = "comment") -> int:
        return add_incident_message(self._get_conn(), self._lock, incident_id,
                                    author, message, msg_type=msg_type)

    def get_incident_messages(self, incident_id: int,
                              limit: int = 200) -> list[dict]:
        return get_incident_messages(self._get_read_conn(), self._read_lock, incident_id,
                                     limit=limit)

    def assign_incident(self, incident_id: int, assigned_to: str) -> bool:
        return assign_incident(self._get_conn(), self._lock, incident_id,
                               assigned_to)
