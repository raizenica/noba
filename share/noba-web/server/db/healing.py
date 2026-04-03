# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – DB functions for the self-healing pipeline (ledger, trust, suggestions)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time


# ── Heal Ledger ───────────────────────────────────────────────────────────────

def insert_heal_outcome(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    *,
    correlation_key: str | None = None,
    rule_id: str | None = None,
    condition: str | None = None,
    target: str | None = None,
    action_type: str | None = None,
    action_params: dict | None = None,
    escalation_step: int = 0,
    action_success: bool | None = None,
    verified: bool = False,
    duration_s: float | None = None,
    metrics_before: dict | None = None,
    metrics_after: dict | None = None,
    trust_level: str | None = None,
    source: str | None = None,
    approval_id: int | None = None,
    # Extended audit trail fields
    risk_level: str | None = None,
    snapshot_id: int | None = None,
    rollback_status: str | None = None,
    dependency_root: str | None = None,
    suppressed_by: str | None = None,
    maintenance_window_id: int | None = None,
    instance_id: str | None = None,
) -> int:
    """Insert a heal outcome record and return its row id."""
    now = int(time.time())
    params = (
        correlation_key,
        rule_id,
        condition,
        target,
        action_type,
        json.dumps(action_params) if action_params is not None else None,
        escalation_step,
        (1 if action_success else 0) if action_success is not None else None,
        1 if verified else 0,
        duration_s,
        json.dumps(metrics_before) if metrics_before is not None else None,
        json.dumps(metrics_after) if metrics_after is not None else None,
        trust_level,
        source,
        approval_id,
        now,
        risk_level,
        snapshot_id,
        rollback_status,
        dependency_root,
        suppressed_by,
        maintenance_window_id,
        instance_id,
    )
    with lock:
        cur = conn.execute(
            """
            INSERT INTO heal_ledger
                (correlation_key, rule_id, condition, target,
                 action_type, action_params, escalation_step,
                 action_success, verified, duration_s,
                 metrics_before, metrics_after, trust_level,
                 source, approval_id, created_at,
                 risk_level, snapshot_id, rollback_status,
                 dependency_root, suppressed_by, maintenance_window_id,
                 instance_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            params,
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def get_heal_outcomes(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    *,
    limit: int = 50,
    rule_id: str | None = None,
    target: str | None = None,
) -> list[dict]:
    """Return heal outcome records, optionally filtered by rule_id / target."""
    clauses: list[str] = []
    args: list = []
    if rule_id is not None:
        clauses.append("rule_id = ?")
        args.append(rule_id)
    if target is not None:
        clauses.append("target = ?")
        args.append(target)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    args.append(limit)
    with lock:
        rows = conn.execute(
            f"SELECT * FROM heal_ledger {where} ORDER BY created_at DESC LIMIT ?",
            args,
        ).fetchall()
        if not rows:
            return []
        cols = [d[0] for d in conn.execute(
            "SELECT * FROM heal_ledger LIMIT 0"
        ).description]
    return [dict(zip(cols, row)) for row in rows]


def get_heal_success_rate(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    action_type: str,
    condition: str,
    *,
    target: str | None = None,
    window_hours: int = 720,
) -> float:
    """Return success rate (0.0–100.0) for a given action_type+condition pair."""
    cutoff = int(time.time()) - window_hours * 3600
    clauses = ["action_type = ?", "condition = ?", "created_at >= ?",
                "action_success IS NOT NULL"]
    args: list = [action_type, condition, cutoff]
    if target is not None:
        clauses.append("target = ?")
        args.append(target)
    where = "WHERE " + " AND ".join(clauses)
    with lock:
        row = conn.execute(
            f"SELECT COUNT(*), SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END) "
            f"FROM heal_ledger {where}",
            args,
        ).fetchone()
    total, successes = row
    if not total:
        return 0.0
    return round((successes or 0) / total * 100.0, 2)


def get_mean_time_to_resolve(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    condition: str,
    *,
    target: str | None = None,
    window_hours: int = 720,
) -> float | None:
    """Return mean duration_s for verified=1 outcomes, or None if no data."""
    cutoff = int(time.time()) - window_hours * 3600
    clauses = ["condition = ?", "verified = 1", "duration_s IS NOT NULL",
                "created_at >= ?"]
    args: list = [condition, cutoff]
    if target is not None:
        clauses.append("target = ?")
        args.append(target)
    where = "WHERE " + " AND ".join(clauses)
    with lock:
        row = conn.execute(
            f"SELECT AVG(duration_s) FROM heal_ledger {where}", args
        ).fetchone()
    val = row[0] if row else None
    return float(val) if val is not None else None


def get_escalation_frequency(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    rule_id: str,
    *,
    window_hours: int = 720,
) -> dict:
    """Return per-escalation_step counts for a rule_id within the window."""
    cutoff = int(time.time()) - window_hours * 3600
    with lock:
        rows = conn.execute(
            "SELECT escalation_step, COUNT(*) FROM heal_ledger "
            "WHERE rule_id = ? AND created_at >= ? "
            "GROUP BY escalation_step",
            (rule_id, cutoff),
        ).fetchall()
    return {row[0]: row[1] for row in rows}


# ── Trust State ───────────────────────────────────────────────────────────────

def upsert_trust_state(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    rule_id: str,
    current_level: str,
    ceiling: str,
) -> None:
    """Insert or update trust state; track promotions/demotions."""
    now = int(time.time())
    _LEVELS = ["notify", "approve", "execute"]

    with lock:
        existing = conn.execute(
            "SELECT current_level, promotion_count, demotion_count "
            "FROM trust_state WHERE rule_id = ?",
            (rule_id,),
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO trust_state
                    (rule_id, current_level, ceiling, promoted_at, demoted_at,
                     promotion_count, demotion_count, last_evaluated)
                VALUES (?, ?, ?, NULL, NULL, 0, 0, ?)
                """,
                (rule_id, current_level, ceiling, now),
            )
        else:
            old_level, promo_count, demo_count = existing
            new_promo = promo_count
            new_demo = demo_count

            old_idx = _LEVELS.index(old_level) if old_level in _LEVELS else -1
            new_idx = _LEVELS.index(current_level) if current_level in _LEVELS else -1

            if old_level != current_level:
                if new_idx > old_idx:
                    new_promo += 1
                    conn.execute(
                        """
                        UPDATE trust_state
                        SET current_level = ?, ceiling = ?,
                            promoted_at = ?, last_evaluated = ?,
                            promotion_count = ?
                        WHERE rule_id = ?
                        """,
                        (current_level, ceiling, now, now, new_promo, rule_id),
                    )
                else:
                    new_demo += 1
                    conn.execute(
                        """
                        UPDATE trust_state
                        SET current_level = ?, ceiling = ?,
                            demoted_at = ?, last_evaluated = ?,
                            demotion_count = ?
                        WHERE rule_id = ?
                        """,
                        (current_level, ceiling, now, now, new_demo, rule_id),
                    )
            else:
                conn.execute(
                    """
                    UPDATE trust_state
                    SET ceiling = ?, last_evaluated = ?
                    WHERE rule_id = ?
                    """,
                    (ceiling, now, rule_id),
                )
        conn.commit()


