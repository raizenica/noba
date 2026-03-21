"""Tests for share/noba-web/server/remediation.py"""
from __future__ import annotations

from unittest.mock import MagicMock, patch



# ---------------------------------------------------------------------------
# validate_action tests
# ---------------------------------------------------------------------------

class TestValidateAction:
    def _import(self):
        from server.remediation import validate_action
        return validate_action

    def test_unknown_type(self):
        validate_action = self._import()
        err = validate_action("does_not_exist", {})
        assert err is not None
        assert "Unknown action type" in err

    def test_restart_container_valid(self):
        validate_action = self._import()
        err = validate_action("restart_container", {"container": "nginx"})
        assert err is None

    def test_restart_container_missing_param(self):
        validate_action = self._import()
        err = validate_action("restart_container", {})
        assert err is not None
        assert "container" in err

    def test_restart_service_valid(self):
        validate_action = self._import()
        err = validate_action("restart_service", {"service": "nginx.service"})
        assert err is None

    def test_restart_service_missing_param(self):
        validate_action = self._import()
        err = validate_action("restart_service", {})
        assert err is not None
        assert "service" in err

    def test_flush_dns_valid(self):
        validate_action = self._import()
        # flush_dns has no required params
        err = validate_action("flush_dns", {})
        assert err is None

    def test_clear_cache_valid(self):
        validate_action = self._import()
        err = validate_action("clear_cache", {"target": "system"})
        assert err is None

    def test_clear_cache_missing_param(self):
        validate_action = self._import()
        err = validate_action("clear_cache", {})
        assert err is not None
        assert "target" in err

    def test_trigger_backup_valid(self):
        validate_action = self._import()
        err = validate_action("trigger_backup", {"source": "home"})
        assert err is None

    def test_trigger_backup_missing_param(self):
        validate_action = self._import()
        err = validate_action("trigger_backup", {})
        assert err is not None
        assert "source" in err

    def test_failover_dns_valid(self):
        validate_action = self._import()
        err = validate_action("failover_dns", {"primary": "1.1.1.1", "secondary": "8.8.8.8"})
        assert err is None

    def test_failover_dns_missing_primary(self):
        validate_action = self._import()
        err = validate_action("failover_dns", {"secondary": "8.8.8.8"})
        assert err is not None
        assert "primary" in err

    def test_failover_dns_missing_secondary(self):
        validate_action = self._import()
        err = validate_action("failover_dns", {"primary": "1.1.1.1"})
        assert err is not None
        assert "secondary" in err

    def test_scale_container_valid(self):
        validate_action = self._import()
        err = validate_action("scale_container", {
            "container": "app", "cpu_limit": "0.5", "mem_limit": "512m"
        })
        assert err is None

    def test_scale_container_missing_container(self):
        validate_action = self._import()
        err = validate_action("scale_container", {"cpu_limit": "0.5", "mem_limit": "512m"})
        assert err is not None
        assert "container" in err

    def test_run_playbook_valid(self):
        validate_action = self._import()
        err = validate_action("run_playbook", {"playbook_id": "abc123"})
        assert err is None

    def test_run_playbook_missing_param(self):
        validate_action = self._import()
        err = validate_action("run_playbook", {})
        assert err is not None
        assert "playbook_id" in err


# ---------------------------------------------------------------------------
# execute_action tests
# ---------------------------------------------------------------------------

class TestExecuteActionRestartContainer:
    @patch("server.remediation.subprocess.run")
    @patch("server.remediation._health_check", return_value=True)
    def test_restart_container_success(self, mock_health, mock_run):
        from server.remediation import execute_action
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = execute_action("restart_container", {"container": "nginx"})

        assert result["success"] is True
        assert "health_check" in result
        assert result["health_check"] == "pass"
        assert "duration_s" in result

    @patch("server.remediation.subprocess.run")
    @patch("server.remediation._health_check", return_value=False)
    def test_restart_container_health_fail(self, mock_health, mock_run):
        from server.remediation import execute_action
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = execute_action("restart_container", {"container": "nginx"})

        assert result["health_check"] == "fail"

    @patch("server.remediation.subprocess.run")
    @patch("server.remediation._health_check", return_value=True)
    def test_restart_container_both_runtimes_fail(self, mock_health, mock_run):
        from server.remediation import execute_action
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "container not found"
        mock_run.return_value = mock_result

        result = execute_action("restart_container", {"container": "missing"})

        assert result["success"] is False


