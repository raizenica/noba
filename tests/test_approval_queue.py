"""Tests for approval_queue DB functions."""
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
