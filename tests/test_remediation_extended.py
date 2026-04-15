# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for migrated action types: run, webhook, automation, agent_command."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestRunAction:
    def test_validate_run(self):
        from server.remediation import validate_action
        err = validate_action("run", {"command": "echo hello"})
        assert err is None

    def test_validate_run_missing(self):
        from server.remediation import validate_action
        err = validate_action("run", {})
        assert err is not None

    @patch("server.remediation.subprocess.run")
    def test_execute_run_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        from server.remediation import _handle_run
        result = _handle_run({"command": "systemctl restart nginx"})
        assert result["success"] is True

    def test_execute_run_blocked_by_allowlist(self):
        from server.remediation import _handle_run
        result = _handle_run({"command": "echo hello"})
        assert result["success"] is False
        assert "allowlist" in result["error"].lower()


class TestWebhookAction:
    def test_validate_webhook(self):
        from server.remediation import validate_action
        err = validate_action("webhook", {"url": "http://example.com/hook"})
        assert err is None

    def test_validate_webhook_missing(self):
        from server.remediation import validate_action
        err = validate_action("webhook", {})
        assert err is not None


class TestAutomationAction:
    def test_validate_automation(self):
        from server.remediation import validate_action
        err = validate_action("automation", {"automation_id": "my-auto"})
        assert err is None

    def test_validate_automation_missing(self):
        from server.remediation import validate_action
        err = validate_action("automation", {})
        assert err is not None


class TestAgentCommandAction:
    def test_validate_agent_command(self):
        from server.remediation import validate_action
        err = validate_action("agent_command", {"hostname": "host1", "command": "restart"})
        assert err is None

    def test_validate_agent_command_missing(self):
        from server.remediation import validate_action
        err = validate_action("agent_command", {})
        assert err is not None
