# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Custom dashboard CRUD persistence."""
from __future__ import annotations

import logging
import time
import sqlite3

logger = logging.getLogger("noba")


def create_dashboard(conn, lock, name: str, owner: str,
                     config_json: str, *, shared: bool = False) -> int | None:
    """Insert a new custom dashboard and return its id."""
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "INSERT INTO custom_dashboards "
                "(name, owner, config_json, shared, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (name, owner, config_json, 1 if shared else 0, now, now),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error("create_dashboard failed: %s", e)
        return None


def get_dashboards(conn, lock, owner: str | None = None) -> list[dict]:
    """Return dashboards visible to *owner* (own + shared), or all if owner is None."""
    try:
        if owner is None:
            clause = ""
            params: tuple = ()
        else:
            clause = " WHERE owner = ? OR shared = 1"
            params = (owner,)
        with lock:
            rows = conn.execute(
                "SELECT id, name, owner, config_json, shared, created_at, updated_at "
                f"FROM custom_dashboards{clause} ORDER BY name",
                params,
            ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "owner": r[2],
                "config_json": r[3], "shared": bool(r[4]),
                "created_at": r[5], "updated_at": r[6],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("get_dashboards failed: %s", e)
        return []


def get_dashboard(conn, lock, dashboard_id: int) -> dict | None:
    """Return a single dashboard by id."""
    try:
        with lock:
            row = conn.execute(
                "SELECT id, name, owner, config_json, shared, created_at, updated_at "
                "FROM custom_dashboards WHERE id = ?",
                (dashboard_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "name": row[1], "owner": row[2],
            "config_json": row[3], "shared": bool(row[4]),
            "created_at": row[5], "updated_at": row[6],
        }
    except Exception as e:
        logger.error("get_dashboard failed: %s", e)
        return None


def update_dashboard(conn, lock, dashboard_id: int, **kwargs) -> bool:
    """Update fields on an existing dashboard."""
    allowed = {"name", "config_json", "shared"}
    sets = []
    vals: list = []
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        if k == "shared":
            v = 1 if v else 0
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return False
    sets.append("updated_at = ?")
    vals.append(int(time.time()))
    vals.append(dashboard_id)
    try:
        with lock:
            cur = conn.execute(
                f"UPDATE custom_dashboards SET {', '.join(sets)} WHERE id = ?",
                vals,
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error("update_dashboard failed: %s", e)
        return False


def delete_dashboard(conn, lock, dashboard_id: int) -> bool:
    """Delete a custom dashboard."""
    try:
        with lock:
            cur = conn.execute(
                "DELETE FROM custom_dashboards WHERE id = ?", (dashboard_id,)
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_dashboard failed: %s", e)
        return False



def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS custom_dashboards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            owner TEXT NOT NULL,
            config_json TEXT NOT NULL,
            shared INTEGER DEFAULT 0,
            created_at INTEGER,
            updated_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_custom_dashboards_owner
            ON custom_dashboards(owner);
    """)


class _DashboardsMixin:
    def create_dashboard(self, name: str, owner: str, config_json: str,
                         *, shared: bool = False) -> int | None:
        return create_dashboard(self._get_conn(), self._lock, name, owner,
                                config_json, shared=shared)

    def get_dashboards(self, owner: str | None = None) -> list[dict]:
        return get_dashboards(self._get_read_conn(), self._read_lock, owner=owner)

    def get_dashboard(self, dashboard_id: int) -> dict | None:
        return get_dashboard(self._get_read_conn(), self._read_lock, dashboard_id)

    def update_dashboard(self, dashboard_id: int, **kwargs) -> bool:
        return update_dashboard(self._get_conn(), self._lock, dashboard_id, **kwargs)

    def delete_dashboard(self, dashboard_id: int) -> bool:
        return delete_dashboard(self._get_conn(), self._lock, dashboard_id)
