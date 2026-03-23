"""Noba – DB functions for integration instances, groups, and capability manifests."""
from __future__ import annotations

import json
import sqlite3
import threading
import time


# ── Table Creation ─────────────────────────────────────────────────────────────

def create_tables(conn: sqlite3.Connection) -> None:
    """Create integration-related tables (idempotent)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS integration_instances (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            platform TEXT NOT NULL,
            url TEXT,
            auth_config TEXT NOT NULL,
            site TEXT,
            tags TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            health_status TEXT DEFAULT 'unknown',
            last_seen INTEGER,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS integration_groups (
            group_name TEXT NOT NULL,
            instance_id TEXT NOT NULL REFERENCES integration_instances(id),
            PRIMARY KEY (group_name, instance_id)
        );

        CREATE TABLE IF NOT EXISTS capability_manifests (
            hostname TEXT PRIMARY KEY,
            manifest TEXT NOT NULL,
            probed_at INTEGER NOT NULL,
            degraded_capabilities TEXT DEFAULT '[]'
        );
    """)


# ── Integration Instances ──────────────────────────────────────────────────────

def insert_instance(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    *,
    id: str,
    category: str,
    platform: str,
    url: str | None = None,
    auth_config: str,
    site: str | None = None,
    tags: str | None = None,
) -> None:
    """Insert a new integration instance."""
    now = int(time.time())
    with lock:
        conn.execute(
            """
            INSERT INTO integration_instances
                (id, category, platform, url, auth_config, site, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (id, category, platform, url, auth_config, site, tags, now),
        )
        conn.commit()


def get_instance(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    instance_id: str,
) -> dict | None:
    """Return an integration instance by id, or None if not found."""
    with lock:
        cur = conn.execute(
            "SELECT * FROM integration_instances WHERE id = ?", (instance_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def list_instances(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    *,
    category: str | None = None,
    site: str | None = None,
) -> list[dict]:
    """Return integration instances, optionally filtered by category and/or site."""
    clauses: list[str] = []
    args: list = []
    if category is not None:
        clauses.append("category = ?")
        args.append(category)
    if site is not None:
        clauses.append("site = ?")
        args.append(site)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with lock:
        cur = conn.execute(
            f"SELECT * FROM integration_instances {where} ORDER BY id", args
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def update_health(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    instance_id: str,
    health_status: str,
) -> None:
    """Update health_status and last_seen timestamp for an instance."""
    now = int(time.time())
    with lock:
        conn.execute(
            "UPDATE integration_instances SET health_status = ?, last_seen = ? WHERE id = ?",
            (health_status, now, instance_id),
        )
        conn.commit()


def delete_instance(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    instance_id: str,
) -> None:
    """Delete an integration instance by id."""
    with lock:
        conn.execute(
            "DELETE FROM integration_instances WHERE id = ?", (instance_id,)
        )
        conn.commit()


# ── Integration Groups ─────────────────────────────────────────────────────────

def add_to_group(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    group_name: str,
    instance_id: str,
) -> None:
    """Add an instance to a named group (idempotent)."""
    with lock:
        conn.execute(
            "INSERT OR IGNORE INTO integration_groups (group_name, instance_id) VALUES (?, ?)",
            (group_name, instance_id),
        )
        conn.commit()


def remove_from_group(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    group_name: str,
    instance_id: str,
) -> None:
    """Remove an instance from a named group."""
    with lock:
        conn.execute(
            "DELETE FROM integration_groups WHERE group_name = ? AND instance_id = ?",
            (group_name, instance_id),
        )
        conn.commit()


def list_group(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    group_name: str,
) -> list[dict]:
    """Return all integration instance dicts that belong to the given group."""
    with lock:
        cur = conn.execute(
            """
            SELECT i.* FROM integration_instances i
            JOIN integration_groups g ON g.instance_id = i.id
            WHERE g.group_name = ?
            ORDER BY i.id
            """,
            (group_name,),
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def list_groups(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> list[str]:
    """Return distinct group name strings."""
    with lock:
        rows = conn.execute(
            "SELECT DISTINCT group_name FROM integration_groups ORDER BY group_name"
        ).fetchall()
    return [row[0] for row in rows]


# ── Capability Manifests ───────────────────────────────────────────────────────

def upsert_manifest(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    hostname: str,
    manifest: str,
) -> None:
    """Insert or replace a capability manifest for a hostname."""
    now = int(time.time())
    with lock:
        conn.execute(
            """
            INSERT INTO capability_manifests (hostname, manifest, probed_at, degraded_capabilities)
            VALUES (?, ?, ?, '[]')
            ON CONFLICT(hostname) DO UPDATE SET
                manifest = excluded.manifest,
                probed_at = excluded.probed_at
            """,
            (hostname, manifest, now),
        )
        conn.commit()


def get_manifest(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    hostname: str,
) -> dict | None:
    """Return capability manifest dict for a hostname, or None if not found."""
    with lock:
        cur = conn.execute(
            "SELECT * FROM capability_manifests WHERE hostname = ?", (hostname,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def mark_capability_degraded(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    hostname: str,
    tool_name: str,
) -> None:
    """Append tool_name to degraded_capabilities JSON list for the hostname."""
    with lock:
        row = conn.execute(
            "SELECT degraded_capabilities FROM capability_manifests WHERE hostname = ?",
            (hostname,),
        ).fetchone()
        if row is None:
            return
        current: list = json.loads(row[0] or "[]")
        if tool_name not in current:
            current.append(tool_name)
        conn.execute(
            "UPDATE capability_manifests SET degraded_capabilities = ? WHERE hostname = ?",
            (json.dumps(current), hostname),
        )
        conn.commit()


# ── Dependency Graph ───────────────────────────────────────────────────────────

def insert_dependency(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    *,
    target: str,
    node_type: str,
    depends_on: str | None = None,
    health_check: str | None = None,
    site: str | None = None,
    auto_discovered: bool = False,
    confirmed: bool = False,
) -> None:
    """Insert a dependency graph node."""
    now = int(time.time())
    with lock:
        conn.execute(
            """
            INSERT INTO dependency_graph
                (target, node_type, depends_on, health_check, site,
                 auto_discovered, confirmed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (target, node_type, depends_on, health_check, site,
             int(auto_discovered), int(confirmed), now),
        )
        conn.commit()


def list_dependencies(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> list[dict]:
    """List all dependency graph nodes."""
    with lock:
        cur = conn.execute("SELECT * FROM dependency_graph ORDER BY target")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def get_dependency(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    target: str,
) -> dict | None:
    """Get a single dependency node by target."""
    with lock:
        cur = conn.execute(
            "SELECT * FROM dependency_graph WHERE target = ?", (target,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def delete_dependency(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    target: str,
) -> None:
    """Delete a dependency node."""
    with lock:
        conn.execute(
            "DELETE FROM dependency_graph WHERE target = ?", (target,)
        )
        conn.commit()


def upsert_dependency(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    *,
    target: str,
    node_type: str,
    depends_on: str | None = None,
    health_check: str | None = None,
    site: str | None = None,
    auto_discovered: bool = False,
    confirmed: bool = False,
) -> None:
    """Insert or update a dependency node."""
    now = int(time.time())
    with lock:
        conn.execute(
            """
            INSERT INTO dependency_graph
                (target, node_type, depends_on, health_check, site,
                 auto_discovered, confirmed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(target) DO UPDATE SET
                node_type        = excluded.node_type,
                depends_on       = excluded.depends_on,
                health_check     = excluded.health_check,
                site             = excluded.site,
                auto_discovered  = excluded.auto_discovered,
                confirmed        = excluded.confirmed
            """,
            (target, node_type, depends_on, health_check, site,
             int(auto_discovered), int(confirmed), now),
        )
        conn.commit()


# ── Heal Maintenance Windows ───────────────────────────────────────────────────

def insert_heal_maintenance_window(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    *,
    target: str,
    duration_s: int,
    reason: str | None = None,
    action: str = "suppress",
    cron_expr: str | None = None,
    created_by: str | None = None,
) -> int:
    """Insert a heal maintenance window and return its id."""
    now = int(time.time())
    expires_at = now + duration_s if cron_expr is None else None
    with lock:
        cur = conn.execute(
            """
            INSERT INTO heal_maintenance_windows
                (target, cron_expr, duration_s, reason, action, active, created_by,
                 created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (target, cron_expr, duration_s, reason, action, created_by, now, expires_at),
        )
        conn.commit()
        return cur.lastrowid


def get_active_heal_maintenance_windows(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> list[dict]:
    """Return all active, non-expired heal maintenance windows."""
    now = int(time.time())
    with lock:
        cur = conn.execute(
            """
            SELECT * FROM heal_maintenance_windows
            WHERE active = 1
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY created_at DESC
            """,
            (now,),
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def end_heal_maintenance_window(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    window_id: int,
) -> bool:
    """Deactivate a heal maintenance window early. Return True if found."""
    with lock:
        cur = conn.execute(
            "UPDATE heal_maintenance_windows SET active = 0 WHERE id = ?",
            (window_id,),
        )
        conn.commit()
    return cur.rowcount > 0


# ── Heal Snapshots ─────────────────────────────────────────────────────────────

def insert_snapshot(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    *,
    ledger_id: int | None,
    target: str,
    action_type: str,
    state: str,
) -> int:
    """Store a pre-heal state snapshot and return its id."""
    now = int(time.time())
    with lock:
        cur = conn.execute(
            """
            INSERT INTO heal_snapshots (ledger_id, target, action_type, state, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ledger_id, target, action_type, state, now),
        )
        conn.commit()
        return cur.lastrowid


def get_snapshot_row(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    snap_id: int,
) -> dict | None:
    """Return a snapshot by its primary key, or None if not found."""
    with lock:
        cur = conn.execute(
            "SELECT * FROM heal_snapshots WHERE id = ?", (snap_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def get_snapshot_by_ledger_id(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    ledger_id: int,
) -> dict | None:
    """Return the most recent snapshot for a given ledger row id, or None."""
    with lock:
        cur = conn.execute(
            "SELECT * FROM heal_snapshots WHERE ledger_id = ? ORDER BY id DESC LIMIT 1",
            (ledger_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))
