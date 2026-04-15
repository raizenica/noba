# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing.snapshots: state capture and rollback."""
from __future__ import annotations

import json
import sqlite3
import threading

import pytest
from unittest.mock import patch


@pytest.fixture()
def snap_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS heal_snapshots (
            id INTEGER PRIMARY KEY,
            ledger_id INTEGER,
            target TEXT NOT NULL,
            action_type TEXT NOT NULL,
            state TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
    """)
    return conn, lock


class TestSnapshotCapture:
    def test_capture_returns_snapshot_dict(self):
        from server.healing.snapshots import capture_snapshot
        # Mock the state fetcher since we can't query docker in tests
        with patch("server.healing.snapshots._fetch_target_state") as mock_fetch:
            mock_fetch.return_value = {"memory": "2g", "cpus": "2.0", "status": "running"}
            snap = capture_snapshot("frigate", "scale_container", {"container": "frigate"})
            assert snap is not None
            assert snap["target"] == "frigate"
            assert snap["action_type"] == "scale_container"
            assert "state" in snap
            assert snap["state"]["memory"] == "2g"

    def test_capture_with_fetch_failure_returns_empty_state(self):
        from server.healing.snapshots import capture_snapshot
        with patch("server.healing.snapshots._fetch_target_state") as mock_fetch:
            mock_fetch.return_value = {}
            snap = capture_snapshot("broken", "service_restart", {})
            assert snap is not None
            assert snap["state"] == {}


class TestSnapshotStorage:
    def test_store_and_retrieve(self, snap_db):
        from server.healing.snapshots import store_snapshot, get_snapshot
        conn, lock = snap_db
        snap_id = store_snapshot(conn, lock, ledger_id=42, target="frigate",
                                action_type="scale_container",
                                state=json.dumps({"memory": "2g"}))
        assert snap_id is not None
        retrieved = get_snapshot(conn, lock, snap_id)
        assert retrieved is not None
        assert retrieved["target"] == "frigate"
        assert "memory" in retrieved["state"]

    def test_get_by_ledger_id(self, snap_db):
        from server.healing.snapshots import store_snapshot, get_snapshot_by_ledger
        conn, lock = snap_db
        store_snapshot(conn, lock, ledger_id=99, target="plex",
                      action_type="restart_container",
                      state=json.dumps({"status": "running"}))
        retrieved = get_snapshot_by_ledger(conn, lock, 99)
        assert retrieved is not None
        assert retrieved["target"] == "plex"

    def test_get_nonexistent_returns_none(self, snap_db):
        from server.healing.snapshots import get_snapshot
        conn, lock = snap_db
        assert get_snapshot(conn, lock, 999) is None


class TestReversibility:
    def test_reversible_action(self):
        from server.healing.snapshots import is_reversible
        assert is_reversible("scale_container") is True

    def test_irreversible_action(self):
        from server.healing.snapshots import is_reversible
        assert is_reversible("process_kill") is False
        assert is_reversible("clear_cache") is False
        assert is_reversible("host_reboot") is False

    def test_unknown_action_is_irreversible(self):
        from server.healing.snapshots import is_reversible
        assert is_reversible("nonexistent_action") is False


class TestRollback:
    def test_rollback_returns_result(self):
        from server.healing.snapshots import execute_rollback
        with patch("server.healing.snapshots._execute_reverse_action") as mock_exec:
            mock_exec.return_value = {"success": True, "output": "rolled back"}
            result = execute_rollback(
                action_type="scale_container",
                target="frigate",
                snapshot_state={"memory": "2g", "cpus": "2.0"},
            )
            assert result["success"] is True

    def test_rollback_irreversible_returns_error(self):
        from server.healing.snapshots import execute_rollback
        result = execute_rollback(
            action_type="process_kill",
            target="runaway",
            snapshot_state={},
        )
        assert result["success"] is False
        assert "irreversible" in result.get("error", "").lower()
