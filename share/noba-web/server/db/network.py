# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Network device discovery persistence."""
from __future__ import annotations

import json
import logging
import time
import sqlite3

logger = logging.getLogger("noba")


def upsert_device(conn, lock, ip: str, mac: str | None = None,
                  hostname: str | None = None, vendor: str | None = None,
                  open_ports: list[int] | None = None,
                  discovered_by: str | None = None) -> int | None:
    """Insert or update a discovered network device. Returns the row id."""
    now = int(time.time())
    ports_json = json.dumps(sorted(open_ports)) if open_ports else "[]"
    try:
        with lock:
            existing = conn.execute(
                "SELECT id, first_seen FROM network_devices WHERE ip = ? AND mac = ?",
                (ip, mac or ""),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE network_devices SET hostname = COALESCE(?, hostname), "
                    "vendor = COALESCE(?, vendor), open_ports = ?, "
                    "discovered_by = COALESCE(?, discovered_by), last_seen = ? "
                    "WHERE id = ?",
                    (hostname, vendor, ports_json, discovered_by, now, existing[0]),
                )
                conn.commit()
                return existing[0]
            else:
                cur = conn.execute(
                    "INSERT INTO network_devices "
                    "(ip, mac, hostname, vendor, open_ports, discovered_by, first_seen, last_seen) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (ip, mac or "", hostname, vendor, ports_json, discovered_by, now, now),
                )
                conn.commit()
                return cur.lastrowid
    except Exception as e:
        logger.error("upsert_device failed: %s", e)
        return None


def list_devices(conn, lock) -> list[dict]:
    """Return all discovered network devices."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, ip, mac, hostname, vendor, open_ports, "
                "discovered_by, first_seen, last_seen "
                "FROM network_devices ORDER BY last_seen DESC"
            ).fetchall()
        return [
            {
                "id": r[0], "ip": r[1], "mac": r[2], "hostname": r[3],
                "vendor": r[4],
                "open_ports": json.loads(r[5]) if r[5] else [],
                "discovered_by": r[6], "first_seen": r[7], "last_seen": r[8],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("list_devices failed: %s", e)
        return []


def get_device(conn, lock, device_id: int) -> dict | None:
    """Return a single network device by id."""
    try:
        with lock:
            row = conn.execute(
                "SELECT id, ip, mac, hostname, vendor, open_ports, "
                "discovered_by, first_seen, last_seen "
                "FROM network_devices WHERE id = ?",
                (device_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "ip": row[1], "mac": row[2], "hostname": row[3],
            "vendor": row[4],
            "open_ports": json.loads(row[5]) if row[5] else [],
            "discovered_by": row[6], "first_seen": row[7], "last_seen": row[8],
        }
    except Exception as e:
        logger.error("get_device failed: %s", e)
        return None


def delete_device(conn, lock, device_id: int) -> bool:
    """Remove a network device by id. Returns True if a row was deleted."""
    try:
        with lock:
            cur = conn.execute(
                "DELETE FROM network_devices WHERE id = ?", (device_id,)
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_device failed: %s", e)
        return False



def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS network_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            mac TEXT,
            hostname TEXT,
            vendor TEXT,
            open_ports TEXT,
            discovered_by TEXT,
            first_seen INTEGER,
            last_seen INTEGER,
            UNIQUE(ip, mac)
        );
        CREATE INDEX IF NOT EXISTS idx_network_devices_ip
            ON network_devices(ip);
    """)
