# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Configuration baseline CRUD and drift check persistence."""
from __future__ import annotations

import logging
import sqlite3
import time

logger = logging.getLogger("noba")


def create_baseline(conn, lock, path: str, expected_hash: str,
                    agent_group: str = "__all__") -> int | None:
    """Insert a new config baseline and return its id."""
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "INSERT INTO config_baselines "
                "(path, expected_hash, agent_group, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (path, expected_hash, agent_group, now, now),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error("create_baseline failed: %s", e)
        return None


def list_baselines(conn, lock) -> list[dict]:
    """Return all config baselines with latest drift summary."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, path, expected_hash, agent_group, created_at, updated_at "
                "FROM config_baselines ORDER BY path"
            ).fetchall()
        baselines = []
        for r in rows:
            bid = r[0]
            # Get latest drift check per baseline
            with lock:
                drift_rows = conn.execute(
                    "SELECT hostname, actual_hash, status, checked_at "
                    "FROM drift_checks WHERE baseline_id = ? "
                    "ORDER BY checked_at DESC, id DESC",
                    (bid,),
                ).fetchall()
            # Deduplicate to latest per hostname
            seen: dict[str, dict] = {}
            for dr in drift_rows:
                h = dr[0]
                if h not in seen:
                    seen[h] = {
                        "hostname": dr[0], "actual_hash": dr[1],
                        "status": dr[2], "checked_at": dr[3],
                    }
            has_drift = any(v["status"] == "drift" for v in seen.values())
            baselines.append({
                "id": bid, "path": r[1], "expected_hash": r[2],
                "agent_group": r[3], "created_at": r[4], "updated_at": r[5],
                "status": "drift" if has_drift else ("match" if seen else "pending"),
                "agent_count": len(seen),
                "drift_count": sum(1 for v in seen.values() if v["status"] == "drift"),
            })
        return baselines
    except Exception as e:
        logger.error("list_baselines failed: %s", e)
        return []


def get_baseline(conn, lock, baseline_id: int) -> dict | None:
    """Return a single baseline by id."""
    try:
        with lock:
            row = conn.execute(
                "SELECT id, path, expected_hash, agent_group, created_at, updated_at "
                "FROM config_baselines WHERE id = ?",
                (baseline_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "path": row[1], "expected_hash": row[2],
            "agent_group": row[3], "created_at": row[4], "updated_at": row[5],
        }
    except Exception as e:
        logger.error("get_baseline failed: %s", e)
        return None


def delete_baseline(conn, lock, baseline_id: int) -> bool:
    """Delete a config baseline and its drift checks."""
    try:
        with lock:
            conn.execute(
                "DELETE FROM drift_checks WHERE baseline_id = ?",
                (baseline_id,),
            )
            cur = conn.execute(
                "DELETE FROM config_baselines WHERE id = ?",
                (baseline_id,),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_baseline failed: %s", e)
        return False


def update_baseline(conn, lock, baseline_id: int,
                    expected_hash: str) -> bool:
    """Update the expected hash of a baseline."""
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "UPDATE config_baselines SET expected_hash = ?, updated_at = ? "
                "WHERE id = ?",
                (expected_hash, now, baseline_id),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error("update_baseline failed: %s", e)
        return False


def record_drift_check(conn, lock, baseline_id: int, hostname: str,
                       actual_hash: str | None, status: str = "match") -> int | None:
    """Record a drift check result for a baseline+hostname pair."""
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "INSERT INTO drift_checks "
                "(baseline_id, hostname, actual_hash, status, checked_at) "
                "VALUES (?,?,?,?,?)",
                (baseline_id, hostname, actual_hash, status, now),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error("record_drift_check failed: %s", e)
        return None


def get_drift_results(conn, lock, baseline_id: int | None = None) -> list[dict]:
    """Return drift check results, optionally filtered by baseline.

    Returns only the latest check per hostname per baseline.
    """
    try:
        if baseline_id is not None:
            clause = " WHERE d.baseline_id = ?"
            params: list = [baseline_id]
        else:
            clause = ""
            params = []
        with lock:
            rows = conn.execute(
                "SELECT d.id, d.baseline_id, d.hostname, d.actual_hash, "
                "d.status, d.checked_at, b.path, b.expected_hash "
                "FROM drift_checks d "
                "JOIN config_baselines b ON d.baseline_id = b.id"
                f"{clause} "
                "ORDER BY d.checked_at DESC, d.id DESC",
                params,
            ).fetchall()
        # Deduplicate to latest per (baseline_id, hostname)
        seen: set[tuple[int, str]] = set()
        results = []
        for r in rows:
            key = (r[1], r[2])
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "id": r[0], "baseline_id": r[1], "hostname": r[2],
                "actual_hash": r[3], "status": r[4], "checked_at": r[5],
                "path": r[6], "expected_hash": r[7],
            })
        return results
    except Exception as e:
        logger.error("get_drift_results failed: %s", e)
        return []



def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS config_baselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            expected_hash TEXT NOT NULL,
            agent_group TEXT DEFAULT '__all__',
            created_at INTEGER,
            updated_at INTEGER
        );

        CREATE TABLE IF NOT EXISTS drift_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            baseline_id INTEGER NOT NULL REFERENCES config_baselines(id),
            hostname TEXT NOT NULL,
            actual_hash TEXT,
            status TEXT DEFAULT 'match',
            checked_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_drift_checks_baseline
            ON drift_checks(baseline_id, checked_at DESC);
        CREATE INDEX IF NOT EXISTS idx_drift_checks_hostname
            ON drift_checks(hostname, checked_at DESC);
    """)


class _BaselinesMixin:
    def create_baseline(self, path: str, expected_hash: str,
                        agent_group: str = "__all__") -> int | None:
        return create_baseline(self._get_conn(), self._lock, path, expected_hash,
                               agent_group=agent_group)

    def list_baselines(self) -> list[dict]:
        return list_baselines(self._get_read_conn(), self._read_lock)

    def get_baseline(self, baseline_id: int) -> dict | None:
        return get_baseline(self._get_read_conn(), self._read_lock, baseline_id)

    def delete_baseline(self, baseline_id: int) -> bool:
        return delete_baseline(self._get_conn(), self._lock, baseline_id)

    def update_baseline(self, baseline_id: int, expected_hash: str) -> bool:
        return update_baseline(self._get_conn(), self._lock, baseline_id, expected_hash)

    def record_drift_check(self, baseline_id: int, hostname: str,
                           actual_hash: str | None, status: str = "match") -> int | None:
        return record_drift_check(self._get_conn(), self._lock, baseline_id,
                                  hostname, actual_hash, status=status)

    def get_drift_results(self, baseline_id: int | None = None) -> list[dict]:
        return get_drift_results(self._get_read_conn(), self._read_lock, baseline_id=baseline_id)
