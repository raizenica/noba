"""Noba – Thread-safe SQLite database layer (core)."""
from __future__ import annotations

import logging
import sqlite3
import threading

from ..config import HISTORY_DB
from .alerts import (
    get_alert_history as _get_alert_history,
    get_incidents as _get_incidents,
    get_sla as _get_sla,
    insert_alert_history as _insert_alert_history,
    insert_incident as _insert_incident,
    resolve_alert as _resolve_alert,
    resolve_incident as _resolve_incident,
)
from .audit import (
    audit_log as _audit_log,
    get_audit as _get_audit,
    get_login_history as _get_login_history,
    prune_audit as _prune_audit,
)
from .automations import (
    delete_api_key as _delete_api_key,
    delete_automation as _delete_automation,
    get_api_key as _get_api_key,
    get_automation as _get_automation,
    get_automation_stats as _get_automation_stats,
    get_job_run as _get_job_run,
    get_job_runs as _get_job_runs,
    get_notifications as _get_notifications,
    get_unread_count as _get_unread_count,
    get_user_dashboard as _get_user_dashboard,
    get_workflow_trace as _get_workflow_trace,
    insert_api_key as _insert_api_key,
    insert_automation as _insert_automation,
    insert_job_run as _insert_job_run,
    insert_notification as _insert_notification,
    list_api_keys as _list_api_keys,
    list_automations as _list_automations,
    mark_all_notifications_read as _mark_all_notifications_read,
    mark_notification_read as _mark_notification_read,
    mark_stale_jobs as _mark_stale_jobs,
    prune_job_runs as _prune_job_runs,
    save_user_dashboard as _save_user_dashboard,
    update_automation as _update_automation,
    update_job_run as _update_job_run,
)
from .metrics import (
    get_history as _get_history,
    get_trend as _get_trend,
    insert_metrics as _insert_metrics,
    prune_history as _prune_history,
)

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

                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'info',
                    source TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    details TEXT DEFAULT '',
                    resolved_at INTEGER DEFAULT 0,
                    auto_generated INTEGER DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_incidents_time ON incidents(timestamp DESC);

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

    # ── Metrics ───────────────────────────────────────────────────────────────
    def insert_metrics(self, metrics: list[tuple]) -> None:
        _insert_metrics(self._get_conn(), self._lock, metrics)

    def get_history(self, metric: str, range_hours: int = 24,
                    resolution: int = 60, anomaly: bool = False,
                    raw: bool = False) -> list[dict]:
        return _get_history(self._get_conn(), self._lock, metric,
                            range_hours=range_hours, resolution=resolution,
                            anomaly=anomaly, raw=raw)

    def prune_history(self) -> None:
        _prune_history(self._get_conn(), self._lock)

    def get_trend(self, metric: str, range_hours: int = 168,
                  projection_hours: int = 168) -> dict:
        return _get_trend(self._get_conn(), self._lock, metric,
                          range_hours=range_hours, projection_hours=projection_hours)

    def rollup_to_1m(self) -> None:
        from .metrics import rollup_to_1m
        rollup_to_1m(self._get_conn(), self._lock)

    def rollup_to_1h(self) -> None:
        from .metrics import rollup_to_1h
        rollup_to_1h(self._get_conn(), self._lock)

    def prune_rollups(self) -> None:
        from .metrics import prune_rollups
        prune_rollups(self._get_conn(), self._lock)

    def catchup_rollups(self) -> None:
        from .metrics import catchup_rollups
        catchup_rollups(self._get_conn(), self._lock)

    # ── Audit ─────────────────────────────────────────────────────────────────
    def audit_log(self, action: str, username: str, details: str = "", ip: str = "") -> None:
        _audit_log(self._get_conn(), self._lock, action, username, details=details, ip=ip)

    def get_audit(self, limit: int = 100, username_filter: str = "",
                  action_filter: str = "", from_ts: int = 0, to_ts: int = 0) -> list[dict]:
        return _get_audit(self._get_conn(), self._lock, limit=limit,
                          username_filter=username_filter, action_filter=action_filter,
                          from_ts=from_ts, to_ts=to_ts)

    def get_login_history(self, username: str, limit: int = 30) -> list[dict]:
        return _get_login_history(self._get_conn(), self._lock, username, limit=limit)

    def prune_audit(self) -> None:
        _prune_audit(self._get_conn(), self._lock)

    # ── Automations ───────────────────────────────────────────────────────────
    def insert_automation(self, auto_id: str, name: str, atype: str,
                          config: dict, schedule: str | None = None,
                          enabled: bool = True) -> bool:
        return _insert_automation(self._get_conn(), self._lock, auto_id, name, atype,
                                  config, schedule=schedule, enabled=enabled)

    def update_automation(self, auto_id: str, **kwargs) -> bool:
        return _update_automation(self._get_conn(), self._lock, auto_id, **kwargs)

    def delete_automation(self, auto_id: str) -> bool:
        return _delete_automation(self._get_conn(), self._lock, auto_id)

    def list_automations(self, type_filter: str | None = None) -> list[dict]:
        return _list_automations(self._get_conn(), self._lock, type_filter=type_filter)

    def get_automation(self, auto_id: str) -> dict | None:
        return _get_automation(self._get_conn(), self._lock, auto_id)

    # ── Job Runs ──────────────────────────────────────────────────────────────
    def insert_job_run(self, automation_id: str | None, trigger: str,
                       triggered_by: str) -> int | None:
        return _insert_job_run(self._get_conn(), self._lock, automation_id, trigger, triggered_by)

    def update_job_run(self, run_id: int, status: str, output: str | None = None,
                       exit_code: int | None = None, error: str | None = None) -> None:
        _update_job_run(self._get_conn(), self._lock, run_id, status,
                        output=output, exit_code=exit_code, error=error)

    def get_job_runs(self, automation_id: str | None = None, limit: int = 50,
                     status: str | None = None, trigger_prefix: str | None = None) -> list[dict]:
        return _get_job_runs(self._get_conn(), self._lock, automation_id=automation_id,
                             limit=limit, status=status, trigger_prefix=trigger_prefix)

    def get_job_run(self, run_id: int) -> dict | None:
        return _get_job_run(self._get_conn(), self._lock, run_id)

    def get_automation_stats(self) -> dict:
        return _get_automation_stats(self._get_conn(), self._lock)

    def get_workflow_trace(self, workflow_auto_id: str, limit: int = 20) -> list[dict]:
        return _get_workflow_trace(self._get_conn(), self._lock, workflow_auto_id, limit=limit)

    def prune_job_runs(self) -> None:
        _prune_job_runs(self._get_conn(), self._lock)

    def mark_stale_jobs(self) -> None:
        _mark_stale_jobs(self._get_conn(), self._lock)

    # ── Alert History ─────────────────────────────────────────────────────────
    def insert_alert_history(self, rule_id: str, severity: str, message: str) -> None:
        _insert_alert_history(self._get_conn(), self._lock, rule_id, severity, message)

    def get_alert_history(self, limit: int = 100, rule_id: str | None = None,
                          from_ts: int = 0, to_ts: int = 0) -> list[dict]:
        return _get_alert_history(self._get_conn(), self._lock, limit=limit,
                                  rule_id=rule_id, from_ts=from_ts, to_ts=to_ts)

    def resolve_alert(self, rule_id: str) -> None:
        _resolve_alert(self._get_conn(), self._lock, rule_id)

    def get_sla(self, rule_id: str, window_hours: int = 720) -> float:
        return _get_sla(self._get_conn(), self._lock, rule_id, window_hours=window_hours)

    # ── API Keys ──────────────────────────────────────────────────────────────
    def insert_api_key(self, key_id: str, name: str, key_hash: str,
                       role: str, expires_at: int | None = None) -> None:
        _insert_api_key(self._get_conn(), self._lock, key_id, name, key_hash,
                        role, expires_at=expires_at)

    def get_api_key(self, key_hash: str) -> dict | None:
        return _get_api_key(self._get_conn(), self._lock, key_hash)

    def list_api_keys(self) -> list[dict]:
        return _list_api_keys(self._get_conn(), self._lock)

    def delete_api_key(self, key_id: str) -> bool:
        return _delete_api_key(self._get_conn(), self._lock, key_id)

    # ── Notifications ─────────────────────────────────────────────────────────
    def insert_notification(self, level: str, title: str, message: str,
                            username: str | None = None) -> None:
        _insert_notification(self._get_conn(), self._lock, level, title, message,
                             username=username)

    def get_notifications(self, username: str | None = None,
                          unread_only: bool = False, limit: int = 50) -> list[dict]:
        return _get_notifications(self._get_conn(), self._lock, username=username,
                                  unread_only=unread_only, limit=limit)

    def mark_notification_read(self, notif_id: int, username: str) -> None:
        _mark_notification_read(self._get_conn(), self._lock, notif_id, username)

    def mark_all_notifications_read(self, username: str) -> None:
        _mark_all_notifications_read(self._get_conn(), self._lock, username)

    def get_unread_count(self, username: str) -> int:
        return _get_unread_count(self._get_conn(), self._lock, username)

    # ── User Dashboards ───────────────────────────────────────────────────────
    def save_user_dashboard(self, username: str, card_order: list | None = None,
                            card_vis: dict | None = None,
                            card_theme: dict | None = None) -> None:
        _save_user_dashboard(self._get_conn(), self._lock, username,
                             card_order=card_order, card_vis=card_vis, card_theme=card_theme)

    def get_user_dashboard(self, username: str) -> dict | None:
        return _get_user_dashboard(self._get_conn(), self._lock, username)

    # ── Incidents ─────────────────────────────────────────────────────────────
    def insert_incident(self, severity: str, source: str, title: str, details: str = "") -> int:
        return _insert_incident(self._get_conn(), self._lock, severity, source, title,
                                details=details)

    def get_incidents(self, limit: int = 100, hours: int = 24) -> list[dict]:
        return _get_incidents(self._get_conn(), self._lock, limit=limit, hours=hours)

    def resolve_incident(self, incident_id: int) -> bool:
        return _resolve_incident(self._get_conn(), self._lock, incident_id)
