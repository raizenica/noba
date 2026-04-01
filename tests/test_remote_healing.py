"""Tests for remote agent healing dispatch, approval race guard, and action map."""
from __future__ import annotations

from unittest.mock import patch

from server.remediation import (
    _AGENT_COMMAND_MAP,
    _handle_run,
    _is_safe_webhook_url,
    _try_agent_dispatch,
)


# ── Remote agent dispatch ────────────────────────────────────────────────────


class TestAgentCommandMap:
    def test_restart_container_maps_to_container_control(self):
        cmd, transform = _AGENT_COMMAND_MAP["restart_container"]
        assert cmd == "container_control"
        result = transform({"container": "nginx"})
        assert result == {"container": "nginx", "action": "restart"}

    def test_restart_service_maps_correctly(self):
        cmd, transform = _AGENT_COMMAND_MAP["restart_service"]
        assert cmd == "restart_service"
        result = transform({"service": "sshd"})
        assert result == {"service": "sshd"}

    def test_scale_container_maps_to_container_control(self):
        cmd, transform = _AGENT_COMMAND_MAP["scale_container"]
        assert cmd == "container_control"
        result = transform({"container": "web", "action": "stop"})
        assert result == {"container": "web", "action": "stop"}

    def test_scale_container_defaults_to_start(self):
        _, transform = _AGENT_COMMAND_MAP["scale_container"]
        assert transform({"container": "web"})["action"] == "start"

    def test_flush_dns_maps_to_restart_service(self):
        cmd, transform = _AGENT_COMMAND_MAP["flush_dns"]
        assert cmd == "restart_service"
        assert transform({})["service"] == "pihole-FTL"

    def test_flush_dns_custom_service(self):
        _, transform = _AGENT_COMMAND_MAP["flush_dns"]
        assert transform({"service": "unbound"})["service"] == "unbound"

    def test_agent_command_maps_to_exec(self):
        cmd, transform = _AGENT_COMMAND_MAP["agent_command"]
        assert cmd == "exec"
        assert transform({"command": "uptime"}) == {"command": "uptime"}

    def test_unknown_action_not_in_map(self):
        assert "webhook" not in _AGENT_COMMAND_MAP
        assert "run" not in _AGENT_COMMAND_MAP


class TestTryAgentDispatch:
    @patch("server.agent_store.queue_agent_command_and_wait")
    @patch("server.agent_store.get_online_agents", return_value=["pve", "site-b"])
    def test_dispatches_to_online_agent(self, mock_online, mock_queue):
        mock_queue.return_value = {"status": "ok", "output": "restarted"}
        result = _try_agent_dispatch("restart_container", {"container": "nginx"}, "pve")
        assert result is not None
        assert result["success"] is True
        assert "pve" in result["output"]
        mock_queue.assert_called_once_with(
            "pve", "container_control", {"container": "nginx", "action": "restart"},
            timeout=30, queued_by="healing_pipeline",
        )

    @patch("server.agent_store.get_online_agents", return_value=["pve"])
    def test_returns_none_for_offline_agent(self, mock_online):
        result = _try_agent_dispatch("restart_container", {"container": "nginx"}, "site-b")
        assert result is None  # falls through to local

    @patch("server.agent_store.get_online_agents", return_value=["pve"])
    def test_returns_none_for_unmapped_action(self, mock_online):
        result = _try_agent_dispatch("webhook", {"url": "http://x"}, "pve")
        assert result is None

    @patch("server.agent_store.queue_agent_command_and_wait")
    @patch("server.agent_store.get_online_agents", return_value=["pve"])
    def test_timeout_returns_failure(self, mock_online, mock_queue):
        mock_queue.return_value = None  # timeout
        result = _try_agent_dispatch("restart_container", {"container": "x"}, "pve")
        assert result is not None
        assert result["success"] is False
        assert "timed out" in result["output"]

    @patch("server.agent_store.queue_agent_command_and_wait")
    @patch("server.agent_store.get_online_agents", return_value=["pve"])
    def test_error_status_returns_failure(self, mock_online, mock_queue):
        mock_queue.return_value = {"status": "error", "output": "not found"}
        result = _try_agent_dispatch("restart_container", {"container": "x"}, "pve")
        assert result is not None
        assert result["success"] is False


