"""Noba – Thread-safe SQLite database layer."""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from datetime import datetime

from .config import AUDIT_RETENTION_DAYS, HISTORY_DB, HISTORY_RETENTION_DAYS, JOB_RETENTION_DAYS

logger = logging.getLogger("noba")


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


# Singleton shared instance
db = Database()
