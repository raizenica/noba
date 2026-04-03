# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for approval_queue DB functions and API endpoints."""
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


class TestApprovalQueue:
    def setup_method(self):
        self.db, self.path = _make_db()

    def teardown_method(self):
        _cleanup(self.path)

    def _insert(self, **kwargs):
        defaults = dict(
            automation_id="auto-1",
            trigger="manual",
            trigger_source=None,
            action_type="restart_service",
            action_params={"service": "nginx"},
            target="host-a",
            requested_by="alice",
        )
        defaults.update(kwargs)
        return self.db.insert_approval(**defaults)

    def test_insert_and_list_pending(self):
        row_id = self._insert()
        assert row_id is not None
        rows = self.db.list_approvals(status="pending")
        assert len(rows) == 1
        assert rows[0]["id"] == row_id
        assert rows[0]["automation_id"] == "auto-1"
        assert rows[0]["action_type"] == "restart_service"
        assert rows[0]["status"] == "pending"

    def test_insert_and_get_by_id(self):
        row_id = self._insert(target="host-b")
        rec = self.db.get_approval(row_id)
        assert rec is not None
        assert rec["id"] == row_id
        assert rec["target"] == "host-b"
        assert rec["action_params"] == {"service": "nginx"}

    def test_get_nonexistent_returns_none(self):
        assert self.db.get_approval(9999) is None

    def test_decide_approve(self):
        row_id = self._insert()
        result = self.db.decide_approval(row_id, "approved", "bob")
        assert result is True
        rec = self.db.get_approval(row_id)
        assert rec["status"] == "approved"
        assert rec["decided_by"] == "bob"
        assert rec["decided_at"] is not None

    def test_decide_deny(self):
        row_id = self._insert()
        result = self.db.decide_approval(row_id, "denied", "carol")
        assert result is True
        rec = self.db.get_approval(row_id)
        assert rec["status"] == "denied"
        assert rec["decided_by"] == "carol"

    def test_decide_on_non_pending_returns_false(self):
        row_id = self._insert()
        self.db.decide_approval(row_id, "approved", "bob")
        # Second decide on already-approved → should return False
        result = self.db.decide_approval(row_id, "denied", "carol")
        assert result is False
        # Status must not have changed
        rec = self.db.get_approval(row_id)
        assert rec["status"] == "approved"

    def test_auto_approve_expired_past_timestamp(self):
        past = int(time.time()) - 3600
        row_id = self._insert(auto_approve_at=past)
        count = self.db.auto_approve_expired()
        assert count == 1
        rec = self.db.get_approval(row_id)
        assert rec["status"] == "auto_approved"

    def test_auto_approve_expired_future_timestamp_not_approved(self):
        future = int(time.time()) + 3600
        row_id = self._insert(auto_approve_at=future)
        count = self.db.auto_approve_expired()
        assert count == 0
        rec = self.db.get_approval(row_id)
        assert rec["status"] == "pending"

    def test_auto_approve_no_auto_approve_at_not_touched(self):
        row_id = self._insert()  # no auto_approve_at
        count = self.db.auto_approve_expired()
        assert count == 0
        rec = self.db.get_approval(row_id)
        assert rec["status"] == "pending"

    def test_count_pending(self):
        assert self.db.count_pending_approvals() == 0
        self._insert()
        self._insert()
        assert self.db.count_pending_approvals() == 2
        row_id = self._insert()
        self.db.decide_approval(row_id, "approved", "admin")
        assert self.db.count_pending_approvals() == 2

    def test_update_approval_result(self):
        row_id = self._insert()
        self.db.update_approval_result(row_id, "Service restarted successfully")
        rec = self.db.get_approval(row_id)
        assert rec["result"] == "Service restarted successfully"

    def test_list_approved_empty_when_pending(self):
        self._insert()
        rows = self.db.list_approvals(status="approved")
        assert rows == []

    def test_list_multiple_statuses(self):
        id1 = self._insert()
        id2 = self._insert()
        self.db.decide_approval(id1, "approved", "admin")
        self.db.decide_approval(id2, "denied", "admin")
        pending = self.db.list_approvals(status="pending")
        approved = self.db.list_approvals(status="approved")
        denied = self.db.list_approvals(status="denied")
        assert len(pending) == 0
        assert len(approved) == 1
        assert len(denied) == 1


# ── API endpoint tests ─────────────────────────────────────────────────────────

def _seed_approval(**kwargs):
    """Insert an approval directly into the shared db singleton used by the app."""
    from server.db import db as app_db
    defaults = dict(
        automation_id="auto-api-test",
        trigger="alert:cpu_high",
        trigger_source=None,
        action_type="restart_service",
        action_params={"service": "nginx"},
        target="host-x",
        requested_by="alert-engine",
    )
    defaults.update(kwargs)
    return app_db.insert_approval(**defaults)


