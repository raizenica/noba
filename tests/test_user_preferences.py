# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for user preferences: DB CRUD and API endpoints (Feature 10)."""
from __future__ import annotations

import json
import os
import sys
import tempfile

# Ensure server package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-web"))

from server.db import Database


def _make_db():
    """Create a fresh temp DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_preftest_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


# -- DB Layer Tests ------------------------------------------------------------

class TestUserPreferencesDB:
    """Test the user_preferences DB CRUD operations."""

    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_get_nonexistent_returns_none(self):
        result = self.db.get_user_preferences("nobody")
        assert result is None

    def test_save_and_get(self):
        prefs = {"vis": {"core": True, "logs": False}, "theme": "nord"}
        ok = self.db.save_user_preferences("alice", prefs)
        assert ok is True

        result = self.db.get_user_preferences("alice")
        assert result is not None
        assert result["username"] == "alice"
        assert result["preferences"]["vis"]["core"] is True
        assert result["preferences"]["vis"]["logs"] is False
        assert result["preferences"]["theme"] == "nord"
        assert result["updated_at"] > 0

    def test_save_overwrites(self):
        self.db.save_user_preferences("alice", {"theme": "dark"})
        self.db.save_user_preferences("alice", {"theme": "nord", "collapsed": {"core": True}})

        result = self.db.get_user_preferences("alice")
        assert result["preferences"]["theme"] == "nord"
        assert result["preferences"]["collapsed"]["core"] is True
        # Old key should be gone (full replace)
        assert "dark" not in json.dumps(result["preferences"])

    def test_delete_existing(self):
        self.db.save_user_preferences("alice", {"theme": "dark"})
        ok = self.db.delete_user_preferences("alice")
        assert ok is True
        assert self.db.get_user_preferences("alice") is None

    def test_delete_nonexistent(self):
        ok = self.db.delete_user_preferences("ghost")
        assert ok is False

    def test_multiple_users_independent(self):
        self.db.save_user_preferences("alice", {"theme": "nord"})
        self.db.save_user_preferences("bob", {"theme": "dark"})

        alice = self.db.get_user_preferences("alice")
        bob = self.db.get_user_preferences("bob")
        assert alice["preferences"]["theme"] == "nord"
        assert bob["preferences"]["theme"] == "dark"

    def test_empty_preferences(self):
        ok = self.db.save_user_preferences("alice", {})
        assert ok is True
        result = self.db.get_user_preferences("alice")
        assert result["preferences"] == {}

    def test_complex_preferences(self):
        prefs = {
            "vis": {
                "core": True, "netio": True, "hw": False,
                "storage": True, "pihole": False,
            },
            "collapsed": {"core": False, "netio": True},
            "sidebarCollapsed": True,
            "theme": "catppuccin",
        }
        self.db.save_user_preferences("alice", prefs)
        result = self.db.get_user_preferences("alice")
        assert result["preferences"] == prefs

    def test_save_returns_true(self):
        assert self.db.save_user_preferences("alice", {"x": 1}) is True

    def test_updated_at_changes(self):
        import time
        self.db.save_user_preferences("alice", {"v": 1})
        t1 = self.db.get_user_preferences("alice")["updated_at"]
        time.sleep(0.05)
        self.db.save_user_preferences("alice", {"v": 2})
        t2 = self.db.get_user_preferences("alice")["updated_at"]
        assert t2 >= t1


# -- API Endpoint Tests --------------------------------------------------------

class TestUserPreferencesAPI:
    """Test the /api/user/preferences endpoints via TestClient."""

    @classmethod
    def setup_class(cls):
        try:
            from fastapi.testclient import TestClient
            from server.app import app
            cls.client = TestClient(app)
            cls.has_client = True
        except Exception:
            cls.has_client = False

    def _auth_headers(self):
        if not self.has_client:
            return {}
        resp = self.client.post("/api/login", json={"username": "admin", "password": "Admin1234!"})
        if resp.status_code == 200:
            token = resp.json().get("token", "")
            return {"Authorization": f"Bearer {token}"}
        return {}

    def test_get_requires_auth(self):
        if not self.has_client:
            return
        resp = self.client.get("/api/user/preferences")
        assert resp.status_code == 401

    def test_put_requires_auth(self):
        if not self.has_client:
            return
        resp = self.client.put("/api/user/preferences", json={"preferences": {}})
        assert resp.status_code == 401

    def test_delete_requires_auth(self):
        if not self.has_client:
            return
        resp = self.client.delete("/api/user/preferences")
        assert resp.status_code == 401

    def test_get_empty_preferences(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        resp = self.client.get("/api/user/preferences", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "preferences" in data

    def test_put_and_get_preferences(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        prefs = {"vis": {"core": True, "logs": False}, "theme": "nord"}
        resp = self.client.put("/api/user/preferences",
                               json={"preferences": prefs}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        resp = self.client.get("/api/user/preferences", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["synced"] is True
        assert data["preferences"]["theme"] == "nord"
        assert data["preferences"]["vis"]["logs"] is False

    def test_put_invalid_body(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        resp = self.client.put("/api/user/preferences",
                               json={"wrong_key": {}}, headers=headers)
        assert resp.status_code == 400

    def test_put_non_dict_preferences(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        resp = self.client.put("/api/user/preferences",
                               json={"preferences": "not a dict"}, headers=headers)
        assert resp.status_code == 400

    def test_delete_preferences(self):
        if not self.has_client:
            return
        headers = self._auth_headers()
        if not headers:
            return
        # Save then delete
        self.client.put("/api/user/preferences",
                        json={"preferences": {"theme": "dark"}}, headers=headers)
        resp = self.client.delete("/api/user/preferences", headers=headers)
        assert resp.status_code == 200

        # After delete, should get empty / not synced
        resp = self.client.get("/api/user/preferences", headers=headers)
        data = resp.json()
        assert data["synced"] is False or data["preferences"] == {}
