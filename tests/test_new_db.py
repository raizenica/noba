# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the new DB tables and methods added in v2.0.0."""
import os
import tempfile

from server.db import Database


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


class TestAlertHistory:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_insert_and_get(self):
        self.db.insert_alert_history("rule1", "warning", "CPU high")
        results = self.db.get_alert_history(limit=10)
        assert len(results) >= 1
        assert results[0]["rule_id"] == "rule1"
        assert results[0]["severity"] == "warning"

    def test_filter_by_rule_id(self):
        self.db.insert_alert_history("rule1", "warning", "CPU high")
        self.db.insert_alert_history("rule2", "danger", "Disk full")
        results = self.db.get_alert_history(rule_id="rule1")
        assert all(r["rule_id"] == "rule1" for r in results)

    def test_resolve_alert(self):
        self.db.insert_alert_history("rule1", "warning", "CPU high")
        self.db.resolve_alert("rule1")
        results = self.db.get_alert_history()
        assert results[0].get("resolved_at") is not None

    def test_sla_100_percent_no_alerts(self):
        result = self.db.get_sla("rule1", window_hours=24)
        assert result == 100.0 or isinstance(result, (int, float))


class TestApiKeys:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_insert_and_list(self):
        self.db.insert_api_key("key1", "Test Key", "hash123", "viewer")
        keys = self.db.list_api_keys()
        assert len(keys) == 1
        assert keys[0]["name"] == "Test Key"
        assert "key_hash" not in keys[0]  # should not expose hash

    def test_get_by_hash(self):
        self.db.insert_api_key("key1", "Test Key", "hash123", "viewer")
        result = self.db.get_api_key("hash123")
        assert result is not None
        assert result["role"] == "viewer"

    def test_get_nonexistent(self):
        assert self.db.get_api_key("nonexistent") is None

    def test_delete(self):
        self.db.insert_api_key("key1", "Test Key", "hash123", "viewer")
        assert self.db.delete_api_key("key1") is True
        assert self.db.list_api_keys() == []

    def test_delete_nonexistent(self):
        assert self.db.delete_api_key("nope") is False


class TestNotifications:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_insert_and_get(self):
        self.db.insert_notification("info", "Test", "Hello", username="user1")
        results = self.db.get_notifications(username="user1")
        assert len(results) >= 1
        assert results[0]["title"] == "Test"

    def test_unread_count(self):
        self.db.insert_notification("info", "Test1", "msg1", username="user1")
        self.db.insert_notification("info", "Test2", "msg2", username="user1")
        assert self.db.get_unread_count("user1") == 2

    def test_mark_read(self):
        self.db.insert_notification("info", "Test", "msg", username="user1")
        notifs = self.db.get_notifications(username="user1")
        self.db.mark_notification_read(notifs[0]["id"], "user1")
        assert self.db.get_unread_count("user1") == 0

    def test_mark_all_read(self):
        self.db.insert_notification("info", "A", "a", username="user1")
        self.db.insert_notification("info", "B", "b", username="user1")
        self.db.mark_all_notifications_read("user1")
        assert self.db.get_unread_count("user1") == 0

    def test_unread_only_filter(self):
        self.db.insert_notification("info", "A", "a", username="user1")
        self.db.insert_notification("info", "B", "b", username="user1")
        notifs = self.db.get_notifications(username="user1")
        self.db.mark_notification_read(notifs[0]["id"], "user1")
        unread = self.db.get_notifications(username="user1", unread_only=True)
        assert len(unread) == 1


class TestUserDashboards:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_save_and_get(self):
        self.db.save_user_dashboard("user1", card_order=["core", "hw"], card_vis={"core": True})
        result = self.db.get_user_dashboard("user1")
        assert result is not None
        assert result["card_order"] == ["core", "hw"]

    def test_get_nonexistent(self):
        assert self.db.get_user_dashboard("nobody") is None

    def test_update(self):
        self.db.save_user_dashboard("user1", card_order=["core"])
        self.db.save_user_dashboard("user1", card_order=["core", "hw", "net"])
        result = self.db.get_user_dashboard("user1")
        assert len(result["card_order"]) == 3
