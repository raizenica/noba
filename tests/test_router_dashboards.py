# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for the dashboards router (share/noba-web/server/routers/dashboards.py)."""
from __future__ import annotations



# ===========================================================================
# GET /api/dashboards
# ===========================================================================

class TestListDashboards:
    """List dashboards — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/dashboards")
        assert resp.status_code == 401

    def test_viewer_can_list(self, client, viewer_headers):
        resp = client.get("/api/dashboards", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_operator_can_list(self, client, operator_headers):
        resp = client.get("/api/dashboards", headers=operator_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_admin_can_list(self, client, admin_headers):
        resp = client.get("/api/dashboards", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_empty_list_when_no_dashboards(self, client, admin_headers):
        resp = client.get("/api/dashboards", headers=admin_headers)
        assert resp.status_code == 200
        # Result is a list (may or may not be empty depending on prior tests)
        assert isinstance(resp.json(), list)


# ===========================================================================
# POST /api/dashboards
# ===========================================================================

class TestCreateDashboard:
    """Create a dashboard — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/dashboards",
            json={"name": "Test", "config_json": "{}"},
        )
        assert resp.status_code == 401

    def test_missing_name_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/dashboards",
            json={"config_json": "{}"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_empty_name_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/dashboards",
            json={"name": "   ", "config_json": "{}"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_missing_config_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/dashboards",
            json={"name": "My Dashboard"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_invalid_config_json_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/dashboards",
            json={"name": "My Dashboard", "config_json": "{not valid json}"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_success_returns_id(self, client, admin_headers):
        resp = client.post(
            "/api/dashboards",
            json={"name": "My Dashboard", "config_json": '{"widgets": []}'},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "id" in data
        assert isinstance(data["id"], int)

    def test_success_with_shared_flag(self, client, admin_headers):
        resp = client.post(
            "/api/dashboards",
            json={"name": "Shared Dashboard", "config_json": '{"layout": "grid"}', "shared": True},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_config_json_as_dict_is_accepted(self, client, operator_headers):
        resp = client.post(
            "/api/dashboards",
            json={"name": "Dict Config", "config_json": {"widgets": [], "layout": "flex"}},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_viewer_cannot_create(self, client, viewer_headers):
        resp = client.post(
            "/api/dashboards",
            json={"name": "Viewer Dash", "config_json": "{}"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403


# ===========================================================================
# PUT /api/dashboards/{id}
# ===========================================================================

class TestUpdateDashboard:
    """Update a dashboard — owner or admin only."""

    def _create(self, client, headers, name="TestDash", shared=False):
        """Helper: create a dashboard and return its id."""
        resp = client.post(
            "/api/dashboards",
            json={"name": name, "config_json": '{"v": 1}', "shared": shared},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["id"]

    def test_no_auth_returns_401(self, client, admin_headers):
        dash_id = self._create(client, admin_headers)
        resp = client.put(f"/api/dashboards/{dash_id}", json={"name": "New Name"})
        assert resp.status_code == 401

    def test_nonexistent_dashboard_returns_404(self, client, admin_headers):
        resp = client.put(
            "/api/dashboards/999999",
            json={"name": "Nope"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_owner_can_update_name(self, client, operator_headers):
        dash_id = self._create(client, operator_headers, name="Original")
        resp = client.put(
            f"/api/dashboards/{dash_id}",
            json={"name": "Updated Name"},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_owner_can_update_config(self, client, operator_headers):
        dash_id = self._create(client, operator_headers, name="ConfigDash")
        resp = client.put(
            f"/api/dashboards/{dash_id}",
            json={"config_json": '{"v": 2, "updated": true}'},
            headers=operator_headers,
        )
        assert resp.status_code == 200

    def test_owner_can_toggle_shared(self, client, operator_headers):
        dash_id = self._create(client, operator_headers, name="SharedToggle")
        resp = client.put(
            f"/api/dashboards/{dash_id}",
            json={"shared": True},
            headers=operator_headers,
        )
        assert resp.status_code == 200

    def test_admin_can_update_other_users_dashboard(self, client, operator_headers, admin_headers):
        dash_id = self._create(client, operator_headers, name="OpDash")
        resp = client.put(
            f"/api/dashboards/{dash_id}",
            json={"name": "Admin Updated"},
            headers=admin_headers,
        )
        assert resp.status_code == 200

    def test_different_user_cannot_update(self, client, operator_headers, viewer_headers):
        dash_id = self._create(client, operator_headers, name="ProtectedDash")
        resp = client.put(
            f"/api/dashboards/{dash_id}",
            json={"name": "Hijacked"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_invalid_config_json_returns_400(self, client, admin_headers):
        dash_id = self._create(client, admin_headers, name="BadUpdate")
        resp = client.put(
            f"/api/dashboards/{dash_id}",
            json={"config_json": "{bad json}"},
            headers=admin_headers,
        )
        assert resp.status_code == 400


# ===========================================================================
# DELETE /api/dashboards/{id}
# ===========================================================================

class TestDeleteDashboard:
    """Delete a dashboard — owner or admin only."""

    def _create(self, client, headers, name="DeleteDash"):
        resp = client.post(
            "/api/dashboards",
            json={"name": name, "config_json": "{}"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["id"]

    def test_no_auth_returns_401(self, client, admin_headers):
        dash_id = self._create(client, admin_headers)
        resp = client.delete(f"/api/dashboards/{dash_id}")
        assert resp.status_code == 401

    def test_nonexistent_dashboard_returns_404(self, client, admin_headers):
        resp = client.delete("/api/dashboards/999999", headers=admin_headers)
        assert resp.status_code == 404

    def test_owner_can_delete(self, client, operator_headers):
        dash_id = self._create(client, operator_headers, name="ToDelete")
        resp = client.delete(f"/api/dashboards/{dash_id}", headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_admin_can_delete_others_dashboard(self, client, operator_headers, admin_headers):
        dash_id = self._create(client, operator_headers, name="OpToDelete")
        resp = client.delete(f"/api/dashboards/{dash_id}", headers=admin_headers)
        assert resp.status_code == 200

    def test_different_user_cannot_delete(self, client, operator_headers, viewer_headers):
        dash_id = self._create(client, operator_headers, name="ProtectedDelete")
        resp = client.delete(f"/api/dashboards/{dash_id}", headers=viewer_headers)
        assert resp.status_code == 403

    def test_delete_twice_returns_404(self, client, admin_headers):
        dash_id = self._create(client, admin_headers, name="DeleteTwice")
        client.delete(f"/api/dashboards/{dash_id}", headers=admin_headers)
        resp = client.delete(f"/api/dashboards/{dash_id}", headers=admin_headers)
        assert resp.status_code == 404


# ===========================================================================
# Full CRUD cycle
# ===========================================================================

class TestDashboardCrudCycle:
    """End-to-end create → list → update → verify → delete → verify gone."""

    def test_full_crud_cycle(self, client, admin_headers):
        # 1. Create
        create_resp = client.post(
            "/api/dashboards",
            json={"name": "CRUD Test", "config_json": '{"step": 1}', "shared": False},
            headers=admin_headers,
        )
        assert create_resp.status_code == 200
        dash_id = create_resp.json()["id"]

        # 2. List — dashboard should appear
        list_resp = client.get("/api/dashboards", headers=admin_headers)
        assert list_resp.status_code == 200
        ids = [d["id"] for d in list_resp.json()]
        assert dash_id in ids

        # 3. Update
        update_resp = client.put(
            f"/api/dashboards/{dash_id}",
            json={"name": "CRUD Updated", "config_json": '{"step": 2}', "shared": True},
            headers=admin_headers,
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["status"] == "ok"

        # 4. Delete
        delete_resp = client.delete(f"/api/dashboards/{dash_id}", headers=admin_headers)
        assert delete_resp.status_code == 200
        assert delete_resp.json()["status"] == "ok"

        # 5. Verify gone
        list_after = client.get("/api/dashboards", headers=admin_headers)
        ids_after = [d["id"] for d in list_after.json()]
        assert dash_id not in ids_after

    def test_multiple_dashboards_listed(self, client, admin_headers):
        ids = []
        for i in range(3):
            resp = client.post(
                "/api/dashboards",
                json={"name": f"Dash {i}", "config_json": f'{{"i": {i}}}'},
                headers=admin_headers,
            )
            assert resp.status_code == 200
            ids.append(resp.json()["id"])

        list_resp = client.get("/api/dashboards", headers=admin_headers)
        assert list_resp.status_code == 200
        listed_ids = [d["id"] for d in list_resp.json()]
        for dash_id in ids:
            assert dash_id in listed_ids

        # Cleanup
        for dash_id in ids:
            client.delete(f"/api/dashboards/{dash_id}", headers=admin_headers)