def get_trust_state(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    rule_id: str,
) -> dict | None:
    """Return trust state for a rule or None if not found."""
    with lock:
        cur = conn.execute(
            "SELECT * FROM trust_state WHERE rule_id = ?", (rule_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def list_trust_states(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> list[dict]:
    """Return all trust state records."""
    with lock:
        cur = conn.execute("SELECT * FROM trust_state ORDER BY rule_id")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


# ── Heal Suggestions ──────────────────────────────────────────────────────────

def insert_heal_suggestion(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    *,
    category: str,
    severity: str,
    message: str,
    rule_id: str | None = None,
    suggested_action: str | None = None,
    evidence: dict | None = None,
) -> int:
    """Insert or replace a heal suggestion (dedup by category+rule_id)."""
    now = int(time.time())
    with lock:
        cur = conn.execute(
            """
            INSERT OR REPLACE INTO heal_suggestions
                (category, severity, message, rule_id,
                 suggested_action, evidence,
                 dismissed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                category,
                severity,
                message,
                rule_id,
                suggested_action,
                json.dumps(evidence) if evidence is not None else None,
                now,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def list_heal_suggestions(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    *,
    include_dismissed: bool = False,
) -> list[dict]:
    """Return heal suggestions, excluding dismissed ones by default."""
    where = "" if include_dismissed else "WHERE dismissed = 0"
    with lock:
        cur = conn.execute(
            f"SELECT * FROM heal_suggestions {where} ORDER BY created_at DESC"
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def dismiss_heal_suggestion(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    suggestion_id: int,
) -> None:
    """Mark a suggestion as dismissed."""
    now = int(time.time())
    with lock:
        conn.execute(
            "UPDATE heal_suggestions SET dismissed = 1, updated_at = ? WHERE id = ?",
            (now, suggestion_id),
        )
        conn.commit()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS heal_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            correlation_key TEXT, rule_id TEXT, condition TEXT, target TEXT,
            action_type TEXT, action_params TEXT, escalation_step INTEGER,
            action_success INTEGER, verified INTEGER, duration_s REAL,
            metrics_before TEXT, metrics_after TEXT, trust_level TEXT,
            source TEXT, approval_id INTEGER, created_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_heal_ledger_lookup
            ON heal_ledger(rule_id, condition, target, created_at);

        CREATE TABLE IF NOT EXISTS trust_state (
            rule_id TEXT PRIMARY KEY,
            current_level TEXT DEFAULT 'notify', ceiling TEXT DEFAULT 'execute',
            promoted_at INTEGER, demoted_at INTEGER,
            promotion_count INTEGER DEFAULT 0, demotion_count INTEGER DEFAULT 0,
            last_evaluated INTEGER
        );

        CREATE TABLE IF NOT EXISTS heal_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT, severity TEXT, message TEXT, rule_id TEXT,
            suggested_action TEXT, evidence TEXT,
            dismissed INTEGER DEFAULT 0, created_at INTEGER, updated_at INTEGER,
            UNIQUE(category, rule_id)
        );
    """)


class _HealingMixin:
    def insert_heal_outcome(self, **kw) -> int:
        return insert_heal_outcome(self._get_conn(), self._lock, **kw)

    def get_heal_outcomes(self, **kw) -> list[dict]:
        return get_heal_outcomes(self._get_read_conn(), self._read_lock, **kw)

    def get_heal_success_rate(self, action_type: str, condition: str, **kw) -> float:
        return get_heal_success_rate(self._get_read_conn(), self._read_lock, action_type, condition, **kw)

    def get_mean_time_to_resolve(self, condition: str, **kw) -> float | None:
        return get_mean_time_to_resolve(self._get_read_conn(), self._read_lock, condition, **kw)

    def get_escalation_frequency(self, rule_id: str, **kw) -> dict:
        return get_escalation_frequency(self._get_read_conn(), self._read_lock, rule_id, **kw)

    def upsert_trust_state(self, rule_id: str, current_level: str, ceiling: str) -> None:
        upsert_trust_state(self._get_conn(), self._lock, rule_id, current_level, ceiling)

    def get_trust_state(self, rule_id: str) -> dict | None:
        return get_trust_state(self._get_read_conn(), self._read_lock, rule_id)

    def list_trust_states(self) -> list[dict]:
        return list_trust_states(self._get_read_conn(), self._read_lock)

    def insert_heal_suggestion(self, **kw) -> int:
        return insert_heal_suggestion(self._get_conn(), self._lock, **kw)

    def list_heal_suggestions(self, **kw) -> list[dict]:
        return list_heal_suggestions(self._get_read_conn(), self._read_lock, **kw)

    def dismiss_heal_suggestion(self, suggestion_id: int) -> None:
        dismiss_heal_suggestion(self._get_conn(), self._lock, suggestion_id)