class TestApprovalCountEndpoint:
    """GET /api/approvals/count"""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/approvals/count")
        assert resp.status_code == 401

    def test_returns_zero_when_empty(self, client, admin_headers):
        resp = client.get("/api/approvals/count", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_counts_pending_approvals(self, client, admin_headers):
        _seed_approval()
        _seed_approval()
        resp = client.get("/api/approvals/count", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["count"] >= 2

    def test_viewer_can_read_count(self, client, viewer_headers):
        resp = client.get("/api/approvals/count", headers=viewer_headers)
        assert resp.status_code == 200
        assert "count" in resp.json()


class TestApprovalListEndpoint:
    """GET /api/approvals"""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/approvals")
        assert resp.status_code == 401

    def test_returns_list(self, client, admin_headers):
        resp = client.get("/api/approvals", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_default_filter_is_pending(self, client, admin_headers):
        approval_id = _seed_approval()
        resp = client.get("/api/approvals", headers=admin_headers)
        assert resp.status_code == 200
        ids = [a["id"] for a in resp.json()]
        assert approval_id in ids

    def test_filter_by_status(self, client, admin_headers):
        from server.db import db as app_db
        approval_id = _seed_approval()
        app_db.decide_approval(approval_id, "denied", "admin")
        resp = client.get("/api/approvals?status=denied", headers=admin_headers)
        assert resp.status_code == 200
        ids = [a["id"] for a in resp.json()]
        assert approval_id in ids

    def test_viewer_can_list(self, client, viewer_headers):
        resp = client.get("/api/approvals", headers=viewer_headers)
        assert resp.status_code == 200


class TestApprovalGetEndpoint:
    """GET /api/approvals/{approval_id}"""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/approvals/999")
        assert resp.status_code == 401

    def test_nonexistent_returns_404(self, client, admin_headers):
        resp = client.get("/api/approvals/999999", headers=admin_headers)
        assert resp.status_code == 404

    def test_returns_approval_detail(self, client, admin_headers):
        approval_id = _seed_approval(target="host-detail")
        resp = client.get(f"/api/approvals/{approval_id}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == approval_id
        assert data["target"] == "host-detail"
        assert data["action_type"] == "restart_service"
        assert data["status"] == "pending"

    def test_viewer_can_get(self, client, viewer_headers):
        approval_id = _seed_approval()
        resp = client.get(f"/api/approvals/{approval_id}", headers=viewer_headers)
        assert resp.status_code == 200


class TestApprovalDecideEndpoint:
    """POST /api/approvals/{approval_id}/decide"""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/approvals/1/decide", json={"decision": "approved"})
        assert resp.status_code == 401

    def test_viewer_cannot_decide_returns_403(self, client, viewer_headers):
        approval_id = _seed_approval()
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"decision": "approved"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_nonexistent_approval_returns_404(self, client, operator_headers):
        resp = client.post(
            "/api/approvals/999999/decide",
            json={"decision": "approved"},
            headers=operator_headers,
        )
        assert resp.status_code == 404

    def test_invalid_decision_returns_400(self, client, operator_headers):
        approval_id = _seed_approval()
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"decision": "maybe"},
            headers=operator_headers,
        )
        assert resp.status_code == 400

    def test_already_decided_returns_400(self, client, operator_headers):
        from server.db import db as app_db
        approval_id = _seed_approval()
        app_db.decide_approval(approval_id, "denied", "admin")
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"decision": "approved"},
            headers=operator_headers,
        )
        assert resp.status_code == 400

    def test_deny_flow(self, client, operator_headers):
        from server.db import db as app_db
        approval_id = _seed_approval()
        resp = client.post(
            f"/api/approvals/{approval_id}/decide",
            json={"decision": "denied"},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["decision"] == "denied"
        rec = app_db.get_approval(approval_id)
        assert rec["status"] == "denied"

    def test_approve_flow_executes_action(self, client, operator_headers):
        from unittest.mock import patch
        from server.db import db as app_db

        approval_id = _seed_approval(
            action_type="restart_service",
            action_params={"service": "nginx"},
        )
        fake_result = {"success": True, "action": "restart_service"}
        with patch("server.remediation.execute_action", return_value=fake_result) as mock_exec:
            resp = client.post(
                f"/api/approvals/{approval_id}/decide",
                json={"decision": "approved"},
                headers=operator_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["decision"] == "approved"
        mock_exec.assert_called_once_with(
            "restart_service",
            {"service": "nginx"},
            triggered_by="operator_user",
            trigger_type="approval",
            trigger_id=str(approval_id),
            target="host-x",
            approved_by="operator_user",
        )
        rec = app_db.get_approval(approval_id)
        assert rec["status"] == "approved"
        assert rec["result"] is not None

    def test_operator_can_decide(self, client, operator_headers):
        from unittest.mock import patch
        approval_id = _seed_approval()
        with patch("server.remediation.execute_action", return_value={"success": True}):
            resp = client.post(
                f"/api/approvals/{approval_id}/decide",
                json={"decision": "approved"},
                headers=operator_headers,
            )
        assert resp.status_code == 200

    def test_admin_can_decide(self, client, admin_headers):
        from unittest.mock import patch
        approval_id = _seed_approval()
        with patch("server.remediation.execute_action", return_value={"success": True}):
            resp = client.post(
                f"/api/approvals/{approval_id}/decide",
                json={"decision": "approved"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
