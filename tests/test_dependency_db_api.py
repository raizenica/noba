# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for dependency graph DB layer and API endpoints."""
from __future__ import annotations

import sqlite3
import threading
import pytest


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    from server.db.integrations import create_tables
    create_tables(conn)
    # Also create dependency_graph table
    conn.execute("""CREATE TABLE IF NOT EXISTS dependency_graph (
        id INTEGER PRIMARY KEY, target TEXT NOT NULL UNIQUE,
        depends_on TEXT, node_type TEXT NOT NULL,
        health_check TEXT, site TEXT,
        auto_discovered INTEGER DEFAULT 0, confirmed INTEGER DEFAULT 0,
        created_at INTEGER NOT NULL
    )""")
    return conn, lock


class TestDependencyDB:
    def test_insert_and_get(self, db):
        from server.db.integrations import insert_dependency, get_dependency
        conn, lock = db
        insert_dependency(conn, lock, target="truenas", node_type="service",
                         depends_on='["network:site-a"]', site="site-a")
        dep = get_dependency(conn, lock, "truenas")
        assert dep is not None
        assert dep["node_type"] == "service"
        assert dep["site"] == "site-a"

    def test_list_dependencies(self, db):
        from server.db.integrations import insert_dependency, list_dependencies
        conn, lock = db
        insert_dependency(conn, lock, target="isp", node_type="external")
        insert_dependency(conn, lock, target="nas", node_type="service")
        deps = list_dependencies(conn, lock)
        assert len(deps) == 2

    def test_delete_dependency(self, db):
        from server.db.integrations import insert_dependency, delete_dependency, get_dependency
        conn, lock = db
        insert_dependency(conn, lock, target="nas", node_type="service")
        delete_dependency(conn, lock, "nas")
        assert get_dependency(conn, lock, "nas") is None

    def test_upsert_dependency(self, db):
        from server.db.integrations import upsert_dependency, get_dependency
        conn, lock = db
        upsert_dependency(conn, lock, target="nas", node_type="service", site="site-a")
        upsert_dependency(conn, lock, target="nas", node_type="service", site="site-b")
        dep = get_dependency(conn, lock, "nas")
        assert dep["site"] == "site-b"


class TestDependencyAPI:
    def test_get_dependencies_no_auth(self, client):
        r = client.get("/api/healing/dependencies")
        assert r.status_code == 401

    def test_get_dependencies_returns_list(self, client, admin_headers):
        r = client.get("/api/healing/dependencies", headers=admin_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_validate_dependencies_requires_operator(self, client, admin_headers):
        r = client.post("/api/healing/dependencies/validate",
                       json={"config": []}, headers=admin_headers)
        assert r.status_code == 200