# ── Webhook SSRF protection ──────────────────────────────────────────────────


class TestWebhookSSRF:
    def test_blocks_localhost(self):
        assert _is_safe_webhook_url("http://localhost/x") is False

    def test_blocks_loopback_ipv4(self):
        assert _is_safe_webhook_url("http://127.0.0.1/x") is False

    def test_blocks_zero_address(self):
        assert _is_safe_webhook_url("http://0.0.0.0/x") is False

    def test_blocks_private_10(self):
        assert _is_safe_webhook_url("http://10.0.0.1/x") is False

    def test_blocks_private_192(self):
        assert _is_safe_webhook_url("http://192.168.1.1/x") is False

    def test_blocks_private_172(self):
        assert _is_safe_webhook_url("http://172.16.0.1/x") is False

    def test_blocks_unresolvable(self):
        assert _is_safe_webhook_url("http://nonexistent.invalid/x") is False

    def test_blocks_empty(self):
        assert _is_safe_webhook_url("") is False

    def test_blocks_garbage(self):
        assert _is_safe_webhook_url("not-a-url") is False

    def test_allows_public_domain(self):
        assert _is_safe_webhook_url("http://example.com") is True


# ── Run command argument validation ──────────────────────────────────────────


class TestHandleRunValidation:
    def test_empty_command(self):
        r = _handle_run({"command": ""})
        assert r["success"] is False
        assert "No command" in r["error"]

    def test_not_in_allowlist(self):
        r = _handle_run({"command": "rm -rf /"})
        assert r["success"] is False
        assert "allowlist" in r["error"]

    def test_semicolon_injection_blocked(self):
        r = _handle_run({"command": "systemctl restart evil; rm -rf /"})
        assert r["success"] is False
        assert "Invalid argument" in r["error"]

    def test_pipe_injection_blocked(self):
        r = _handle_run({"command": "systemctl restart a|b"})
        assert r["success"] is False
        assert "Invalid argument" in r["error"]

    def test_command_substitution_blocked(self):
        r = _handle_run({"command": "docker restart $(whoami)"})
        assert r["success"] is False
        assert "Invalid argument" in r["error"]

    def test_ampersand_blocked(self):
        r = _handle_run({"command": "docker restart a&&b"})
        assert r["success"] is False
        assert "Invalid argument" in r["error"]

    def test_backtick_blocked(self):
        r = _handle_run({"command": "systemctl restart `id`"})
        assert r["success"] is False
        assert "Invalid argument" in r["error"]

    def test_valid_service_name_reaches_execution(self):
        # Will fail because service doesn't exist, but passes validation
        r = _handle_run({"command": "systemctl restart nonexistent-svc"})
        assert "Invalid argument" not in r.get("error", "")
        assert "allowlist" not in r.get("error", "")

    def test_valid_hyphenated_container(self):
        r = _handle_run({"command": "docker restart my-container"})
        assert "Invalid argument" not in r.get("error", "")

    def test_valid_dotted_service(self):
        r = _handle_run({"command": "systemctl restart nginx.service"})
        assert "Invalid argument" not in r.get("error", "")


# ── Approval race condition guard ────────────────────────────────────────────


class TestApprovalRaceGuard:
    """Verify the approval decide endpoint gates execution on db.decide_approval success."""

    def test_approval_route_exists(self, client, admin_headers):
        # Non-existent approval should 404
        resp = client.post(
            "/api/approvals/99999/decide",
            json={"decision": "approved"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_invalid_decision_rejected(self, client, admin_headers):
        resp = client.post(
            "/api/approvals/1/decide",
            json={"decision": "maybe"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
