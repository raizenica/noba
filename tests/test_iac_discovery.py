# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for IaC export auto-discovery and Graylog auth fallback."""
from __future__ import annotations


class TestIaCExportEndpoints:
    """Verify IaC export endpoints accept discover parameter."""

    def test_ansible_no_auth_401(self, client):
        resp = client.get("/api/export/ansible")
        assert resp.status_code == 401

    def test_ansible_viewer_can_read(self, client, viewer_headers):
        resp = client.get("/api/export/ansible", headers=viewer_headers)
        assert resp.status_code == 200

    def test_ansible_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/export/ansible", headers=operator_headers)
        assert resp.status_code == 200

    def test_ansible_post_discover(self, client, operator_headers):
        resp = client.post("/api/export/ansible",
                           json={"discover": True}, headers=operator_headers)
        assert resp.status_code == 200

    def test_docker_compose_requires_hostname(self, client, operator_headers):
        resp = client.get("/api/export/docker-compose", headers=operator_headers)
        assert resp.status_code == 400

    def test_docker_compose_with_hostname(self, client, operator_headers):
        resp = client.get("/api/export/docker-compose?hostname=test", headers=operator_headers)
        assert resp.status_code == 200

    def test_docker_compose_post_discover(self, client, operator_headers):
        resp = client.post(
            "/api/export/docker-compose",
            json={"hostname": "test", "discover": True},
            headers=operator_headers,
        )
        assert resp.status_code == 200

    def test_shell_requires_hostname(self, client, operator_headers):
        resp = client.get("/api/export/shell", headers=operator_headers)
        assert resp.status_code == 400

    def test_shell_post_discover(self, client, operator_headers):
        resp = client.post(
            "/api/export/shell",
            json={"hostname": "test", "discover": True},
            headers=operator_headers,
        )
        assert resp.status_code == 200


class TestGraylogSearchAuth:
    """Verify Graylog search endpoint handles auth fallback."""

    def test_graylog_search_no_auth_401(self, client):
        resp = client.get("/api/graylog/search?q=test&hours=1")
        assert resp.status_code == 401

    def test_graylog_search_viewer_403(self, client, viewer_headers):
        resp = client.get("/api/graylog/search?q=test&hours=1", headers=viewer_headers)
        assert resp.status_code == 403

    def test_graylog_search_not_configured(self, client, operator_headers):
        resp = client.get("/api/graylog/search?q=test&hours=1", headers=operator_headers)
        assert resp.status_code == 404


class TestHealingTrustPut:
    """Verify PUT /api/healing/trust/{rule_id} endpoint."""

    def test_no_auth_401(self, client):
        resp = client.put("/api/healing/trust/test-rule", json={"level": "notify"})
        assert resp.status_code == 401

    def test_viewer_403(self, client, viewer_headers):
        resp = client.put(
            "/api/healing/trust/test-rule",
            json={"level": "notify"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_403(self, client, operator_headers):
        resp = client.put(
            "/api/healing/trust/test-rule",
            json={"level": "notify"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_admin_can_set_trust(self, client, admin_headers):
        resp = client.put(
            "/api/healing/trust/test-put-rule",
            json={"level": "approve", "ceiling": "execute"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["level"] == "approve"
        assert data["ceiling"] == "execute"

    def test_invalid_level_rejected(self, client, admin_headers):
        resp = client.put(
            "/api/healing/trust/test-rule",
            json={"level": "invalid_level", "ceiling": "execute"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_invalid_ceiling_rejected(self, client, admin_headers):
        resp = client.put(
            "/api/healing/trust/test-rule",
            json={"level": "notify", "ceiling": "banana"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_all_valid_levels(self, client, admin_headers):
        for level in ("observation", "dry_run", "notify", "approve", "execute"):
            resp = client.put(
                f"/api/healing/trust/test-level-{level}",
                json={"level": level, "ceiling": "execute"},
                headers=admin_headers,
            )
            assert resp.status_code == 200, f"Failed for level={level}"
