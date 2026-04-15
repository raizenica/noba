# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for service dependency topology: DB CRUD and impact analysis."""
from __future__ import annotations

import os
import sys
import tempfile

# Ensure server package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-web"))

from server.db import Database


def _make_db():
    """Create a fresh temp DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_deptest_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


class TestDependencyCRUD:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_create_and_list(self):
        dep_id = self.db.create_dependency("nginx", "postgresql")
        assert dep_id is not None
        assert isinstance(dep_id, int)
        deps = self.db.list_dependencies()
        assert len(deps) == 1
        assert deps[0]["source_service"] == "nginx"
        assert deps[0]["target_service"] == "postgresql"
        assert deps[0]["dependency_type"] == "requires"
        assert deps[0]["auto_discovered"] is False

    def test_create_with_type(self):
        dep_id = self.db.create_dependency("app", "cache",
                                           dependency_type="optional")
        assert dep_id is not None
        deps = self.db.list_dependencies()
        assert deps[0]["dependency_type"] == "optional"

    def test_create_auto_discovered(self):
        dep_id = self.db.create_dependency("svc-a", "svc-b",
                                           auto_discovered=True)
        assert dep_id is not None
        deps = self.db.list_dependencies()
        assert deps[0]["auto_discovered"] is True

    def test_create_network_type(self):
        self.db.create_dependency("webserver", "dns",
                                           dependency_type="network")
        deps = self.db.list_dependencies()
        assert deps[0]["dependency_type"] == "network"

    def test_multiple_dependencies(self):
        self.db.create_dependency("app", "db")
        self.db.create_dependency("app", "cache")
        self.db.create_dependency("web", "app")
        deps = self.db.list_dependencies()
        assert len(deps) == 3

    def test_delete(self):
        dep_id = self.db.create_dependency("app", "db")
        ok = self.db.delete_dependency(dep_id)
        assert ok is True
        deps = self.db.list_dependencies()
        assert len(deps) == 0

    def test_delete_nonexistent(self):
        ok = self.db.delete_dependency(9999)
        assert ok is False

    def test_timestamps_set(self):
        self.db.create_dependency("app", "db")
        deps = self.db.list_dependencies()
        assert deps[0]["created_at"] is not None
        assert deps[0]["created_at"] > 0

    def test_ordering(self):
        self.db.create_dependency("zebra", "alpha")
        self.db.create_dependency("alpha", "beta")
        deps = self.db.list_dependencies()
        sources = [d["source_service"] for d in deps]
        assert sources == ["alpha", "zebra"]


class TestImpactAnalysis:
    """Test transitive impact analysis."""

    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_direct_dependency(self):
        # app requires db -> if db goes down, app is affected
        self.db.create_dependency("app", "db")
        affected = self.db.get_impact_analysis("db")
        assert "app" in affected

    def test_no_dependents(self):
        self.db.create_dependency("app", "db")
        # Nothing depends on app
        affected = self.db.get_impact_analysis("app")
        assert affected == []

    def test_transitive_dependency(self):
        # web -> app -> db
        # If db goes down, both app and web are affected
        self.db.create_dependency("app", "db")
        self.db.create_dependency("web", "app")
        affected = self.db.get_impact_analysis("db")
        assert "app" in affected
        assert "web" in affected

    def test_deep_chain(self):
        # a -> b -> c -> d
        self.db.create_dependency("a", "b")
        self.db.create_dependency("b", "c")
        self.db.create_dependency("c", "d")
        affected = self.db.get_impact_analysis("d")
        assert sorted(affected) == ["a", "b", "c"]

    def test_diamond_dependency(self):
        # web -> app -> db
        # web -> cache -> db
        self.db.create_dependency("app", "db")
        self.db.create_dependency("cache", "db")
        self.db.create_dependency("web", "app")
        self.db.create_dependency("web", "cache")
        affected = self.db.get_impact_analysis("db")
        assert "app" in affected
        assert "cache" in affected
        assert "web" in affected
        assert len(affected) == 3

    def test_unknown_service(self):
        self.db.create_dependency("app", "db")
        affected = self.db.get_impact_analysis("nonexistent")
        assert affected == []

    def test_self_not_in_result(self):
        self.db.create_dependency("app", "db")
        affected = self.db.get_impact_analysis("db")
        assert "db" not in affected

    def test_cycle_handling(self):
        # a -> b -> a (cycle) -- should not infinite loop
        self.db.create_dependency("a", "b")
        self.db.create_dependency("b", "a")
        affected = self.db.get_impact_analysis("a")
        assert "b" in affected
        affected2 = self.db.get_impact_analysis("b")
        assert "a" in affected2

    def test_empty_graph(self):
        affected = self.db.get_impact_analysis("anything")
        assert affected == []

    def test_multiple_roots(self):
        # web1 -> app -> db
        # web2 -> app -> db
        self.db.create_dependency("app", "db")
        self.db.create_dependency("web1", "app")
        self.db.create_dependency("web2", "app")
        affected = self.db.get_impact_analysis("db")
        assert sorted(affected) == ["app", "web1", "web2"]

    def test_impact_mid_chain(self):
        # web -> app -> db
        self.db.create_dependency("app", "db")
        self.db.create_dependency("web", "app")
        # Impact of app: only web is affected
        affected = self.db.get_impact_analysis("app")
        assert affected == ["web"]
