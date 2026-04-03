# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Service dependency CRUD and impact analysis."""
from __future__ import annotations

import logging
import time
import sqlite3

logger = logging.getLogger("noba")


def create_dependency(conn, lock, source: str, target: str, *,
                      dependency_type: str = "requires",
                      auto_discovered: bool = False) -> int | None:
    """Insert a new service dependency and return its id."""
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "INSERT INTO service_dependencies "
                "(source_service, target_service, dependency_type, "
                " auto_discovered, created_at) "
                "VALUES (?,?,?,?,?)",
                (source, target, dependency_type,
                 1 if auto_discovered else 0, now),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error("create_dependency failed: %s", e)
        return None


def list_dependencies(conn, lock) -> list[dict]:
    """Return all service dependencies."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, source_service, target_service, dependency_type, "
                "auto_discovered, created_at "
                "FROM service_dependencies ORDER BY source_service, target_service"
            ).fetchall()
        return [
            {
                "id": r[0], "source_service": r[1], "target_service": r[2],
                "dependency_type": r[3], "auto_discovered": bool(r[4]),
                "created_at": r[5],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("list_dependencies failed: %s", e)
        return []


def delete_dependency(conn, lock, dep_id: int) -> bool:
    """Delete a service dependency."""
    try:
        with lock:
            cur = conn.execute(
                "DELETE FROM service_dependencies WHERE id = ?", (dep_id,)
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_dependency failed: %s", e)
        return False


def get_impact_analysis(conn, lock, service_name: str) -> list[str]:
    """Return all services transitively dependent on *service_name*.

    Walks the dependency graph: if A requires B and B requires C, then
    asking for the impact of C returns [B, A] -- everything that would
    break if C goes down.
    """
    try:
        with lock:
            rows = conn.execute(
                "SELECT source_service, target_service FROM service_dependencies"
            ).fetchall()

        # Build reverse adjacency: target -> set of sources that depend on it
        reverse: dict[str, set[str]] = {}
        for src, tgt in rows:
            reverse.setdefault(tgt, set()).add(src)

        # BFS from service_name through the reverse graph
        visited: set[str] = set()
        queue = [service_name]
        while queue:
            current = queue.pop(0)
            for dependent in reverse.get(current, set()):
                if dependent not in visited:
                    visited.add(dependent)
                    queue.append(dependent)

        return sorted(visited)
    except Exception as e:
        logger.error("get_impact_analysis failed: %s", e)
        return []



def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS service_dependencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_service TEXT NOT NULL,
            target_service TEXT NOT NULL,
            dependency_type TEXT DEFAULT 'requires',
            auto_discovered INTEGER DEFAULT 0,
            created_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_svc_deps_source
            ON service_dependencies(source_service);
        CREATE INDEX IF NOT EXISTS idx_svc_deps_target
            ON service_dependencies(target_service);
    """)


class _DependenciesMixin:
    def create_dependency(self, source: str, target: str, *,
                          dependency_type: str = "requires",
                          auto_discovered: bool = False) -> int | None:
        return create_dependency(self._get_conn(), self._lock, source, target,
                                 dependency_type=dependency_type,
                                 auto_discovered=auto_discovered)

    def list_dependencies(self) -> list[dict]:
        return list_dependencies(self._get_read_conn(), self._read_lock)

    def delete_dependency(self, dep_id: int) -> bool:
        return delete_dependency(self._get_conn(), self._lock, dep_id)

    def get_impact_analysis(self, service_name: str) -> list[str]:
        return get_impact_analysis(self._get_read_conn(), self._read_lock, service_name)
