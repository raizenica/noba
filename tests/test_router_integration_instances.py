# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for the integration_instances router."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


_VALID_INSTANCE = {
    "id": "test-inst-1",
    "category": "monitoring",
    "platform": "prometheus",
    "url": "https://prometheus.example.com",
    "auth_config": {"token": "secret"},
    "tags": ["prod"],
}


def _create_instance(client, admin_headers, **overrides):
    """Helper to create an instance for test setup."""
    body = {**_VALID_INSTANCE, **overrides}
    return client.post("/api/integrations/instances", json=body, headers=admin_headers)


# ===========================================================================
# GET /api/integrations/instances
# ===========================================================================

class TestListInstances:
    """List integration instances — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/integrations/instances")
        assert resp.status_code == 401

    def test_viewer_can_list(self, client, viewer_headers):
        resp = client.get("/api/integrations/instances", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_operator_can_list(self, client, operator_headers):
        resp = client.get("/api/integrations/instances", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_list(self, client, admin_headers):
        resp = client.get("/api/integrations/instances", headers=admin_headers)
        assert resp.status_code == 200

    def test_non_admin_gets_redacted_auth(self, client, admin_headers, viewer_headers):
        _create_instance(client, admin_headers, id="redact-test")
        resp = client.get("/api/integrations/instances", headers=viewer_headers)
        assert resp.status_code == 200
        for item in resp.json():
            if isinstance(item, dict) and item.get("id") == "redact-test":
                assert item["auth_config"] == {"redacted": True}

    def test_filter_by_category(self, client, admin_headers):
        resp = client.get(
            "/api/integrations/instances?category=monitoring",
            headers=admin_headers,
        )
        assert resp.status_code == 200

    def test_filter_by_site(self, client, admin_headers):
        resp = client.get(
            "/api/integrations/instances?site=site-a",
            headers=admin_headers,
        )
        assert resp.status_code == 200


# ===========================================================================
# GET /api/integrations/instances/{instance_id}
# ===========================================================================

class TestGetInstance:
    """Get single instance — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/integrations/instances/some-id")
        assert resp.status_code == 401

    def test_not_found_returns_404(self, client, admin_headers):
        resp = client.get(
            "/api/integrations/instances/nonexistent-xyz",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_admin_sees_full_auth_config(self, client, admin_headers):
        _create_instance(client, admin_headers, id="full-auth-test")
        resp = client.get(
            "/api/integrations/instances/full-auth-test",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_config"] != {"redacted": True}

    def test_viewer_sees_redacted_auth_config(self, client, admin_headers, viewer_headers):
        _create_instance(client, admin_headers, id="redact-single")
        resp = client.get(
            "/api/integrations/instances/redact-single",
            headers=viewer_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["auth_config"] == {"redacted": True}


# ===========================================================================
# POST /api/integrations/instances
# ===========================================================================

class TestCreateInstance:
    """Create integration instance — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/integrations/instances", json=_VALID_INSTANCE)
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/integrations/instances",
            json=_VALID_INSTANCE,
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post(
            "/api/integrations/instances",
            json=_VALID_INSTANCE,
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_admin_can_create(self, client, admin_headers):
        resp = _create_instance(client, admin_headers, id="create-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "create-test"
        assert data["status"] == "created"

    def test_missing_id_returns_400(self, client, admin_headers):
        body = {"category": "monitoring", "platform": "prometheus"}
        resp = client.post("/api/integrations/instances", json=body, headers=admin_headers)
        assert resp.status_code == 400

    def test_missing_category_returns_400(self, client, admin_headers):
        body = {"id": "no-cat", "platform": "prometheus"}
        resp = client.post("/api/integrations/instances", json=body, headers=admin_headers)
        assert resp.status_code == 400

    def test_missing_platform_returns_400(self, client, admin_headers):
        body = {"id": "no-plat", "category": "monitoring"}
        resp = client.post("/api/integrations/instances", json=body, headers=admin_headers)
        assert resp.status_code == 400

    def test_duplicate_id_returns_400(self, client, admin_headers):
        _create_instance(client, admin_headers, id="dup-id")
        resp = _create_instance(client, admin_headers, id="dup-id")
        assert resp.status_code == 400


# ===========================================================================
# PATCH /api/integrations/instances/{instance_id}
# ===========================================================================

class TestUpdateInstance:
    """Update integration instance — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.patch("/api/integrations/instances/some-id", json={"url": "http://x"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.patch(
            "/api/integrations/instances/some-id",
            json={"url": "http://x"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.patch(
            "/api/integrations/instances/some-id",
            json={"url": "http://x"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_not_found_returns_404(self, client, admin_headers):
        resp = client.patch(
            "/api/integrations/instances/nonexistent-xyz",
            json={"url": "http://new-url.example.com"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_admin_can_update(self, client, admin_headers):
        _create_instance(client, admin_headers, id="patch-test")
        resp = client.patch(
            "/api/integrations/instances/patch-test",
            json={"url": "https://updated.example.com"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

    def test_unknown_fields_silently_ignored(self, client, admin_headers):
        """Fields not in the extract list are silently ignored (no-op update)."""
        _create_instance(client, admin_headers, id="bad-field")
        resp = client.patch(
            "/api/integrations/instances/bad-field",
            json={"totally_invalid_field": "value"},
            headers=admin_headers,
        )
        # Unknown fields are simply not extracted, resulting in empty update_fields
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"


# ===========================================================================
# DELETE /api/integrations/instances/{instance_id}
# ===========================================================================

class TestDeleteInstance:
    """Delete integration instance — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.delete("/api/integrations/instances/some-id")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.delete(
            "/api/integrations/instances/some-id",
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.delete(
            "/api/integrations/instances/some-id",
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_admin_can_delete(self, client, admin_headers):
        _create_instance(client, admin_headers, id="del-test")
        resp = client.delete(
            "/api/integrations/instances/del-test",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_not_found_returns_404(self, client, admin_headers):
        resp = client.delete(
            "/api/integrations/instances/nonexistent-xyz",
            headers=admin_headers,
        )
        assert resp.status_code == 404


# ===========================================================================
# POST /api/integrations/instances/test-connection
# ===========================================================================

class TestConnectionTest:
    """Test connectivity — operator+."""

    def test_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/integrations/instances/test-connection",
            json={"url": "https://example.com", "platform": "generic"},
        )
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/integrations/instances/test-connection",
            json={"url": "https://example.com", "platform": "generic"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post(
            "/api/integrations/instances/test-connection",
            json={"url": "https://external.example.com", "platform": "prometheus"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_admin_can_test(self, client, admin_headers):
        with patch("server.routers.integration_instances._is_safe_url", return_value=True), \
             patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value = type("R", (), {"status_code": 200})()
            resp = client.post(
                "/api/integrations/instances/test-connection",
                json={"url": "https://external.example.com", "platform": "grafana"},
                headers=admin_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["success"] is True

    def test_no_url_returns_error(self, client, admin_headers):
        resp = client.post(
            "/api/integrations/instances/test-connection",
            json={"platform": "generic"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "No URL" in resp.json()["error"]


# ===========================================================================
# SSRF Protection
# ===========================================================================

class TestSSRFProtection:
    """_is_safe_url unit tests — the function guards automation webhooks (remediation.py).
    Integration test-connection is operator-gated and intentionally allows private IPs
    so users can reach their own NAS/Proxmox/UniFi on local networks."""

    def test_localhost_blocked(self):
        from server.routers.integration_instances import _is_safe_url
        assert _is_safe_url("http://localhost:8080/api") is False

    def test_127_0_0_1_blocked(self):
        from server.routers.integration_instances import _is_safe_url
        assert _is_safe_url("http://127.0.0.1:9090") is False

    def test_private_ip_10_x_blocked(self):
        from server.routers.integration_instances import _is_safe_url
        assert _is_safe_url("http://10.0.0.1:3000") is False

    def test_private_ip_192_168_blocked(self):
        from server.routers.integration_instances import _is_safe_url
        assert _is_safe_url("http://192.168.1.1") is False

    def test_metadata_169_254_blocked(self):
        from server.routers.integration_instances import _is_safe_url
        assert _is_safe_url("http://169.254.169.254/latest/meta-data/") is False

    def test_ipv6_loopback_blocked(self):
        from server.routers.integration_instances import _is_safe_url
        assert _is_safe_url("http://[::1]:8080") is False

    def test_dns_rebind_private_blocked(self):
        """Hostname resolving to private IP should be blocked."""
        from server.routers.integration_instances import _is_safe_url
        with patch("server.routers.integration_instances.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 6, "", ("10.0.0.5", 80))]
            assert _is_safe_url("http://evil.example.com/api") is False

    def test_integration_endpoint_allows_private_ip(self, client, admin_headers):
        """test-connection must NOT block private IPs — admins configure local devices."""
        with patch("server.routers.integration_instances.httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_resp)
            resp = client.post(
                "/api/integrations/instances/test-connection",
                json={"url": "http://192.168.1.100/api", "platform": "truenas"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        assert resp.json().get("success") is True


# ===========================================================================
# SQL field allowlist
# ===========================================================================

class TestFieldAllowlist:
    """PATCH with invalid fields should be rejected."""

    def test_allowed_field_url_accepted(self, client, admin_headers):
        _create_instance(client, admin_headers, id="field-ok")
        resp = client.patch(
            "/api/integrations/instances/field-ok",
            json={"url": "https://new.example.com"},
            headers=admin_headers,
        )
        assert resp.status_code == 200

    def test_unknown_field_ignored_not_written(self, client, admin_headers):
        """Fields like 'id' are not in the extract list so they're silently dropped."""
        _create_instance(client, admin_headers, id="field-bad")
        resp = client.patch(
            "/api/integrations/instances/field-bad",
            json={"id": "injected-id"},
            headers=admin_headers,
        )
        # 'id' is not extracted by the handler, so update_fields is empty → 200 no-op
        assert resp.status_code == 200
        # Verify the id was NOT changed
        get_resp = client.get(
            "/api/integrations/instances/field-bad", headers=admin_headers,
        )
        assert get_resp.status_code == 200

    def test_sql_injection_field_ignored(self, client, admin_headers):
        """Arbitrary key names are not extracted — no SQL injection possible."""
        _create_instance(client, admin_headers, id="field-sqli")
        resp = client.patch(
            "/api/integrations/instances/field-sqli",
            json={"'; DROP TABLE integration_instances; --": "pwned"},
            headers=admin_headers,
        )
        # Unknown key is silently ignored
        assert resp.status_code == 200
        # Table still works — instance still retrievable
        get_resp = client.get(
            "/api/integrations/instances/field-sqli", headers=admin_headers,
        )
        assert get_resp.status_code == 200
