"""Noba – Thread-safe SQLite database layer (core)."""
from __future__ import annotations

import logging
import sqlite3
import threading

from ..config import HISTORY_DB
from .dashboards import (
    create_dashboard as _create_dashboard,
    delete_dashboard as _delete_dashboard,
    get_dashboard as _get_dashboard,
    get_dashboards as _get_dashboards,
    update_dashboard as _update_dashboard,
)
from .dependencies import (
    create_dependency as _create_dependency,
    delete_dependency as _delete_dependency,
    get_impact_analysis as _get_impact_analysis,
    list_dependencies as _list_dependencies,
)
from .agents import (
    delete_agent as _delete_agent,
    get_all_agents as _get_all_agents,
    update_agent_config as _update_agent_config,
    upsert_agent as _upsert_agent,
)
from .baselines import (  # noqa: F401
    create_baseline as _create_baseline,
    delete_baseline as _delete_baseline,
    get_baseline as _get_baseline,
    get_drift_results as _get_drift_results,
    list_baselines as _list_baselines,
    record_drift_check as _record_drift_check,
    update_baseline as _update_baseline,
)
from .endpoints import (  # noqa: F401
    create_monitor as _create_monitor,
    delete_monitor as _delete_monitor,
    get_due_monitors as _get_due_monitors,
    get_endpoint_avg_latency as _get_endpoint_avg_latency,
    get_endpoint_check_history as _get_endpoint_check_history,
    get_endpoint_uptime as _get_endpoint_uptime,
    get_monitor as _get_monitor,
    get_monitors as _get_monitors,
    prune_endpoint_check_history as _prune_endpoint_check_history,
    record_check_result as _record_check_result,
    record_endpoint_check_history as _record_endpoint_check_history,
    update_monitor as _update_monitor,
)
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
    _auto_approve_expired,
    _count_pending_approvals,
    _decide_approval,
    _delete_maintenance_window,
    _get_action_audit,
    _get_active_maintenance_windows,
    _get_approval,
    _get_playbook_template,
    _get_workflow_context,
    _insert_action_audit,
    _insert_approval,
    _insert_maintenance_window,
    _list_approvals,
    _list_maintenance_windows,
    _list_playbook_templates,
    _save_workflow_context,
    _seed_default_playbooks,
    _update_approval_result,
    _update_maintenance_window,
    _upsert_playbook_template,
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
from .user_preferences import (
    delete_user_preferences as _delete_user_preferences,
    get_user_preferences as _get_user_preferences,
    save_user_preferences as _save_user_preferences,
)
from .security import (  # noqa: F401
    get_aggregate_score as _get_aggregate_score,
    get_findings as _get_findings,
    get_latest_scores as _get_latest_scores,
    get_score_history as _get_score_history,
    record_scan as _record_scan,
)
from .webhooks import (
    create_webhook as _create_webhook,
    delete_webhook as _delete_webhook,
    get_webhook_by_hook_id as _get_webhook_by_hook_id,
    list_webhooks as _list_webhooks,
    record_trigger as _record_trigger,
)
from .backup_verify import (  # noqa: F401
    get_321_status as _get_321_status,
    list_verifications as _list_verifications,
    record_verification as _record_verification,
    update_321_status as _update_321_status,
)
from .status_page import (  # noqa: F401
    add_incident_message as _add_incident_message,
    add_status_update as _add_status_update,
    assign_incident as _assign_incident,
    create_status_component as _create_status_component,
    create_status_incident as _create_status_incident,
    delete_status_component as _delete_status_component,
    get_incident_messages as _get_incident_messages,
    get_status_incident as _get_status_incident,
    get_status_uptime_history as _get_status_uptime_history,
    list_status_components as _list_status_components,
    list_status_incidents as _list_status_incidents,
    resolve_status_incident as _resolve_status_incident,
    update_status_component as _update_status_component,
    update_status_incident as _update_status_incident,
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
            # Use incremental auto-vacuum instead of manual VACUUM to avoid
            # stop-the-world locks on the 24/7 time-series database.
            cur_av = self._conn.execute("PRAGMA auto_vacuum;").fetchone()[0]
            if cur_av != 2:  # 2 = INCREMENTAL
                self._conn.execute("PRAGMA auto_vacuum=INCREMENTAL;")
                self._conn.execute("VACUUM;")  # one-time migration to enable it
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

                CREATE TABLE IF NOT EXISTS endpoint_monitors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    method TEXT DEFAULT 'GET',
                    expected_status INTEGER DEFAULT 200,
                    check_interval INTEGER DEFAULT 300,
                    timeout INTEGER DEFAULT 10,
                    agent_hostname TEXT,
                    enabled INTEGER DEFAULT 1,
                    created_at INTEGER,
                    last_checked INTEGER,
                    last_status TEXT,
                    last_response_ms INTEGER,
                    cert_expiry_days INTEGER,
                    notify_cert_days INTEGER DEFAULT 14
                );
                CREATE INDEX IF NOT EXISTS idx_endpoint_monitors_enabled
                    ON endpoint_monitors(enabled);

                CREATE TABLE IF NOT EXISTS custom_dashboards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    shared INTEGER DEFAULT 0,
                    created_at INTEGER,
                    updated_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_custom_dashboards_owner
                    ON custom_dashboards(owner);

                CREATE TABLE IF NOT EXISTS status_components (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    group_name TEXT DEFAULT 'Default',
                    service_key TEXT,
                    display_order INTEGER DEFAULT 0,
                    enabled INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS status_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    severity TEXT DEFAULT 'minor',
                    status TEXT DEFAULT 'investigating',
                    created_at INTEGER,
                    resolved_at INTEGER,
                    created_by TEXT,
                    assigned_to TEXT
                );

                CREATE TABLE IF NOT EXISTS status_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL REFERENCES status_incidents(id),
                    message TEXT NOT NULL,
                    status TEXT DEFAULT 'investigating',
                    created_at INTEGER,
                    created_by TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_status_updates_incident
                    ON status_updates(incident_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS incident_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL,
                    author TEXT NOT NULL,
                    message TEXT NOT NULL,
                    msg_type TEXT DEFAULT 'comment',
                    created_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_incident_messages_incident
                    ON incident_messages(incident_id, created_at ASC);

                CREATE TABLE IF NOT EXISTS service_dependencies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_service TEXT NOT NULL,
                    target_service TEXT NOT NULL,
                    dependency_type TEXT DEFAULT 'requires',
                    auto_discovered INTEGER DEFAULT 0,
                    created_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_svc_deps_source
                    ON service_dependencies(source_service);
                CREATE INDEX IF NOT EXISTS idx_svc_deps_target
                    ON service_dependencies(target_service);

                CREATE TABLE IF NOT EXISTS user_preferences (
                    username TEXT PRIMARY KEY,
                    preferences_json TEXT DEFAULT '{}',
                    updated_at INTEGER
                );

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

                CREATE TABLE IF NOT EXISTS config_baselines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    expected_hash TEXT NOT NULL,
                    agent_group TEXT DEFAULT '__all__',
                    created_at INTEGER,
                    updated_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS drift_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    baseline_id INTEGER NOT NULL REFERENCES config_baselines(id),
                    hostname TEXT NOT NULL,
                    actual_hash TEXT,
                    status TEXT DEFAULT 'match',
                    checked_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_drift_checks_baseline
                    ON drift_checks(baseline_id, checked_at DESC);
                CREATE INDEX IF NOT EXISTS idx_drift_checks_hostname
                    ON drift_checks(hostname, checked_at DESC);

                CREATE TABLE IF NOT EXISTS network_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip TEXT NOT NULL,
                    mac TEXT,
                    hostname TEXT,
                    vendor TEXT,
                    open_ports TEXT,
                    discovered_by TEXT,
                    first_seen INTEGER,
                    last_seen INTEGER,
                    UNIQUE(ip, mac)
                );
                CREATE INDEX IF NOT EXISTS idx_network_devices_ip
                    ON network_devices(ip);

                CREATE TABLE IF NOT EXISTS webhook_endpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    hook_id TEXT UNIQUE NOT NULL,
                    secret TEXT NOT NULL,
                    automation_id TEXT,
                    enabled INTEGER DEFAULT 1,
                    last_triggered INTEGER,
                    trigger_count INTEGER DEFAULT 0,
                    created_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS backup_verifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backup_path TEXT NOT NULL,
                    hostname TEXT NOT NULL,
                    verification_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details TEXT,
                    verified_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_backup_verif_host
                    ON backup_verifications(hostname, verified_at DESC);

                CREATE TABLE IF NOT EXISTS backup_321_status (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backup_name TEXT NOT NULL UNIQUE,
                    copies INTEGER DEFAULT 0,
                    media_types TEXT DEFAULT '[]',
                    has_offsite INTEGER DEFAULT 0,
                    last_verified INTEGER,
                    updated_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS approval_queue (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    automation_id   TEXT NOT NULL,
                    run_id          INTEGER,
                    trigger         TEXT NOT NULL,
                    trigger_source  TEXT,
                    action_type     TEXT NOT NULL,
                    action_params   TEXT NOT NULL DEFAULT '{}',
                    target          TEXT,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    requested_at    INTEGER NOT NULL,
                    requested_by    TEXT,
                    decided_at      INTEGER,
                    decided_by      TEXT,
                    auto_approve_at INTEGER,
                    result          TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_approval_queue_status
                    ON approval_queue(status, requested_at DESC);

                CREATE TABLE IF NOT EXISTS maintenance_windows (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    name              TEXT NOT NULL,
                    schedule          TEXT,
                    duration_min      INTEGER NOT NULL DEFAULT 60,
                    one_off_start     INTEGER,
                    one_off_end       INTEGER,
                    suppress_alerts   INTEGER NOT NULL DEFAULT 1,
                    override_autonomy TEXT,
                    auto_close_alerts INTEGER NOT NULL DEFAULT 0,
                    enabled           INTEGER NOT NULL DEFAULT 1,
                    created_by        TEXT,
                    created_at        INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_maint_windows_enabled
                    ON maintenance_windows(enabled);

                CREATE TABLE IF NOT EXISTS action_audit (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       INTEGER NOT NULL,
                    trigger_type    TEXT NOT NULL,
                    trigger_id      TEXT,
                    action_type     TEXT NOT NULL,
                    action_params   TEXT,
                    target          TEXT,
                    outcome         TEXT NOT NULL,
                    duration_s      REAL,
                    output          TEXT,
                    approved_by     TEXT,
                    rollback_result TEXT,
                    error           TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_action_audit_ts
                    ON action_audit(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_action_audit_trigger_type
                    ON action_audit(trigger_type);
                CREATE INDEX IF NOT EXISTS idx_action_audit_outcome
                    ON action_audit(outcome);

                CREATE TABLE IF NOT EXISTS endpoint_check_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    monitor_id  INTEGER NOT NULL,
                    timestamp   INTEGER NOT NULL,
                    status      TEXT NOT NULL,
                    response_ms INTEGER,
                    error       TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_ech_monitor_ts
                    ON endpoint_check_history(monitor_id, timestamp);

                CREATE TABLE IF NOT EXISTS playbook_templates (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    description TEXT,
                    category    TEXT,
                    config      TEXT NOT NULL,
                    version     INTEGER NOT NULL DEFAULT 1
                );
            """)
            # Migrate existing databases: add assigned_to column if missing
            try:
                cols = [row[1] for row in conn.execute(
                    "PRAGMA table_info(status_incidents)").fetchall()]
                if "assigned_to" not in cols:
                    conn.execute(
                        "ALTER TABLE status_incidents ADD COLUMN assigned_to TEXT")
                    conn.commit()
            except Exception:
                pass
            # Migrate approval_queue: add workflow_context column if missing
            try:
                conn.execute("ALTER TABLE approval_queue ADD COLUMN workflow_context TEXT")
                conn.commit()
            except Exception:
                pass  # Column already exists
        # Seed default playbook templates (outside the with-lock block so
        # _seed_default_playbooks can acquire the lock itself without deadlocking)
        _seed_default_playbooks(self._get_conn(), self._lock)

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

    # ── User Preferences (Feature 10: Multi-user Dashboard Views) ────────────
    def get_user_preferences(self, username: str) -> dict | None:
        return _get_user_preferences(self._get_conn(), self._lock, username)

    def save_user_preferences(self, username: str, preferences: dict) -> bool:
        return _save_user_preferences(self._get_conn(), self._lock, username, preferences)

    def delete_user_preferences(self, username: str) -> bool:
        return _delete_user_preferences(self._get_conn(), self._lock, username)

    # ── Incidents ─────────────────────────────────────────────────────────────
    def insert_incident(self, severity: str, source: str, title: str, details: str = "") -> int:
        return _insert_incident(self._get_conn(), self._lock, severity, source, title,
                                details=details)

    def get_incidents(self, limit: int = 100, hours: int = 24) -> list[dict]:
        return _get_incidents(self._get_conn(), self._lock, limit=limit, hours=hours)

    def resolve_incident(self, incident_id: int) -> bool:
        return _resolve_incident(self._get_conn(), self._lock, incident_id)

    # ── Agent Registry ────────────────────────────────────────────────────────
    def upsert_agent(self, hostname: str, ip: str, platform_name: str,
                     arch: str, agent_version: str) -> None:
        _upsert_agent(self._get_conn(), self._lock, hostname, ip, platform_name, arch, agent_version)

    def get_all_agents(self) -> list[dict]:
        return _get_all_agents(self._get_conn(), self._lock)

    def delete_agent(self, hostname: str) -> None:
        _delete_agent(self._get_conn(), self._lock, hostname)

    def update_agent_config(self, hostname: str, config: dict) -> None:
        _update_agent_config(self._get_conn(), self._lock, hostname, config)

    # ── Agent Command History (Phase 1d) ─────────────────────────────────────
    def record_command(self, cmd_id: str, hostname: str, cmd_type: str,
                       params: dict, queued_by: str) -> None:
        """Record a newly queued agent command."""
        import json
        import time
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
        import json
        import time
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
        import json
        try:
            clauses: list[str] = []
            params: list = []
            if hostname:
                clauses.append("hostname = ?")
                params.append(hostname)
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            with self._lock:
                conn = self._get_conn()
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

    # ── Endpoint Monitors ────────────────────────────────────────────────────
    def create_endpoint_monitor(self, name: str, url: str, **kwargs) -> int | None:
        return _create_monitor(self._get_conn(), self._lock, name, url, **kwargs)

    def get_endpoint_monitors(self, *, enabled_only: bool = False) -> list[dict]:
        return _get_monitors(self._get_conn(), self._lock, enabled_only=enabled_only)

    def get_endpoint_monitor(self, monitor_id: int) -> dict | None:
        return _get_monitor(self._get_conn(), self._lock, monitor_id)

    def update_endpoint_monitor(self, monitor_id: int, **kwargs) -> bool:
        return _update_monitor(self._get_conn(), self._lock, monitor_id, **kwargs)

    def delete_endpoint_monitor(self, monitor_id: int) -> bool:
        return _delete_monitor(self._get_conn(), self._lock, monitor_id)

    def record_endpoint_check(self, monitor_id: int, **kwargs) -> None:
        _record_check_result(self._get_conn(), self._lock, monitor_id, **kwargs)

    def get_due_endpoint_monitors(self) -> list[dict]:
        return _get_due_monitors(self._get_conn(), self._lock)

    def record_endpoint_check_history(self, monitor_id: int, status: str,
                                       response_ms: int | None = None,
                                       error: str | None = None) -> None:
        _record_endpoint_check_history(self._get_conn(), self._lock,
                                       monitor_id, status,
                                       response_ms=response_ms, error=error)

    def get_endpoint_check_history(self, monitor_id: int,
                                    hours: int = 720) -> list[dict]:
        return _get_endpoint_check_history(self._get_conn(), self._lock,
                                           monitor_id, hours=hours)

    def get_endpoint_uptime(self, monitor_id: int, hours: int = 720) -> float:
        return _get_endpoint_uptime(self._get_conn(), self._lock,
                                    monitor_id, hours=hours)

    def get_endpoint_avg_latency(self, monitor_id: int,
                                  hours: int = 720) -> float | None:
        return _get_endpoint_avg_latency(self._get_conn(), self._lock,
                                         monitor_id, hours=hours)

    def prune_endpoint_check_history(self, days: int = 90) -> None:
        _prune_endpoint_check_history(self._get_conn(), self._lock, days=days)

    # ── Custom Dashboards ────────────────────────────────────────────────────
    def create_dashboard(self, name: str, owner: str, config_json: str,
                         *, shared: bool = False) -> int | None:
        return _create_dashboard(self._get_conn(), self._lock, name, owner,
                                 config_json, shared=shared)

    def get_dashboards(self, owner: str | None = None) -> list[dict]:
        return _get_dashboards(self._get_conn(), self._lock, owner=owner)

    def get_dashboard(self, dashboard_id: int) -> dict | None:
        return _get_dashboard(self._get_conn(), self._lock, dashboard_id)

    def update_dashboard(self, dashboard_id: int, **kwargs) -> bool:
        return _update_dashboard(self._get_conn(), self._lock, dashboard_id, **kwargs)

    def delete_dashboard(self, dashboard_id: int) -> bool:
        return _delete_dashboard(self._get_conn(), self._lock, dashboard_id)

    # ── Status Page ──────────────────────────────────────────────────────────
    def create_status_component(self, name: str, group_name: str = "Default",
                                service_key: str | None = None,
                                display_order: int = 0) -> int:
        return _create_status_component(self._get_conn(), self._lock, name,
                                        group_name=group_name, service_key=service_key,
                                        display_order=display_order)

    def list_status_components(self) -> list[dict]:
        return _list_status_components(self._get_conn(), self._lock)

    def update_status_component(self, comp_id: int, **kwargs) -> bool:
        return _update_status_component(self._get_conn(), self._lock, comp_id, **kwargs)

    def delete_status_component(self, comp_id: int) -> bool:
        return _delete_status_component(self._get_conn(), self._lock, comp_id)

    def create_status_incident(self, title: str, severity: str = "minor",
                               message: str = "", created_by: str = "") -> int:
        return _create_status_incident(self._get_conn(), self._lock, title,
                                       severity=severity, message=message,
                                       created_by=created_by)

    def list_status_incidents(self, limit: int = 50,
                              include_resolved: bool = True) -> list[dict]:
        return _list_status_incidents(self._get_conn(), self._lock, limit=limit,
                                      include_resolved=include_resolved)

    def get_status_incident(self, incident_id: int) -> dict | None:
        return _get_status_incident(self._get_conn(), self._lock, incident_id)

    def update_status_incident(self, incident_id: int, **kwargs) -> bool:
        return _update_status_incident(self._get_conn(), self._lock, incident_id, **kwargs)

    def add_status_update(self, incident_id: int, message: str,
                          status: str = "investigating",
                          created_by: str = "") -> int:
        return _add_status_update(self._get_conn(), self._lock, incident_id,
                                  message, status=status, created_by=created_by)

    def resolve_status_incident(self, incident_id: int,
                                created_by: str = "") -> bool:
        return _resolve_status_incident(self._get_conn(), self._lock, incident_id,
                                        created_by=created_by)

    def get_status_uptime_history(self, days: int = 90) -> list[dict]:
        return _get_status_uptime_history(self._get_conn(), self._lock, days=days)

    # ── Incident War Room ────────────────────────────────────────────────────
    def add_incident_message(self, incident_id: int, author: str,
                             message: str, msg_type: str = "comment") -> int:
        return _add_incident_message(self._get_conn(), self._lock, incident_id,
                                     author, message, msg_type=msg_type)

    def get_incident_messages(self, incident_id: int,
                              limit: int = 200) -> list[dict]:
        return _get_incident_messages(self._get_conn(), self._lock, incident_id,
                                      limit=limit)

    def assign_incident(self, incident_id: int, assigned_to: str) -> bool:
        return _assign_incident(self._get_conn(), self._lock, incident_id,
                                assigned_to)

    # ── Security Posture Scoring ────────────────────────────────────────────
    def record_security_scan(self, hostname: str, score: int,
                             findings: list[dict]) -> int | None:
        return _record_scan(self._get_conn(), self._lock, hostname, score, findings)

    def get_security_scores(self) -> list[dict]:
        return _get_latest_scores(self._get_conn(), self._lock)

    def get_security_findings(self, hostname: str | None = None,
                              severity: str | None = None,
                              limit: int = 200) -> list[dict]:
        return _get_findings(self._get_conn(), self._lock,
                             hostname=hostname, severity=severity, limit=limit)

    def get_aggregate_security_score(self) -> dict:
        return _get_aggregate_score(self._get_conn(), self._lock)

    def get_security_score_history(self, hostname: str | None = None,
                                   limit: int = 50) -> list[dict]:
        return _get_score_history(self._get_conn(), self._lock,
                                  hostname=hostname, limit=limit)

    # ── Service Dependencies ─────────────────────────────────────────────────
    def create_dependency(self, source: str, target: str, *,
                          dependency_type: str = "requires",
                          auto_discovered: bool = False) -> int | None:
        return _create_dependency(self._get_conn(), self._lock, source, target,
                                  dependency_type=dependency_type,
                                  auto_discovered=auto_discovered)

    def list_dependencies(self) -> list[dict]:
        return _list_dependencies(self._get_conn(), self._lock)

    def delete_dependency(self, dep_id: int) -> bool:
        return _delete_dependency(self._get_conn(), self._lock, dep_id)

    def get_impact_analysis(self, service_name: str) -> list[str]:
        return _get_impact_analysis(self._get_conn(), self._lock, service_name)

    # ── Config Baselines / Drift Detection ───────────────────────────────────
    def create_baseline(self, path: str, expected_hash: str,
                        agent_group: str = "__all__") -> int | None:
        return _create_baseline(self._get_conn(), self._lock, path, expected_hash,
                                agent_group=agent_group)

    def list_baselines(self) -> list[dict]:
        return _list_baselines(self._get_conn(), self._lock)

    def get_baseline(self, baseline_id: int) -> dict | None:
        return _get_baseline(self._get_conn(), self._lock, baseline_id)

    def delete_baseline(self, baseline_id: int) -> bool:
        return _delete_baseline(self._get_conn(), self._lock, baseline_id)

    def update_baseline(self, baseline_id: int, expected_hash: str) -> bool:
        return _update_baseline(self._get_conn(), self._lock, baseline_id, expected_hash)

    def record_drift_check(self, baseline_id: int, hostname: str,
                           actual_hash: str | None, status: str = "match") -> int | None:
        return _record_drift_check(self._get_conn(), self._lock, baseline_id,
                                   hostname, actual_hash, status=status)

    def get_drift_results(self, baseline_id: int | None = None) -> list[dict]:
        return _get_drift_results(self._get_conn(), self._lock, baseline_id=baseline_id)

    # ── Network Devices ──────────────────────────────────────────────────
    def upsert_network_device(self, ip: str, mac: str | None = None,
                              hostname: str | None = None,
                              vendor: str | None = None,
                              open_ports: list[int] | None = None,
                              discovered_by: str | None = None) -> int | None:
        from .network import upsert_device
        return upsert_device(self._get_conn(), self._lock, ip, mac=mac,
                             hostname=hostname, vendor=vendor,
                             open_ports=open_ports, discovered_by=discovered_by)

    def list_network_devices(self) -> list[dict]:
        from .network import list_devices
        return list_devices(self._get_conn(), self._lock)

    def get_network_device(self, device_id: int) -> dict | None:
        from .network import get_device
        return get_device(self._get_conn(), self._lock, device_id)

    def delete_network_device(self, device_id: int) -> bool:
        from .network import delete_device
        return delete_device(self._get_conn(), self._lock, device_id)

    # ── Webhook Endpoints (Feature 8) ────────────────────────────────────
    def create_webhook(self, name: str, hook_id: str, secret: str,
                       automation_id: str | None = None) -> int | None:
        return _create_webhook(self._get_conn(), self._lock, name, hook_id, secret,
                               automation_id=automation_id)

    def list_webhooks(self) -> list[dict]:
        return _list_webhooks(self._get_conn(), self._lock)

    def get_webhook_by_hook_id(self, hook_id: str) -> dict | None:
        return _get_webhook_by_hook_id(self._get_conn(), self._lock, hook_id)

    def delete_webhook(self, webhook_id: int) -> bool:
        return _delete_webhook(self._get_conn(), self._lock, webhook_id)

    def record_webhook_trigger(self, webhook_id: int) -> None:
        _record_trigger(self._get_conn(), self._lock, webhook_id)

    # ── Backup Verification (Feature 4) ─────────────────────────────────
    def record_backup_verification(
        self, backup_path: str, hostname: str, verification_type: str,
        status: str, details: str | None = None,
    ) -> int | None:
        return _record_verification(
            self._get_conn(), self._lock, backup_path, hostname,
            verification_type, status, details=details,
        )

    def list_backup_verifications(
        self, hostname: str | None = None, limit: int = 100,
    ) -> list[dict]:
        return _list_verifications(
            self._get_conn(), self._lock, hostname=hostname, limit=limit,
        )

    def get_backup_321_status(self) -> list[dict]:
        return _get_321_status(self._get_conn(), self._lock)

    def update_backup_321_status(
        self, backup_name: str, *,
        copies: int | None = None,
        media_types: list[str] | None = None,
        has_offsite: bool | None = None,
        last_verified: int | None = None,
    ) -> int | None:
        return _update_321_status(
            self._get_conn(), self._lock, backup_name,
            copies=copies, media_types=media_types,
            has_offsite=has_offsite, last_verified=last_verified,
        )

    # ── Approval Queue ────────────────────────────────────────────────────────
    def insert_approval(self, **kwargs) -> int | None:
        return _insert_approval(self._get_conn(), self._lock, **kwargs)

    def list_approvals(self, status: str = "pending") -> list[dict]:
        return _list_approvals(self._get_conn(), self._lock, status)

    def get_approval(self, approval_id: int) -> dict | None:
        return _get_approval(self._get_conn(), self._lock, approval_id)

    def decide_approval(self, approval_id: int, decision: str,
                        decided_by: str) -> bool:
        return _decide_approval(self._get_conn(), self._lock,
                                approval_id, decision, decided_by)

    def update_approval_result(self, approval_id: int, result: str) -> None:
        _update_approval_result(self._get_conn(), self._lock, approval_id, result)

    def auto_approve_expired(self) -> int:
        return _auto_approve_expired(self._get_conn(), self._lock)

    def count_pending_approvals(self) -> int:
        return _count_pending_approvals(self._get_conn(), self._lock)

    def save_workflow_context(self, approval_id: int, context: dict) -> bool:
        return _save_workflow_context(self._get_conn(), self._lock, approval_id, context)

    def get_workflow_context(self, approval_id: int) -> dict | None:
        return _get_workflow_context(self._get_conn(), self._lock, approval_id)

    # ── Maintenance Windows ───────────────────────────────────────────────────
    def insert_maintenance_window(self, **kwargs) -> int | None:
        return _insert_maintenance_window(self._get_conn(), self._lock, **kwargs)

    def list_maintenance_windows(self) -> list[dict]:
        return _list_maintenance_windows(self._get_conn(), self._lock)

    def update_maintenance_window(self, window_id: int, **kwargs) -> bool:
        return _update_maintenance_window(self._get_conn(), self._lock,
                                          window_id, **kwargs)

    def delete_maintenance_window(self, window_id: int) -> bool:
        return _delete_maintenance_window(self._get_conn(), self._lock, window_id)

    def get_active_maintenance_windows(self) -> list[dict]:
        return _get_active_maintenance_windows(self._get_conn(), self._lock)

    # ── Action Audit Trail ────────────────────────────────────────────────────
    def insert_action_audit(
        self,
        trigger_type: str,
        trigger_id: str | None,
        action_type: str,
        action_params: dict | None,
        target: str | None,
        outcome: str,
        duration_s: float | None = None,
        output: str | None = None,
        approved_by: str | None = None,
        rollback_result: str | None = None,
        error: str | None = None,
    ) -> int | None:
        return _insert_action_audit(
            self._get_conn(), self._lock,
            trigger_type, trigger_id, action_type, action_params,
            target, outcome, duration_s=duration_s, output=output,
            approved_by=approved_by, rollback_result=rollback_result,
            error=error,
        )

    def get_action_audit(
        self,
        limit: int = 100,
        trigger_type: str | None = None,
        outcome: str | None = None,
    ) -> list[dict]:
        return _get_action_audit(
            self._get_conn(), self._lock,
            limit=limit, trigger_type=trigger_type, outcome=outcome,
        )

    # ── Playbook Templates ────────────────────────────────────────────────────
    def list_playbook_templates(self) -> list[dict]:
        return _list_playbook_templates(self._get_conn(), self._lock)

    def get_playbook_template(self, template_id: str) -> dict | None:
        return _get_playbook_template(self._get_conn(), self._lock, template_id)

    def upsert_playbook_template(
        self,
        template_id: str,
        name: str,
        description: str | None,
        category: str | None,
        config: dict,
        version: int = 1,
    ) -> bool:
        return _upsert_playbook_template(
            self._get_conn(), self._lock,
            template_id, name, description, category, config, version=version,
        )
