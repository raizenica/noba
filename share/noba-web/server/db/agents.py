"""Noba – Agent registry persistence."""
from __future__ import annotations

import json
import time


def upsert_agent(conn, lock, hostname, ip, platform_name, arch, agent_version):
    """Insert or update agent in registry."""
    now = int(time.time())
    with lock:
        existing = conn.execute(
            "SELECT first_seen FROM agent_registry WHERE hostname = ?", (hostname,)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE agent_registry
                SET ip = ?, platform = ?, arch = ?, agent_version = ?, last_seen = ?
                WHERE hostname = ?
            """, (ip, platform_name, arch, agent_version, now, hostname))
        else:
            conn.execute("""
                INSERT INTO agent_registry (hostname, ip, platform, arch, agent_version, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (hostname, ip, platform_name, arch, agent_version, now, now))
        conn.commit()


def get_all_agents(conn, lock):
    """Load all agents from registry."""
    with lock:
        rows = conn.execute(
            "SELECT hostname, ip, platform, arch, agent_version, first_seen, last_seen, config_json "
            "FROM agent_registry"
        ).fetchall()
    return [
        {
            "hostname": r[0], "ip": r[1], "platform": r[2], "arch": r[3],
            "agent_version": r[4], "first_seen": r[5], "last_seen": r[6],
            "config": json.loads(r[7] or "{}"),
        }
        for r in rows
    ]


def delete_agent(conn, lock, hostname):
    """Remove agent from registry."""
    with lock:
        conn.execute("DELETE FROM agent_registry WHERE hostname = ?", (hostname,))
        conn.commit()


def update_agent_config(conn, lock, hostname, config):
    """Update per-agent config JSON."""
    with lock:
        conn.execute(
            "UPDATE agent_registry SET config_json = ? WHERE hostname = ?",
            (json.dumps(config), hostname),
        )
        conn.commit()
