"""Tests for agent_command automation type in workflow engine and alert healing."""
from __future__ import annotations

import time
from unittest.mock import patch

from server.agent_store import (
    _agent_cmd_lock,
    _agent_cmd_results,
    _agent_commands,
    _agent_data,
    _agent_data_lock,
    queue_agent_command,
    queue_agent_command_and_wait,
)


class TestQueueAgentCommand:
    """Test the basic queue_agent_command helper."""

    def setup_method(self):
        with _agent_cmd_lock:
            _agent_commands.clear()
            _agent_cmd_results.clear()

    def teardown_method(self):
        with _agent_cmd_lock:
            _agent_commands.clear()
            _agent_cmd_results.clear()

    def test_queues_command(self):
        cmd_id = queue_agent_command("host1", "restart_service", {"service": "nginx"})
        assert cmd_id
        with _agent_cmd_lock:
            cmds = _agent_commands.get("host1", [])
        assert len(cmds) == 1
        assert cmds[0]["id"] == cmd_id
        assert cmds[0]["type"] == "restart_service"
        assert cmds[0]["params"]["service"] == "nginx"

    def test_multiple_commands_queue(self):
        queue_agent_command("host1", "ping", {})
        queue_agent_command("host1", "exec", {"cmd": "ls"})
        with _agent_cmd_lock:
            cmds = _agent_commands.get("host1", [])
        assert len(cmds) == 2


class TestQueueAgentCommandAndWait:
    """Test queue_agent_command_and_wait with simulated results."""

    def setup_method(self):
        with _agent_cmd_lock:
            _agent_commands.clear()
            _agent_cmd_results.clear()
        with _agent_data_lock:
            _agent_data.clear()

    def teardown_method(self):
        with _agent_cmd_lock:
            _agent_commands.clear()
            _agent_cmd_results.clear()
        with _agent_data_lock:
            _agent_data.clear()

    def test_returns_none_on_timeout(self):
        """With no result injected, should time out and return None."""
        result = queue_agent_command_and_wait("host1", "ping", {}, timeout=0.3)
        assert result is None

    def test_returns_result_when_available(self):
        """Inject a result before calling; should find it."""
        # We need to pre-populate the result so polling finds it.
        # First queue the command to get a cmd_id, then inject a matching result.
        import threading

        result_holder = {}

        def inject_result():
            # Wait a tiny bit for the queue to happen
            time.sleep(0.05)
            with _agent_cmd_lock:
                cmds = _agent_commands.get("host1", [])
                if cmds:
                    cmd_id = cmds[0]["id"]
                    _agent_cmd_results.setdefault("host1", []).append({
                        "id": cmd_id,
                        "type": "result",
                        "status": "ok",
                        "data": {"uptime": 12345},
                    })
                    result_holder["cmd_id"] = cmd_id

        t = threading.Thread(target=inject_result, daemon=True)
        t.start()
        result = queue_agent_command_and_wait("host1", "ping", {}, timeout=2)
        t.join(timeout=3)
        assert result is not None
        assert result["status"] == "ok"
        assert result["id"] == result_holder["cmd_id"]

    def test_all_broadcast_no_agents(self):
        """__all__ with no online agents returns None."""
        result = queue_agent_command_and_wait("__all__", "ping", {}, timeout=0.3)
        assert result is None

    def test_all_broadcast_with_agents(self):
        """__all__ with online agents dispatches to each."""
        now = time.time()
        with _agent_data_lock:
            _agent_data["host1"] = {"_received": now}
            _agent_data["host2"] = {"_received": now}

        # Inject results for both hosts quickly
        import threading

        def inject_results():
            time.sleep(0.05)
            for host in ("host1", "host2"):
                with _agent_cmd_lock:
                    cmds = _agent_commands.get(host, [])
                    if cmds:
                        _agent_cmd_results.setdefault(host, []).append({
                            "id": cmds[0]["id"],
                            "type": "result",
                            "status": "ok",
                        })

        t = threading.Thread(target=inject_results, daemon=True)
        t.start()
        result = queue_agent_command_and_wait("__all__", "ping", {}, timeout=2)
        t.join(timeout=3)
        assert result is not None
        assert result.get("__all__") is True
        assert "host1" in result["results"]
        assert "host2" in result["results"]


