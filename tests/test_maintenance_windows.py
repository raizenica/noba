# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for maintenance_windows DB functions and API endpoints."""
from __future__ import annotations

import os
import tempfile
import time


from server.db import Database


def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_test_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


class TestMaintenanceWindows:
    def setup_method(self):
        self.db, self.path = _make_db()

    def teardown_method(self):
        _cleanup(self.path)

    def _insert(self, **kwargs):
        defaults = dict(name="Test Window", created_by="admin")
        defaults.update(kwargs)
        return self.db.insert_maintenance_window(**defaults)

    # ── CRUD basics ───────────────────────────────────────────────────────────

    def test_insert_and_list(self):
        wid = self._insert(name="Deploy window")
        assert wid is not None
        rows = self.db.list_maintenance_windows()
        assert len(rows) == 1
        assert rows[0]["id"] == wid
        assert rows[0]["name"] == "Deploy window"
        assert rows[0]["enabled"] is True
        assert rows[0]["suppress_alerts"] is True
        assert rows[0]["duration_min"] == 60

    def test_insert_multiple_ordered_newest_first(self):
        id1 = self._insert(name="First")
        id2 = self._insert(name="Second")
        rows = self.db.list_maintenance_windows()
        assert len(rows) == 2
        # Both rows present regardless of insertion-order tie-break
        ids = {r["id"] for r in rows}
        assert id1 in ids
        assert id2 in ids

    def test_update_name(self):
        wid = self._insert(name="Old Name")
        result = self.db.update_maintenance_window(wid, name="New Name")
        assert result is True
        rows = self.db.list_maintenance_windows()
        assert rows[0]["name"] == "New Name"

    def test_update_enabled(self):
        wid = self._insert()
        self.db.update_maintenance_window(wid, enabled=False)
        rows = self.db.list_maintenance_windows()
        assert rows[0]["enabled"] is False

    def test_update_duration(self):
        wid = self._insert()
        self.db.update_maintenance_window(wid, duration_min=120)
        rows = self.db.list_maintenance_windows()
        assert rows[0]["duration_min"] == 120

    def test_update_nonexistent_returns_false(self):
        result = self.db.update_maintenance_window(9999, name="Ghost")
        assert result is False

    def test_update_no_valid_fields_returns_false(self):
        wid = self._insert()
        result = self.db.update_maintenance_window(wid, nonexistent_field="x")
        assert result is False

    def test_delete(self):
        wid = self._insert()
        result = self.db.delete_maintenance_window(wid)
        assert result is True
        rows = self.db.list_maintenance_windows()
        assert rows == []

    def test_delete_nonexistent_returns_false(self):
        result = self.db.delete_maintenance_window(9999)
        assert result is False

    # ── get_active: one-off windows ───────────────────────────────────────────

    def test_get_active_one_off_in_range(self):
        now = int(time.time())
        wid = self._insert(
            name="Active one-off",
            one_off_start=now - 300,
            one_off_end=now + 300,
        )
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid in ids

    def test_get_active_one_off_not_started(self):
        now = int(time.time())
        wid = self._insert(
            name="Future one-off",
            one_off_start=now + 600,
            one_off_end=now + 1200,
        )
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid not in ids

    def test_get_active_one_off_already_ended(self):
        now = int(time.time())
        wid = self._insert(
            name="Past one-off",
            one_off_start=now - 1200,
            one_off_end=now - 600,
        )
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid not in ids

    # ── get_active: disabled window must not appear ───────────────────────────

    def test_get_active_disabled_one_off_excluded(self):
        now = int(time.time())
        wid = self._insert(
            name="Disabled window",
            one_off_start=now - 300,
            one_off_end=now + 300,
        )
        self.db.update_maintenance_window(wid, enabled=False)
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid not in ids

    def test_get_active_disabled_cron_excluded(self):
        wid = self._insert(
            name="Disabled cron window",
            schedule="* * * * *",
            duration_min=60,
        )
        self.db.update_maintenance_window(wid, enabled=False)
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid not in ids

    # ── get_active: cron-based windows ───────────────────────────────────────

    def test_get_active_cron_always_matches(self):
        """'* * * * *' should always match — window should be active."""
        wid = self._insert(
            name="Always-on cron",
            schedule="* * * * *",
            duration_min=60,
        )
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid in ids

    def test_get_active_no_schedule_no_one_off_not_active(self):
        """A window with neither schedule nor one_off times is not active."""
        wid = self._insert(name="No schedule window")
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid not in ids

    # ── field values in returned dicts ───────────────────────────────────────

    def test_suppress_alerts_default_true(self):
        self._insert()
        rows = self.db.list_maintenance_windows()
        assert rows[0]["suppress_alerts"] is True

    def test_suppress_alerts_false(self):
        self._insert(suppress_alerts=False)
        rows = self.db.list_maintenance_windows()
        assert rows[0]["suppress_alerts"] is False

    def test_override_autonomy_stored(self):
        self._insert(override_autonomy="manual_only")
        rows = self.db.list_maintenance_windows()
        assert rows[0]["override_autonomy"] == "manual_only"

    def test_auto_close_alerts_false_by_default(self):
        self._insert()
        rows = self.db.list_maintenance_windows()
        assert rows[0]["auto_close_alerts"] is False

    def test_created_by_stored(self):
        self._insert(created_by="engineer")
        rows = self.db.list_maintenance_windows()
        assert rows[0]["created_by"] == "engineer"


