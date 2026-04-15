# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for playbook template DB functions and API endpoints."""
from __future__ import annotations

import os
import tempfile

from server.db import Database


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_test_pb_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


# ── DB-level tests ────────────────────────────────────────────────────────────

class TestPlaybookTemplatesDB:
    def setup_method(self):
        self.db, self.path = _make_db()

    def teardown_method(self):
        _cleanup(self.path)

    def test_list_returns_seeded_data(self):
        """list_playbook_templates returns the 4 seeded templates."""
        templates = self.db.list_playbook_templates()
        assert len(templates) == 4

    def test_list_returns_expected_ids(self):
        """All 4 seeded template ids are present."""
        ids = {t["id"] for t in self.db.list_playbook_templates()}
        assert "update-all-agents" in ids
        assert "rolling-dns-restart" in ids
        assert "backup-verification" in ids
        assert "disk-cleanup" in ids

    def test_list_templates_have_required_fields(self):
        """Each template has id, name, description, category, config, version."""
        for t in self.db.list_playbook_templates():
            assert "id" in t
            assert "name" in t
            assert "description" in t
            assert "category" in t
            assert "config" in t
            assert "version" in t

    def test_list_templates_config_is_dict(self):
        """config field is deserialized as a dict with nodes and edges."""
        for t in self.db.list_playbook_templates():
            assert isinstance(t["config"], dict)
            assert "nodes" in t["config"]
            assert "edges" in t["config"]
            assert "entry" in t["config"]

    def test_get_template_by_id(self):
        """get_playbook_template returns the correct template."""
        t = self.db.get_playbook_template("update-all-agents")
        assert t is not None
        assert t["id"] == "update-all-agents"
        assert t["name"] == "Update All Agents"
        assert t["category"] == "maintenance"

    def test_get_template_disk_cleanup(self):
        """get_playbook_template returns disk-cleanup with correct category."""
        t = self.db.get_playbook_template("disk-cleanup")
        assert t is not None
        assert t["category"] == "maintenance"

    def test_get_template_backup_verification(self):
        """backup-verification has category backup."""
        t = self.db.get_playbook_template("backup-verification")
        assert t is not None
        assert t["category"] == "backup"

    def test_get_nonexistent_returns_none(self):
        """get_playbook_template returns None for unknown id."""
        result = self.db.get_playbook_template("does-not-exist")
        assert result is None

    def test_upsert_creates_new_template(self):
        """upsert_playbook_template creates a new template."""
        config = {
            "nodes": [{"id": "n1", "type": "notify", "params": {}}],
            "edges": [],
            "entry": "n1",
        }
        ok = self.db.upsert_playbook_template(
            "my-custom",
            "My Custom",
            "A custom playbook",
            "custom",
            config,
        )
        assert ok is True
        t = self.db.get_playbook_template("my-custom")
        assert t is not None
        assert t["name"] == "My Custom"
        assert t["category"] == "custom"

    def test_upsert_updates_existing_template(self):
        """upsert_playbook_template overwrites an existing template."""
        config = {"nodes": [], "edges": [], "entry": "n1"}
        self.db.upsert_playbook_template("update-all-agents", "Updated Name",
                                         "desc", "maintenance", config, version=2)
        t = self.db.get_playbook_template("update-all-agents")
        assert t["name"] == "Updated Name"
        assert t["version"] == 2

    def test_seed_is_idempotent(self):
        """Re-creating DB with same path returns exactly 4 templates (no duplicates)."""
        # Create a second Database instance on the same file — seeds again
        db2 = Database(path=self.path)
        templates = db2.list_playbook_templates()
        assert len(templates) == 4


# ── API-level tests ───────────────────────────────────────────────────────────