class TestExecuteActionRestartService:
    @patch("server.remediation.subprocess.run")
    @patch("server.remediation._health_check", return_value=True)
    def test_restart_service_success(self, mock_health, mock_run):
        from server.remediation import execute_action
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = execute_action("restart_service", {"service": "nginx.service"})

        assert result["success"] is True
        assert result["health_check"] == "pass"
        mock_run.assert_called_once_with(
            ["sudo", "systemctl", "restart", "nginx.service"],
            capture_output=True, text=True, timeout=30,
        )

    @patch("server.remediation.subprocess.run")
    @patch("server.remediation._health_check", return_value=True)
    def test_restart_service_failure(self, mock_health, mock_run):
        from server.remediation import execute_action
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Unit not found"
        mock_run.return_value = mock_result

        result = execute_action("restart_service", {"service": "bogus.service"})

        assert result["success"] is False


class TestExecuteActionFlushDns:
    @patch("server.remediation.subprocess.run")
    @patch("server.remediation.read_yaml_settings", return_value={})
    def test_flush_dns_via_systemd(self, mock_cfg, mock_run):
        from server.remediation import execute_action
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = execute_action("flush_dns", {})

        assert result["success"] is True
        assert "DNS" in result["output"]
        mock_run.assert_called_once_with(
            ["sudo", "systemd-resolve", "--flush-caches"],
            capture_output=True, text=True, timeout=10,
        )

    @patch("server.remediation.read_yaml_settings", return_value={"piholeUrl": "http://pihole"})
    def test_flush_dns_via_pihole(self, mock_cfg):
        from server.remediation import execute_action
        with patch("httpx.post", return_value=MagicMock(status_code=200)):
            result = execute_action("flush_dns", {})

        assert result["success"] is True
        assert "Pi-hole" in result["output"]

    @patch("server.remediation.read_yaml_settings", return_value={"piholeUrl": "http://pihole"})
    def test_flush_dns_pihole_error(self, mock_cfg):
        from server.remediation import execute_action
        with patch("httpx.post", side_effect=Exception("connection refused")):
            result = execute_action("flush_dns", {})

        assert result["success"] is False


class TestExecuteActionUnknownType:
    def test_unknown_type_returns_error(self):
        from server.remediation import execute_action
        result = execute_action("totally_unknown_type", {})
        assert result["success"] is False
        assert "error" in result
        assert "Unknown action" in result["error"]


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------

class TestHealthCheck:
    @patch("server.remediation.subprocess.run")
    @patch("server.remediation.time.sleep")
    def test_health_check_container_pass(self, mock_sleep, mock_run):
        from server.remediation import _health_check
        mock_result = MagicMock()
        mock_result.stdout = "true\n"
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = _health_check("restart_container", {"container": "nginx"})

        assert result is True
        mock_run.assert_called_once_with(
            ["docker", "inspect", "-f", "{{.State.Running}}", "nginx"],
            capture_output=True, text=True, timeout=10,
        )

    @patch("server.remediation.subprocess.run")
    @patch("server.remediation.time.sleep")
    def test_health_check_container_fail(self, mock_sleep, mock_run):
        from server.remediation import _health_check
        mock_result = MagicMock()
        mock_result.stdout = "false\n"
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = _health_check("restart_container", {"container": "nginx"})

        assert result is False

    @patch("server.remediation.subprocess.run")
    @patch("server.remediation.time.sleep")
    def test_health_check_service_pass(self, mock_sleep, mock_run):
        from server.remediation import _health_check
        mock_result = MagicMock()
        mock_result.stdout = "active\n"
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = _health_check("restart_service", {"service": "nginx.service"})

        assert result is True
        mock_run.assert_called_once_with(
            ["systemctl", "is-active", "nginx.service"],
            capture_output=True, text=True, timeout=10,
        )

    @patch("server.remediation.subprocess.run")
    @patch("server.remediation.time.sleep")
    def test_health_check_service_fail(self, mock_sleep, mock_run):
        from server.remediation import _health_check
        mock_result = MagicMock()
        mock_result.stdout = "inactive\n"
        mock_result.returncode = 3
        mock_run.return_value = mock_result

        result = _health_check("restart_service", {"service": "nginx.service"})

        assert result is False

    @patch("server.remediation.time.sleep")
    def test_health_check_no_check_type_returns_true(self, mock_sleep):
        from server.remediation import _health_check
        # Action types without a specific check path return True by default
        result = _health_check("flush_dns", {})
        assert result is True
