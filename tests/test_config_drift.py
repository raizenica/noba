# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for configuration drift detection: DB CRUD + drift checks."""
from __future__ import annotations

import os
import sys
import tempfile

# Ensure server package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-web"))

from server.db import Database


def _make_db():
    """Create a fresh temp DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_drifttest_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


# ── Baseline CRUD Tests ──────────────────────────────────────────────────────

class TestBaselineCRUD:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_create_and_list(self):
        bid = self.db.create_baseline("/etc/resolv.conf", "abc123")
        assert bid is not None
        assert isinstance(bid, int)
        baselines = self.db.list_baselines()
        assert len(baselines) == 1
        assert baselines[0]["path"] == "/etc/resolv.conf"
        assert baselines[0]["expected_hash"] == "abc123"
        assert baselines[0]["agent_group"] == "__all__"
        assert baselines[0]["status"] == "pending"

    def test_create_with_group(self):
        bid = self.db.create_baseline("/etc/hostname", "def456",
                                      agent_group="web-servers")
        assert bid is not None
        b = self.db.get_baseline(bid)
        assert b is not None
        assert b["agent_group"] == "web-servers"

    def test_get_single_baseline(self):
        bid = self.db.create_baseline("/etc/hosts", "hash1")
        b = self.db.get_baseline(bid)
        assert b is not None
        assert b["path"] == "/etc/hosts"

    def test_get_nonexistent_returns_none(self):
        assert self.db.get_baseline(9999) is None

    def test_update_baseline(self):
        bid = self.db.create_baseline("/etc/resolv.conf", "oldhash")
        ok = self.db.update_baseline(bid, "newhash")
        assert ok is True
        b = self.db.get_baseline(bid)
        assert b["expected_hash"] == "newhash"
        assert b["updated_at"] is not None

    def test_update_nonexistent(self):
        ok = self.db.update_baseline(9999, "anyhash")
        assert ok is False

    def test_delete_baseline(self):
        bid = self.db.create_baseline("/etc/resolv.conf", "hash1")
        ok = self.db.delete_baseline(bid)
        assert ok is True
        baselines = self.db.list_baselines()
        assert len(baselines) == 0

    def test_delete_nonexistent(self):
        ok = self.db.delete_baseline(9999)
        assert ok is False

    def test_delete_cascade_removes_drift_checks(self):
        bid = self.db.create_baseline("/etc/test.conf", "hash1")
        self.db.record_drift_check(bid, "host1", "hash1", status="match")
        self.db.record_drift_check(bid, "host2", "hash2", status="drift")
        # Drift results should exist
        results = self.db.get_drift_results(baseline_id=bid)
        assert len(results) == 2
        # Delete baseline should cascade
        self.db.delete_baseline(bid)
        results = self.db.get_drift_results(baseline_id=bid)
        assert len(results) == 0

    def test_multiple_baselines(self):
        self.db.create_baseline("/etc/resolv.conf", "hash1")
        self.db.create_baseline("/etc/hostname", "hash2")
        self.db.create_baseline("/etc/hosts", "hash3")
        baselines = self.db.list_baselines()
        assert len(baselines) == 3
        # Sorted by path
        paths = [b["path"] for b in baselines]
        assert paths == sorted(paths)


# ── Drift Check Tests ────────────────────────────────────────────────────────

class TestDriftChecks:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_record_match(self):
        bid = self.db.create_baseline("/etc/resolv.conf", "abc123")
        rid = self.db.record_drift_check(bid, "host1", "abc123", status="match")
        assert rid is not None
        results = self.db.get_drift_results(baseline_id=bid)
        assert len(results) == 1
        assert results[0]["hostname"] == "host1"
        assert results[0]["status"] == "match"
        assert results[0]["actual_hash"] == "abc123"

    def test_record_drift(self):
        bid = self.db.create_baseline("/etc/resolv.conf", "abc123")
        self.db.record_drift_check(bid, "host1", "different", status="drift")
        results = self.db.get_drift_results(baseline_id=bid)
        assert len(results) == 1
        assert results[0]["status"] == "drift"

    def test_record_timeout(self):
        bid = self.db.create_baseline("/etc/resolv.conf", "abc123")
        self.db.record_drift_check(bid, "host1", None, status="timeout")
        results = self.db.get_drift_results(baseline_id=bid)
        assert len(results) == 1
        assert results[0]["status"] == "timeout"
        assert results[0]["actual_hash"] is None

    def test_multiple_hosts(self):
        bid = self.db.create_baseline("/etc/resolv.conf", "abc123")
        self.db.record_drift_check(bid, "host1", "abc123", status="match")
        self.db.record_drift_check(bid, "host2", "abc123", status="match")
        self.db.record_drift_check(bid, "host3", "different", status="drift")
        results = self.db.get_drift_results(baseline_id=bid)
        assert len(results) == 3

    def test_deduplication_latest_per_host(self):
        """Only the latest check per hostname should be returned."""
        bid = self.db.create_baseline("/etc/resolv.conf", "abc123")
        # Record multiple checks for same host
        self.db.record_drift_check(bid, "host1", "old_hash", status="drift")
        self.db.record_drift_check(bid, "host1", "abc123", status="match")
        results = self.db.get_drift_results(baseline_id=bid)
        assert len(results) == 1
        assert results[0]["status"] == "match"
        assert results[0]["actual_hash"] == "abc123"

    def test_baseline_status_reflects_drift(self):
        bid = self.db.create_baseline("/etc/resolv.conf", "abc123")
        # All match
        self.db.record_drift_check(bid, "host1", "abc123", status="match")
        baselines = self.db.list_baselines()
        assert baselines[0]["status"] == "match"
        # Now one drifts
        self.db.record_drift_check(bid, "host2", "different", status="drift")
        baselines = self.db.list_baselines()
        assert baselines[0]["status"] == "drift"
        assert baselines[0]["drift_count"] == 1
        assert baselines[0]["agent_count"] == 2

    def test_get_drift_results_all(self):
        bid1 = self.db.create_baseline("/etc/resolv.conf", "hash1")
        bid2 = self.db.create_baseline("/etc/hostname", "hash2")
        self.db.record_drift_check(bid1, "host1", "hash1", status="match")
        self.db.record_drift_check(bid2, "host1", "hash2", status="match")
        # Get all results
        results = self.db.get_drift_results()
        assert len(results) == 2

    def test_get_drift_results_filtered(self):
        bid1 = self.db.create_baseline("/etc/resolv.conf", "hash1")
        bid2 = self.db.create_baseline("/etc/hostname", "hash2")
        self.db.record_drift_check(bid1, "host1", "hash1", status="match")
        self.db.record_drift_check(bid2, "host1", "hash2", status="match")
        # Filter by baseline
        results = self.db.get_drift_results(baseline_id=bid1)
        assert len(results) == 1
        assert results[0]["path"] == "/etc/resolv.conf"

    def test_baseline_pending_when_no_checks(self):
        self.db.create_baseline("/etc/resolv.conf", "abc123")
        baselines = self.db.list_baselines()
        assert baselines[0]["status"] == "pending"
        assert baselines[0]["agent_count"] == 0

    def test_drift_result_includes_expected_hash(self):
        """Drift results should include the expected hash from the baseline."""
        bid = self.db.create_baseline("/etc/resolv.conf", "expected_abc")
        self.db.record_drift_check(bid, "host1", "actual_xyz", status="drift")
        results = self.db.get_drift_results(baseline_id=bid)
        assert results[0]["expected_hash"] == "expected_abc"
        assert results[0]["path"] == "/etc/resolv.conf"
