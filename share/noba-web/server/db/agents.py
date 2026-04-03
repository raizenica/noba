# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Agent registry persistence."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
logger = logging.getLogger("noba")



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



def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_registry (
            hostname      TEXT PRIMARY KEY,
            ip            TEXT,
            platform      TEXT,
            arch          TEXT,
            agent_version TEXT,
            first_seen    INTEGER,
            last_seen     INTEGER,
            config_json   TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS agent_command_history (
            id          TEXT PRIMARY KEY,
            hostname    TEXT NOT NULL,
            cmd_type    TEXT NOT NULL,
            params      TEXT DEFAULT '{}',
            queued_by   TEXT NOT NULL,
            queued_at   INTEGER NOT NULL,
            status      TEXT NOT NULL DEFAULT 'queued',
            result      TEXT,
            finished_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_cmd_hist_host
            ON agent_command_history(hostname, queued_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cmd_hist_status
            ON agent_command_history(status);
    """)




class _AgentsMixin:
    def upsert_agent(self, hostname: str, ip: str, platform_name: str,
                     arch: str, agent_version: str) -> None:
        upsert_agent(self._get_conn(), self._lock, hostname, ip, platform_name, arch, agent_version)

    def get_all_agents(self) -> list[dict]:
        return get_all_agents(self._get_read_conn(), self._read_lock)

    def delete_agent(self, hostname: str) -> None:
        delete_agent(self._get_conn(), self._lock, hostname)

    def update_agent_config(self, hostname: str, config: dict) -> None:
        update_agent_config(self._get_conn(), self._lock, hostname, config)

    def record_command(self, cmd_id: str, hostname: str, cmd_type: str,
                       params: dict, queued_by: str) -> None:
        """Record a newly queued agent command."""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "INSERT OR IGNORE INTO agent_command_history "
                    "(id, hostname, cmd_type, params, queued_by, queued_at, status) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (cmd_id, hostname, cmd_type, json.dumps(params),
                     queued_by, int(time.time()), "queued"),
                )
                conn.commit()
        except Exception as e:
            logger.error("record_command failed: %s", e)

    def complete_command(self, cmd_id: str, result: dict) -> None:
        """Mark a command as completed with its result."""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "UPDATE agent_command_history SET status=?, result=?, finished_at=? "
                    "WHERE id=?",
                    (
                        "ok" if result.get("status") == "ok" else "error",
                        json.dumps(result),
                        int(time.time()),
                        cmd_id,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error("complete_command failed: %s", e)

    def get_command_history(self, hostname: str | None = None,
                            limit: int = 50) -> list[dict]:
        """Return recent command history, optionally filtered by hostname."""
        try:
            clauses: list[str] = []
            params: list = []
            if hostname:
                clauses.append("hostname = ?")
                params.append(hostname)
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            with self._read_lock:
                conn = self._get_read_conn()
                rows = conn.execute(
                    "SELECT id, hostname, cmd_type, params, queued_by, "
                    "queued_at, status, result, finished_at "
                    f"FROM agent_command_history{where} "
                    "ORDER BY queued_at DESC LIMIT ?",
                    params,
                ).fetchall()
            return [
                {
                    "id": r[0], "hostname": r[1], "cmd_type": r[2],
                    "params": json.loads(r[3]) if r[3] else {},
                    "queued_by": r[4], "queued_at": r[5],
                    "status": r[6],
                    "result": json.loads(r[7]) if r[7] else None,
                    "finished_at": r[8],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error("get_command_history failed: %s", e)
            return []