class TestWorkflowAgentCommand:
    """Test the _build_auto_agent_command_process workflow builder."""

    def test_missing_hostname_returns_none(self):
        from server.workflow_engine import _build_auto_agent_command_process
        proc = _build_auto_agent_command_process({"command": "ping"})
        assert proc is None

    def test_missing_command_returns_none(self):
        from server.workflow_engine import _build_auto_agent_command_process
        proc = _build_auto_agent_command_process({"hostname": "host1"})
        assert proc is None

    @patch("server.agent_store.queue_agent_command_and_wait")
    def test_timeout_returns_failure_process(self, mock_wait):
        from server.workflow_engine import _build_auto_agent_command_process
        mock_wait.return_value = None
        proc = _build_auto_agent_command_process({
            "hostname": "host1", "command": "ping", "params": {},
        })
        assert proc is not None
        proc.wait(timeout=5)
        assert proc.returncode != 0

    @patch("server.agent_store.queue_agent_command_and_wait")
    def test_success_returns_zero_exit(self, mock_wait):
        from server.workflow_engine import _build_auto_agent_command_process
        mock_wait.return_value = {"status": "ok", "id": "abc123"}
        proc = _build_auto_agent_command_process({
            "hostname": "host1", "command": "restart_service",
            "params": {"service": "nginx"},
        })
        assert proc is not None
        proc.wait(timeout=5)
        assert proc.returncode == 0

    @patch("server.agent_store.queue_agent_command_and_wait")
    def test_error_result_returns_nonzero(self, mock_wait):
        from server.workflow_engine import _build_auto_agent_command_process
        mock_wait.return_value = {"status": "error", "id": "abc123", "error": "command failed"}
        proc = _build_auto_agent_command_process({
            "hostname": "host1", "command": "exec",
            "params": {"cmd": "bad-command"},
        })
        assert proc is not None
        proc.wait(timeout=5)
        assert proc.returncode != 0

    @patch("server.agent_store.queue_agent_command_and_wait")
    def test_broadcast_all_success(self, mock_wait):
        from server.workflow_engine import _build_auto_agent_command_process
        mock_wait.return_value = {
            "__all__": True,
            "results": {
                "host1": {"status": "ok", "id": "a1"},
                "host2": {"status": "ok", "id": "a2"},
            },
        }
        proc = _build_auto_agent_command_process({
            "hostname": "__all__", "command": "update_agent", "params": {},
        })
        assert proc is not None
        proc.wait(timeout=5)
        assert proc.returncode == 0

    @patch("server.agent_store.queue_agent_command_and_wait")
    def test_broadcast_partial_failure(self, mock_wait):
        from server.workflow_engine import _build_auto_agent_command_process
        mock_wait.return_value = {
            "__all__": True,
            "results": {
                "host1": {"status": "ok", "id": "a1"},
                "host2": None,  # timed out
            },
        }
        proc = _build_auto_agent_command_process({
            "hostname": "__all__", "command": "update_agent", "params": {},
        })
        assert proc is not None
        proc.wait(timeout=5)
        assert proc.returncode != 0

    def test_in_auto_builders(self):
        from server.workflow_engine import _AUTO_BUILDERS
        assert "agent_command" in _AUTO_BUILDERS

    def test_in_allowed_types(self):
        from server.config import ALLOWED_AUTO_TYPES
        assert "agent_command" in ALLOWED_AUTO_TYPES


