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
        self._init_schema()

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_schema(self) -> None:
        import os
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with self._lock:
            with self._connect() as conn:
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
                with self._connect() as conn:
                    conn.executemany(
                        "INSERT INTO metrics (timestamp, metric, value, tags) VALUES (?,?,?,?)",
                        rows,
                    )
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
        with self._connect() as conn:
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
                with self._connect() as conn:
                    c = conn.execute(
                        "SELECT COUNT(*) FROM metrics WHERE timestamp < ?", (cutoff,)
                    )
                    stale = c.fetchone()[0]
                    if stale == 0:
                        return
                    conn.execute("DELETE FROM metrics WHERE timestamp < ?", (cutoff,))
                    logger.info("History pruned: %d rows older than %d days", stale, HISTORY_RETENTION_DAYS)
                    if stale > 50_000:
                        conn.execute("VACUUM")
                        logger.info("History DB vacuumed")
        except Exception as e:
            logger.error("prune_history failed: %s", e)

    def prune_audit(self) -> None:
        cutoff = int(time.time()) - AUDIT_RETENTION_DAYS * 86400
        try:
            with self._lock:
                with self._connect() as conn:
                    stale = conn.execute(
                        "SELECT COUNT(*) FROM audit WHERE timestamp < ?", (cutoff,)
                    ).fetchone()[0]
                    if stale == 0:
                        return
                    conn.execute("DELETE FROM audit WHERE timestamp < ?", (cutoff,))
                    logger.info("Audit pruned: %d rows older than %d days", stale, AUDIT_RETENTION_DAYS)
        except Exception as e:
            logger.error("prune_audit failed: %s", e)

    # ── Audit ─────────────────────────────────────────────────────────────────
    def audit_log(self, action: str, username: str, details: str = "", ip: str = "") -> None:
        try:
            with self._lock:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT INTO audit (timestamp, username, action, details, ip) VALUES (?,?,?,?,?)",
                        (int(time.time()), username, action, details, ip),
                    )
        except Exception as e:
            logger.error("audit_log failed: %s", e)

    def get_audit(self, limit: int = 100) -> list[dict]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT timestamp, username, action, details, ip FROM audit ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {"time": r[0], "username": r[1], "action": r[2], "details": r[3], "ip": r[4]}
                for r in rows
            ]
        except Exception as e:
            logger.error("get_audit failed: %s", e)
            return []


# Singleton shared instance
db = Database()
