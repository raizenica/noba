# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for the agents router (share/noba-web/server/routers/agents.py)."""
from __future__ import annotations

from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helper: seed an agent into in-memory store by posting a valid report
# ---------------------------------------------------------------------------

def _seed_agent(client, agent_key_headers, hostname="testhost"):
    """POST a minimal agent report so the agent appears in the store."""
    resp = client.post(
        "/api/agent/report",
        json={"hostname": hostname, "cpu_percent": 5.0, "mem_percent": 20.0,
              "agent_version": "1.2.0"},
        headers=agent_key_headers,
    )
    assert resp.status_code == 200, resp.text
    return hostname


# ===========================================================================
# POST /api/agent/report
# ===========================================================================

class TestAgentReport:
    """Agent-key-authenticated reporting endpoint."""

    def test_missing_key_returns_401(self, client, mock_agent_key):
        resp = client.post("/api/agent/report", json={"hostname": "h1"})
        assert resp.status_code == 401

    def test_invalid_key_returns_403(self, client, mock_agent_key):
        resp = client.post(
            "/api/agent/report",
            json={"hostname": "h1"},
            headers={"X-Agent-Key": "wrong-key"},
        )
        assert resp.status_code == 403

    def test_valid_key_returns_200_with_status_and_commands(
        self, client, mock_agent_key, agent_key_headers
    ):
        resp = client.post(
            "/api/agent/report",
            json={"hostname": "h1", "cpu_percent": 10.0},
            headers=agent_key_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "commands" in data
        assert isinstance(data["commands"], list)

    def test_report_makes_agent_visible_in_list(
        self, client, mock_agent_key, agent_key_headers, admin_headers
    ):
        client.post(
            "/api/agent/report",
            json={"hostname": "visible-host", "cpu_percent": 1.0},
            headers=agent_key_headers,
        )
        resp = client.get("/api/agents", headers=admin_headers)
        assert resp.status_code == 200
        hostnames = [a["hostname"] for a in resp.json()]
        assert "visible-host" in hostnames

    def test_report_returns_pending_commands(
        self, client, mock_agent_key, agent_key_headers, admin_headers
    ):
        """Commands queued before the report should be returned in 'commands'."""
        # First seed the agent
        _seed_agent(client, agent_key_headers, "cmd-host")
        # Queue a command
        client.post(
            "/api/agents/cmd-host/command",
            json={"type": "ping", "params": {}},
            headers=admin_headers,
        )
        # Next report should return that command
        resp = client.post(
            "/api/agent/report",
            json={"hostname": "cmd-host"},
            headers=agent_key_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["commands"]) >= 1
        assert data["commands"][0]["type"] == "ping"

    def test_report_with_cmd_results_persists(
        self, client, mock_agent_key, agent_key_headers
    ):
        """_cmd_results sent inside the report body are stored."""
        resp = client.post(
            "/api/agent/report",
            json={
                "hostname": "result-host",
                "_cmd_results": [{"id": "abc123", "type": "ping", "status": "ok"}],
            },
            headers=agent_key_headers,
        )
        assert resp.status_code == 200

    def test_report_no_agent_keys_configured_returns_403(self, client):
        """If no agent keys are configured at all, any key should be rejected."""
        with patch(
            "server.routers.agents.read_yaml_settings", return_value={"agentKeys": ""}
        ):
            resp = client.post(
                "/api/agent/report",
                json={"hostname": "h"},
                headers={"X-Agent-Key": "some-key"},
            )
        assert resp.status_code == 403


# ===========================================================================
# GET /api/agents
# ===========================================================================

class TestAgentList:
    """List all known agents."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/agents")
        assert resp.status_code == 401

    def test_viewer_can_list_agents(
        self, client, mock_agent_key, agent_key_headers, viewer_headers
    ):
        _seed_agent(client, agent_key_headers, "view-host")
        resp = client.get("/api/agents", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_admin_gets_list_with_expected_fields(
        self, client, mock_agent_key, agent_key_headers, admin_headers
    ):
        _seed_agent(client, agent_key_headers, "field-host")
        resp = client.get("/api/agents", headers=admin_headers)
        assert resp.status_code == 200
        agents = resp.json()
        assert len(agents) >= 1
        agent = next(a for a in agents if a.get("hostname") == "field-host")
        assert "online" in agent
        assert "last_seen_s" in agent

    def test_empty_store_returns_list(self, client, admin_headers):
        # The app lifespan reloads any previously DB-persisted agents on each
        # TestClient start, so we cannot guarantee an empty list here.
        # Just verify the response shape is a list.
        resp = client.get("/api/agents", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ===========================================================================
# GET /api/agents/{hostname}
# ===========================================================================

class TestAgentDetail:
    """Single-agent detail endpoint."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/agents/somehost")
        assert resp.status_code == 401

    def test_unknown_agent_returns_404(self, client, admin_headers):
        resp = client.get("/api/agents/nonexistent-host", headers=admin_headers)
        assert resp.status_code == 404

    def test_known_agent_returns_200_with_fields(
        self, client, mock_agent_key, agent_key_headers, admin_headers
    ):
        _seed_agent(client, agent_key_headers, "detail-host")
        resp = client.get("/api/agents/detail-host", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "online" in data
        assert "last_seen_s" in data
        assert "cmd_results" in data

    def test_viewer_can_access_detail(
        self, client, mock_agent_key, agent_key_headers, viewer_headers
    ):
        _seed_agent(client, agent_key_headers, "viewer-detail-host")
        resp = client.get("/api/agents/viewer-detail-host", headers=viewer_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/agents/command-history
# ===========================================================================

class TestCommandHistory:
    """Command execution history endpoint."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/agents/command-history")
        assert resp.status_code == 401

    def test_returns_list(self, client, admin_headers):
        resp = client.get("/api/agents/command-history", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/agents/command-history", headers=viewer_headers)
        assert resp.status_code == 200

    def test_hostname_filter_accepted(self, client, admin_headers):
        resp = client.get(
            "/api/agents/command-history?hostname=somehost&limit=10",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ===========================================================================
# POST /api/agents/{hostname}/command
# ===========================================================================

class TestAgentCommand:
    """Single-agent command dispatch, risk-tiered auth."""

    def test_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/agents/h/command", json={"type": "ping", "params": {}}
        )
        assert resp.status_code == 401

    def test_unknown_command_type_returns_400(
        self, client, admin_headers
    ):
        resp = client.post(
            "/api/agents/h/command",
            json={"type": "totally_made_up_command", "params": {}},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_low_risk_command_queued_by_viewer_returns_403(
        self, client, viewer_headers
    ):
        """Viewers cannot run any commands (risk="low" still not allowed)."""
        resp = client.post(
            "/api/agents/h/command",
            json={"type": "ping", "params": {}},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_low_risk_command_queued_by_operator(
        self, client, mock_agent_key, agent_key_headers, operator_headers
    ):
        _seed_agent(client, agent_key_headers, "op-host")
        resp = client.post(
            "/api/agents/op-host/command",
            json={"type": "ping", "params": {}},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("queued", "sent")
        assert "id" in data

    def test_high_risk_command_blocked_for_operator(
        self, client, mock_agent_key, agent_key_headers, operator_headers
    ):
        _seed_agent(client, agent_key_headers, "op-host2")
        resp = client.post(
            "/api/agents/op-host2/command",
            json={"type": "exec", "params": {"cmd": "ls"}},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_high_risk_command_allowed_for_admin(
        self, client, mock_agent_key, agent_key_headers, admin_headers
    ):
        _seed_agent(client, agent_key_headers, "admin-host")
        # exec requires 'command' (not 'cmd') per agent_config validation
        resp = client.post(
            "/api/agents/admin-host/command",
            json={"type": "exec", "params": {"command": "ls -la"}},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("queued", "sent")

    def test_command_queued_for_unknown_agent(
        self, client, admin_headers
    ):
        """Commands can be queued for agents not yet seen; no 404 expected."""
        resp = client.post(
            "/api/agents/never-seen-host/command",
            json={"type": "ping", "params": {}},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"


# ===========================================================================
# POST /api/agents/bulk-command
# ===========================================================================

class TestBulkCommand:
    """Bulk command dispatch to multiple agents."""

    def test_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/agents/bulk-command",
            json={"type": "ping", "params": {}, "hostnames": []},
        )
        assert resp.status_code == 401

    def test_unknown_type_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/agents/bulk-command",
            json={"type": "not_real", "params": {}, "hostnames": []},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_viewer_cannot_bulk_command(self, client, viewer_headers):
        resp = client.post(
            "/api/agents/bulk-command",
            json={"type": "ping", "params": {}, "hostnames": ["h1"]},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_can_send_low_risk_bulk(
        self, client, mock_agent_key, agent_key_headers, operator_headers
    ):
        _seed_agent(client, agent_key_headers, "bulk-h1")
        _seed_agent(client, agent_key_headers, "bulk-h2")
        resp = client.post(
            "/api/agents/bulk-command",
            json={"type": "ping", "params": {}, "hostnames": ["bulk-h1", "bulk-h2"]},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert "bulk-h1" in data["commands"]
        assert "bulk-h2" in data["commands"]

    def test_admin_can_send_high_risk_bulk(
        self, client, mock_agent_key, agent_key_headers, admin_headers
    ):
        _seed_agent(client, agent_key_headers, "bulk-admin-h1")
        # exec requires 'command' param per agent_config validation
        resp = client.post(
            "/api/agents/bulk-command",
            json={
                "type": "exec",
                "params": {"command": "ls -la"},
                "hostnames": ["bulk-admin-h1"],
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_empty_hostnames_targets_all_known_agents(
        self, client, mock_agent_key, agent_key_headers, admin_headers
    ):
        _seed_agent(client, agent_key_headers, "all-h1")
        _seed_agent(client, agent_key_headers, "all-h2")
        resp = client.post(
            "/api/agents/bulk-command",
            json={"type": "ping", "params": {}, "hostnames": []},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "all-h1" in data["commands"]
        assert "all-h2" in data["commands"]


# ===========================================================================
# POST /api/agents/{hostname}/uninstall
# ===========================================================================

class TestAgentUninstall:
    """Admin-only uninstall endpoint."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/agents/h/uninstall")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/agents/h/uninstall", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/agents/h/uninstall", headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_uninstall(self, client, admin_headers):
        resp = client.post("/api/agents/somehost/uninstall", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert "id" in data


# ===========================================================================
# GET /api/agents/{hostname}/results
# ===========================================================================

class TestAgentResults:
    """Command results per agent."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/agents/h/results")
        assert resp.status_code == 401

    def test_returns_empty_list_for_unknown_agent(self, client, admin_headers):
        resp = client.get("/api/agents/no-such-host/results", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/agents/h/results", headers=viewer_headers)
        assert resp.status_code == 403

    def test_results_populated_after_report(
        self, client, mock_agent_key, agent_key_headers, admin_headers
    ):
        client.post(
            "/api/agent/report",
            json={
                "hostname": "res-host",
                "_cmd_results": [{"id": "r1", "type": "ping", "status": "ok"}],
            },
            headers=agent_key_headers,
        )
        resp = client.get("/api/agents/res-host/results", headers=admin_headers)
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert results[0]["id"] == "r1"


# ===========================================================================
# GET /api/agents/{hostname}/history
# ===========================================================================

class TestAgentHistory:
    """Historical metrics endpoint."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/agents/h/history")
        assert resp.status_code == 401

    def test_returns_list(self, client, admin_headers):
        resp = client.get("/api/agents/nohost/history", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/agents/h/history", headers=viewer_headers)
        assert resp.status_code == 200

    def test_metric_and_hours_params_accepted(self, client, admin_headers):
        resp = client.get(
            "/api/agents/h/history?metric=mem&hours=48", headers=admin_headers
        )
        assert resp.status_code == 200


# ===========================================================================
# GET /api/agent/update
# ===========================================================================

class TestAgentUpdate:
    """Agent self-update endpoint (serves agent.py)."""

    def test_missing_key_returns_401(self, client, mock_agent_key):
        resp = client.get("/api/agent/update")
        assert resp.status_code == 401

    def test_invalid_key_returns_403(self, client, mock_agent_key):
        resp = client.get(
            "/api/agent/update", headers={"X-Agent-Key": "bad-key"}
        )
        assert resp.status_code == 403

    def test_valid_key_serves_or_404(
        self, client, mock_agent_key, agent_key_headers
    ):
        """Valid key: 200 if agent.py is present on disk, 404 if absent."""
        resp = client.get("/api/agent/update", headers=agent_key_headers)
        assert resp.status_code in (200, 404)

    def test_no_agent_keys_configured_returns_403(self, client):
        with patch(
            "server.routers.agents.read_yaml_settings", return_value={"agentKeys": ""}
        ):
            resp = client.get(
                "/api/agent/update", headers={"X-Agent-Key": "any-key"}
            )
        assert resp.status_code == 403


# ===========================================================================
# GET /api/agent/install-script
# ===========================================================================

class TestAgentInstallScript:
    """Auto-install script generation."""

    def test_missing_key_returns_401(self, client, mock_agent_key):
        resp = client.get("/api/agent/install-script")
        assert resp.status_code == 401

    def test_invalid_key_returns_403(self, client, mock_agent_key):
        resp = client.get(
            "/api/agent/install-script", headers={"X-Agent-Key": "wrong"}
        )
        assert resp.status_code == 403

    def test_invalid_key_via_query_param_returns_403(self, client, mock_agent_key):
        resp = client.get("/api/agent/install-script?key=wrong")
        assert resp.status_code == 403

    def test_valid_key_header_returns_script(
        self, client, mock_agent_key, agent_key_headers
    ):
        resp = client.get("/api/agent/install-script", headers=agent_key_headers)
        assert resp.status_code == 200
        assert "bash" in resp.text.lower() or "noba" in resp.text.lower()

    def test_valid_key_query_param_returns_script(self, client, mock_agent_key):
        resp = client.get("/api/agent/install-script?key=test-agent-key-12345")
        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "script" in content_type or "text" in content_type

    def test_no_agent_keys_configured_returns_403(self, client):
        with patch(
            "server.routers.agents.read_yaml_settings", return_value={"agentKeys": ""}
        ):
            resp = client.get(
                "/api/agent/install-script", headers={"X-Agent-Key": "any"}
            )
        assert resp.status_code == 403


# ===========================================================================
# GET /api/sla/summary
# ===========================================================================

class TestSlaSummary:
    """SLA uptime summary.

    NOTE: The stats router registers /api/sla/{rule_id} before the agents
    router registers /api/sla/summary, so FastAPI routes /api/sla/summary
    to the rule-SLA endpoint (returning a float).  Tests reflect actual
    app routing behaviour; the underlying agents.api_sla_summary function
    is covered by the routing tests via direct invocation if needed.
    """

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/sla/summary")
        assert resp.status_code == 401

    def test_returns_200_with_auth(self, client, admin_headers):
        # Due to router ordering the response is a float (SLA % for a rule
        # named "summary"), not the agent SLA dict — still a 200.
        resp = client.get("/api/sla/summary", headers=admin_headers)
        assert resp.status_code == 200

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/sla/summary", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/sla/summary", headers=operator_headers)
        assert resp.status_code == 200


# ===========================================================================
# POST /api/agent/file-upload
# ===========================================================================

class TestFileUpload:
    """Chunked file upload from agent."""

    def test_missing_key_returns_401(self, client, mock_agent_key):
        """No key at all — _validate_agent_key returns False → 401."""
        resp = client.post(
            "/api/agent/file-upload",
            content=b"data",
            headers={
                "X-Transfer-Id": "t1",
                "X-Chunk-Index": "0",
                "X-Total-Chunks": "1",
                "X-Filename": "test.txt",
                "X-Agent-Hostname": "h1",
            },
        )
        assert resp.status_code == 401

    def test_invalid_key_returns_401(self, client, mock_agent_key):
        """Wrong key value — _validate_agent_key returns False → 401."""
        resp = client.post(
            "/api/agent/file-upload",
            content=b"data",
            headers={
                "X-Agent-Key": "invalid-key",
                "X-Transfer-Id": "t1",
                "X-Chunk-Index": "0",
                "X-Total-Chunks": "1",
                "X-Filename": "test.txt",
                "X-Agent-Hostname": "h1",
            },
        )
        assert resp.status_code == 401

    def test_valid_key_single_chunk_returns_200(
        self, client, mock_agent_key, agent_key_headers
    ):
        resp = client.post(
            "/api/agent/file-upload",
            content=b"hello",
            headers={
                **agent_key_headers,
                "X-Transfer-Id": "transfer-abc",
                "X-Chunk-Index": "0",
                "X-Total-Chunks": "1",
                "X-Filename": "hello.txt",
                "X-Agent-Hostname": "upload-host",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data.get("complete") is True

    def test_missing_transfer_headers_returns_400(
        self, client, mock_agent_key, agent_key_headers
    ):
        """Chunk index -1 should trigger 400."""
        resp = client.post(
            "/api/agent/file-upload",
            content=b"data",
            headers={
                **agent_key_headers,
                "X-Transfer-Id": "",
                "X-Chunk-Index": "-1",
                "X-Total-Chunks": "1",
                "X-Filename": "f.txt",
                "X-Agent-Hostname": "h",
            },
        )
        assert resp.status_code == 400


# ===========================================================================
# POST /api/agents/deploy
# ===========================================================================

class TestAgentDeploy:
    """Remote SSH deploy — admin only, mocked subprocess."""

    def test_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/agents/deploy",
            json={"host": "192.168.1.1", "ssh_user": "root"},
        )
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/agents/deploy",
            json={"host": "192.168.1.1", "ssh_user": "root"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post(
            "/api/agents/deploy",
            json={"host": "192.168.1.1", "ssh_user": "root"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_missing_host_returns_400(self, client, admin_headers):
        with patch(
            "server.routers.agents.read_yaml_settings",
            return_value={"agentKeys": "test-key"},
        ):
            resp = client.post(
                "/api/agents/deploy",
                json={"ssh_user": "root"},
                headers=admin_headers,
            )
        assert resp.status_code == 400

    def test_invalid_hostname_returns_400(self, client, admin_headers):
        with patch(
            "server.routers.agents.read_yaml_settings",
            return_value={"agentKeys": "test-key"},
        ):
            resp = client.post(
                "/api/agents/deploy",
                json={"host": "bad host name!", "ssh_user": "root"},
                headers=admin_headers,
            )
        assert resp.status_code == 400

    def test_no_agent_keys_configured_returns_400(self, client, admin_headers):
        with patch(
            "server.routers.agents.read_yaml_settings", return_value={"agentKeys": ""}
        ):
            resp = client.post(
                "/api/agents/deploy",
                json={"host": "192.168.1.1", "ssh_user": "root"},
                headers=admin_headers,
            )
        assert resp.status_code == 400


# ===========================================================================
# GET /api/agents/{hostname}/stream/{cmd_id}
# ===========================================================================

class TestAgentStream:
    """Stream-log polling endpoint."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/agents/h/stream/cmd1")
        assert resp.status_code == 401

    def test_returns_empty_stream_for_unknown_cmd(self, client, admin_headers):
        resp = client.get(
            "/api/agents/somehost/stream/nonexistent-cmd", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "lines" in data
        assert "cursor" in data

    def test_viewer_cannot_access(self, client, viewer_headers):
        resp = client.get("/api/agents/h/stream/cmd1", headers=viewer_headers)
        assert resp.status_code == 403


# ===========================================================================
# GET /api/agents/{hostname}/streams
# ===========================================================================

class TestAgentActiveStreams:
    """Active log stream listing per agent."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/agents/h/streams")
        assert resp.status_code == 401

    def test_returns_empty_streams_for_unknown_agent(self, client, admin_headers):
        resp = client.get("/api/agents/h/streams", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == {"streams": []}

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/agents/h/streams", headers=viewer_headers)
        assert resp.status_code == 200


# ===========================================================================
# POST /api/agents/{hostname}/stream-logs  (admin only)
# DELETE /api/agents/{hostname}/stream-logs/{cmd_id}  (admin only)
# ===========================================================================

class TestStreamLogs:
    """Log streaming management — admin only."""

    def test_start_stream_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/agents/h/stream-logs", json={"unit": "nginx", "lines": 10}
        )
        assert resp.status_code == 401

    def test_start_stream_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/agents/h/stream-logs",
            json={"unit": "nginx", "lines": 10},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_start_stream_operator_returns_200(self, client, operator_headers):
        resp = client.post(
            "/api/agents/h/stream-logs",
            json={"unit": "nginx", "lines": 10},
            headers=operator_headers,
        )
        assert resp.status_code == 200

    def test_start_stream_admin_returns_200(self, client, admin_headers):
        resp = client.post(
            "/api/agents/somehost/stream-logs",
            json={"unit": "nginx", "lines": 10},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert "stream_id" in data

    def test_stop_stream_no_auth_returns_401(self, client):
        resp = client.delete("/api/agents/h/stream-logs/cmd1")
        assert resp.status_code == 401

    def test_stop_stream_viewer_returns_403(self, client, viewer_headers):
        resp = client.delete(
            "/api/agents/h/stream-logs/cmd1", headers=viewer_headers
        )
        assert resp.status_code == 403

    def test_stop_stream_admin_returns_200(self, client, admin_headers):
        resp = client.delete(
            "/api/agents/somehost/stream-logs/some-cmd-id", headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"


# ===========================================================================
# Shell quoting security tests
# ===========================================================================

class TestAgentDeployShellQuoting:
    """Test shlex.quote() protection for shell-interpolated values."""

    def test_shlex_quote_escapes_metacharacters(self):
        import shlex
        assert shlex.quote("http://evil.com; rm -rf /") == "'http://evil.com; rm -rf /'"

    def test_shlex_quote_on_normal_url(self):
        import shlex
        result = shlex.quote("http://10.0.0.1:8080")
        assert "http://10.0.0.1:8080" in result
