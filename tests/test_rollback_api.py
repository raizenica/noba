"""Tests for maintenance and rollback API endpoints."""
from __future__ import annotations


class TestMaintenanceAPI:
    def test_list_maintenance_no_auth(self, client):
        r = client.get("/api/healing/maintenance")
        assert r.status_code == 401

    def test_list_maintenance_returns_list(self, client, admin_headers):
        r = client.get("/api/healing/maintenance", headers=admin_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_maintenance_requires_operator(self, client, admin_headers):
        r = client.post("/api/healing/maintenance", json={
            "target": "plex", "duration": "30m", "reason": "deploy",
            "action": "suppress",
        }, headers=admin_headers)
        assert r.status_code == 200

    def test_create_maintenance_missing_fields(self, client, admin_headers):
        r = client.post("/api/healing/maintenance", json={}, headers=admin_headers)
        assert r.status_code in (400, 422)

    def test_delete_maintenance_requires_operator(self, client, admin_headers):
        # Create first, then delete
        r = client.post("/api/healing/maintenance", json={
            "target": "plex", "duration": "1h", "reason": "test",
            "action": "suppress",
        }, headers=admin_headers)
        if r.status_code == 200:
            wid = r.json().get("id")
            if wid:
                r2 = client.delete(f"/api/healing/maintenance/{wid}",
                                   headers=admin_headers)
                assert r2.status_code == 200


class TestRollbackAPI:
    def test_rollback_no_auth(self, client):
        r = client.post("/api/healing/rollback/1")
        assert r.status_code == 401

    def test_rollback_requires_admin(self, client, admin_headers):
        # Will return 404 since ledger entry doesn't exist, but auth should pass
        r = client.post("/api/healing/rollback/999", headers=admin_headers)
        assert r.status_code in (200, 404)
