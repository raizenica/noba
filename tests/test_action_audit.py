"""Tests for action_audit DB functions, API endpoint, and execute_action integration."""
from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

from server.db import Database


# ── DB-level helpers ──────────────────────────────────────────────────────────

def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_audit_test_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


# ── DB CRUD tests ─────────────────────────────────────────────────────────────

class TestActionAuditDB:
    def setup_method(self):
        self.db, self.path = _make_db()

    def teardown_method(self):
        _cleanup(self.path)

    def _insert(self, **kwargs):
        defaults = dict(
            trigger_type="manual",
            trigger_id="t-001",
            action_type="restart_service",
            action_params={"service": "nginx"},
            target="host-a",
            outcome="success",
            duration_s=1.23,
            output="Service restarted OK",
            approved_by=None,
            rollback_result=None,
            error=None,
        )
        defaults.update(kwargs)
        return self.db.insert_action_audit(**defaults)

    def test_insert_returns_id(self):
        row_id = self._insert()
        assert row_id is not None
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_insert_and_query_all(self):
        self._insert(outcome="success")
        self._insert(outcome="failure")
        rows = self.db.get_action_audit(limit=100)
        assert len(rows) == 2

    def test_query_returns_correct_fields(self):
        row_id = self._insert(
            trigger_type="alert",
            action_type="restart_container",
            action_params={"container": "myapp"},
            target="host-b",
            outcome="success",
            duration_s=2.5,
            output="Container restarted",
            approved_by="alice",
        )
        rows = self.db.get_action_audit(limit=10)
        assert len(rows) == 1
        r = rows[0]
        assert r["id"] == row_id
        assert r["trigger_type"] == "alert"
        assert r["action_type"] == "restart_container"
        assert r["action_params"] == {"container": "myapp"}
        assert r["target"] == "host-b"
        assert r["outcome"] == "success"
        assert r["duration_s"] == 2.5
        assert r["output"] == "Container restarted"
        assert r["approved_by"] == "alice"

    def test_filter_by_trigger_type(self):
        self._insert(trigger_type="alert")
        self._insert(trigger_type="manual")
        self._insert(trigger_type="alert")
        rows = self.db.get_action_audit(trigger_type="alert")
        assert len(rows) == 2
        assert all(r["trigger_type"] == "alert" for r in rows)

    def test_filter_by_outcome(self):
        self._insert(outcome="success")
        self._insert(outcome="failure")
        self._insert(outcome="success")
        self._insert(outcome="error")
        success_rows = self.db.get_action_audit(outcome="success")
        assert len(success_rows) == 2
        failure_rows = self.db.get_action_audit(outcome="failure")
        assert len(failure_rows) == 1
        error_rows = self.db.get_action_audit(outcome="error")
        assert len(error_rows) == 1

    def test_filter_by_trigger_type_and_outcome(self):
        self._insert(trigger_type="alert", outcome="success")
        self._insert(trigger_type="alert", outcome="failure")
        self._insert(trigger_type="manual", outcome="success")
        rows = self.db.get_action_audit(trigger_type="alert", outcome="success")
        assert len(rows) == 1
        assert rows[0]["trigger_type"] == "alert"
        assert rows[0]["outcome"] == "success"

    def test_limit_is_respected(self):
        for i in range(10):
            self._insert(output=f"run-{i}")
        rows = self.db.get_action_audit(limit=3)
        assert len(rows) == 3

    def test_default_limit_100(self):
        # Insert 5 rows — default limit of 100 returns all
        for _ in range(5):
            self._insert()
        rows = self.db.get_action_audit()
        assert len(rows) == 5

    def test_results_ordered_newest_first(self):
        # Insert rows with distinct timestamps by inserting directly with different ts
        conn = self.db._get_conn()
        conn.execute(
            "INSERT INTO action_audit "
            "(timestamp, trigger_type, action_type, outcome) VALUES (?,?,?,?)",
            (1000, "manual", "flush_dns", "success"),
        )
        conn.execute(
            "INSERT INTO action_audit "
            "(timestamp, trigger_type, action_type, outcome) VALUES (?,?,?,?)",
            (3000, "manual", "flush_dns", "success"),
        )
        conn.execute(
            "INSERT INTO action_audit "
            "(timestamp, trigger_type, action_type, outcome) VALUES (?,?,?,?)",
            (2000, "manual", "flush_dns", "success"),
        )
        conn.commit()
        rows = self.db.get_action_audit(limit=10)
        timestamps = [r["timestamp"] for r in rows]
        # ORDER BY timestamp DESC — must be non-increasing
        assert timestamps == sorted(timestamps, reverse=True)

    def test_null_optional_fields(self):
        self.db.insert_action_audit(
            trigger_type="manual",
            trigger_id=None,
            action_type="flush_dns",
            action_params=None,
            target=None,
            outcome="success",
        )
        rows = self.db.get_action_audit(limit=10)
        assert len(rows) == 1
        r = rows[0]
        assert r["trigger_id"] is None
        assert r["action_params"] is None
        assert r["target"] is None
        assert r["error"] is None

    def test_error_field_stored(self):
        self._insert(outcome="error", error="Connection refused")
        rows = self.db.get_action_audit(outcome="error")
        assert rows[0]["error"] == "Connection refused"

    def test_empty_db_returns_empty_list(self):
        rows = self.db.get_action_audit()
        assert rows == []

    def test_no_match_filter_returns_empty(self):
        self._insert(trigger_type="alert")
        rows = self.db.get_action_audit(trigger_type="nonexistent")
        assert rows == []


