# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for the operations router (share/noba-web/server/routers/operations.py)."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proc(returncode=0, stdout="", stderr=""):
    """Return a minimal subprocess.CompletedProcess-like object."""
    r = type("R", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()
    return r


def _seed_agent(hostname: str = "test-host") -> None:
    """Seed an agent directly into the in-memory store."""
    from server.agent_store import _agent_data, _agent_data_lock

    with _agent_data_lock:
        _agent_data[hostname] = {"hostname": hostname, "_received": time.time()}


# ===========================================================================
# POST /api/recovery/tailscale-reconnect  (admin only)
# ===========================================================================

class TestRecoveryTailscale:
    """POST /api/recovery/tailscale-reconnect — admin required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/recovery/tailscale-reconnect")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/recovery/tailscale-reconnect", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "VPN is up", "")):
            resp = client.post("/api/recovery/tailscale-reconnect", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_success(self, client, admin_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "VPN is up", "")) as mock_run:
            resp = client.post("/api/recovery/tailscale-reconnect", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "output" in data
        mock_run.assert_called_once()

    def test_admin_subprocess_error_returns_error_status(self, client, admin_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(1, "", "failed")):
            resp = client.post("/api/recovery/tailscale-reconnect", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"

    def test_admin_exception_returns_error(self, client, admin_headers):
        with patch("server.routers.operations.subprocess.run",
                   side_effect=OSError("no such file")):
            resp = client.post("/api/recovery/tailscale-reconnect", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"


# ===========================================================================
# POST /api/recovery/dns-flush  (admin only)
# ===========================================================================

class TestRecoveryDnsFlush:
    """POST /api/recovery/dns-flush — admin required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/recovery/dns-flush")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/recovery/dns-flush", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "", "")):
            resp = client.post("/api/recovery/dns-flush", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_success(self, client, admin_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "", "")) as mock_run:
            resp = client.post("/api/recovery/dns-flush", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_run.assert_called_once()

    def test_admin_subprocess_failure(self, client, admin_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(1, "", "restart failed")):
            resp = client.post("/api/recovery/dns-flush", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"

    def test_admin_exception_returns_error(self, client, admin_headers):
        with patch("server.routers.operations.subprocess.run",
                   side_effect=Exception("boom")):
            resp = client.post("/api/recovery/dns-flush", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"


# ===========================================================================
# POST /api/recovery/service-restart  (admin only)
# ===========================================================================

class TestRecoveryServiceRestart:
    """POST /api/recovery/service-restart — admin required, service name validated."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/recovery/service-restart", json={"service": "nginx"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/recovery/service-restart",
                           json={"service": "nginx"}, headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "", "")):
            resp = client.post("/api/recovery/service-restart",
                               json={"service": "nginx"}, headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_empty_service_returns_400(self, client, admin_headers):
        resp = client.post("/api/recovery/service-restart",
                           json={"service": ""}, headers=admin_headers)
        assert resp.status_code == 400

    def test_admin_invalid_service_name_returns_400(self, client, admin_headers):
        resp = client.post("/api/recovery/service-restart",
                           json={"service": "rm -rf /"}, headers=admin_headers)
        assert resp.status_code == 400

    def test_admin_service_name_too_long_returns_400(self, client, admin_headers):
        resp = client.post("/api/recovery/service-restart",
                           json={"service": "a" * 257}, headers=admin_headers)
        assert resp.status_code == 400

    def test_admin_valid_service_success(self, client, admin_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "", "")) as mock_run:
            resp = client.post("/api/recovery/service-restart",
                               json={"service": "nginx.service"}, headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "nginx.service"
        mock_run.assert_called_once()

    def test_admin_service_with_at_sign(self, client, admin_headers):
        """Unit names with @ (template instances) are valid."""
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "", "")):
            resp = client.post("/api/recovery/service-restart",
                               json={"service": "container@myapp.service"}, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_admin_subprocess_failure(self, client, admin_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(1, "", "not found")):
            resp = client.post("/api/recovery/service-restart",
                               json={"service": "missing.service"}, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"


# ===========================================================================
# POST /api/system/cpu-governor  (admin only)
# ===========================================================================

class TestCpuGovernor:
    """POST /api/system/cpu-governor — admin required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/system/cpu-governor", json={"governor": "performance"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/system/cpu-governor",
                           json={"governor": "performance"}, headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/system/cpu-governor",
                           json={"governor": "performance"}, headers=operator_headers)
        assert resp.status_code == 403

    def test_invalid_governor_returns_400(self, client, admin_headers):
        resp = client.post("/api/system/cpu-governor",
                           json={"governor": "turbo"}, headers=admin_headers)
        assert resp.status_code == 400

    def test_empty_governor_returns_400(self, client, admin_headers):
        resp = client.post("/api/system/cpu-governor",
                           json={"governor": ""}, headers=admin_headers)
        assert resp.status_code == 400

    def test_valid_governor_performance(self, client, admin_headers):
        mock_r = MagicMock()
        mock_r.returncode = 0
        with patch("server.routers.operations.subprocess.run", return_value=mock_r):
            resp = client.post("/api/system/cpu-governor",
                               json={"governor": "performance"}, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_valid_governor_powersave(self, client, admin_headers):
        mock_r = MagicMock()
        mock_r.returncode = 0
        with patch("server.routers.operations.subprocess.run", return_value=mock_r):
            resp = client.post("/api/system/cpu-governor",
                               json={"governor": "powersave"}, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_subprocess_failure_returns_success_false(self, client, admin_headers):
        with patch("server.routers.operations.subprocess.run",
                   side_effect=Exception("cpupower not found")):
            resp = client.post("/api/system/cpu-governor",
                               json={"governor": "schedutil"}, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ===========================================================================
# GET /api/sites/sync-status  (any auth)
# ===========================================================================

class TestSiteSyncStatus:
    """GET /api/sites/sync-status — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/sites/sync-status")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/sites/sync-status", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/sites/sync-status", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/sites/sync-status", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_services_list_or_message(self, client, admin_headers):
        resp = client.get("/api/sites/sync-status", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "services" in data or "message" in data

    def test_no_site_map_returns_empty_services(self, client, admin_headers):
        with patch("server.routers.operations.read_yaml_settings", return_value={}):
            resp = client.get("/api/sites/sync-status", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("services") == [] or "message" in data

    def test_with_site_map_returns_services_list(self, client, admin_headers):
        with patch("server.routers.operations.read_yaml_settings",
                   return_value={"siteMap": {"service_a": "site1", "service_b": "site2"}}):
            resp = client.get("/api/sites/sync-status", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data.get("services"), list)
        keys = [s["key"] for s in data["services"]]
        assert "service_a" in keys
        assert "service_b" in keys


# ===========================================================================
# GET /api/smart  (any auth)
# ===========================================================================

class TestSmart:
    """GET /api/smart — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/smart")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with patch("server.routers.operations.collect_smart", return_value=[]):
            resp = client.get("/api/smart", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.routers.operations.collect_smart", return_value=[]):
            resp = client.get("/api/smart", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        with patch("server.routers.operations.collect_smart", return_value=[]):
            resp = client.get("/api/smart", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_list(self, client, admin_headers):
        fake_data = [{"device": "/dev/sda", "health": "PASSED", "temp": 35}]
        with patch("server.routers.operations.collect_smart", return_value=fake_data):
            resp = client.get("/api/smart", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["device"] == "/dev/sda"

    def test_returns_empty_list_when_no_disks(self, client, admin_headers):
        with patch("server.routers.operations.collect_smart", return_value=[]):
            resp = client.get("/api/smart", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == []


# ===========================================================================
# GET /api/journal  (operator+)
# ===========================================================================

class TestJournal:
    """GET /api/journal — operator or higher."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/journal")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/journal", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "Mar 01 00:00:00 host systemd: started\n", "")):
            resp = client.get("/api/journal", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "Mar 01 00:00:00 host systemd: started\n", "")):
            resp = client.get("/api/journal", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_plain_text(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "some log line\n", "")):
            resp = client.get("/api/journal", headers=operator_headers)
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_empty_stdout_returns_no_entries(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "", "")):
            resp = client.get("/api/journal", headers=operator_headers)
        assert resp.status_code == 200
        assert "No entries" in resp.text

    def test_unit_filter_valid(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "nginx log\n", "")) as mock_run:
            resp = client.get("/api/journal?unit=nginx.service", headers=operator_headers)
        assert resp.status_code == 200
        call_args = mock_run.call_args[0][0]
        assert "-u" in call_args
        assert "nginx.service" in call_args

    def test_unit_filter_invalid_returns_400(self, client, operator_headers):
        resp = client.get("/api/journal?unit=../etc/passwd", headers=operator_headers)
        assert resp.status_code == 400

    def test_priority_filter_valid(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "err log\n", "")) as mock_run:
            resp = client.get("/api/journal?priority=err", headers=operator_headers)
        assert resp.status_code == 200
        call_args = mock_run.call_args[0][0]
        assert "-p" in call_args
        assert "err" in call_args

    def test_invalid_priority_ignored(self, client, operator_headers):
        """Unknown priority values are silently ignored (not added to cmd)."""
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "log\n", "")) as mock_run:
            resp = client.get("/api/journal?priority=bogus", headers=operator_headers)
        assert resp.status_code == 200
        call_args = mock_run.call_args[0][0]
        assert "-p" not in call_args

    def test_since_filter_valid(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "log\n", "")):
            resp = client.get("/api/journal?since=1+hour+ago", headers=operator_headers)
        assert resp.status_code == 200

    def test_lines_param_respected(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "log\n", "")) as mock_run:
            resp = client.get("/api/journal?lines=100", headers=operator_headers)
        assert resp.status_code == 200
        call_args = mock_run.call_args[0][0]
        assert "100" in call_args

    def test_journalctl_not_found_returns_graceful_message(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   side_effect=FileNotFoundError):
            resp = client.get("/api/journal", headers=operator_headers)
        assert resp.status_code == 200
        assert "journalctl not available" in resp.text

    def test_timeout_returns_504(self, client, operator_headers):
        import subprocess as _sp
        with patch("server.routers.operations.subprocess.run",
                   side_effect=_sp.TimeoutExpired(["journalctl"], 10)):
            resp = client.get("/api/journal", headers=operator_headers)
        assert resp.status_code == 504


# ===========================================================================
# GET /api/journal/units  (operator+)
# ===========================================================================

class TestJournalUnits:
    """GET /api/journal/units — operator or higher."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/journal/units")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/journal/units", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "", "")):
            resp = client.get("/api/journal/units", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "", "")):
            resp = client.get("/api/journal/units", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_list(self, client, operator_headers):
        stdout = (
            "nginx.service   loaded active running   A high performance web server\n"
            "sshd.service    loaded active running   OpenSSH Daemon\n"
        )
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, stdout, "")):
            resp = client.get("/api/journal/units", headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["name"] == "nginx.service"
        assert "status" in data[0]

    def test_exception_returns_empty_list(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   side_effect=Exception("systemctl not found")):
            resp = client.get("/api/journal/units", headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_empty_output_returns_empty_list(self, client, operator_headers):
        with patch("server.routers.operations.subprocess.run",
                   return_value=_make_proc(0, "", "")):
            resp = client.get("/api/journal/units", headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json() == []


# ===========================================================================
# GET /api/system/info  (any auth)
# ===========================================================================

class TestSystemInfo:
    """GET /api/system/info — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/system/info")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/system/info", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/system/info", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/system/info", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_dict_with_required_fields(self, client, admin_headers):
        resp = client.get("/api/system/info", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        for field in ("hostname", "arch", "python", "cpu_cores", "noba_version"):
            assert field in data

    def test_noba_version_present(self, client, admin_headers):
        resp = client.get("/api/system/info", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["noba_version"]  # should be a non-empty string

    def test_psutil_fields_present_when_available(self, client, admin_headers):
        """When psutil is importable, RAM/swap fields should appear."""
        mock_vm = MagicMock()
        mock_vm.total = 8 * 1024 ** 3
        mock_vm.available = 4 * 1024 ** 3
        mock_sw = MagicMock()
        mock_sw.total = 2 * 1024 ** 3
        mock_sw.used = 512 * 1024 ** 2

        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value = mock_vm
        mock_psutil.swap_memory.return_value = mock_sw

        import sys
        original = sys.modules.get("psutil")
        sys.modules["psutil"] = mock_psutil
        try:
            resp = client.get("/api/system/info", headers=admin_headers)
        finally:
            if original is None:
                sys.modules.pop("psutil", None)
            else:
                sys.modules["psutil"] = original

        assert resp.status_code == 200
        data = resp.json()
        assert "ram_total_gb" in data
        assert data["ram_total_gb"] == 8.0


# ===========================================================================
# GET /api/system/health  (any auth)
# ===========================================================================

class TestSystemHealth:
    """GET /api/system/health — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/system/health")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/system/health", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/system/health", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/system/health", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_score_grade_checks(self, client, admin_headers):
        resp = client.get("/api/system/health", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data
        assert "grade" in data
        assert "checks" in data
        assert isinstance(data["checks"], list)

    def test_score_between_0_and_100(self, client, admin_headers):
        resp = client.get("/api/system/health", headers=admin_headers)
        data = resp.json()
        assert 0 <= data["score"] <= 100

    def test_grade_is_valid_letter(self, client, admin_headers):
        resp = client.get("/api/system/health", headers=admin_headers)
        data = resp.json()
        assert data["grade"] in ("A", "B", "C", "D", "F")

    def test_high_cpu_produces_warning_or_critical(self, client, admin_headers):
        """When bg_collector reports high CPU, health score should drop."""
        mock_stats = {"cpuPercent": 95, "memPercent": 10, "disks": []}
        with patch("server.deps.bg_collector") as mock_bg:
            mock_bg.get.return_value = mock_stats
            resp = client.get("/api/system/health", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        cpu_check = next((c for c in data["checks"] if c["name"] == "CPU"), None)
        assert cpu_check is not None
        assert cpu_check["status"] in ("warning", "critical")

    def test_healthy_system_gets_grade_a(self, client, admin_headers):
        """Clean stats should yield score >= 90 and grade A."""
        mock_stats = {
            "cpuPercent": 10,
            "memPercent": 30,
            "disks": [{"mount": "/", "percent": 50}],
            "cpuTemp": "45°C",
            "services": [],
            "netHealth": {},
            "alerts": [],
        }
        with patch("server.deps.bg_collector") as mock_bg:
            mock_bg.get.return_value = mock_stats
            resp = client.get("/api/system/health", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] >= 90
        assert data["grade"] == "A"


# ===========================================================================
# GET /api/processes/history  (any auth)
# ===========================================================================

class TestProcessHistory:
    """GET /api/processes/history — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/processes/history")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with patch("server.metrics.services.get_process_history", return_value=[]):
            resp = client.get("/api/processes/history", headers=viewer_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        with patch("server.metrics.services.get_process_history", return_value=[]):
            resp = client.get("/api/processes/history", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_list(self, client, admin_headers):
        with patch("server.metrics.services.get_process_history", return_value=[]):
            resp = client.get("/api/processes/history", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ===========================================================================
# GET /api/processes/current  (any auth)
# ===========================================================================

class TestProcessesCurrent:
    """GET /api/processes/current — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/processes/current")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/processes/current", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/processes/current", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/processes/current", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_list(self, client, admin_headers):
        resp = client.get("/api/processes/current", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_process_entries_have_expected_fields(self, client, admin_headers):
        """Each process entry should have pid, name, cpu, mem, status, user."""
        mock_proc = MagicMock()
        mock_proc.info = {
            "pid": 1234,
            "name": "python3",
            "cpu_percent": 5.0,
            "memory_percent": 2.5,
            "status": "running",
            "username": "root",
            "create_time": time.time(),
        }

        import psutil as _psutil_real
        with patch.object(_psutil_real, "process_iter", return_value=[mock_proc]):
            resp = client.get("/api/processes/current", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        if data:  # only check if at least one entry
            entry = data[0]
            for field in ("pid", "name", "cpu", "mem", "status", "user"):
                assert field in entry


# ===========================================================================
# GET /api/export/ansible  (operator+)
# ===========================================================================

class TestExportAnsible:
    """GET /api/export/ansible — operator+ (read-only from cache).
    POST /api/export/ansible — operator+ (with optional discovery).

    Tightened from viewer → operator in the honesty-gap sweep: an Ansible
    playbook reveals full infrastructure topology (hostnames, services,
    ports, paths) which is an info-disclosure risk for viewer accounts.
    """

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/export/ansible")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/export/ansible", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.iac_export.generate_ansible",
                   return_value="---\n- hosts: all\n"):
            resp = client.get("/api/export/ansible", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        with patch("server.iac_export.generate_ansible",
                   return_value="---\n- hosts: all\n"):
            resp = client.get("/api/export/ansible", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_yaml_content_type(self, client, admin_headers):
        with patch("server.iac_export.generate_ansible",
                   return_value="---\n"):
            resp = client.get("/api/export/ansible", headers=admin_headers)
        assert resp.status_code == 200
        assert "yaml" in resp.headers.get("content-type", "")

    def test_hostname_param_passed_through(self, client, admin_headers):
        with patch("server.iac_export.generate_ansible",
                   return_value="---\n") as mock_gen:
            resp = client.get("/api/export/ansible?hostname=myhost", headers=admin_headers)
        assert resp.status_code == 200
        call_kwargs = mock_gen.call_args
        # hostname should be passed as 5th positional arg or keyword
        assert "myhost" in str(call_kwargs)

    def test_post_discover_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/export/ansible",
                           json={"discover": True}, headers=viewer_headers)
        assert resp.status_code == 403

    def test_post_discover_operator_can_access(self, client, operator_headers):
        with patch("server.iac_export.generate_ansible",
                   return_value="---\n"):
            resp = client.post("/api/export/ansible",
                               json={"discover": True}, headers=operator_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/export/docker-compose  (operator+)
# ===========================================================================

class TestExportDockerCompose:
    """GET /api/export/docker-compose — operator+ (read-only from cache).
    POST /api/export/docker-compose — operator+ (with optional discovery).

    Tightened from viewer → operator — a docker-compose file reveals full
    container topology and must not be readable by viewer-role accounts.
    """

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/export/docker-compose?hostname=h1")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/export/docker-compose?hostname=h1",
                          headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.iac_export.generate_docker_compose",
                   return_value="version: '3'\n"):
            resp = client.get("/api/export/docker-compose?hostname=h1",
                              headers=operator_headers)
        assert resp.status_code == 200

    def test_missing_hostname_returns_400(self, client, admin_headers):
        resp = client.get("/api/export/docker-compose", headers=admin_headers)
        assert resp.status_code == 400

    def test_admin_with_hostname_succeeds(self, client, admin_headers):
        with patch("server.iac_export.generate_docker_compose",
                   return_value="version: '3'\n"):
            resp = client.get("/api/export/docker-compose?hostname=myhost",
                              headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_yaml_content_type(self, client, admin_headers):
        with patch("server.iac_export.generate_docker_compose",
                   return_value="version: '3'\n"):
            resp = client.get("/api/export/docker-compose?hostname=myhost",
                              headers=admin_headers)
        assert "yaml" in resp.headers.get("content-type", "")


# ===========================================================================
# GET /api/export/shell  (operator+)
# ===========================================================================

class TestExportShell:
    """GET /api/export/shell — operator+ (read-only from cache).
    POST /api/export/shell — operator+ (with optional discovery).

    Tightened from viewer → operator — a shell provisioning script
    reveals hostnames, installed packages, and service paths.
    """

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/export/shell?hostname=h1")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/export/shell?hostname=h1",
                          headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.iac_export.generate_shell_script",
                   return_value="#!/bin/bash\n"):
            resp = client.get("/api/export/shell?hostname=h1",
                              headers=operator_headers)
        assert resp.status_code == 200

    def test_missing_hostname_returns_400(self, client, admin_headers):
        resp = client.get("/api/export/shell", headers=admin_headers)
        assert resp.status_code == 400

    def test_admin_with_hostname_succeeds(self, client, admin_headers):
        with patch("server.iac_export.generate_shell_script",
                   return_value="#!/bin/bash\n"):
            resp = client.get("/api/export/shell?hostname=myhost",
                              headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_shell_content_type(self, client, admin_headers):
        with patch("server.iac_export.generate_shell_script",
                   return_value="#!/bin/bash\n"):
            resp = client.get("/api/export/shell?hostname=myhost",
                              headers=admin_headers)
        ct = resp.headers.get("content-type", "")
        assert "shell" in ct or "text" in ct


# ===========================================================================
# GET /api/backup/verifications  (any auth)
# ===========================================================================

class TestBackupVerifications:
    """GET /api/backup/verifications — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/backup/verifications")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/backup/verifications", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/backup/verifications", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/backup/verifications", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_list(self, client, admin_headers):
        resp = client.get("/api/backup/verifications", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_hostname_filter_accepted(self, client, admin_headers):
        resp = client.get("/api/backup/verifications?hostname=myhost&limit=10",
                          headers=admin_headers)
        assert resp.status_code == 200

    def test_limit_capped_at_500(self, client, admin_headers):
        """Limit over 500 is capped at 500 — response must still be 200."""
        resp = client.get("/api/backup/verifications?limit=9999", headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# POST /api/backup/verify  (operator+)
# ===========================================================================

class TestBackupVerify:
    """POST /api/backup/verify — operator or higher."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/backup/verify",
                           json={"hostname": "h1", "path": "/backup"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/backup/verify",
                           json={"hostname": "h1", "path": "/backup"},
                           headers=viewer_headers)
        assert resp.status_code == 403

    def test_missing_hostname_returns_400(self, client, operator_headers):
        resp = client.post("/api/backup/verify",
                           json={"path": "/backup"},
                           headers=operator_headers)
        assert resp.status_code == 400

    def test_missing_path_returns_400(self, client, operator_headers):
        resp = client.post("/api/backup/verify",
                           json={"hostname": "h1"},
                           headers=operator_headers)
        assert resp.status_code == 400

    def test_invalid_verification_type_returns_400(self, client, operator_headers):
        resp = client.post("/api/backup/verify",
                           json={"hostname": "h1", "path": "/backup",
                                 "verification_type": "unknown"},
                           headers=operator_headers)
        assert resp.status_code == 400

    def test_agent_not_found_returns_404(self, client, operator_headers):
        resp = client.post("/api/backup/verify",
                           json={"hostname": "nonexistent", "path": "/backup"},
                           headers=operator_headers)
        assert resp.status_code == 404

    def test_operator_with_seeded_agent_queues_command(self, client, operator_headers):
        _seed_agent("backup-host")
        resp = client.post("/api/backup/verify",
                           json={"hostname": "backup-host", "path": "/mnt/backup",
                                 "verification_type": "checksum"},
                           headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("sent", "queued")
        assert data["hostname"] == "backup-host"
        assert "id" in data

    def test_admin_with_seeded_agent_succeeds(self, client, admin_headers):
        _seed_agent("admin-backup-host")
        resp = client.post("/api/backup/verify",
                           json={"hostname": "admin-backup-host", "path": "/backup",
                                 "verification_type": "db_integrity"},
                           headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("sent", "queued")

    def test_valid_verification_types(self, client, operator_headers):
        for vtype in ("checksum", "restore_test", "db_integrity"):
            _seed_agent(f"host-{vtype}")
            resp = client.post("/api/backup/verify",
                               json={"hostname": f"host-{vtype}", "path": "/backup",
                                     "verification_type": vtype},
                               headers=operator_headers)
            assert resp.status_code == 200, f"vtype={vtype} failed: {resp.text}"


# ===========================================================================
# GET /api/backup/321-status  (any auth)
# ===========================================================================

class TestBackup321Status:
    """GET /api/backup/321-status — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/backup/321-status")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/backup/321-status", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/backup/321-status", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/backup/321-status", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_list(self, client, admin_headers):
        resp = client.get("/api/backup/321-status", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ===========================================================================
# PUT /api/backup/321-status  (operator+)
# ===========================================================================

class TestBackup321Update:
    """PUT /api/backup/321-status — operator or higher."""

    def test_no_auth_returns_401(self, client):
        resp = client.put("/api/backup/321-status",
                          json={"backup_name": "daily"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.put("/api/backup/321-status",
                          json={"backup_name": "daily"},
                          headers=viewer_headers)
        assert resp.status_code == 403

    def test_missing_backup_name_returns_400(self, client, operator_headers):
        resp = client.put("/api/backup/321-status",
                          json={"copies": 3},
                          headers=operator_headers)
        assert resp.status_code == 400

    def test_operator_can_update(self, client, operator_headers):
        resp = client.put("/api/backup/321-status",
                          json={"backup_name": "daily", "copies": 3,
                                "media_types": ["disk", "tape"], "has_offsite": True},
                          headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "id" in data

    def test_admin_can_update(self, client, admin_headers):
        resp = client.put("/api/backup/321-status",
                          json={"backup_name": "weekly", "copies": 2,
                                "has_offsite": False},
                          headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_minimal_payload_with_only_backup_name(self, client, operator_headers):
        resp = client.put("/api/backup/321-status",
                          json={"backup_name": "minimal-backup"},
                          headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
