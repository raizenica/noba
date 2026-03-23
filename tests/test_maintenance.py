"""Tests for healing.maintenance: maintenance window management."""
from __future__ import annotations

import sqlite3
import threading
import time

import pytest


@pytest.fixture()
def maint_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS heal_maintenance_windows (
            id INTEGER PRIMARY KEY,
            target TEXT NOT NULL,
            cron_expr TEXT,
            duration_s INTEGER NOT NULL,
            reason TEXT,
            action TEXT NOT NULL DEFAULT 'suppress',
            active INTEGER NOT NULL DEFAULT 1,
            created_by TEXT,
            created_at INTEGER NOT NULL,
            expires_at INTEGER
        );
    """)
    return conn, lock


class TestMaintenanceManager:
    def test_no_active_windows(self, maint_db):
        from server.healing.maintenance import MaintenanceManager
        mgr = MaintenanceManager(maint_db[0], maint_db[1])
        assert not mgr.is_in_maintenance("plex")

    def test_create_adhoc_window(self, maint_db):
        from server.healing.maintenance import MaintenanceManager
        mgr = MaintenanceManager(maint_db[0], maint_db[1])
        wid = mgr.create_window(target="plex", duration_s=3600, reason="deploy",
                                action="suppress", created_by="admin")
        assert wid is not None
        assert mgr.is_in_maintenance("plex")

    def test_global_window_blocks_all(self, maint_db):
        from server.healing.maintenance import MaintenanceManager
        mgr = MaintenanceManager(maint_db[0], maint_db[1])
        mgr.create_window(target="all", duration_s=3600, reason="backup",
                          action="suppress_all", created_by="admin")
        assert mgr.is_in_maintenance("plex")
        assert mgr.is_in_maintenance("truenas")
        assert mgr.is_in_maintenance("anything")

    def test_per_target_window_only_blocks_target(self, maint_db):
        from server.healing.maintenance import MaintenanceManager
        mgr = MaintenanceManager(maint_db[0], maint_db[1])
        mgr.create_window(target="plex", duration_s=3600, reason="update",
                          action="suppress", created_by="admin")
        assert mgr.is_in_maintenance("plex")
        assert not mgr.is_in_maintenance("truenas")

    def test_expired_window_not_active(self, maint_db):
        from server.healing.maintenance import MaintenanceManager
        conn, lock = maint_db
        # Insert already-expired window
        now = int(time.time())
        with lock:
            conn.execute(
                "INSERT INTO heal_maintenance_windows (target, duration_s, reason, action, active, created_at, expires_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                ("plex", 60, "test", "suppress", now - 120, now - 60),
            )
            conn.commit()
        mgr = MaintenanceManager(conn, lock)
        assert not mgr.is_in_maintenance("plex")

    def test_end_window_early(self, maint_db):
        from server.healing.maintenance import MaintenanceManager
        mgr = MaintenanceManager(maint_db[0], maint_db[1])
        wid = mgr.create_window(target="plex", duration_s=3600, reason="deploy",
                                action="suppress", created_by="admin")
        mgr.end_window(wid)
        assert not mgr.is_in_maintenance("plex")

    def test_list_active_windows(self, maint_db):
        from server.healing.maintenance import MaintenanceManager
        mgr = MaintenanceManager(maint_db[0], maint_db[1])
        mgr.create_window(target="plex", duration_s=3600, reason="a",
                          action="suppress", created_by="admin")
        mgr.create_window(target="truenas", duration_s=3600, reason="b",
                          action="suppress", created_by="admin")
        windows = mgr.get_active_windows()
        assert len(windows) == 2

    def test_get_window_action(self, maint_db):
        from server.healing.maintenance import MaintenanceManager
        mgr = MaintenanceManager(maint_db[0], maint_db[1])
        mgr.create_window(target="plex", duration_s=3600, reason="deploy",
                          action="queue", created_by="admin")
        action = mgr.get_maintenance_action("plex")
        assert action == "queue"

    def test_no_maintenance_returns_none_action(self, maint_db):
        from server.healing.maintenance import MaintenanceManager
        mgr = MaintenanceManager(maint_db[0], maint_db[1])
        assert mgr.get_maintenance_action("plex") is None
