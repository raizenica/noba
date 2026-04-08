# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – DB metric functions (insert, query, prune, trend)."""
from __future__ import annotations

import logging
import math
import sqlite3
import threading
import time
from datetime import datetime

from ..config import HISTORY_RETENTION_DAYS

logger = logging.getLogger("noba")


def insert_metrics(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    metrics: list[tuple],
) -> None:
    """Batch insert: each element is (metric, value, tags)."""
    now = int(time.time())
    rows = [(now, m, v, t) for m, v, t in metrics]
    try:
        with lock:
            conn.executemany(
                "INSERT INTO metrics (timestamp, metric, value, tags) VALUES (?,?,?,?)",
                rows,
            )
            conn.commit()
    except Exception as e:
        logger.error("insert_metrics failed: %s", e)


def get_history(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    metric: str,
    range_hours: int = 24,
    resolution: int = 60,
    anomaly: bool = False,
    raw: bool = False,
) -> list[dict]:
    cutoff = int(time.time()) - range_hours * 3600
    if raw or range_hours <= 1:
        table = "metrics"
    elif range_hours <= 168:  # 7 days
        table = "metrics_1m"
    else:
        table = "metrics_1h"

    if table == "metrics":
        sql = """
            SELECT (timestamp / ?) * ? AS slot, AVG(value)
            FROM metrics
            WHERE metric = ? AND timestamp >= ?
            GROUP BY slot
            ORDER BY slot ASC
        """
    else:
        ts_col = "ts"
        key_col = "key"
        sql = f"""
            SELECT ({ts_col} / ?) * ? AS slot, AVG(value)
            FROM {table}
            WHERE {key_col} = ? AND {ts_col} >= ?
            GROUP BY slot
            ORDER BY slot ASC
        """
    with lock:
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
        p["anomaly"] = values[i] > mean + Z * std or values[i] < mean - Z * std
    return points


def prune_history(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    days: int | None = None,
) -> None:
    retention = days if days is not None else HISTORY_RETENTION_DAYS
    cutoff = int(time.time()) - retention * 86400
    try:
        with lock:
            c = conn.execute(
                "SELECT COUNT(*) FROM metrics WHERE timestamp < ?", (cutoff,)
            )
            stale = c.fetchone()[0]
            if stale == 0:
                return
            conn.execute("DELETE FROM metrics WHERE timestamp < ?", (cutoff,))
            conn.commit()
            logger.info("History pruned: %d rows older than %d days", stale, retention)
        if stale > 50_000:
            # Reclaim free pages incrementally — avoids the stop-the-world
            # lock of a full VACUUM on a 24/7 time-series database.
            with lock:
                conn.execute("PRAGMA incremental_vacuum(1000);")
                logger.info("History DB incremental vacuum (%d pages)", 1000)
    except Exception as e:
        logger.error("prune_history failed: %s", e)


def get_trend(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    metric: str,
    range_hours: int = 168,
    projection_hours: int = 168,
) -> dict:
    """Linear regression trend with future projection."""
    points = get_history(conn, lock, metric, range_hours=range_hours, resolution=300, raw=True)
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
        "slope": round(slope, 8),
        "r_squared": round(r_squared, 4),
        "trend": trend,
        "projection": projection,
        "full_at": full_at,
    }


def rollup_to_1m(conn: sqlite3.Connection, lock: threading.Lock) -> None:
    """Aggregate raw metrics into 1-minute buckets for all missing intervals."""
    now = int(time.time())
    with lock:
        # Find the last 1m rollup
        row = conn.execute("SELECT MAX(ts) FROM metrics_1m").fetchone()
        # If no rollups yet, start 1h ago
        last_ts = row[0] if row and row[0] else now - 3600
        
        # Process every missing minute bucket up to the previous complete minute
        for ts in range(last_ts + 60, now - (now % 60), 60):
            conn.execute("""
                INSERT OR REPLACE INTO metrics_1m (ts, key, value)
                SELECT ?, metric, AVG(value)
                FROM metrics
                WHERE timestamp >= ? AND timestamp < ?
                GROUP BY metric
                HAVING COUNT(*) > 0
            """, (ts, ts, ts + 60))
        conn.commit()