class TestAlertHealAgentCommand:
    """Test the agent_command case in alert self-healing."""

    @patch("server.agent_store.queue_agent_command_and_wait")
    def test_heal_agent_command_success(self, mock_wait):
        from server.alerts import _execute_heal_agent_command
        mock_wait.return_value = {"status": "ok", "id": "abc123"}
        result = _execute_heal_agent_command(
            {"hostname": "host-a", "command": "restart_service",
             "params": {"service": "unbound"}},
            rule_id="rule1",
        )
        assert result is True
        mock_wait.assert_called_once_with(
            "host-a", "restart_service", {"service": "unbound"},
            timeout=30, queued_by="heal:rule1",
        )

    @patch("server.agent_store.queue_agent_command_and_wait")
    def test_heal_agent_command_timeout(self, mock_wait):
        from server.alerts import _execute_heal_agent_command
        mock_wait.return_value = None
        result = _execute_heal_agent_command(
            {"hostname": "host1", "command": "ping", "params": {}},
            rule_id="rule2",
        )
        assert result is False

    @patch("server.agent_store.queue_agent_command_and_wait")
    def test_heal_agent_command_error(self, mock_wait):
        from server.alerts import _execute_heal_agent_command
        mock_wait.return_value = {"status": "error", "id": "x", "error": "fail"}
        result = _execute_heal_agent_command(
            {"hostname": "host1", "command": "exec", "params": {"cmd": "bad"}},
            rule_id="rule3",
        )
        assert result is False

    def test_heal_agent_command_missing_hostname(self):
        from server.alerts import _execute_heal_agent_command
        result = _execute_heal_agent_command(
            {"command": "ping", "params": {}},
            rule_id="rule4",
        )
        assert result is False

    def test_heal_agent_command_missing_command(self):
        from server.alerts import _execute_heal_agent_command
        result = _execute_heal_agent_command(
            {"hostname": "host1", "params": {}},
            rule_id="rule5",
        )
        assert result is False

    @patch("server.agent_store.queue_agent_command_and_wait")
    def test_heal_broadcast_success(self, mock_wait):
        from server.alerts import _execute_heal_agent_command
        mock_wait.return_value = {
            "__all__": True,
            "results": {
                "h1": {"status": "ok", "id": "a"},
                "h2": {"status": "ok", "id": "b"},
            },
        }
        result = _execute_heal_agent_command(
            {"hostname": "__all__", "command": "update_agent", "params": {}},
            rule_id="rule6",
        )
        assert result is True

    @patch("server.agent_store.queue_agent_command_and_wait")
    def test_heal_broadcast_partial_failure(self, mock_wait):
        from server.alerts import _execute_heal_agent_command
        mock_wait.return_value = {
            "__all__": True,
            "results": {
                "h1": {"status": "ok", "id": "a"},
                "h2": {"status": "error", "id": "b", "error": "fail"},
            },
        }
        result = _execute_heal_agent_command(
            {"hostname": "__all__", "command": "restart_service",
             "params": {"service": "nginx"}},
            rule_id="rule7",
        )
        assert result is False

    def test_execute_heal_dispatches_agent_command(self):
        """_execute_heal routes type=agent_command to the agent_command handler."""
        from server.alerts import _execute_heal
        with patch("server.alerts._execute_heal_agent_command") as mock_handler:
            mock_handler.return_value = True
            action_cfg = {
                "type": "agent_command",
                "hostname": "host1",
                "command": "ping",
                "params": {},
            }
            result = _execute_heal(action_cfg, "rule_test", lambda: {})
            assert result is True
            mock_handler.assert_called_once_with(action_cfg, "rule_test")

    def test_execute_heal_validates_config(self):
        """Verify the _validate_auto_config function accepts agent_command."""
        from server.workflow_engine import _validate_auto_config

        # Valid config should not raise
        _validate_auto_config("agent_command", {
            "hostname": "host1", "command": "ping", "params": {},
        })

    def test_execute_heal_validates_missing_hostname(self):
        """Verify _validate_auto_config rejects agent_command without hostname."""
        import pytest
        from fastapi import HTTPException
        from server.workflow_engine import _validate_auto_config
        with pytest.raises(HTTPException):
            _validate_auto_config("agent_command", {"command": "ping"})

    def test_execute_heal_validates_missing_command(self):
        """Verify _validate_auto_config rejects agent_command without command."""
        import pytest
        from fastapi import HTTPException
        from server.workflow_engine import _validate_auto_config
        with pytest.raises(HTTPException):
            _validate_auto_config("agent_command", {"hostname": "host1"})
