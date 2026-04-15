# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for custom dashboards: DB CRUD and ownership/sharing logic."""
from __future__ import annotations

import json
import os
import sys
import tempfile

# Ensure server package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-web"))

from server.db import Database


def _make_db():
    """Create a fresh temp DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_dashtest_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


class TestDashboardCRUD:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_create_and_list(self):
        config = json.dumps({"metrics": ["cpu_percent"], "range": 24})
        did = self.db.create_dashboard("Test Dash", "alice", config)
        assert did is not None
        assert isinstance(did, int)
        dashboards = self.db.get_dashboards(owner="alice")
        assert len(dashboards) == 1
        assert dashboards[0]["name"] == "Test Dash"
        assert dashboards[0]["owner"] == "alice"
        assert dashboards[0]["shared"] is False
        parsed = json.loads(dashboards[0]["config_json"])
        assert parsed["metrics"] == ["cpu_percent"]

    def test_create_shared(self):
        config = json.dumps({"metrics": ["mem_percent"]})
        did = self.db.create_dashboard("Shared Dash", "alice", config, shared=True)
        assert did is not None
        dash = self.db.get_dashboard(did)
        assert dash is not None
        assert dash["shared"] is True

    def test_get_single(self):
        config = json.dumps({"metrics": ["disk_percent"]})
        did = self.db.create_dashboard("Single", "bob", config)
        dash = self.db.get_dashboard(did)
        assert dash is not None
        assert dash["name"] == "Single"
        assert dash["owner"] == "bob"
        assert dash["created_at"] is not None
        assert dash["updated_at"] is not None

    def test_get_nonexistent_returns_none(self):
        assert self.db.get_dashboard(9999) is None

    def test_update_name(self):
        config = json.dumps({"metrics": ["cpu_percent"]})
        did = self.db.create_dashboard("Old Name", "alice", config)
        ok = self.db.update_dashboard(did, name="New Name")
        assert ok is True
        dash = self.db.get_dashboard(did)
        assert dash["name"] == "New Name"

    def test_update_config(self):
        config = json.dumps({"metrics": ["cpu_percent"]})
        did = self.db.create_dashboard("Cfg Dash", "alice", config)
        new_config = json.dumps({"metrics": ["cpu_percent", "mem_percent"], "range": 168})
        ok = self.db.update_dashboard(did, config_json=new_config)
        assert ok is True
        dash = self.db.get_dashboard(did)
        parsed = json.loads(dash["config_json"])
        assert "mem_percent" in parsed["metrics"]

    def test_update_shared_flag(self):
        config = json.dumps({"metrics": ["cpu_percent"]})
        did = self.db.create_dashboard("Share Toggle", "alice", config)
        self.db.update_dashboard(did, shared=True)
        dash = self.db.get_dashboard(did)
        assert dash["shared"] is True
        self.db.update_dashboard(did, shared=False)
        dash = self.db.get_dashboard(did)
        assert dash["shared"] is False

    def test_update_nonexistent(self):
        ok = self.db.update_dashboard(9999, name="Nope")
        assert ok is False

    def test_update_no_valid_fields(self):
        config = json.dumps({"metrics": ["cpu_percent"]})
        did = self.db.create_dashboard("NoOp", "alice", config)
        ok = self.db.update_dashboard(did, invalid_field="ignored")
        assert ok is False

    def test_delete(self):
        config = json.dumps({"metrics": ["cpu_percent"]})
        did = self.db.create_dashboard("ToDelete", "alice", config)
        ok = self.db.delete_dashboard(did)
        assert ok is True
        assert self.db.get_dashboard(did) is None

    def test_delete_nonexistent(self):
        ok = self.db.delete_dashboard(9999)
        assert ok is False

    def test_timestamps_set(self):
        config = json.dumps({"metrics": ["cpu_percent"]})
        did = self.db.create_dashboard("Timed", "alice", config)
        dash = self.db.get_dashboard(did)
        assert dash["created_at"] > 0
        assert dash["updated_at"] > 0
        assert dash["updated_at"] >= dash["created_at"]


class TestDashboardVisibility:
    """Test ownership and sharing visibility rules."""

    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_owner_sees_own_dashboards(self):
        config = json.dumps({"metrics": ["cpu_percent"]})
        self.db.create_dashboard("Alice Dash", "alice", config)
        self.db.create_dashboard("Bob Dash", "bob", config)
        alice_dashes = self.db.get_dashboards(owner="alice")
        assert len(alice_dashes) == 1
        assert alice_dashes[0]["name"] == "Alice Dash"

    def test_owner_sees_shared_from_others(self):
        config = json.dumps({"metrics": ["cpu_percent"]})
        self.db.create_dashboard("Bob Shared", "bob", config, shared=True)
        self.db.create_dashboard("Bob Private", "bob", config, shared=False)
        alice_dashes = self.db.get_dashboards(owner="alice")
        assert len(alice_dashes) == 1
        assert alice_dashes[0]["name"] == "Bob Shared"

    def test_owner_sees_own_plus_shared(self):
        config = json.dumps({"metrics": ["cpu_percent"]})
        self.db.create_dashboard("Alice Own", "alice", config)
        self.db.create_dashboard("Bob Shared", "bob", config, shared=True)
        self.db.create_dashboard("Bob Private", "bob", config, shared=False)
        alice_dashes = self.db.get_dashboards(owner="alice")
        names = [d["name"] for d in alice_dashes]
        assert "Alice Own" in names
        assert "Bob Shared" in names
        assert "Bob Private" not in names

    def test_none_owner_returns_all(self):
        config = json.dumps({"metrics": ["cpu_percent"]})
        self.db.create_dashboard("A", "alice", config)
        self.db.create_dashboard("B", "bob", config)
        self.db.create_dashboard("C", "charlie", config, shared=True)
        all_dashes = self.db.get_dashboards(owner=None)
        assert len(all_dashes) == 3

    def test_ordering_by_name(self):
        config = json.dumps({"metrics": ["cpu_percent"]})
        self.db.create_dashboard("Zebra", "alice", config)
        self.db.create_dashboard("Alpha", "alice", config)
        self.db.create_dashboard("Middle", "alice", config)
        dashes = self.db.get_dashboards(owner="alice")
        names = [d["name"] for d in dashes]
        assert names == ["Alpha", "Middle", "Zebra"]

    def test_multiple_shared_visible(self):
        config = json.dumps({"metrics": ["cpu_percent"]})
        self.db.create_dashboard("S1", "bob", config, shared=True)
        self.db.create_dashboard("S2", "charlie", config, shared=True)
        alice_dashes = self.db.get_dashboards(owner="alice")
        assert len(alice_dashes) == 2
