"""Noba – MaintenanceManager for the self-healing pipeline.

Maintenance windows pause or queue healing for specific targets or globally.
They can be scheduled (cron_expr) or ad-hoc (expires_at = now + duration_s).
"""
from __future__ import annotations

import sqlite3
import threading
import time


class MaintenanceManager:
    """Thread-safe maintenance window manager backed by the DB.

    Uses the ``heal_maintenance_windows`` table (distinct from the
    automations-system ``maintenance_windows`` table).
    """

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = conn
        self._lock = lock

    # ── Public API ────────────────────────────────────────────────────────────

    def create_window(
        self,
        *,
        target: str,
        duration_s: int,
        reason: str | None = None,
        action: str = "suppress",
        cron_expr: str | None = None,
        created_by: str | None = None,
    ) -> int:
        """Insert a maintenance window and return its id.

        For ad-hoc windows ``expires_at`` is set to ``now + duration_s``.
        For cron-based windows ``expires_at`` is NULL (the cron schedule
        controls activation) and ``duration_s`` tracks how long each
        activation lasts.
        """
        now = int(time.time())
        expires_at = now + duration_s if cron_expr is None else None
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO heal_maintenance_windows
                    (target, cron_expr, duration_s, reason, action, active,
                     created_by, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (target, cron_expr, duration_s, reason, action,
                 created_by, now, expires_at),
            )
            self._conn.commit()
            return cur.lastrowid

    def end_window(self, window_id: int) -> bool:
        """Deactivate a window early (sets active = 0). Returns True if found."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE heal_maintenance_windows SET active = 0 WHERE id = ?",
                (window_id,),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def is_in_maintenance(self, target: str) -> bool:
        """Return True if *target* (or all targets) is covered by an active window."""
        now = int(time.time())
        with self._lock:
            row = self._conn.execute(
                """
                SELECT 1 FROM heal_maintenance_windows
                WHERE active = 1
                  AND (expires_at IS NULL OR expires_at > ?)
                  AND (target = ? OR target = 'all')
                LIMIT 1
                """,
                (now, target),
            ).fetchone()
        return row is not None

    def get_active_windows(self) -> list[dict]:
        """Return all active, non-expired windows as dicts."""
        now = int(time.time())
        with self._lock:
            cur = self._conn.execute(
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

    def get_maintenance_action(self, target: str) -> str | None:
        """Return the action type for *target* if in maintenance, else None.

        When multiple windows match, the most-recently-created window wins.
        """
        now = int(time.time())
        with self._lock:
            row = self._conn.execute(
                """
                SELECT action FROM heal_maintenance_windows
                WHERE active = 1
                  AND (expires_at IS NULL OR expires_at > ?)
                  AND (target = ? OR target = 'all')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (now, target),
            ).fetchone()
        if row is None:
            return None
        # Support both sqlite3.Row and plain tuple
        return row[0] if not hasattr(row, "keys") else row["action"]
