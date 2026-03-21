"""Tests for remediation automation type in workflow engine."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from unittest.mock import patch


# ── Builder presence ──────────────────────────────────────────────────────────

class TestRemediationBuilderRegistry:
    """Verify remediation is registered in the builder map and allowed types."""

    def test_in_auto_builders(self):
        from server.workflow_engine import _AUTO_BUILDERS
        assert "remediation" in _AUTO_BUILDERS

    def test_builder_is_callable(self):
        from server.workflow_engine import _AUTO_BUILDERS
        assert callable(_AUTO_BUILDERS["remediation"])

    def test_in_allowed_auto_types(self):
        from server.config import ALLOWED_AUTO_TYPES
        assert "remediation" in ALLOWED_AUTO_TYPES


# ── Validation ────────────────────────────────────────────────────────────────

class TestRemediationValidation:
    """Validate that _validate_auto_config enforces remediation_type."""

    def test_missing_remediation_type_raises_400(self):
        from server.workflow_engine import _validate_auto_config
        with pytest.raises(HTTPException) as exc_info:
            _validate_auto_config("remediation", {})
        assert exc_info.value.status_code == 400

    def test_missing_remediation_type_with_params_only_raises_400(self):
        from server.workflow_engine import _validate_auto_config
        with pytest.raises(HTTPException) as exc_info:
            _validate_auto_config("remediation", {"params": {"service": "nginx"}})
        assert exc_info.value.status_code == 400

    def test_valid_config_passes(self):
        from server.workflow_engine import _validate_auto_config
        # Should not raise
        _validate_auto_config("remediation", {
            "remediation_type": "restart_service",
            "params": {"service": "nginx"},
        })

    def test_valid_config_no_params_passes(self):
        from server.workflow_engine import _validate_auto_config
        # params is optional
        _validate_auto_config("remediation", {"remediation_type": "flush_dns"})


# ── Builder behaviour ─────────────────────────────────────────────────────────

class TestBuildAutoRemediationProcess:
    """Unit-test _build_auto_remediation_process using a mocked execute_action."""

    def test_missing_remediation_type_returns_none(self):
        from server.workflow_engine import _build_auto_remediation_process
        result = _build_auto_remediation_process({})
        assert result is None

    @patch("server.remediation.execute_action")
    def test_success_returns_exit_code_0(self, mock_execute):
        from server.workflow_engine import _build_auto_remediation_process
        mock_execute.return_value = {
            "success": True,
            "output": "Service restarted OK",
            "duration_s": 0.5,
        }
        proc = _build_auto_remediation_process({
            "remediation_type": "restart_service",
            "params": {"service": "nginx"},
        }, run_id=42)
        assert proc is not None
        assert proc.returncode == 0
        assert proc.wait() == 0

    @patch("server.remediation.execute_action")
    def test_failure_returns_exit_code_1(self, mock_execute):
        from server.workflow_engine import _build_auto_remediation_process
        mock_execute.return_value = {
            "success": False,
            "error": "service not found",
            "duration_s": 0.1,
        }
        proc = _build_auto_remediation_process({
            "remediation_type": "restart_service",
            "params": {"service": "nonexistent"},
        }, run_id=99)
        assert proc is not None
        assert proc.returncode == 1
        assert proc.wait() == 1

    @patch("server.remediation.execute_action")
    def test_execute_action_called_with_correct_args(self, mock_execute):
        from server.workflow_engine import _build_auto_remediation_process
        mock_execute.return_value = {"success": True, "output": "Done"}
        _build_auto_remediation_process({
            "remediation_type": "flush_dns",
            "params": {},
        }, run_id=7)
        mock_execute.assert_called_once_with(
            "flush_dns", {}, trigger_type="workflow", trigger_id="7",
        )

    @patch("server.remediation.execute_action")
    def test_error_message_included_in_output(self, mock_execute):
        from server.workflow_engine import _build_auto_remediation_process
        mock_execute.return_value = {
            "success": False,
            "output": "stdout output",
            "error": "fatal error",
        }
        proc = _build_auto_remediation_process({
            "remediation_type": "restart_container",
            "params": {"container": "broken"},
        }, run_id=0)
        assert proc is not None
        raw = proc.stdout.read().decode()
        assert "stdout output" in raw
        assert "fatal error" in raw

    @patch("server.remediation.execute_action")
    def test_output_only_no_error_key(self, mock_execute):
        """When result has no 'error' key, output is just the output field."""
        from server.workflow_engine import _build_auto_remediation_process
        mock_execute.return_value = {"success": True, "output": "all good"}
        proc = _build_auto_remediation_process({
            "remediation_type": "clear_cache",
            "params": {"target": "system"},
        }, run_id=0)
        assert proc is not None
        raw = proc.stdout.read().decode()
        assert raw == "all good"

    @patch("server.remediation.execute_action")
    def test_default_run_id_is_zero(self, mock_execute):
        """Builder accepts config-only call (run_id defaults to 0)."""
        from server.workflow_engine import _build_auto_remediation_process
        mock_execute.return_value = {"success": True, "output": "ok"}
        proc = _build_auto_remediation_process({"remediation_type": "flush_dns", "params": {}})
        assert proc is not None
        mock_execute.assert_called_once_with(
            "flush_dns", {}, trigger_type="workflow", trigger_id="0",
        )

    @patch("server.remediation.execute_action")
    def test_params_defaults_to_empty_dict(self, mock_execute):
        """If config has no 'params' key, builder passes {} to execute_action."""
        from server.workflow_engine import _build_auto_remediation_process
        mock_execute.return_value = {"success": True, "output": "ok"}
        _build_auto_remediation_process({"remediation_type": "flush_dns"}, run_id=1)
        mock_execute.assert_called_once_with(
            "flush_dns", {}, trigger_type="workflow", trigger_id="1",
        )
