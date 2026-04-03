# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for the security router (share/noba-web/server/routers/security.py)."""
from __future__ import annotations

import time


def _seed_agent(hostname: str = "test-host") -> None:
    """Seed an agent directly into the in-memory store."""
    from server.agent_store import _agent_data, _agent_data_lock

    with _agent_data_lock:
        _agent_data[hostname] = {"hostname": hostname, "_received": time.time()}


# ===========================================================================
# GET /api/security/score
# ===========================================================================

class TestSecurityScore:
    """Aggregate security score — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/security/score")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/security/score", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/security/score", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/security/score", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_score_data(self, client, admin_headers):
        resp = client.get("/api/security/score", headers=admin_headers)
        assert resp.status_code == 200
        # Result should be a dict or list (DB aggregate result)
        data = resp.json()
        assert data is not None


# ===========================================================================
# GET /api/security/findings
# ===========================================================================

class TestSecurityFindings:
    """Security findings list — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/security/findings")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/security/findings", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/security/findings", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/security/findings", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_list(self, client, admin_headers):
        resp = client.get("/api/security/findings", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_hostname_filter_accepted(self, client, admin_headers):
        resp = client.get(
            "/api/security/findings?hostname=myhost&severity=high&limit=10",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_limit_param_accepted(self, client, admin_headers):
        resp = client.get("/api/security/findings?limit=5", headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/security/history
# ===========================================================================

class TestSecurityHistory:
    """Historical security scores — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/security/history")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/security/history", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/security/history", headers=operator_headers)
        assert resp.status_code == 200

    def test_returns_list(self, client, admin_headers):
        resp = client.get("/api/security/history", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_hostname_filter_accepted(self, client, admin_headers):
        resp = client.get(
            "/api/security/history?hostname=myhost&limit=10",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_limit_param_accepted(self, client, admin_headers):
        resp = client.get("/api/security/history?limit=20", headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# POST /api/security/scan/{hostname}
# ===========================================================================

class TestSecurityScan:
    """Trigger a security scan on a specific agent.

    security_scan has risk="low"; viewer role has no allowed risks → 403.
    operator has low+medium → 200 when agent exists.
    """

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/security/scan/myhost")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/security/scan/myhost", headers=viewer_headers)
        assert resp.status_code == 403

    def test_unknown_agent_returns_404(self, client, operator_headers):
        resp = client.post(
            "/api/security/scan/nonexistent-host-xyz", headers=operator_headers
        )
        assert resp.status_code == 404

    def test_operator_can_scan_known_agent(self, client, operator_headers):
        _seed_agent("scan-host-op")
        resp = client.post("/api/security/scan/scan-host-op", headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("sent", "queued")
        assert data["hostname"] == "scan-host-op"
        assert "id" in data

    def test_admin_can_scan_known_agent(self, client, admin_headers):
        _seed_agent("scan-host-admin")
        resp = client.post("/api/security/scan/scan-host-admin", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("sent", "queued")

    def test_scan_returns_queued_when_no_websocket(self, client, operator_headers):
        """Without an active WebSocket the command should be queued."""
        _seed_agent("queue-scan-host")
        resp = client.post("/api/security/scan/queue-scan-host", headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_scan_id_is_hex_string(self, client, admin_headers):
        _seed_agent("hex-id-host")
        resp = client.post("/api/security/scan/hex-id-host", headers=admin_headers)
        assert resp.status_code == 200
        cmd_id = resp.json()["id"]
        assert len(cmd_id) == 16
        assert all(c in "0123456789abcdef" for c in cmd_id)


# ===========================================================================
# POST /api/security/scan-all
# ===========================================================================

class TestSecurityScanAll:
    """Trigger security scan on all online agents."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/security/scan-all")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/security/scan-all", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_can_scan_all_with_no_agents(self, client, operator_headers):
        # Ensure the store is empty before this test
        from server.agent_store import _agent_data, _agent_data_lock
        with _agent_data_lock:
            _agent_data.clear()
        resp = client.post("/api/security/scan-all", headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert data["count"] == 0
        assert data["agents"] == {}

    def test_operator_can_scan_all_with_agents(self, client, operator_headers):
        # Start from a clean slate then seed exactly two agents
        from server.agent_store import _agent_data, _agent_data_lock
        with _agent_data_lock:
            _agent_data.clear()
        _seed_agent("all-host-1")
        _seed_agent("all-host-2")
        resp = client.post("/api/security/scan-all", headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert data["count"] == 2
        assert "all-host-1" in data["agents"]
        assert "all-host-2" in data["agents"]

    def test_admin_can_scan_all(self, client, admin_headers):
        _seed_agent("admin-scan-host")
        resp = client.post("/api/security/scan-all", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "admin-scan-host" in data["agents"]

    def test_scan_all_only_targets_online_agents(self, client, operator_headers):
        """Agents with old _received timestamps should not be targeted."""
        from server.agent_store import _agent_data, _agent_data_lock

        with _agent_data_lock:
            _agent_data["stale-host"] = {
                "hostname": "stale-host",
                "_received": time.time() - 99999,  # very old
            }
            _agent_data["online-host"] = {
                "hostname": "online-host",
                "_received": time.time(),
            }

        resp = client.post("/api/security/scan-all", headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "online-host" in data["agents"]
        assert "stale-host" not in data["agents"]

    def test_scan_all_agents_have_id_field(self, client, admin_headers):
        _seed_agent("id-check-host")
        resp = client.post("/api/security/scan-all", headers=admin_headers)
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        for _hostname, info in agents.items():
            assert "id" in info
            assert "websocket" in info


# ===========================================================================
# POST /api/security/record
# ===========================================================================

class TestSecurityRecord:
    """Record security scan results — admin only (security audit Fix 8)."""

    def test_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/security/record",
            json={"hostname": "h", "score": 80, "findings": []},
        )
        assert resp.status_code == 401

    def test_missing_hostname_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/security/record",
            json={"score": 80, "findings": []},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_missing_score_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/security/record",
            json={"hostname": "myhost", "findings": []},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_admin_can_record(self, client, admin_headers):
        resp = client.post(
            "/api/security/record",
            json={"hostname": "myhost", "score": 85, "findings": []},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_operator_cannot_record(self, client, operator_headers):
        """security/record requires admin (security audit Fix 8)."""
        resp = client.post(
            "/api/security/record",
            json={"hostname": "ophost", "score": 70, "findings": []},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_viewer_cannot_record(self, client, viewer_headers):
        """security/record requires admin (security audit Fix 8)."""
        resp = client.post(
            "/api/security/record",
            json={"hostname": "vhost", "score": 60, "findings": []},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_record_with_findings_list(self, client, admin_headers):
        findings = [
            {"check": "ssh_root_login", "severity": "high", "message": "Root login allowed"},
            {"check": "firewall_status", "severity": "medium", "message": "No firewall active"},
        ]
        resp = client.post(
            "/api/security/record",
            json={"hostname": "findings-host", "score": 55, "findings": findings},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_record_score_zero_is_valid(self, client, admin_headers):
        resp = client.post(
            "/api/security/record",
            json={"hostname": "zero-host", "score": 0, "findings": []},
            headers=admin_headers,
        )
        assert resp.status_code == 200