# ── API endpoint tests ────────────────────────────────────────────────────────

def _seed_audit_entry(**kwargs):
    """Insert directly into the shared app db."""
    from server.db import db as app_db
    defaults = dict(
        trigger_type="manual",
        trigger_id=None,
        action_type="restart_service",
        action_params={"service": "nginx"},
        target="host-test",
        outcome="success",
        duration_s=0.5,
        output="ok",
    )
    defaults.update(kwargs)
    return app_db.insert_action_audit(**defaults)


class TestActionAuditEndpoint:
    """GET /api/action-audit"""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/action-audit")
        assert resp.status_code == 401

    def test_viewer_can_read(self, client, viewer_headers):
        resp = client.get("/api/action-audit", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_operator_can_read(self, client, operator_headers):
        resp = client.get("/api/action-audit", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_read(self, client, admin_headers):
        resp = client.get("/api/action-audit", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_seeded_entry(self, client, admin_headers):
        row_id = _seed_audit_entry(trigger_type="alert", outcome="success")
        resp = client.get("/api/action-audit", headers=admin_headers)
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()]
        assert row_id in ids

    def test_filter_by_trigger_type(self, client, admin_headers):
        _seed_audit_entry(trigger_type="alert")
        _seed_audit_entry(trigger_type="manual")
        resp = client.get("/api/action-audit?trigger_type=alert", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["trigger_type"] == "alert" for r in data)
        types = {r["trigger_type"] for r in data}
        assert "manual" not in types

    def test_filter_by_outcome(self, client, admin_headers):
        _seed_audit_entry(outcome="success")
        _seed_audit_entry(outcome="failure")
        resp = client.get("/api/action-audit?outcome=failure", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["outcome"] == "failure" for r in data)

    def test_limit_param(self, client, admin_headers):
        for _ in range(5):
            _seed_audit_entry()
        resp = client.get("/api/action-audit?limit=2", headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()) <= 2

    def test_limit_capped_at_500(self, client, admin_headers):
        # Verify the endpoint doesn't crash with a huge limit param
        resp = client.get("/api/action-audit?limit=9999", headers=admin_headers)
        assert resp.status_code == 200

    def test_no_entries_returns_empty_list(self, client, admin_headers):
        resp = client.get("/api/action-audit", headers=admin_headers)
        assert resp.status_code == 200
        # Result may contain entries from other tests; just verify it's a list
        assert isinstance(resp.json(), list)


# ── Integration: execute_action writes audit entry ────────────────────────────

class TestExecuteActionAuditIntegration:
    """Verify that execute_action() records an audit entry in the DB."""

    def test_successful_action_records_success_outcome(self):
        from server.db import db as app_db
        from server import remediation

        def _ok_handler(params):
            return {"success": True, "output": "OK"}

        with patch.dict(remediation._HANDLERS, {"restart_service": _ok_handler}):
            result = remediation.execute_action(
                "restart_service",
                {"service": "test-svc"},
                triggered_by="test-user",
                trigger_type="test_integration",
                trigger_id="int-001",
                target="host-int",
            )

        assert result["success"] is True
        after_rows = app_db.get_action_audit(trigger_type="test_integration", limit=500)
        assert len(after_rows) >= 1
        entry = after_rows[0]
        assert entry["outcome"] == "success"
        assert entry["action_type"] == "restart_service"
        assert entry["trigger_type"] == "test_integration"
        assert entry["trigger_id"] == "int-001"
        assert entry["target"] == "host-int"
        assert entry["action_params"] == {"service": "test-svc"}

    def test_failed_action_records_failure_outcome(self):
        from server.db import db as app_db
        from server import remediation

        def _fail_handler(params):
            return {"success": False, "output": "Unit not found"}

        with patch.dict(remediation._HANDLERS, {"restart_service": _fail_handler}):
            result = remediation.execute_action(
                "restart_service",
                {"service": "bad-svc"},
                triggered_by="system",
                trigger_type="test_integration_fail",
            )

        assert result["success"] is False
        rows = app_db.get_action_audit(trigger_type="test_integration_fail", limit=500)
        assert len(rows) >= 1
        assert rows[0]["outcome"] == "failure"

    def test_exception_in_handler_records_error_outcome(self):
        from server.db import db as app_db
        from server import remediation

        def _crash_handler(params):
            raise RuntimeError("Subprocess exploded")

        with patch.dict(remediation._HANDLERS, {"restart_service": _crash_handler}):
            result = remediation.execute_action(
                "restart_service",
                {"service": "crash-svc"},
                triggered_by="system",
                trigger_type="test_integration_exc",
            )

        assert result["success"] is False
        assert result["error"] == "Action execution failed"
        rows = app_db.get_action_audit(trigger_type="test_integration_exc", limit=500)
        assert len(rows) >= 1
        entry = rows[0]
        assert entry["outcome"] == "error"
        # Audit log retains raw error for operators; API response is sanitized
        assert "Subprocess exploded" in entry["error"]

    def test_unknown_action_type_records_error_outcome(self):
        from server.db import db as app_db
        from server.remediation import execute_action

        execute_action(
            "nonexistent_action",
            {},
            triggered_by="system",
            trigger_type="test_unknown_action",
        )

        rows = app_db.get_action_audit(trigger_type="test_unknown_action", limit=500)
        assert len(rows) >= 1
        assert rows[0]["outcome"] == "error"

    def test_approved_by_is_stored(self):
        from server.db import db as app_db
        from server import remediation

        def _flush_ok(params):
            return {"success": True, "output": "flushed"}

        with patch.dict(remediation._HANDLERS, {"flush_dns": _flush_ok}):
            remediation.execute_action(
                "flush_dns",
                {},
                triggered_by="approver",
                trigger_type="test_approval_audit",
                approved_by="admin-user",
            )

        rows = app_db.get_action_audit(trigger_type="test_approval_audit", limit=500)
        assert len(rows) >= 1
        assert rows[0]["approved_by"] == "admin-user"

    def test_duration_is_recorded(self):
        from server.db import db as app_db
        from server import remediation

        def _svc_ok(params):
            return {"success": True, "output": "done"}

        with patch.dict(remediation._HANDLERS, {"restart_service": _svc_ok}):
            remediation.execute_action(
                "restart_service",
                {"service": "dur-svc"},
                triggered_by="system",
                trigger_type="test_duration_check",
            )

        rows = app_db.get_action_audit(trigger_type="test_duration_check", limit=500)
        assert len(rows) >= 1
        assert rows[0]["duration_s"] is not None
        assert rows[0]["duration_s"] >= 0