class TestPlaybookAPI:
    """Tests for /api/playbooks endpoints."""

    # ── GET /api/playbooks ────────────────────────────────────────────────────

    def test_list_no_auth_returns_401(self, client):
        resp = client.get("/api/playbooks")
        assert resp.status_code == 401

    def test_list_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/playbooks", headers=viewer_headers)
        assert resp.status_code == 200

    def test_list_returns_list_with_4_items(self, client, admin_headers):
        resp = client.get("/api/playbooks", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 4

    def test_list_items_have_required_fields(self, client, viewer_headers):
        resp = client.get("/api/playbooks", headers=viewer_headers)
        assert resp.status_code == 200
        for item in resp.json():
            assert "id" in item
            assert "name" in item
            assert "category" in item
            assert "config" in item

    def test_list_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/playbooks", headers=operator_headers)
        assert resp.status_code == 200

    # ── GET /api/playbooks/{id} ───────────────────────────────────────────────

    def test_get_single_no_auth_returns_401(self, client):
        resp = client.get("/api/playbooks/update-all-agents")
        assert resp.status_code == 401

    def test_get_single_returns_template_details(self, client, viewer_headers):
        resp = client.get("/api/playbooks/update-all-agents", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "update-all-agents"
        assert data["name"] == "Update All Agents"
        assert data["category"] == "maintenance"
        assert "nodes" in data["config"]
        assert "edges" in data["config"]
        assert "entry" in data["config"]

    def test_get_disk_cleanup_template(self, client, admin_headers):
        resp = client.get("/api/playbooks/disk-cleanup", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "disk-cleanup"
        assert data["category"] == "maintenance"

    def test_get_backup_verification_template(self, client, viewer_headers):
        resp = client.get("/api/playbooks/backup-verification", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "backup"

    def test_get_nonexistent_returns_404(self, client, viewer_headers):
        resp = client.get("/api/playbooks/nonexistent-playbook", headers=viewer_headers)
        assert resp.status_code == 404

    def test_get_nonexistent_no_auth_returns_401(self, client):
        resp = client.get("/api/playbooks/nonexistent-playbook")
        assert resp.status_code == 401

    # ── POST /api/playbooks/{id}/install ─────────────────────────────────────

    def test_install_no_auth_returns_401(self, client):
        resp = client.post("/api/playbooks/update-all-agents/install", json={})
        assert resp.status_code == 401

    def test_viewer_cannot_install(self, client, viewer_headers):
        resp = client.post(
            "/api/playbooks/update-all-agents/install",
            json={},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_install_nonexistent_returns_404(self, client, operator_headers):
        resp = client.post(
            "/api/playbooks/no-such-playbook/install",
            json={},
            headers=operator_headers,
        )
        assert resp.status_code == 404

    def test_install_creates_automation_returns_id(self, client, operator_headers):
        resp = client.post(
            "/api/playbooks/update-all-agents/install",
            json={},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["status"] == "ok"
        assert len(data["id"]) == 12  # secrets.token_hex(6)

    def test_install_with_custom_name(self, client, operator_headers, admin_headers):
        resp = client.post(
            "/api/playbooks/disk-cleanup/install",
            json={"name": "My Custom Cleanup"},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        auto_id = resp.json()["id"]

        # Verify the automation was created with the custom name
        from server.deps import db
        auto = db.get_automation(auto_id)
        assert auto is not None
        assert auto["name"] == "My Custom Cleanup"

    def test_install_uses_template_name_when_no_name_given(self, client, operator_headers):
        resp = client.post(
            "/api/playbooks/backup-verification/install",
            json={},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        auto_id = resp.json()["id"]

        from server.deps import db
        auto = db.get_automation(auto_id)
        assert auto is not None
        assert auto["name"] == "Backup Verification"

    def test_install_creates_workflow_type_automation(self, client, operator_headers):
        resp = client.post(
            "/api/playbooks/rolling-dns-restart/install",
            json={},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        auto_id = resp.json()["id"]

        from server.deps import db
        auto = db.get_automation(auto_id)
        assert auto is not None
        assert auto["type"] == "workflow"

    def test_install_automation_config_matches_template(self, client, operator_headers):
        resp = client.post(
            "/api/playbooks/rolling-dns-restart/install",
            json={},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        auto_id = resp.json()["id"]

        from server.deps import db
        auto = db.get_automation(auto_id)
        assert auto is not None
        config = auto["config"]
        assert "nodes" in config
        assert "edges" in config
        assert "entry" in config
        # Verify content matches the template
        template = db.get_playbook_template("rolling-dns-restart")
        assert config == template["config"]

    def test_install_automation_is_disabled_by_default(self, client, operator_headers):
        resp = client.post(
            "/api/playbooks/disk-cleanup/install",
            json={},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        auto_id = resp.json()["id"]

        from server.deps import db
        auto = db.get_automation(auto_id)
        assert auto is not None
        assert auto["enabled"] is False

    def test_admin_can_also_install(self, client, admin_headers):
        resp = client.post(
            "/api/playbooks/update-all-agents/install",
            json={"name": "Admin Install"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
