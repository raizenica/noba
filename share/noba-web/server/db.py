"""Noba – Thread-safe SQLite database layer."""
from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import time
from datetime import datetime

from .config import AUDIT_RETENTION_DAYS, HISTORY_DB, HISTORY_RETENTION_DAYS, JOB_RETENTION_DAYS

logger = logging.getLogger("noba")


def _parse_step_from_trigger(trigger: str) -> dict:
    """Parse step index and retry info from a workflow trigger string."""
    # Format: "workflow:<auto_id>:step<N>" or "workflow:<auto_id>:step<N>:retry<M>"
    # or "workflow:<auto_id>:parallel<N>"
    result: dict = {"index": 0, "retry": 0, "mode": "sequential"}
    if ":step" in trigger:
        m = re.search(r":step(\d+)", trigger)
        if m:
            result["index"] = int(m.group(1))
        m = re.search(r":retry(\d+)", trigger)
        if m:
            result["retry"] = int(m.group(1))
    elif ":parallel" in trigger:
        m = re.search(r":parallel(\d+)", trigger)
        if m:
            result["index"] = int(m.group(1))
            result["mode"] = "parallel"
    return result


class Database:
    """Single shared DB object. Uses WAL mode + a write lock for safety."""

    def __init__(self, path: str = HISTORY_DB) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_schema()

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _get_conn(self) -> sqlite3.Connection:
        """Return persistent connection, creating if needed."""
        if self._conn is None:
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
        return self._conn

    def _init_schema(self) -> None:
        import os
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with self._lock:
            conn = self._get_conn()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    metric    TEXT NOT NULL,
                    value     REAL,
                    tags      TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_metric_time ON metrics(metric, timestamp);

                CREATE TABLE IF NOT EXISTS audit (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    username  TEXT NOT NULL,
                    action    TEXT NOT NULL,
                    details   TEXT,
                    ip        TEXT
                );

                CREATE TABLE IF NOT EXISTS automations (
                    id         TEXT PRIMARY KEY,
                    name       TEXT NOT NULL,
                    type       TEXT NOT NULL,
                    config     TEXT NOT NULL DEFAULT '{}',
                    schedule   TEXT,
                    enabled    INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_runs (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    automation_id TEXT,
                    trigger       TEXT NOT NULL,
                    status        TEXT NOT NULL DEFAULT 'queued',
                    started_at    INTEGER,
                    finished_at   INTEGER,
                    exit_code     INTEGER,
                    output        TEXT,
                    triggered_by  TEXT,
                    error         TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_job_runs_auto
                    ON job_runs(automation_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_job_runs_status
                    ON job_runs(status);

                CREATE TABLE IF NOT EXISTS alert_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_id     TEXT NOT NULL,
                    timestamp   INTEGER NOT NULL,
                    severity    TEXT NOT NULL,
                    message     TEXT,
                    resolved_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_alert_hist ON alert_history(rule_id, timestamp);

                CREATE TABLE IF NOT EXISTS api_keys (
                    id         TEXT PRIMARY KEY,
                    name       TEXT NOT NULL,
                    key_hash   TEXT NOT NULL,
                    role       TEXT NOT NULL DEFAULT 'viewer',
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER,
                    last_used  INTEGER
                );

                CREATE TABLE IF NOT EXISTS notifications (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp  INTEGER NOT NULL,
                    level      TEXT NOT NULL,
                    title      TEXT NOT NULL,
                    message    TEXT,
                    read       INTEGER NOT NULL DEFAULT 0,
                    username   TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(username, read);

                CREATE TABLE IF NOT EXISTS user_dashboards (
                    username    TEXT PRIMARY KEY,
                    card_order  TEXT,
                    card_vis    TEXT,
                    card_theme  TEXT,
                    updated_at  INTEGER NOT NULL
                );
            """)

    # ── Metrics ───────────────────────────────────────────────────────────────
    def insert_metrics(self, metrics: list[tuple]) -> None:
        """Batch insert: each element is (metric, value, tags)."""
        now = int(time.time())
        rows = [(now, m, v, t) for m, v, t in metrics]
        try:
            with self._lock:
                conn = self._get_conn()
                conn.executemany(
                    "INSERT INTO metrics (timestamp, metric, value, tags) VALUES (?,?,?,?)",
                    rows,
                )
                conn.commit()
        except Exception as e:
            logger.error("insert_metrics failed: %s", e)

    def get_history(
        self,
        metric: str,
        range_hours: int = 24,
        resolution: int = 60,
        anomaly: bool = False,
    ) -> list[dict]:
        cutoff = int(time.time()) - range_hours * 3600
        sql = """
            SELECT (timestamp / ?) * ? AS slot, AVG(value)
            FROM metrics
            WHERE metric = ? AND timestamp >= ?
            GROUP BY slot
            ORDER BY slot ASC
        """
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(sql, (resolution, resolution, metric, cutoff)).fetchall()

        points = [{"time": r[0], "value": round(r[1], 2)} for r in rows]
        if not anomaly or len(points) < 4:
            return points

        values = [p["value"] for p in points]
        n = len(values)
        window = max(6, n // 3)
        Z = 2.5
        for i, p in enumerate(points):
            lo, hi = max(0, i - window // 2), min(n, i + window // 2)
            win = values[lo:hi]
            mean = sum(win) / len(win)
            variance = sum((x - mean) ** 2 for x in win) / len(win)
            std = math.sqrt(variance) if variance > 0 else 0.0001
            p["upper_band"] = round(mean + Z * std, 2)
            p["lower_band"] = round(mean - Z * std, 2)
            p["anomaly"]    = values[i] > mean + Z * std or values[i] < mean - Z * std
        return points

    def prune_history(self) -> None:
        cutoff = int(time.time()) - HISTORY_RETENTION_DAYS * 86400
        try:
            with self._lock:
                conn = self._get_conn()
                c = conn.execute(
                    "SELECT COUNT(*) FROM metrics WHERE timestamp < ?", (cutoff,)
                )
                stale = c.fetchone()[0]
                if stale == 0:
                    return
                conn.execute("DELETE FROM metrics WHERE timestamp < ?", (cutoff,))
                conn.commit()
                logger.info("History pruned: %d rows older than %d days", stale, HISTORY_RETENTION_DAYS)
            if stale > 50_000:
                # VACUUM must run outside any transaction
                with self._lock:
                    conn = self._get_conn()
                    conn.execute("VACUUM")
                    logger.info("History DB vacuumed")
        except Exception as e:
            logger.error("prune_history failed: %s", e)

    def prune_audit(self) -> None:
        cutoff = int(time.time()) - AUDIT_RETENTION_DAYS * 86400
        try:
            with self._lock:
                conn = self._get_conn()
                stale = conn.execute(
                    "SELECT COUNT(*) FROM audit WHERE timestamp < ?", (cutoff,)
                ).fetchone()[0]
                if stale == 0:
                    return
                conn.execute("DELETE FROM audit WHERE timestamp < ?", (cutoff,))
                conn.commit()
                logger.info("Audit pruned: %d rows older than %d days", stale, AUDIT_RETENTION_DAYS)
        except Exception as e:
            logger.error("prune_audit failed: %s", e)

    # ── Audit ─────────────────────────────────────────────────────────────────
    def audit_log(self, action: str, username: str, details: str = "", ip: str = "") -> None:
        if len(details) > 512:
            details = details[:512] + "…"
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "INSERT INTO audit (timestamp, username, action, details, ip) VALUES (?,?,?,?,?)",
                    (int(time.time()), username, action, details, ip),
                )
                conn.commit()
        except Exception as e:
            logger.error("audit_log failed: %s", e)

    def get_audit(self, limit: int = 100, username_filter: str = "",
                  action_filter: str = "", from_ts: int = 0, to_ts: int = 0) -> list[dict]:
        try:
            clauses = []
            params: list = []
            if username_filter:
                clauses.append("username = ?")
                params.append(username_filter)
            if action_filter:
                clauses.append("action = ?")
                params.append(action_filter)
            if from_ts:
                clauses.append("timestamp >= ?")
                params.append(from_ts)
            if to_ts:
                clauses.append("timestamp <= ?")
                params.append(to_ts)
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            with self._lock:
                conn = self._get_conn()
                rows = conn.execute(
                    f"SELECT timestamp, username, action, details, ip FROM audit{where} ORDER BY timestamp DESC LIMIT ?",
                    params,
                ).fetchall()
            return [
                {"time": r[0], "username": r[1], "action": r[2], "details": r[3], "ip": r[4]}
                for r in rows
            ]
        except Exception as e:
            logger.error("get_audit failed: %s", e)
            return []

    def get_login_history(self, username: str, limit: int = 30) -> list[dict]:
        """Get login history for a specific user."""
        try:
            with self._lock:
                conn = self._get_conn()
                rows = conn.execute(
                    "SELECT timestamp, action, details, ip FROM audit "
                    "WHERE username = ? AND action IN ('login', 'login_failed') "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (username, limit),
                ).fetchall()
            return [{"time": r[0], "action": r[1], "details": r[2], "ip": r[3]} for r in rows]
        except Exception as e:
            logger.error("get_login_history failed: %s", e)
            return []

    def get_trend(self, metric: str, range_hours: int = 168, projection_hours: int = 168) -> dict:
        """Linear regression trend with future projection."""
        points = self.get_history(metric, range_hours=range_hours, resolution=300)
        if len(points) < 10:
            return {"error": "Insufficient data"}
        xs = [p["time"] for p in points]
        ys = [p["value"] for p in points]
        n = len(xs)
        sum_x = sum(xs)
        sum_y = sum(ys)
        sum_xy = sum(x * y for x, y in zip(xs, ys))
        sum_x2 = sum(x * x for x in xs)
        denom = n * sum_x2 - sum_x ** 2
        if denom == 0:
            return {"slope": 0, "trend": [], "projection": []}
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        # R-squared
        y_mean = sum_y / n
        ss_tot = sum((y - y_mean) ** 2 for y in ys)
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        # Trend line over historical range
        trend = [{"time": x, "value": round(slope * x + intercept, 2)} for x in xs]
        # Future projection
        last_t = xs[-1]
        step = 300
        proj_points = int(projection_hours * 3600 / step)
        projection = []
        for i in range(1, proj_points + 1):
            t = last_t + i * step
            v = slope * t + intercept
            projection.append({"time": t, "value": round(v, 2)})
        # Estimate when metric hits 100% (for disk/memory)
        full_at = None
        if slope > 0:
            t_full = (100 - intercept) / slope
            if t_full > last_t:
                from datetime import timezone
                full_at = datetime.fromtimestamp(t_full, tz=timezone.utc).isoformat()
        return {
            "slope": round(slope, 8), "r_squared": round(r_squared, 4),
            "trend": trend, "projection": projection, "full_at": full_at,
        }

    # ── Automations ───────────────────────────────────────────────────────────
    def insert_automation(self, auto_id: str, name: str, atype: str,
                          config: dict, schedule: str | None = None,
                          enabled: bool = True) -> bool:
        now = int(time.time())
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "INSERT OR IGNORE INTO automations "
                    "(id, name, type, config, schedule, enabled, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (auto_id, name, atype, json.dumps(config), schedule,
                     1 if enabled else 0, now, now),
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error("insert_automation failed: %s", e)
            return False

    def update_automation(self, auto_id: str, **kwargs) -> bool:
        allowed = {"name", "type", "config", "schedule", "enabled"}
        sets = []
        params: list = []
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            if k == "config" and isinstance(v, dict):
                v = json.dumps(v)
            if k == "enabled":
                v = 1 if v else 0
            sets.append(f"{k} = ?")
            params.append(v)
        if not sets:
            return False
        sets.append("updated_at = ?")
        params.append(int(time.time()))
        params.append(auto_id)
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    f"UPDATE automations SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error("update_automation failed: %s", e)
            return False

    def delete_automation(self, auto_id: str) -> bool:
        try:
            with self._lock:
                conn = self._get_conn()
                cur = conn.execute("DELETE FROM automations WHERE id = ?", (auto_id,))
                conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            logger.error("delete_automation failed: %s", e)
            return False

    def list_automations(self, type_filter: str | None = None) -> list[dict]:
        try:
            with self._lock:
                conn = self._get_conn()
                if type_filter:
                    rows = conn.execute(
                        "SELECT id, name, type, config, schedule, enabled, created_at, updated_at "
                        "FROM automations WHERE type = ? ORDER BY name",
                        (type_filter,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT id, name, type, config, schedule, enabled, created_at, updated_at "
                        "FROM automations ORDER BY name"
                    ).fetchall()
            return [
                {
                    "id": r[0], "name": r[1], "type": r[2],
                    "config": json.loads(r[3]) if r[3] else {},
                    "schedule": r[4], "enabled": bool(r[5]),
                    "created_at": r[6], "updated_at": r[7],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error("list_automations failed: %s", e)
            return []

    def get_automation(self, auto_id: str) -> dict | None:
        try:
            with self._lock:
                conn = self._get_conn()
                r = conn.execute(
                    "SELECT id, name, type, config, schedule, enabled, created_at, updated_at "
                    "FROM automations WHERE id = ?",
                    (auto_id,),
                ).fetchone()
            if not r:
                return None
            return {
                "id": r[0], "name": r[1], "type": r[2],
                "config": json.loads(r[3]) if r[3] else {},
                "schedule": r[4], "enabled": bool(r[5]),
                "created_at": r[6], "updated_at": r[7],
            }
        except Exception as e:
            logger.error("get_automation failed: %s", e)
            return None

    # ── Job Runs ──────────────────────────────────────────────────────────────
    def insert_job_run(self, automation_id: str | None, trigger: str,
                       triggered_by: str) -> int | None:
        now = int(time.time())
        try:
            with self._lock:
                conn = self._get_conn()
                cur = conn.execute(
                    "INSERT INTO job_runs "
                    "(automation_id, trigger, status, started_at, triggered_by) "
                    "VALUES (?,?,?,?,?)",
                    (automation_id, trigger, "running", now, triggered_by),
                )
                conn.commit()
                return cur.lastrowid
        except Exception as e:
            logger.error("insert_job_run failed: %s", e)
            return None

    def update_job_run(self, run_id: int, status: str,
                       output: str | None = None, exit_code: int | None = None,
                       error: str | None = None) -> None:
        now = int(time.time())
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "UPDATE job_runs SET status=?, finished_at=?, output=?, "
                    "exit_code=?, error=? WHERE id=?",
                    (status, now, output, exit_code, error, run_id),
                )
                conn.commit()
        except Exception as e:
            logger.error("update_job_run failed: %s", e)

    def get_job_runs(self, automation_id: str | None = None,
                     limit: int = 50, status: str | None = None,
                     trigger_prefix: str | None = None) -> list[dict]:
        try:
            clauses = []
            params: list = []
            if automation_id:
                clauses.append("automation_id = ?")
                params.append(automation_id)
            if status:
                clauses.append("status = ?")
                params.append(status)
            if trigger_prefix:
                clauses.append("trigger LIKE ?")
                params.append(trigger_prefix + "%")
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            with self._lock:
                conn = self._get_conn()
                rows = conn.execute(
                    "SELECT id, automation_id, trigger, status, started_at, "
                    "finished_at, exit_code, triggered_by, error "
                    f"FROM job_runs{where} ORDER BY id DESC LIMIT ?",
                    params,
                ).fetchall()
            return [
                {
                    "id": r[0], "automation_id": r[1], "trigger": r[2],
                    "status": r[3], "started_at": r[4], "finished_at": r[5],
                    "exit_code": r[6], "triggered_by": r[7], "error": r[8],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error("get_job_runs failed: %s", e)
            return []

    def get_job_run(self, run_id: int) -> dict | None:
        try:
            with self._lock:
                conn = self._get_conn()
                r = conn.execute(
                    "SELECT id, automation_id, trigger, status, started_at, "
                    "finished_at, exit_code, output, triggered_by, error "
                    "FROM job_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
            if not r:
                return None
            return {
                "id": r[0], "automation_id": r[1], "trigger": r[2],
                "status": r[3], "started_at": r[4], "finished_at": r[5],
                "exit_code": r[6], "output": r[7], "triggered_by": r[8],
                "error": r[9],
            }
        except Exception as e:
            logger.error("get_job_run failed: %s", e)
            return None

    def get_automation_stats(self) -> dict:
        """Return per-automation success/failure counts and avg duration."""
        try:
            with self._lock:
                conn = self._get_conn()
                rows = conn.execute("""
                    SELECT automation_id,
                           COUNT(*) AS total,
                           SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS ok,
                           SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS fail,
                           AVG(CASE WHEN finished_at IS NOT NULL AND started_at IS NOT NULL
                               THEN finished_at - started_at END) AS avg_dur,
                           MAX(started_at) AS last_run
                    FROM job_runs
                    WHERE automation_id IS NOT NULL
                    GROUP BY automation_id
                """).fetchall()
            return {
                r[0]: {"total": r[1], "ok": r[2], "fail": r[3],
                       "avg_duration": round(r[4], 1) if r[4] else None,
                       "last_run": r[5]}
                for r in rows
            }
        except Exception as e:
            logger.error("get_automation_stats failed: %s", e)
            return {}

    def get_workflow_trace(self, workflow_auto_id: str, limit: int = 20) -> list[dict]:
        """Get execution traces for a workflow — groups runs by trigger timestamp."""
        try:
            with self._lock:
                conn = self._get_conn()
                rows = conn.execute(
                    "SELECT id, automation_id, trigger, status, started_at, finished_at, "
                    "exit_code, output, triggered_by, error "
                    "FROM job_runs WHERE trigger LIKE ? "
                    "ORDER BY id DESC LIMIT ?",
                    (f"workflow:{workflow_auto_id}%", limit),
                ).fetchall()
            return [
                {
                    "id": r[0], "automation_id": r[1], "trigger": r[2],
                    "status": r[3], "started_at": r[4], "finished_at": r[5],
                    "exit_code": r[6], "output": r[7][:500] if r[7] else None,
                    "triggered_by": r[8], "error": r[9],
                    "step": _parse_step_from_trigger(r[2]),
                }
                for r in rows
            ]
        except Exception as e:
            logger.error("get_workflow_trace failed: %s", e)
            return []

    def prune_job_runs(self) -> None:
        cutoff = int(time.time()) - JOB_RETENTION_DAYS * 86400
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "DELETE FROM job_runs WHERE finished_at IS NOT NULL AND finished_at < ?",
                    (cutoff,),
                )
                conn.commit()
        except Exception as e:
            logger.error("prune_job_runs failed: %s", e)

    def mark_stale_jobs(self) -> None:
        """Mark any 'running' jobs as 'failed' on startup (leftover from crash)."""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "UPDATE job_runs SET status='failed', error='Server restarted' "
                    "WHERE status IN ('running', 'queued')"
                )
                conn.commit()
        except Exception as e:
            logger.error("mark_stale_jobs failed: %s", e)

    # ── Alert History (Round 2) ───────────────────────────────────────────────
    def insert_alert_history(self, rule_id: str, severity: str, message: str) -> None:
        """Insert an alert event with the current timestamp."""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "INSERT INTO alert_history (rule_id, timestamp, severity, message) "
                    "VALUES (?,?,?,?)",
                    (rule_id, int(time.time()), severity, message),
                )
                conn.commit()
        except Exception as e:
            logger.error("insert_alert_history failed: %s", e)

    def get_alert_history(self, limit: int = 100, rule_id: str | None = None,
                          from_ts: int = 0, to_ts: int = 0) -> list[dict]:
        """Query alert history with optional filters."""
        try:
            clauses: list[str] = []
            params: list = []
            if rule_id:
                clauses.append("rule_id = ?")
                params.append(rule_id)
            if from_ts:
                clauses.append("timestamp >= ?")
                params.append(from_ts)
            if to_ts:
                clauses.append("timestamp <= ?")
                params.append(to_ts)
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            with self._lock:
                conn = self._get_conn()
                rows = conn.execute(
                    "SELECT id, rule_id, timestamp, severity, message, resolved_at "
                    f"FROM alert_history{where} ORDER BY timestamp DESC LIMIT ?",
                    params,
                ).fetchall()
            return [
                {
                    "id": r[0], "rule_id": r[1], "timestamp": r[2],
                    "severity": r[3], "message": r[4], "resolved_at": r[5],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error("get_alert_history failed: %s", e)
            return []

    def resolve_alert(self, rule_id: str) -> None:
        """Mark all unresolved alerts for a rule as resolved now."""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "UPDATE alert_history SET resolved_at = ? "
                    "WHERE rule_id = ? AND resolved_at IS NULL",
                    (int(time.time()), rule_id),
                )
                conn.commit()
        except Exception as e:
            logger.error("resolve_alert failed: %s", e)

    def get_sla(self, rule_id: str, window_hours: int = 720) -> float:
        """Calculate uptime percentage for a rule over the given window.

        Counts total seconds in the window minus seconds where an alert was
        active (timestamp to resolved_at or now if still open).  Returns the
        uptime as a percentage (0-100).
        """
        try:
            now = int(time.time())
            window_start = now - window_hours * 3600
            window_seconds = window_hours * 3600
            with self._lock:
                conn = self._get_conn()
                rows = conn.execute(
                    "SELECT timestamp, resolved_at FROM alert_history "
                    "WHERE rule_id = ? AND "
                    "(resolved_at IS NULL OR resolved_at >= ?) AND timestamp <= ?",
                    (rule_id, window_start, now),
                ).fetchall()
            downtime = 0
            for alert_start, resolved_at in rows:
                start = max(alert_start, window_start)
                end = resolved_at if resolved_at else now
                end = min(end, now)
                if end > start:
                    downtime += end - start
            if window_seconds == 0:
                return 100.0
            uptime = max(0.0, (window_seconds - downtime) / window_seconds * 100)
            return round(uptime, 4)
        except Exception as e:
            logger.error("get_sla failed: %s", e)
            return 100.0

    # ── API Keys (Round 6) ────────────────────────────────────────────────────
    def insert_api_key(self, key_id: str, name: str, key_hash: str,
                       role: str, expires_at: int | None = None) -> None:
        """Insert a new API key."""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "INSERT INTO api_keys (id, name, key_hash, role, created_at, expires_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (key_id, name, key_hash, role, int(time.time()), expires_at),
                )
                conn.commit()
        except Exception as e:
            logger.error("insert_api_key failed: %s", e)

    def get_api_key(self, key_hash: str) -> dict | None:
        """Look up an API key by its hash and update last_used timestamp."""
        try:
            with self._lock:
                conn = self._get_conn()
                r = conn.execute(
                    "SELECT id, name, key_hash, role, created_at, expires_at, last_used "
                    "FROM api_keys WHERE key_hash = ?",
                    (key_hash,),
                ).fetchone()
                if not r:
                    return None
                conn.execute(
                    "UPDATE api_keys SET last_used = ? WHERE key_hash = ?",
                    (int(time.time()), key_hash),
                )
                conn.commit()
            return {
                "id": r[0], "name": r[1], "key_hash": r[2], "role": r[3],
                "created_at": r[4], "expires_at": r[5], "last_used": r[6],
            }
        except Exception as e:
            logger.error("get_api_key failed: %s", e)
            return None

    def list_api_keys(self) -> list[dict]:
        """List all API keys (excluding key_hash from results)."""
        try:
            with self._lock:
                conn = self._get_conn()
                rows = conn.execute(
                    "SELECT id, name, role, created_at, expires_at, last_used "
                    "FROM api_keys ORDER BY created_at DESC"
                ).fetchall()
            return [
                {
                    "id": r[0], "name": r[1], "role": r[2],
                    "created_at": r[3], "expires_at": r[4], "last_used": r[5],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error("list_api_keys failed: %s", e)
            return []

    def delete_api_key(self, key_id: str) -> bool:
        """Delete an API key by its id."""
        try:
            with self._lock:
                conn = self._get_conn()
                cur = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
                conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            logger.error("delete_api_key failed: %s", e)
            return False

    # ── Notifications (Round 7) ───────────────────────────────────────────────
    def insert_notification(self, level: str, title: str, message: str,
                            username: str | None = None) -> None:
        """Insert a notification."""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "INSERT INTO notifications (timestamp, level, title, message, username) "
                    "VALUES (?,?,?,?,?)",
                    (int(time.time()), level, title, message, username),
                )
                conn.commit()
        except Exception as e:
            logger.error("insert_notification failed: %s", e)

    def get_notifications(self, username: str | None = None,
                          unread_only: bool = False, limit: int = 50) -> list[dict]:
        """Query notifications with optional filters."""
        try:
            clauses: list[str] = []
            params: list = []
            if username:
                clauses.append("(username = ? OR username IS NULL)")
                params.append(username)
            if unread_only:
                clauses.append("read = 0")
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            with self._lock:
                conn = self._get_conn()
                rows = conn.execute(
                    "SELECT id, timestamp, level, title, message, read, username "
                    f"FROM notifications{where} ORDER BY timestamp DESC LIMIT ?",
                    params,
                ).fetchall()
            return [
                {
                    "id": r[0], "timestamp": r[1], "level": r[2],
                    "title": r[3], "message": r[4], "read": bool(r[5]),
                    "username": r[6],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error("get_notifications failed: %s", e)
            return []

    def mark_notification_read(self, notif_id: int, username: str) -> None:
        """Mark a single notification as read."""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "UPDATE notifications SET read = 1 "
                    "WHERE id = ? AND (username = ? OR username IS NULL)",
                    (notif_id, username),
                )
                conn.commit()
        except Exception as e:
            logger.error("mark_notification_read failed: %s", e)

    def mark_all_notifications_read(self, username: str) -> None:
        """Mark all notifications for a user as read."""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "UPDATE notifications SET read = 1 "
                    "WHERE (username = ? OR username IS NULL) AND read = 0",
                    (username,),
                )
                conn.commit()
        except Exception as e:
            logger.error("mark_all_notifications_read failed: %s", e)

    def get_unread_count(self, username: str) -> int:
        """Return count of unread notifications for a user."""
        try:
            with self._lock:
                conn = self._get_conn()
                r = conn.execute(
                    "SELECT COUNT(*) FROM notifications "
                    "WHERE (username = ? OR username IS NULL) AND read = 0",
                    (username,),
                ).fetchone()
            return r[0] if r else 0
        except Exception as e:
            logger.error("get_unread_count failed: %s", e)
            return 0

    # ── User Dashboards (Round 7) ─────────────────────────────────────────────
    def save_user_dashboard(self, username: str, card_order: list | None = None,
                            card_vis: dict | None = None,
                            card_theme: dict | None = None) -> None:
        """Save or update a user's dashboard layout preferences."""
        try:
            with self._lock:
                conn = self._get_conn()
                conn.execute(
                    "INSERT OR REPLACE INTO user_dashboards "
                    "(username, card_order, card_vis, card_theme, updated_at) "
                    "VALUES (?,?,?,?,?)",
                    (
                        username,
                        json.dumps(card_order) if card_order is not None else None,
                        json.dumps(card_vis) if card_vis is not None else None,
                        json.dumps(card_theme) if card_theme is not None else None,
                        int(time.time()),
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error("save_user_dashboard failed: %s", e)

    def get_user_dashboard(self, username: str) -> dict | None:
        """Retrieve a user's dashboard layout preferences."""
        try:
            with self._lock:
                conn = self._get_conn()
                r = conn.execute(
                    "SELECT username, card_order, card_vis, card_theme, updated_at "
                    "FROM user_dashboards WHERE username = ?",
                    (username,),
                ).fetchone()
            if not r:
                return None
            return {
                "username": r[0],
                "card_order": json.loads(r[1]) if r[1] else None,
                "card_vis": json.loads(r[2]) if r[2] else None,
                "card_theme": json.loads(r[3]) if r[3] else None,
                "updated_at": r[4],
            }
        except Exception as e:
            logger.error("get_user_dashboard failed: %s", e)
            return None


# Singleton shared instance
db = Database()
