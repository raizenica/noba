# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Thread-safe SQLite database layer (core)."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading

from ..config import HISTORY_DB
from . import (
    agents,
    alerts,
    api_keys,
    audit,
    automations,
    backup_verify,
    baselines,
    dashboards,
    dependencies,
    endpoints,
    healing,
    integrations,
    linked_providers,
    metrics,
    network,
    notifications,
    security,
    status_page,
    tokens,
    user_dashboards,
    user_preferences,
    webhooks,
)
from .agents import _AgentsMixin
from .alerts import _AlertsMixin
from .api_keys import _ApiKeysMixin
from .audit import _AuditMixin
from .automations import _ApprovalsMixin, _AutomationsMixin
from .backup_verify import _BackupVerifyMixin
from .baselines import _BaselinesMixin
from .dashboards import _DashboardsMixin
from .dependencies import _DependenciesMixin
from .endpoints import _EndpointsMixin
from .healing import _HealingMixin
from .integrations import _IntegrationsMixin
from .linked_providers import _LinkedProvidersMixin
from .metrics import _MetricsMixin
from .notifications import _NotificationsMixin
from .security import _SecurityMixin
from .status_page import _StatusPageMixin
from .tokens import _TokensMixin
from .user_dashboards import _UserDashboardsMixin
from .user_preferences import _UserPreferencesMixin
from .webhooks import _WebhooksMixin

logger = logging.getLogger("noba")

_SCHEMA_MODULES = [
    metrics, audit, automations, alerts, api_keys, tokens,
    notifications, user_dashboards, user_preferences, agents,
    endpoints, dashboards, status_page, security, dependencies,
    baselines, network, webhooks, backup_verify, healing,
    integrations, linked_providers,
]


def _run_alter_migrations(conn: sqlite3.Connection) -> None:
    """Idempotent additive column migrations. Swallows OperationalError
    ('duplicate column name') so they are safe to run on every startup."""
    migrations = [
        "ALTER TABLE status_incidents ADD COLUMN assigned_to TEXT",
        "ALTER TABLE approval_queue ADD COLUMN workflow_context TEXT",
        "ALTER TABLE integration_instances ADD COLUMN verify_ssl INTEGER DEFAULT 1",
        "ALTER TABLE integration_instances ADD COLUMN ca_bundle TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN risk_level TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN snapshot_id INTEGER",
        "ALTER TABLE heal_ledger ADD COLUMN rollback_status TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN dependency_root TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN suppressed_by TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN maintenance_window_id INTEGER",
        "ALTER TABLE heal_ledger ADD COLUMN instance_id TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise


class DatabaseBase:
    """Connection management, schema init, and WAL checkpoint. No domain logic."""

    def __init__(self, path: str = HISTORY_DB) -> None:
        self._path = path
        self._lock = threading.RLock()      # write lock (RLock for reentrancy with migrations)
        self._read_lock = threading.Lock()  # read lock (protects read conn)
        self._conn: sqlite3.Connection | None = None
        self._read_conn: sqlite3.Connection | None = None
        parent = os.path.dirname(self._path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Return persistent write connection, creating if needed.

        WARNING: Callers MUST hold self._lock for writes, or use
        execute_write()/transaction() which handle locking automatically.
        """
        if self._conn is None:
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            cur_av = self._conn.execute("PRAGMA auto_vacuum;").fetchone()[0]
            if cur_av != 2:  # 2 = INCREMENTAL
                self._conn.execute("PRAGMA auto_vacuum=INCREMENTAL;")
                self._conn.execute("VACUUM;")  # one-time migration to enable it
        return self._conn

    def _get_read_conn(self) -> sqlite3.Connection:
        """Return a read-only connection for concurrent reads.

        For in-memory databases (:memory:), falls back to the write
        connection since each :memory: connect() creates a separate DB.
        """
        if self._path == ":memory:":
            return self._get_conn()
        if self._read_conn is None:
            self._read_conn = sqlite3.connect(
                self._path, check_same_thread=False,
                isolation_level=None,  # autocommit: each SELECT sees latest data
            )
            self._read_conn.execute("PRAGMA journal_mode=WAL;")
            self._read_conn.execute("PRAGMA synchronous=NORMAL;")
            self._read_conn.execute("PRAGMA busy_timeout=5000;")
            self._read_conn.execute("PRAGMA foreign_keys=ON;")
            self._read_conn.execute("PRAGMA query_only=ON;")  # safety: prevent writes
        return self._read_conn

    def execute_read(self, fn):
        """Execute a read operation without acquiring the write lock."""
        conn = self._get_read_conn()
        return fn(conn)

    def execute_write(self, fn):
        """Execute a write operation with proper lock + connection isolation."""
        with self._lock:
            conn = self._get_conn()
            result = fn(conn)
            conn.commit()
            return result

    def transaction(self, fn):
        """Execute multiple operations in a single atomic transaction."""
        with self._lock:
            conn = self._get_conn()
            try:
                result = fn(conn)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._get_conn()
            for mod in _SCHEMA_MODULES:
                mod.init_schema(conn)
            _run_alter_migrations(conn)
            conn.commit()
        # Seed default playbook templates outside the lock block to avoid deadlock
        automations._seed_default_playbooks(self._get_conn(), self._lock)

    def wal_checkpoint(self) -> None:
        """Run WAL checkpoint. Safe to call from cleanup loop."""
        with self._lock:
            self._get_conn().execute("PRAGMA wal_checkpoint(TRUNCATE);")


class Database(
    DatabaseBase,
    _MetricsMixin, _AuditMixin, _AutomationsMixin, _AlertsMixin,
    _ApiKeysMixin, _TokensMixin, _NotificationsMixin, _UserDashboardsMixin,
    _UserPreferencesMixin, _AgentsMixin, _EndpointsMixin,
    _DashboardsMixin, _StatusPageMixin, _SecurityMixin, _DependenciesMixin,
    _BaselinesMixin, _WebhooksMixin, _BackupVerifyMixin,
    _ApprovalsMixin, _HealingMixin, _IntegrationsMixin, _LinkedProvidersMixin,
):
    """Thread-safe SQLite database with all domain methods via mixins."""

    # Network delegation methods (no mixin per spec)
    def upsert_network_device(self, ip: str, mac: str | None = None,
                              hostname: str | None = None,
                              vendor: str | None = None,
                              open_ports: list[int] | None = None,
                              discovered_by: str | None = None) -> int | None:
        return network.upsert_device(self._get_conn(), self._lock, ip, mac=mac,
                                     hostname=hostname, vendor=vendor,
                                     open_ports=open_ports, discovered_by=discovered_by)

    def list_network_devices(self) -> list[dict]:
        return network.list_devices(self._get_read_conn(), self._read_lock)

    def get_network_device(self, device_id: int) -> dict | None:
        return network.get_device(self._get_read_conn(), self._read_lock, device_id)

    def delete_network_device(self, device_id: int) -> bool:
        return network.delete_device(self._get_conn(), self._lock, device_id)
