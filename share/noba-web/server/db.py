"""Noba – Thread-safe SQLite database layer."""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from datetime import datetime

from .config import AUDIT_RETENTION_DAYS, HISTORY_DB, HISTORY_RETENTION_DAYS

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


# Singleton shared instance
db = Database()
