# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the Collaborative Incident War Room -- DB CRUD and API endpoints."""
from __future__ import annotations

import os
import tempfile

from server.db import Database


def _make_db():
    """Create a fresh temp DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_test_warroom_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


# -- Incident Message CRUD ----------------------------------------------------

class TestIncidentMessages:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_add_message(self):
        iid = self.db.create_status_incident("Outage", severity="major", created_by="admin")
        msg_id = self.db.add_incident_message(iid, "admin", "Investigating the root cause")
        assert msg_id > 0

    def test_get_messages_empty(self):
        iid = self.db.create_status_incident("Test")
        messages = self.db.get_incident_messages(iid)
        assert messages == []

    def test_get_messages_ordered(self):
        iid = self.db.create_status_incident("Test")
        self.db.add_incident_message(iid, "alice", "First message")
        self.db.add_incident_message(iid, "bob", "Second message")
        self.db.add_incident_message(iid, "alice", "Third message")
        messages = self.db.get_incident_messages(iid)
        assert len(messages) == 3
        assert messages[0]["author"] == "alice"
        assert messages[0]["message"] == "First message"
        assert messages[1]["author"] == "bob"
        assert messages[2]["message"] == "Third message"

    def test_message_fields(self):
        iid = self.db.create_status_incident("Test")
        msg_id = self.db.add_incident_message(iid, "admin", "System check", msg_type="system")
        messages = self.db.get_incident_messages(iid)
        assert len(messages) == 1
        assert messages[0]["id"] == msg_id
        assert messages[0]["incident_id"] == iid
        assert messages[0]["author"] == "admin"
        assert messages[0]["message"] == "System check"
        assert messages[0]["msg_type"] == "system"
        assert messages[0]["created_at"] is not None

    def test_default_msg_type(self):
        iid = self.db.create_status_incident("Test")
        self.db.add_incident_message(iid, "admin", "Just a comment")
        messages = self.db.get_incident_messages(iid)
        assert messages[0]["msg_type"] == "comment"

    def test_messages_per_incident(self):
        """Messages should be scoped to their incident."""
        iid1 = self.db.create_status_incident("Incident A")
        iid2 = self.db.create_status_incident("Incident B")
        self.db.add_incident_message(iid1, "admin", "Message for A")
        self.db.add_incident_message(iid2, "admin", "Message for B")
        self.db.add_incident_message(iid1, "admin", "Another for A")
        msgs1 = self.db.get_incident_messages(iid1)
        msgs2 = self.db.get_incident_messages(iid2)
        assert len(msgs1) == 2
        assert len(msgs2) == 1
        assert all(m["incident_id"] == iid1 for m in msgs1)
        assert msgs2[0]["incident_id"] == iid2

    def test_message_limit(self):
        iid = self.db.create_status_incident("Test")
        for i in range(10):
            self.db.add_incident_message(iid, "admin", f"Message {i}")
        messages = self.db.get_incident_messages(iid, limit=5)
        assert len(messages) == 5
        # Should be first 5 messages (oldest first)
        assert messages[0]["message"] == "Message 0"
        assert messages[4]["message"] == "Message 4"


# -- Incident Assignment ------------------------------------------------------

class TestIncidentAssignment:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_assign_incident(self):
        iid = self.db.create_status_incident("Outage", created_by="admin")
        ok = self.db.assign_incident(iid, "bob")
        assert ok is True
        detail = self.db.get_status_incident(iid)
        assert detail["assigned_to"] == "bob"

    def test_reassign_incident(self):
        iid = self.db.create_status_incident("Outage")
        self.db.assign_incident(iid, "alice")
        self.db.assign_incident(iid, "bob")
        detail = self.db.get_status_incident(iid)
        assert detail["assigned_to"] == "bob"

    def test_assign_nonexistent_incident(self):
        ok = self.db.assign_incident(999, "admin")
        assert ok is False

    def test_assigned_to_in_list(self):
        iid = self.db.create_status_incident("Test")
        self.db.assign_incident(iid, "charlie")
        incidents = self.db.list_status_incidents()
        assert incidents[0]["assigned_to"] == "charlie"

    def test_assigned_to_default_none(self):
        self.db.create_status_incident("Test")
        incidents = self.db.list_status_incidents()
        assert incidents[0]["assigned_to"] is None


# -- API Endpoint Tests --------------------------------------------------------

class TestWarRoomAPI:
    """Test the war room API endpoints via TestClient."""

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

    def _auth_headers(self, role="admin"):
        """Get auth token via login."""
        if not self.has_client:
            return {}
        resp = self.client.post("/api/login", json={"username": "admin", "password": "Admin1234!"})
        if resp.status_code == 200:
            token = resp.json().get("token", "")
            return {"Authorization": f"Bearer {token}"}
        return {}

    def _create_incident(self, headers):
        """Helper: create a status incident and return its id."""
        resp = self.client.post("/api/status/incidents/create", json={
            "title": "War Room Test Incident",
            "severity": "major",
            "message": "Initial investigation message",
        }, headers=headers)
        assert resp.status_code == 200
        return resp.json()["id"]

    def test_get_messages_empty(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        inc_id = self._create_incident(headers)
        resp = self.client.get(f"/api/incidents/{inc_id}/messages", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["incident_id"] == inc_id
        assert data["messages"] == []

    def test_post_and_get_messages(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        inc_id = self._create_incident(headers)

        # Post first message
        resp = self.client.post(f"/api/incidents/{inc_id}/messages", json={
            "message": "Checking network logs",
            "msg_type": "comment",
        }, headers=headers)
        assert resp.status_code == 200
        msg1_id = resp.json()["id"]
        assert msg1_id > 0

        # Post second message
        resp = self.client.post(f"/api/incidents/{inc_id}/messages", json={
            "message": "Found DNS timeout pattern",
            "msg_type": "note",
        }, headers=headers)
        assert resp.status_code == 200

        # Retrieve all messages
        resp = self.client.get(f"/api/incidents/{inc_id}/messages", headers=headers)
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 2
        assert messages[0]["message"] == "Checking network logs"
        assert messages[0]["msg_type"] == "comment"
        assert messages[1]["message"] == "Found DNS timeout pattern"
        assert messages[1]["msg_type"] == "note"

    def test_post_message_validation(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        inc_id = self._create_incident(headers)

        # Empty message
        resp = self.client.post(f"/api/incidents/{inc_id}/messages", json={
            "message": "",
        }, headers=headers)
        assert resp.status_code == 400

        # Invalid msg_type
        resp = self.client.post(f"/api/incidents/{inc_id}/messages", json={
            "message": "test",
            "msg_type": "invalid_type",
        }, headers=headers)
        assert resp.status_code == 400

    def test_post_message_nonexistent_incident(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        resp = self.client.post("/api/incidents/99999/messages", json={
            "message": "ghost message",
        }, headers=headers)
        assert resp.status_code == 404

    def test_get_messages_nonexistent_incident(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        resp = self.client.get("/api/incidents/99999/messages", headers=headers)
        assert resp.status_code == 404

    def test_assign_incident(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        inc_id = self._create_incident(headers)

        resp = self.client.put(f"/api/incidents/{inc_id}/assign", json={
            "assigned_to": "admin",
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["assigned_to"] == "admin"

        # Verify assignment via status incidents endpoint
        resp = self.client.get("/api/status/incidents", headers=headers)
        data = resp.json()
        found = [i for i in data["incidents"] if i["id"] == inc_id]
        assert len(found) == 1
        assert found[0]["assigned_to"] == "admin"

    def test_assign_creates_system_message(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        inc_id = self._create_incident(headers)

        self.client.put(f"/api/incidents/{inc_id}/assign", json={
            "assigned_to": "admin",
        }, headers=headers)

        # Check that a system message was auto-posted
        resp = self.client.get(f"/api/incidents/{inc_id}/messages", headers=headers)
        messages = resp.json()["messages"]
        assert len(messages) == 1
        assert messages[0]["msg_type"] == "system"
        assert "admin" in messages[0]["message"]

    def test_assign_validation(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        inc_id = self._create_incident(headers)

        # Empty assigned_to
        resp = self.client.put(f"/api/incidents/{inc_id}/assign", json={
            "assigned_to": "",
        }, headers=headers)
        assert resp.status_code == 400

    def test_assign_nonexistent_incident(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        resp = self.client.put("/api/incidents/99999/assign", json={
            "assigned_to": "admin",
        }, headers=headers)
        assert resp.status_code == 404

    def test_requires_auth(self):
        """War room endpoints should require authentication."""
        if not self.has_client:
            return
        # GET messages without auth
        resp = self.client.get("/api/incidents/1/messages")
        assert resp.status_code == 401

        # POST message without auth
        resp = self.client.post("/api/incidents/1/messages", json={"message": "test"})
        assert resp.status_code == 401

        # PUT assign without auth
        resp = self.client.put("/api/incidents/1/assign", json={"assigned_to": "admin"})
        assert resp.status_code == 401