def rollup_to_1h(conn: sqlite3.Connection, lock: threading.Lock) -> None:
    """Aggregate 1m metrics into 1-hour buckets for all missing intervals."""
    now = int(time.time())
    with lock:
        # Find the last 1h rollup
        row = conn.execute("SELECT MAX(ts) FROM metrics_1h").fetchone()
        # If no rollups yet, start 24h ago
        last_ts = row[0] if row and row[0] else now - 86400
        
        # Process every missing hour bucket up to the previous complete hour
        for ts in range(last_ts + 3600, now - (now % 3600), 3600):
            conn.execute("""
                INSERT OR REPLACE INTO metrics_1h (ts, key, value)
                SELECT ?, key, AVG(value)
                FROM metrics_1m
                WHERE ts >= ? AND ts < ?
                GROUP BY key
                HAVING COUNT(*) > 0
            """, (ts, ts, ts + 3600))
        conn.commit()


def prune_rollups(conn: sqlite3.Connection, lock: threading.Lock) -> None:
    """Enforce retention: 7 days for 1m, 90 days for 1h."""
    now = int(time.time())
    with lock:
        conn.execute("DELETE FROM metrics_1m WHERE ts < ?", (now - 7 * 86400,))
        conn.execute("DELETE FROM metrics_1h WHERE ts < ?", (now - 90 * 86400,))
        conn.commit()


def catchup_rollups(conn: sqlite3.Connection, lock: threading.Lock) -> None:
    """On startup, fill gaps in rollup tables since last run."""
    now = int(time.time())
    with lock:
        # Catch up 1m rollups
        row = conn.execute("SELECT MAX(ts) FROM metrics_1m").fetchone()
        last_1m = row[0] if row and row[0] else now - 3600
        for ts in range(last_1m + 60, now - (now % 60), 60):
            conn.execute("""
                INSERT OR IGNORE INTO metrics_1m (ts, key, value)
                SELECT ?, metric, AVG(value)
                FROM metrics WHERE timestamp >= ? AND timestamp < ?
                GROUP BY metric
                HAVING COUNT(*) > 0
            """, (ts, ts, ts + 60))

        # Catch up 1h rollups
        row = conn.execute("SELECT MAX(ts) FROM metrics_1h").fetchone()
        last_1h = row[0] if row and row[0] else now - 86400
        for ts in range(last_1h + 3600, now - (now % 3600), 3600):
            conn.execute("""
                INSERT OR IGNORE INTO metrics_1h (ts, key, value)
                SELECT ?, key, AVG(value)
                FROM metrics_1m WHERE ts >= ? AND ts < ?
                GROUP BY key
                HAVING COUNT(*) > 0
            """, (ts, ts, ts + 3600))
        conn.commit()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS metrics (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            metric    TEXT NOT NULL,
            value     REAL,
            tags      TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_metric_time ON metrics(metric, timestamp);

        CREATE TABLE IF NOT EXISTS metrics_1m (
            ts    INTEGER NOT NULL,
            key   TEXT NOT NULL,
            value REAL,
            PRIMARY KEY (ts, key)
        );
        CREATE TABLE IF NOT EXISTS metrics_1h (
            ts    INTEGER NOT NULL,
            key   TEXT NOT NULL,
            value REAL,
            PRIMARY KEY (ts, key)
        );
    """)


class _MetricsMixin:
    def insert_metrics(self, metrics: list[tuple]) -> None:
        insert_metrics(self._get_conn(), self._lock, metrics)

    def get_history(self, metric: str, range_hours: int = 24,
                    resolution: int = 60, anomaly: bool = False,
                    raw: bool = False) -> list[dict]:
        return get_history(self._get_read_conn(), self._read_lock, metric,
                           range_hours=range_hours, resolution=resolution,
                           anomaly=anomaly, raw=raw)

    def prune_history(self, days: int | None = None) -> None:
        prune_history(self._get_conn(), self._lock, days=days)

    def get_trend(self, metric: str, range_hours: int = 168,
                  projection_hours: int = 168) -> dict:
        return get_trend(self._get_read_conn(), self._read_lock, metric,
                         range_hours=range_hours, projection_hours=projection_hours)

    def rollup_to_1m(self) -> None:
        rollup_to_1m(self._get_conn(), self._lock)

    def rollup_to_1h(self) -> None:
        rollup_to_1h(self._get_conn(), self._lock)

    def prune_rollups(self) -> None:
        prune_rollups(self._get_conn(), self._lock)

    def catchup_rollups(self) -> None:
        catchup_rollups(self._get_conn(), self._lock)
