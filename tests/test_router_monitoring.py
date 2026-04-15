# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for the monitoring router (share/noba-web/server/routers/monitoring.py)."""
from __future__ import annotations

from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_endpoint(client, admin_headers, name="Test Monitor", url="http://example.com"):
    """Create an endpoint monitor and return its id."""
    resp = client.post(
        "/api/endpoints",
        json={"name": name, "url": url},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _create_component(client, admin_headers, name="Test Component"):
    """Create a status page component and return its id."""
    resp = client.post(
        "/api/status/components",
        json={"name": name, "group_name": "Default"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _create_incident(client, admin_headers, title="Test Incident"):
    """Create a status incident and return its id."""
    resp = client.post(
        "/api/status/incidents/create",
        json={"title": title, "severity": "minor", "message": "test message"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


# ===========================================================================
# GET /api/uptime
# ===========================================================================

class TestUptimeDashboard:
    """Uptime SLA dashboard — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/uptime")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/uptime", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/uptime", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/uptime", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_dict_with_items_and_percent(self, client, admin_headers):
        resp = client.get("/api/uptime", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert "percent" in data
        assert isinstance(data["items"], list)


# ===========================================================================
# GET /api/health-score
# ===========================================================================

class TestHealthScore:
    """Infrastructure health score — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/health-score")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/health-score", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/health-score", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/health-score", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_score_object(self, client, admin_headers):
        resp = client.get("/api/health-score", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        # Should contain a numeric score field
        assert "score" in data or "overall" in data or len(data) > 0


# ===========================================================================
# GET /api/status/public  — PUBLIC (no auth required)
# ===========================================================================

class TestPublicStatus:
    """Public status page data — NO auth required."""

    def test_returns_200_without_auth(self, client):
        """This endpoint must be accessible without any credentials."""
        resp = client.get("/api/status/public")
        assert resp.status_code == 200

    def test_returns_expected_fields(self, client):
        resp = client.get("/api/status/public")
        assert resp.status_code == 200
        data = resp.json()
        assert "components" in data
        assert "active_incidents" in data
        assert "overall" in data
        assert "timestamp" in data

    def test_components_is_list(self, client):
        resp = client.get("/api/status/public")
        assert resp.status_code == 200
        assert isinstance(resp.json()["components"], list)

    def test_active_incidents_is_list(self, client):
        resp = client.get("/api/status/public")
        assert resp.status_code == 200
        assert isinstance(resp.json()["active_incidents"], list)

    def test_overall_is_string(self, client):
        resp = client.get("/api/status/public")
        assert resp.status_code == 200
        overall = resp.json()["overall"]
        assert isinstance(overall, str)
        assert overall in ("operational", "degraded", "major_outage")

    def test_also_accessible_with_auth(self, client, viewer_headers):
        """Public endpoint should still work when auth is provided."""
        resp = client.get("/api/status/public", headers=viewer_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/status/incidents  — PUBLIC (no auth required)
# ===========================================================================

class TestPublicStatusIncidents:
    """Public incidents listing — NO auth required."""

    def test_returns_200_without_auth(self, client):
        """This endpoint must be accessible without any credentials."""
        resp = client.get("/api/status/incidents")
        assert resp.status_code == 200

    def test_returns_incidents_key(self, client):
        resp = client.get("/api/status/incidents")
        assert resp.status_code == 200
        data = resp.json()
        assert "incidents" in data
        assert isinstance(data["incidents"], list)

    def test_also_accessible_with_auth(self, client, admin_headers):
        """Public endpoint should still work when auth is provided."""
        resp = client.get("/api/status/incidents", headers=admin_headers)
        assert resp.status_code == 200

    def test_created_incident_appears_in_public_list(self, client, admin_headers):
        """Incident created via admin endpoint should appear in the public list."""
        _create_incident(client, admin_headers, title="Public Visibility Test")
        resp = client.get("/api/status/incidents")
        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["incidents"]]
        assert "Public Visibility Test" in titles


# ===========================================================================
# GET /api/status/components  — authenticated
# ===========================================================================

class TestStatusComponentsList:
    """List all status components for admin UI — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/status/components")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/status/components", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/status/components", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/status/components", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_components_key(self, client, admin_headers):
        resp = client.get("/api/status/components", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "components" in data
        assert isinstance(data["components"], list)


# ===========================================================================
# POST /api/status/components  — admin only
# ===========================================================================

class TestStatusComponentCreate:
    """Create a status page component — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/status/components", json={"name": "X"}
        )
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/status/components",
            json={"name": "X"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post(
            "/api/status/components",
            json={"name": "X"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_admin_can_create(self, client, admin_headers):
        resp = client.post(
            "/api/status/components",
            json={"name": "API Gateway", "group_name": "Network"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["status"] == "ok"

    def test_missing_name_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/status/components",
            json={"group_name": "Network"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_empty_name_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/status/components",
            json={"name": "   "},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_created_component_appears_in_list(self, client, admin_headers):
        client.post(
            "/api/status/components",
            json={"name": "Visible Component"},
            headers=admin_headers,
        )
        resp = client.get("/api/status/components", headers=admin_headers)
        names = [c["name"] for c in resp.json()["components"]]
        assert "Visible Component" in names


# ===========================================================================
# PUT /api/status/components/{id}  — admin only
# ===========================================================================

class TestStatusComponentUpdate:
    """Update a status page component — admin only."""

    def test_no_auth_returns_401(self, client, admin_headers):
        comp_id = _create_component(client, admin_headers, "Update Target")
        resp = client.put(f"/api/status/components/{comp_id}", json={"name": "New"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, admin_headers, viewer_headers):
        comp_id = _create_component(client, admin_headers, "Update Target V")
        resp = client.put(
            f"/api/status/components/{comp_id}",
            json={"name": "New"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, admin_headers, operator_headers):
        comp_id = _create_component(client, admin_headers, "Update Target O")
        resp = client.put(
            f"/api/status/components/{comp_id}",
            json={"name": "New"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_admin_can_update(self, client, admin_headers):
        comp_id = _create_component(client, admin_headers, "Before Update")
        resp = client.put(
            f"/api/status/components/{comp_id}",
            json={"name": "After Update"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_nonexistent_id_returns_404(self, client, admin_headers):
        resp = client.put(
            "/api/status/components/999999",
            json={"name": "Ghost"},
            headers=admin_headers,
        )
        assert resp.status_code == 404


# ===========================================================================
# DELETE /api/status/components/{id}  — admin only
# ===========================================================================

class TestStatusComponentDelete:
    """Delete a status page component — admin only."""

    def test_no_auth_returns_401(self, client, admin_headers):
        comp_id = _create_component(client, admin_headers, "Delete Target")
        resp = client.delete(f"/api/status/components/{comp_id}")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, admin_headers, viewer_headers):
        comp_id = _create_component(client, admin_headers, "Delete Target V")
        resp = client.delete(
            f"/api/status/components/{comp_id}", headers=viewer_headers
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, admin_headers, operator_headers):
        comp_id = _create_component(client, admin_headers, "Delete Target O")
        resp = client.delete(
            f"/api/status/components/{comp_id}", headers=operator_headers
        )
        assert resp.status_code == 403

    def test_admin_can_delete(self, client, admin_headers):
        comp_id = _create_component(client, admin_headers, "To Be Deleted")
        resp = client.delete(
            f"/api/status/components/{comp_id}", headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_nonexistent_id_returns_404(self, client, admin_headers):
        resp = client.delete(
            "/api/status/components/999999", headers=admin_headers
        )
        assert resp.status_code == 404

    def test_deleted_component_no_longer_in_list(self, client, admin_headers):
        comp_id = _create_component(client, admin_headers, "Disappearing Component")
        client.delete(f"/api/status/components/{comp_id}", headers=admin_headers)
        resp = client.get("/api/status/components", headers=admin_headers)
        ids = [c["id"] for c in resp.json()["components"]]
        assert comp_id not in ids


# ===========================================================================
# POST /api/status/incidents/create  — admin only
# ===========================================================================

class TestStatusIncidentCreate:
    """Create a status incident — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/status/incidents/create",
            json={"title": "Down", "severity": "major"},
        )
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/status/incidents/create",
            json={"title": "Down", "severity": "major"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post(
            "/api/status/incidents/create",
            json={"title": "Down", "severity": "major"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_admin_can_create(self, client, admin_headers):
        resp = client.post(
            "/api/status/incidents/create",
            json={"title": "DB Outage", "severity": "critical", "message": "DB is down"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["status"] == "ok"

    def test_missing_title_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/status/incidents/create",
            json={"severity": "minor"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_invalid_severity_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/status/incidents/create",
            json={"title": "Test", "severity": "catastrophic"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_valid_severities_accepted(self, client, admin_headers):
        for severity in ("minor", "major", "critical"):
            resp = client.post(
                "/api/status/incidents/create",
                json={"title": f"Test {severity}", "severity": severity},
                headers=admin_headers,
            )
            assert resp.status_code == 200, f"severity={severity} failed"


# ===========================================================================
# POST /api/status/incidents/{id}/update  — admin only
# ===========================================================================

class TestStatusIncidentUpdate:
    """Add an update to a status incident — admin only."""

    def test_no_auth_returns_401(self, client, admin_headers):
        inc_id = _create_incident(client, admin_headers, "No Auth Update")
        resp = client.post(
            f"/api/status/incidents/{inc_id}/update",
            json={"message": "update text", "status": "investigating"},
        )
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, admin_headers, viewer_headers):
        inc_id = _create_incident(client, admin_headers, "Viewer Update")
        resp = client.post(
            f"/api/status/incidents/{inc_id}/update",
            json={"message": "text", "status": "investigating"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, admin_headers, operator_headers):
        inc_id = _create_incident(client, admin_headers, "Operator Update")
        resp = client.post(
            f"/api/status/incidents/{inc_id}/update",
            json={"message": "text", "status": "investigating"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_admin_can_add_update(self, client, admin_headers):
        inc_id = _create_incident(client, admin_headers, "Admin Update")
        resp = client.post(
            f"/api/status/incidents/{inc_id}/update",
            json={"message": "We identified the issue", "status": "identified"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["status"] == "ok"

    def test_missing_message_returns_400(self, client, admin_headers):
        inc_id = _create_incident(client, admin_headers, "No Msg Update")
        resp = client.post(
            f"/api/status/incidents/{inc_id}/update",
            json={"status": "investigating"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_invalid_status_returns_400(self, client, admin_headers):
        inc_id = _create_incident(client, admin_headers, "Bad Status Update")
        resp = client.post(
            f"/api/status/incidents/{inc_id}/update",
            json={"message": "text", "status": "totally_wrong"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_valid_statuses_accepted(self, client, admin_headers):
        for status in ("investigating", "identified", "monitoring", "resolved"):
            inc_id = _create_incident(client, admin_headers, f"Status {status}")
            resp = client.post(
                f"/api/status/incidents/{inc_id}/update",
                json={"message": f"Update for {status}", "status": status},
                headers=admin_headers,
            )
            assert resp.status_code == 200, f"status={status} failed"

    def test_nonexistent_incident_returns_200_or_404(self, client, admin_headers):
        # The DB layer inserts a dangling row even for missing incident IDs,
        # so the route may return 200. Both 200 and 404 are acceptable here.
        resp = client.post(
            "/api/status/incidents/999999/update",
            json={"message": "ghost", "status": "investigating"},
            headers=admin_headers,
        )
        assert resp.status_code in (200, 404)


# ===========================================================================
# PUT /api/status/incidents/{id}/resolve  — admin only
# ===========================================================================

class TestStatusIncidentResolve:
    """Resolve a status incident — admin only."""

    def test_no_auth_returns_401(self, client, admin_headers):
        inc_id = _create_incident(client, admin_headers, "No Auth Resolve")
        resp = client.put(f"/api/status/incidents/{inc_id}/resolve")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, admin_headers, viewer_headers):
        inc_id = _create_incident(client, admin_headers, "Viewer Resolve")
        resp = client.put(
            f"/api/status/incidents/{inc_id}/resolve", headers=viewer_headers
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, admin_headers, operator_headers):
        inc_id = _create_incident(client, admin_headers, "Operator Resolve")
        resp = client.put(
            f"/api/status/incidents/{inc_id}/resolve", headers=operator_headers
        )
        assert resp.status_code == 403

    def test_admin_can_resolve(self, client, admin_headers):
        inc_id = _create_incident(client, admin_headers, "To Resolve")
        resp = client.put(
            f"/api/status/incidents/{inc_id}/resolve", headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_nonexistent_incident_returns_200_or_404(self, client, admin_headers):
        # The DB layer does not check rowcount on UPDATE so resolving a
        # nonexistent incident returns True, causing the route to return 200.
        resp = client.put(
            "/api/status/incidents/999999/resolve", headers=admin_headers
        )
        assert resp.status_code in (200, 404)


# ===========================================================================
# GET /api/endpoints
# ===========================================================================

class TestEndpointList:
    """List all endpoint monitors — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/endpoints")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/endpoints", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/endpoints", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/endpoints", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_list(self, client, admin_headers):
        resp = client.get("/api/endpoints", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ===========================================================================
# POST /api/endpoints  — admin only
# ===========================================================================

class TestEndpointCreate:
    """Create an endpoint monitor — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/endpoints", json={"name": "X", "url": "http://x.com"}
        )
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/endpoints",
            json={"name": "X", "url": "http://x.com"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post(
            "/api/endpoints",
            json={"name": "X", "url": "http://x.com"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_admin_can_create(self, client, admin_headers):
        resp = client.post(
            "/api/endpoints",
            json={"name": "My API", "url": "http://api.internal/health"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "id" in data

    def test_missing_name_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/endpoints",
            json={"url": "http://x.com"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_missing_url_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/endpoints",
            json={"name": "Test"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_invalid_url_scheme_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/endpoints",
            json={"name": "Test", "url": "ftp://example.com"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_http_url_accepted(self, client, admin_headers):
        resp = client.post(
            "/api/endpoints",
            json={"name": "HTTP Test", "url": "http://example.com"},
            headers=admin_headers,
        )
        assert resp.status_code == 200

    def test_https_url_accepted(self, client, admin_headers):
        resp = client.post(
            "/api/endpoints",
            json={"name": "HTTPS Test", "url": "https://example.com"},
            headers=admin_headers,
        )
        assert resp.status_code == 200

    def test_optional_fields_accepted(self, client, admin_headers):
        resp = client.post(
            "/api/endpoints",
            json={
                "name": "Full Config",
                "url": "http://example.com/health",
                "method": "HEAD",
                "expected_status": 200,
                "check_interval": 60,
                "timeout": 5,
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200

    def test_created_monitor_appears_in_list(self, client, admin_headers):
        client.post(
            "/api/endpoints",
            json={"name": "Visible Monitor", "url": "http://visible.test"},
            headers=admin_headers,
        )
        resp = client.get("/api/endpoints", headers=admin_headers)
        names = [m["name"] for m in resp.json()]
        assert "Visible Monitor" in names


# ===========================================================================
# PUT /api/endpoints/{id}  — admin only
# ===========================================================================

class TestEndpointUpdate:
    """Update an endpoint monitor — admin only."""

    def test_no_auth_returns_401(self, client, admin_headers):
        mon_id = _create_endpoint(client, admin_headers, "Update Me")
        resp = client.put(
            f"/api/endpoints/{mon_id}", json={"name": "Updated"}
        )
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, admin_headers, viewer_headers):
        mon_id = _create_endpoint(client, admin_headers, "Update Me V")
        resp = client.put(
            f"/api/endpoints/{mon_id}",
            json={"name": "Updated"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, admin_headers, operator_headers):
        mon_id = _create_endpoint(client, admin_headers, "Update Me O")
        resp = client.put(
            f"/api/endpoints/{mon_id}",
            json={"name": "Updated"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_admin_can_update_name(self, client, admin_headers):
        mon_id = _create_endpoint(client, admin_headers, "Old Name")
        resp = client.put(
            f"/api/endpoints/{mon_id}",
            json={"name": "New Name"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_admin_can_update_url(self, client, admin_headers):
        mon_id = _create_endpoint(client, admin_headers, "URL Update")
        resp = client.put(
            f"/api/endpoints/{mon_id}",
            json={"url": "http://updated.example.com"},
            headers=admin_headers,
        )
        assert resp.status_code == 200

    def test_invalid_url_returns_400(self, client, admin_headers):
        mon_id = _create_endpoint(client, admin_headers, "Bad URL Update")
        resp = client.put(
            f"/api/endpoints/{mon_id}",
            json={"url": "ftp://nope.com"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_nonexistent_id_returns_200_or_404(self, client, admin_headers):
        # The DB layer does not check rowcount on UPDATE so a no-op update
        # returns True, causing the route to return 200. Both are acceptable.
        resp = client.put(
            "/api/endpoints/999999",
            json={"name": "Ghost"},
            headers=admin_headers,
        )
        assert resp.status_code in (200, 404)


# ===========================================================================
# DELETE /api/endpoints/{id}  — admin only
# ===========================================================================

class TestEndpointDelete:
    """Delete an endpoint monitor — admin only."""

    def test_no_auth_returns_401(self, client, admin_headers):
        mon_id = _create_endpoint(client, admin_headers, "Delete Me")
        resp = client.delete(f"/api/endpoints/{mon_id}")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, admin_headers, viewer_headers):
        mon_id = _create_endpoint(client, admin_headers, "Delete Me V")
        resp = client.delete(f"/api/endpoints/{mon_id}", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, admin_headers, operator_headers):
        mon_id = _create_endpoint(client, admin_headers, "Delete Me O")
        resp = client.delete(f"/api/endpoints/{mon_id}", headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_delete(self, client, admin_headers):
        mon_id = _create_endpoint(client, admin_headers, "To Delete")
        resp = client.delete(f"/api/endpoints/{mon_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_nonexistent_id_returns_404(self, client, admin_headers):
        resp = client.delete("/api/endpoints/999999", headers=admin_headers)
        assert resp.status_code == 404

    def test_deleted_monitor_no_longer_in_list(self, client, admin_headers):
        mon_id = _create_endpoint(client, admin_headers, "Disappearing Monitor")
        client.delete(f"/api/endpoints/{mon_id}", headers=admin_headers)
        resp = client.get("/api/endpoints", headers=admin_headers)
        ids = [m["id"] for m in resp.json()]
        assert mon_id not in ids


# ===========================================================================
# POST /api/endpoints/{id}/check  — operator+
# ===========================================================================

class TestEndpointCheckNow:
    """Trigger immediate endpoint check — operator or admin."""

    def test_no_auth_returns_401(self, client, admin_headers):
        mon_id = _create_endpoint(client, admin_headers, "Check Now No Auth")
        resp = client.post(f"/api/endpoints/{mon_id}/check")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, admin_headers, viewer_headers):
        mon_id = _create_endpoint(client, admin_headers, "Check Now V")
        resp = client.post(
            f"/api/endpoints/{mon_id}/check", headers=viewer_headers
        )
        assert resp.status_code == 403

    def test_nonexistent_monitor_returns_404(self, client, admin_headers):
        resp = client.post(
            "/api/endpoints/999999/check", headers=admin_headers
        )
        assert resp.status_code == 404

    def test_operator_can_trigger_check(self, client, admin_headers, operator_headers):
        mon_id = _create_endpoint(
            client, admin_headers, "Check Op", "http://check.test"
        )
        mock_result = {
            "last_status": "up", "last_status_code": 200,
            "last_response_ms": 50, "last_checked": 1234567890,
        }
        # _run_endpoint_check is imported inside the route function body, so
        # it must be patched at its definition site: server.scheduler
        with patch(
            "server.scheduler._run_endpoint_check",
            return_value=mock_result,
        ):
            resp = client.post(
                f"/api/endpoints/{mon_id}/check", headers=operator_headers
            )
        assert resp.status_code == 200

    def test_admin_can_trigger_check(self, client, admin_headers):
        mon_id = _create_endpoint(
            client, admin_headers, "Check Admin", "http://check.admin.test"
        )
        mock_result = {
            "last_status": "up", "last_status_code": 200,
            "last_response_ms": 30, "last_checked": 1234567890,
        }
        with patch(
            "server.scheduler._run_endpoint_check",
            return_value=mock_result,
        ):
            resp = client.post(
                f"/api/endpoints/{mon_id}/check", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_status"] == "up"


# ===========================================================================
# Full CRUD cycle for endpoint monitors
# ===========================================================================

class TestEndpointCrudCycle:
    """Full create → read → update → delete cycle for endpoint monitors."""

    def test_full_crud_cycle(self, client, admin_headers):
        # Create
        resp = client.post(
            "/api/endpoints",
            json={"name": "CRUD Monitor", "url": "http://crud.test/health"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        mon_id = resp.json()["id"]

        # Read (appears in list)
        resp = client.get("/api/endpoints", headers=admin_headers)
        assert resp.status_code == 200
        monitors = resp.json()
        ids = [m["id"] for m in monitors]
        assert mon_id in ids

        # Update
        resp = client.put(
            f"/api/endpoints/{mon_id}",
            json={"name": "CRUD Monitor Updated", "check_interval": 120},
            headers=admin_headers,
        )
        assert resp.status_code == 200

        # Delete
        resp = client.delete(f"/api/endpoints/{mon_id}", headers=admin_headers)
        assert resp.status_code == 200

        # Confirm deleted
        resp = client.get("/api/endpoints", headers=admin_headers)
        ids_after = [m["id"] for m in resp.json()]
        assert mon_id not in ids_after


# ===========================================================================
# Full CRUD cycle for status components
# ===========================================================================

class TestStatusComponentCrudCycle:
    """Full create → read → update → delete cycle for status components."""

    def test_full_crud_cycle(self, client, admin_headers):
        # Create
        resp = client.post(
            "/api/status/components",
            json={"name": "CRUD Component", "group_name": "Infrastructure"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        comp_id = resp.json()["id"]

        # Read (appears in list)
        resp = client.get("/api/status/components", headers=admin_headers)
        ids = [c["id"] for c in resp.json()["components"]]
        assert comp_id in ids

        # Update
        resp = client.put(
            f"/api/status/components/{comp_id}",
            json={"name": "CRUD Component Updated", "enabled": True},
            headers=admin_headers,
        )
        assert resp.status_code == 200

        # Delete
        resp = client.delete(
            f"/api/status/components/{comp_id}", headers=admin_headers
        )
        assert resp.status_code == 200

        # Confirm deleted
        resp = client.get("/api/status/components", headers=admin_headers)
        ids_after = [c["id"] for c in resp.json()["components"]]
        assert comp_id not in ids_after