# ── API tests ─────────────────────────────────────────────────────────────────

class TestMaintenanceWindowsAPI:
    """API tests for /api/maintenance-windows endpoints."""

    # ── GET /api/maintenance-windows — auth required ───────────────────────

    def test_list_unauthenticated_returns_401(self, client):
        resp = client.get("/api/maintenance-windows")
        assert resp.status_code == 401

    def test_list_authenticated_returns_list(self, client, admin_headers):
        resp = client.get("/api/maintenance-windows", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_viewer_allowed(self, client, viewer_headers):
        resp = client.get("/api/maintenance-windows", headers=viewer_headers)
        assert resp.status_code == 200

    # ── POST /api/maintenance-windows — admin creates ──────────────────────

    def test_create_returns_id(self, client, admin_headers):
        resp = client.post(
            "/api/maintenance-windows",
            json={"name": "Test Window"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["status"] == "ok"
        assert isinstance(data["id"], int)

    def test_create_without_name_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/maintenance-windows",
            json={"schedule": "* * * * *"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_create_empty_name_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/maintenance-windows",
            json={"name": "   "},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_viewer_cannot_create_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/maintenance-windows",
            json={"name": "Denied"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_create_window_appears_in_list(self, client, admin_headers):
        resp = client.post(
            "/api/maintenance-windows",
            json={"name": "Visible Window"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        wid = resp.json()["id"]
        list_resp = client.get("/api/maintenance-windows", headers=admin_headers)
        ids = [w["id"] for w in list_resp.json()]
        assert wid in ids

    def test_create_with_full_fields(self, client, admin_headers):
        resp = client.post(
            "/api/maintenance-windows",
            json={
                "name": "Full Window",
                "schedule": "0 2 * * *",
                "duration_min": 120,
                "suppress_alerts": True,
                "override_autonomy": "notify",
                "auto_close_alerts": True,
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    # ── PUT /api/maintenance-windows/{id} — update ────────────────────────

    def test_update_existing_window(self, client, admin_headers):
        create_resp = client.post(
            "/api/maintenance-windows",
            json={"name": "Original"},
            headers=admin_headers,
        )
        wid = create_resp.json()["id"]
        update_resp = client.put(
            f"/api/maintenance-windows/{wid}",
            json={"name": "Updated"},
            headers=admin_headers,
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["status"] == "ok"
        list_resp = client.get("/api/maintenance-windows", headers=admin_headers)
        names = [w["name"] for w in list_resp.json()]
        assert "Updated" in names

    def test_update_nonexistent_returns_404(self, client, admin_headers):
        resp = client.put(
            "/api/maintenance-windows/999999",
            json={"name": "Ghost"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_viewer_cannot_update_returns_403(self, client, admin_headers, viewer_headers):
        create_resp = client.post(
            "/api/maintenance-windows",
            json={"name": "No Touchy"},
            headers=admin_headers,
        )
        wid = create_resp.json()["id"]
        resp = client.put(
            f"/api/maintenance-windows/{wid}",
            json={"name": "Hacked"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    # ── DELETE /api/maintenance-windows/{id} ──────────────────────────────

    def test_delete_existing_window(self, client, admin_headers):
        create_resp = client.post(
            "/api/maintenance-windows",
            json={"name": "To Delete"},
            headers=admin_headers,
        )
        wid = create_resp.json()["id"]
        del_resp = client.delete(
            f"/api/maintenance-windows/{wid}",
            headers=admin_headers,
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "ok"
        list_resp = client.get("/api/maintenance-windows", headers=admin_headers)
        ids = [w["id"] for w in list_resp.json()]
        assert wid not in ids

    def test_delete_nonexistent_returns_404(self, client, admin_headers):
        resp = client.delete(
            "/api/maintenance-windows/999999",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_viewer_cannot_delete_returns_403(self, client, admin_headers, viewer_headers):
        create_resp = client.post(
            "/api/maintenance-windows",
            json={"name": "Protected"},
            headers=admin_headers,
        )
        wid = create_resp.json()["id"]
        resp = client.delete(
            f"/api/maintenance-windows/{wid}",
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    # ── GET /api/maintenance-windows/active ───────────────────────────────

    def test_active_endpoint_returns_list(self, client, admin_headers):
        resp = client.get("/api/maintenance-windows/active", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_active_unauthenticated_returns_401(self, client):
        resp = client.get("/api/maintenance-windows/active")
        assert resp.status_code == 401

    def test_active_shows_one_off_window_in_range(self, client, admin_headers):
        now = int(time.time())
        resp = client.post(
            "/api/maintenance-windows",
            json={
                "name": "Active Now",
                "one_off_start": now - 300,
                "one_off_end": now + 300,
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        active_resp = client.get("/api/maintenance-windows/active", headers=admin_headers)
        names = [w["name"] for w in active_resp.json()]
        assert "Active Now" in names

    def test_active_does_not_show_future_window(self, client, admin_headers):
        now = int(time.time())
        resp = client.post(
            "/api/maintenance-windows",
            json={
                "name": "Future Window",
                "one_off_start": now + 600,
                "one_off_end": now + 1200,
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        active_resp = client.get("/api/maintenance-windows/active", headers=admin_headers)
        names = [w["name"] for w in active_resp.json()]
        assert "Future Window" not in names

    # ── Full CRUD cycle via API ────────────────────────────────────────────

    def test_full_crud_cycle(self, client, admin_headers):
        # Create
        create_resp = client.post(
            "/api/maintenance-windows",
            json={"name": "Cycle Window", "duration_min": 30},
            headers=admin_headers,
        )
        assert create_resp.status_code == 200
        wid = create_resp.json()["id"]

        # Read via list
        list_resp = client.get("/api/maintenance-windows", headers=admin_headers)
        window = next((w for w in list_resp.json() if w["id"] == wid), None)
        assert window is not None
        assert window["name"] == "Cycle Window"
        assert window["duration_min"] == 30

        # Update
        up_resp = client.put(
            f"/api/maintenance-windows/{wid}",
            json={"name": "Cycle Window Updated", "duration_min": 90},
            headers=admin_headers,
        )
        assert up_resp.status_code == 200

        # Verify update
        list_resp2 = client.get("/api/maintenance-windows", headers=admin_headers)
        window2 = next((w for w in list_resp2.json() if w["id"] == wid), None)
        assert window2["name"] == "Cycle Window Updated"
        assert window2["duration_min"] == 90

        # Delete
        del_resp = client.delete(f"/api/maintenance-windows/{wid}", headers=admin_headers)
        assert del_resp.status_code == 200

        # Verify deletion
        list_resp3 = client.get("/api/maintenance-windows", headers=admin_headers)
        ids = [w["id"] for w in list_resp3.json()]
        assert wid not in ids
