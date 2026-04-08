# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Security posture scoring persistence."""
from __future__ import annotations

import json
import sqlite3
import time


def record_scan(conn, lock, hostname: str, score: int, findings: list[dict]) -> int | None:
    """Record a completed security scan (score + findings).

    Inserts into ``security_scores`` (aggregate row) and
    ``security_findings`` (one row per finding).
    Returns the ``security_scores`` row id.
    """
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "INSERT INTO security_scores (hostname, score, scanned_at, findings_json) "
                "VALUES (?, ?, ?, ?)",
                (hostname, score, now, json.dumps(findings)),
            )
            score_id = cur.lastrowid
            # Replace old findings for this host (prevents duplicates on re-scan)
            conn.execute(
                "DELETE FROM security_findings WHERE hostname = ?",
                (hostname,),
            )
            for f in findings:
                conn.execute(
                    "INSERT INTO security_findings "
                    "(hostname, category, severity, description, remediation, score, found_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        hostname,
                        f.get("category", ""),
                        f.get("severity", "low"),
                        f.get("description", ""),
                        f.get("remediation", ""),
                        score,
                        now,
                    ),
                )
            conn.commit()
            return score_id
    except Exception:
        return None


def get_latest_scores(conn, lock) -> list[dict]:
    """Return the most-recent security score for every hostname."""
    sql = (
        "SELECT s.hostname, s.score, s.scanned_at, s.findings_json "
        "FROM security_scores s "
        "INNER JOIN ("
        "  SELECT hostname, MAX(id) AS latest_id "
        "  FROM security_scores GROUP BY hostname"
        ") g ON s.id = g.latest_id "
        "ORDER BY s.hostname"
    )
    with lock:
        rows = conn.execute(sql).fetchall()
    return [
        {
            "hostname": r[0],
            "score": r[1],
            "scanned_at": r[2],
            "findings": json.loads(r[3]) if r[3] else [],
        }
        for r in rows
    ]


def get_findings(
    conn,
    lock,
    hostname: str | None = None,
    severity: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Return security findings, optionally filtered by hostname/severity."""
    clauses: list[str] = []
    params: list = []
    if hostname:
        clauses.append("hostname = ?")
        params.append(hostname)
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with lock:
        rows = conn.execute(
            "SELECT id, hostname, category, severity, description, "
            "remediation, score, found_at, resolved_at "
            f"FROM security_findings{where} "
            "ORDER BY found_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [
        {
            "id": r[0],
            "hostname": r[1],
            "category": r[2],
            "severity": r[3],
            "description": r[4],
            "remediation": r[5],
            "score": r[6],
            "found_at": r[7],
            "resolved_at": r[8],
        }
        for r in rows
    ]


def get_aggregate_score(conn, lock) -> dict:
    """Return the aggregate security score across all agents.

    The aggregate is the average of the latest per-host scores.
    """
    scores = get_latest_scores(conn, lock)
    if not scores:
        return {"score": None, "agent_count": 0, "agents": []}
    total = sum(s["score"] for s in scores)
    return {
        "score": round(total / len(scores)),
        "agent_count": len(scores),
        "agents": scores,
    }


def get_score_history(conn, lock, hostname: str | None = None,
                      limit: int = 50) -> list[dict]:
    """Return historical security scores for charting."""
    if hostname:
        sql = ("SELECT hostname, score, scanned_at FROM security_scores "
               "WHERE hostname = ? ORDER BY scanned_at DESC LIMIT ?")
        params: list = [hostname, limit]
    else:
        sql = ("SELECT hostname, score, scanned_at FROM security_scores "
               "ORDER BY scanned_at DESC LIMIT ?")
        params = [limit]
    with lock:
        rows = conn.execute(sql, params).fetchall()
    return [{"hostname": r[0], "score": r[1], "scanned_at": r[2]} for r in rows]



def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS security_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT NOT NULL,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            description TEXT NOT NULL,
            remediation TEXT,
            score INTEGER,
            found_at INTEGER,
            resolved_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_sec_findings_host
            ON security_findings(hostname, found_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sec_findings_sev
            ON security_findings(severity);

        CREATE TABLE IF NOT EXISTS security_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT NOT NULL,
            score INTEGER NOT NULL,
            scanned_at INTEGER,
            findings_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sec_scores_host
            ON security_scores(hostname, scanned_at DESC);
    """)


class _SecurityMixin:
    def record_security_scan(self, hostname: str, score: int,
                             findings: list[dict]) -> int | None:
        return record_scan(self._get_conn(), self._lock, hostname, score, findings)

    def get_security_scores(self) -> list[dict]:
        return get_latest_scores(self._get_read_conn(), self._read_lock)

    def get_security_findings(self, hostname: str | None = None,
                              severity: str | None = None,
                              limit: int = 200) -> list[dict]:
        return get_findings(self._get_read_conn(), self._read_lock,
                            hostname=hostname, severity=severity, limit=limit)

    def get_aggregate_security_score(self) -> dict:
        return get_aggregate_score(self._get_read_conn(), self._read_lock)

    def get_security_score_history(self, hostname: str | None = None,
                                   limit: int = 50) -> list[dict]:
        return get_score_history(self._get_read_conn(), self._read_lock,
                                 hostname=hostname, limit=limit)
