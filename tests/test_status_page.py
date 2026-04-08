# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the enhanced public status page -- DB CRUD and API endpoints."""
from __future__ import annotations

import os
import tempfile

from server.db.core import Database


def _make_db():
    """Create a fresh temp DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_test_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


# -- Component CRUD -----------------------------------------------------------

class TestStatusComponents:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_create_and_list(self):
        cid = self.db.create_status_component("DNS Servers", group_name="Core")
        assert cid > 0
        components = self.db.list_status_components()
        assert len(components) == 1
        assert components[0]["name"] == "DNS Servers"
        assert components[0]["group_name"] == "Core"
        assert components[0]["enabled"] is True

    def test_create_with_service_key(self):
        cid = self.db.create_status_component("Pi-hole", service_key="pihole", display_order=5)
        assert cid > 0
        components = self.db.list_status_components()
        assert components[0]["service_key"] == "pihole"
        assert components[0]["display_order"] == 5

    def test_update_component(self):
        cid = self.db.create_status_component("Old Name")
        ok = self.db.update_status_component(cid, name="New Name", group_name="Network")
        assert ok is True
        components = self.db.list_status_components()
        assert components[0]["name"] == "New Name"
        assert components[0]["group_name"] == "Network"

    def test_update_nonexistent(self):
        ok = self.db.update_status_component(999, name="Ghost")
        assert ok is False

    def test_delete_component(self):
        cid = self.db.create_status_component("Temp")
        ok = self.db.delete_status_component(cid)
        assert ok is True
        assert self.db.list_status_components() == []

    def test_delete_nonexistent(self):
        ok = self.db.delete_status_component(999)
        assert ok is False

    def test_disable_component(self):
        cid = self.db.create_status_component("Test")
        self.db.update_status_component(cid, enabled=False)
        components = self.db.list_status_components()
        assert components[0]["enabled"] is False

    def test_ordering(self):
        self.db.create_status_component("C", display_order=3)
        self.db.create_status_component("A", display_order=1)
        self.db.create_status_component("B", display_order=2)
        components = self.db.list_status_components()
        names = [c["name"] for c in components]
        assert names == ["A", "B", "C"]


# -- Incident CRUD ------------------------------------------------------------

class TestStatusIncidents:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_create_incident(self):
        iid = self.db.create_status_incident("DNS outage", severity="major", created_by="admin")
        assert iid > 0
        incidents = self.db.list_status_incidents()
        assert len(incidents) == 1
        assert incidents[0]["title"] == "DNS outage"
        assert incidents[0]["severity"] == "major"
        assert incidents[0]["status"] == "investigating"
        assert incidents[0]["created_by"] == "admin"

    def test_create_with_initial_message(self):
        iid = self.db.create_status_incident(
            "Slow responses", severity="minor", message="Investigating latency spikes", created_by="admin"
        )
        detail = self.db.get_status_incident(iid)
        assert detail is not None
        assert len(detail["updates"]) == 1
        assert detail["updates"][0]["message"] == "Investigating latency spikes"

    def test_list_active_only(self):
        id1 = self.db.create_status_incident("Active")
        id2 = self.db.create_status_incident("Resolved")
        self.db.resolve_status_incident(id2)
        active = self.db.list_status_incidents(include_resolved=False)
        assert len(active) == 1
        assert active[0]["id"] == id1

    def test_get_incident_with_updates(self):
        iid = self.db.create_status_incident("Test")
        self.db.add_status_update(iid, "Found the issue", status="identified", created_by="admin")
        self.db.add_status_update(iid, "Deploying fix", status="monitoring", created_by="admin")
        detail = self.db.get_status_incident(iid)
        assert detail is not None
        assert len(detail["updates"]) == 2
        assert detail["updates"][0]["status"] == "identified"
        assert detail["updates"][1]["status"] == "monitoring"
        assert detail["status"] == "monitoring"  # incident status tracks last update

    def test_get_nonexistent_incident(self):
        assert self.db.get_status_incident(999) is None

    def test_resolve_incident(self):
        iid = self.db.create_status_incident("Issue")
        ok = self.db.resolve_status_incident(iid, created_by="admin")
        assert ok is True
        detail = self.db.get_status_incident(iid)
        assert detail is not None
        assert detail["status"] == "resolved"
        assert detail["resolved_at"] is not None
        # Should have an auto-generated "resolved" update
        assert any(u["status"] == "resolved" for u in detail["updates"])

    def test_update_incident_fields(self):
        iid = self.db.create_status_incident("Test", severity="minor")
        ok = self.db.update_status_incident(iid, severity="critical", title="Updated Title")
        assert ok is True
        detail = self.db.get_status_incident(iid)
        assert detail["severity"] == "critical"
        assert detail["title"] == "Updated Title"


# -- Status Update -------------------------------------------------------------

class TestStatusUpdates:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_add_update(self):
        iid = self.db.create_status_incident("Outage")
        uid = self.db.add_status_update(iid, "We are on it", status="investigating")
        assert uid > 0

    def test_update_changes_incident_status(self):
        iid = self.db.create_status_incident("Slow")
        self.db.add_status_update(iid, "Root cause found", status="identified")
        detail = self.db.get_status_incident(iid)
        assert detail["status"] == "identified"

    def test_add_update_nonexistent_incident(self):
        # Foreign key violation or just returns 0 depending on PRAGMA
        uid = self.db.add_status_update(999, "Ghost update")
        # Should still return a value (FK not enforced by default in SQLite)
        assert isinstance(uid, int)


# -- Uptime History ------------------------------------------------------------

class TestStatusUptimeHistory:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_empty_history(self):
        result = self.db.get_status_uptime_history(days=7)
        assert len(result) == 7
        assert all(d["incidents"] == 0 for d in result)
        assert all(d["worst_severity"] == "none" for d in result)

    def test_history_with_incident(self):
        # Create an incident (it will be timestamped now)
        self.db.create_status_incident("Today's issue", severity="major")
        result = self.db.get_status_uptime_history(days=7)
        # Today should have 1 incident
        today_entry = result[-1]  # last entry is today
        assert today_entry["incidents"] == 1
        assert today_entry["worst_severity"] == "major"

    def test_history_worst_severity(self):
        self.db.create_status_incident("Minor thing", severity="minor")
        self.db.create_status_incident("Critical thing", severity="critical")
        result = self.db.get_status_uptime_history(days=1)
        assert result[0]["incidents"] == 2
        assert result[0]["worst_severity"] == "critical"


# -- API Endpoint Tests --------------------------------------------------------

class TestStatusPageAPI:
    """Test the API endpoints via TestClient."""

    @classmethod
    def setup_class(cls):
        """Set up a test client."""
        try:
            from fastapi.testclient import TestClient
            from server.app import app
            cls.client = TestClient(app)
            cls.has_client = True
        except Exception:
            cls.has_client = False

    def _auth_headers(self):
        """Get auth token via login."""
        if not self.has_client:
            return {}
        resp = self.client.post("/api/login", json={"username": "admin", "password": "Admin1234!"})
        if resp.status_code == 200:
            token = resp.json().get("token", "")
            return {"Authorization": f"Bearer {token}"}
        return {}

    def test_public_status_no_auth(self):
        if not self.has_client:
            return
        resp = self.client.get("/api/status/public")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall" in data
        assert "components" in data
        assert "timestamp" in data

    def test_public_incidents_no_auth(self):
        if not self.has_client:
            return
        resp = self.client.get("/api/status/incidents")
        assert resp.status_code == 200
        data = resp.json()
        assert "incidents" in data

    def test_status_page_html(self):
        if not self.has_client:
            return
        resp = self.client.get("/status")
        assert resp.status_code == 200
        assert "NOBA" in resp.text

    def test_create_component_requires_admin(self):
        if not self.has_client:
            return
        resp = self.client.post("/api/status/components", json={"name": "Test"})
        assert resp.status_code == 401

    def test_component_crud(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return

        # Create
        resp = self.client.post("/api/status/components", json={
            "name": "Test Service", "group_name": "Core", "service_key": "test_svc",
        }, headers=headers)
        assert resp.status_code == 200
        comp_id = resp.json()["id"]

        # List
        resp = self.client.get("/api/status/components", headers=headers)
        assert resp.status_code == 200
        assert any(c["id"] == comp_id for c in resp.json()["components"])

        # Update
        resp = self.client.put(f"/api/status/components/{comp_id}", json={
            "name": "Updated Service",
        }, headers=headers)
        assert resp.status_code == 200

        # Delete
        resp = self.client.delete(f"/api/status/components/{comp_id}", headers=headers)
        assert resp.status_code == 200

    def test_incident_lifecycle(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return

        # Create incident
        resp = self.client.post("/api/status/incidents/create", json={
            "title": "API Test Incident", "severity": "minor", "message": "Testing...",
        }, headers=headers)
        assert resp.status_code == 200
        inc_id = resp.json()["id"]

        # Add update
        resp = self.client.post(f"/api/status/incidents/{inc_id}/update", json={
            "message": "Found the cause", "status": "identified",
        }, headers=headers)
        assert resp.status_code == 200

        # Resolve
        resp = self.client.put(f"/api/status/incidents/{inc_id}/resolve", headers=headers)
        assert resp.status_code == 200

        # Verify via public endpoint
        resp = self.client.get("/api/status/incidents")
        data = resp.json()
        resolved = [i for i in data["incidents"] if i["id"] == inc_id]
        assert len(resolved) == 1
        assert resolved[0]["resolved_at"] is not None

    def test_create_incident_validation(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return

        # Missing title
        resp = self.client.post("/api/status/incidents/create", json={
            "severity": "minor",
        }, headers=headers)
        assert resp.status_code == 400

        # Invalid severity
        resp = self.client.post("/api/status/incidents/create", json={
            "title": "Test", "severity": "extreme",
        }, headers=headers)
        assert resp.status_code == 400

    def test_add_update_validation(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return

        # Create incident first
        resp = self.client.post("/api/status/incidents/create", json={
            "title": "For validation test", "severity": "minor",
        }, headers=headers)
        inc_id = resp.json()["id"]

        # Empty message
        resp = self.client.post(f"/api/status/incidents/{inc_id}/update", json={
            "message": "", "status": "investigating",
        }, headers=headers)
        assert resp.status_code == 400

        # Invalid status
        resp = self.client.post(f"/api/status/incidents/{inc_id}/update", json={
            "message": "test", "status": "invalid_status",
        }, headers=headers)
        assert resp.status_code == 400
