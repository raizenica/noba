# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for the containers router (share/noba-web/server/routers/containers.py)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


# ===========================================================================
# POST /api/container-control
# ===========================================================================

class TestContainerControl:
    """Start/stop/restart a container — operator auth required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/container-control", json={"name": "nginx", "action": "start"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/container-control",
            json={"name": "nginx", "action": "start"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_invalid_action_returns_400(self, client, operator_headers):
        resp = client.post(
            "/api/container-control",
            json={"name": "nginx", "action": "destroy"},
            headers=operator_headers,
        )
        assert resp.status_code == 400

    def test_invalid_container_name_returns_400(self, client, operator_headers):
        resp = client.post(
            "/api/container-control",
            json={"name": "bad name!", "action": "start"},
            headers=operator_headers,
        )
        assert resp.status_code == 400

    def test_empty_container_name_returns_400(self, client, operator_headers):
        resp = client.post(
            "/api/container-control",
            json={"name": "", "action": "start"},
            headers=operator_headers,
        )
        assert resp.status_code == 400

    def test_success_with_docker(self, client, operator_headers):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.post(
                "/api/container-control",
                json={"name": "nginx", "action": "restart"},
                headers=operator_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "runtime" in data

    def test_no_runtime_found_returns_404(self, client, operator_headers):
        with patch(
            "server.routers.containers.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            resp = client.post(
                "/api/container-control",
                json={"name": "nginx", "action": "stop"},
                headers=operator_headers,
            )
        assert resp.status_code == 404

    def test_admin_can_control(self, client, admin_headers):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.post(
                "/api/container-control",
                json={"name": "mycontainer", "action": "start"},
                headers=admin_headers,
            )
        assert resp.status_code == 200


# ===========================================================================
# GET /api/containers/{name}/logs
# ===========================================================================

class TestContainerLogs:
    """Stream container logs — operator auth required."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/containers/nginx/logs")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/containers/nginx/logs", headers=viewer_headers)
        assert resp.status_code == 403

    def test_invalid_name_returns_400(self, client, operator_headers):
        resp = client.get("/api/containers/bad name!/logs", headers=operator_headers)
        assert resp.status_code in (400, 404, 422)

    def test_success_returns_plain_text(self, client, operator_headers):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "log line 1\nlog line 2\n"
        mock_result.stderr = ""
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.get("/api/containers/nginx/logs", headers=operator_headers)
        assert resp.status_code == 200
        assert "log line" in resp.text

    def test_no_runtime_returns_404(self, client, operator_headers):
        with patch(
            "server.routers.containers.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            resp = client.get("/api/containers/nginx/logs", headers=operator_headers)
        assert resp.status_code == 404

    def test_lines_query_param_accepted(self, client, operator_headers):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output"
        mock_result.stderr = ""
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.get(
                "/api/containers/nginx/logs?lines=50", headers=operator_headers
            )
        assert resp.status_code == 200


# ===========================================================================
# GET /api/containers/{name}/inspect
# ===========================================================================

class TestContainerInspect:
    """Detailed container info — operator auth required."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/containers/nginx/inspect")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/containers/nginx/inspect", headers=viewer_headers)
        assert resp.status_code == 403

    def test_success_returns_container_fields(self, client, operator_headers):
        fake_inspect = json.dumps([{
            "Name": "/nginx",
            "Created": "2024-01-01T00:00:00Z",
            "RestartCount": 0,
            "Config": {"Image": "nginx:latest", "Env": ["PATH=/usr/bin"]},
            "HostConfig": {"Memory": 0, "CpuShares": 0, "RestartPolicy": {"Name": "always"}},
            "NetworkSettings": {"Ports": {}, "Networks": {}},
            "State": {"Status": "running", "StartedAt": "2024-01-01T00:01:00Z"},
            "Mounts": [],
        }])
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_inspect
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.get("/api/containers/nginx/inspect", headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "nginx"
        assert data["image"] == "nginx:latest"
        assert data["status"] == "running"
        assert "restart_policy" in data

    def test_no_runtime_returns_404(self, client, operator_headers):
        with patch(
            "server.routers.containers.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            resp = client.get("/api/containers/nginx/inspect", headers=operator_headers)
        assert resp.status_code == 404

    def test_env_vars_are_masked(self, client, operator_headers):
        fake_inspect = json.dumps([{
            "Name": "/app",
            "Created": "",
            "RestartCount": 0,
            "Config": {"Image": "app:latest", "Env": ["SECRET_KEY=supersecret", "DB_PASS=hunter2"]},
            "HostConfig": {"Memory": 0, "CpuShares": 0, "RestartPolicy": {"Name": "no"}},
            "NetworkSettings": {"Ports": {}, "Networks": {}},
            "State": {"Status": "running", "StartedAt": ""},
            "Mounts": [],
        }])
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_inspect
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.get("/api/containers/app/inspect", headers=operator_headers)
        assert resp.status_code == 200
        env = resp.json()["env"]
        assert all("***" in e for e in env)
        assert not any("supersecret" in e for e in env)
        assert not any("hunter2" in e for e in env)


# ===========================================================================
# GET /api/containers/stats
# ===========================================================================

class TestContainerStats:
    """Per-container resource usage — operator auth required."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/containers/stats")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with patch("server.routers.containers.subprocess.run", side_effect=FileNotFoundError):
            resp = client.get("/api/containers/stats", headers=viewer_headers)
        assert resp.status_code in (200, 404)

    def test_success_returns_list(self, client, operator_headers):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "nginx|0.5%|50MiB / 1GiB|5.0%|10kB / 20kB|1MB / 2MB|5\n"
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.get("/api/containers/stats", headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "nginx"
        assert data[0]["cpu"] == "0.5%"

    def test_no_runtime_returns_empty_list(self, client, operator_headers):
        with patch(
            "server.routers.containers.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            resp = client.get("/api/containers/stats", headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_admin_can_access(self, client, admin_headers):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.get("/api/containers/stats", headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# POST /api/containers/{name}/pull
# ===========================================================================

class TestContainerPull:
    """Pull latest image — admin auth required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/containers/nginx/pull")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/containers/nginx/pull", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/containers/nginx/pull", headers=operator_headers)
        assert resp.status_code == 403

    def test_invalid_name_returns_400(self, client, admin_headers):
        resp = client.post("/api/containers/bad name!/pull", headers=admin_headers)
        assert resp.status_code in (400, 404, 422)

    def test_success_returns_run_id(self, client, admin_headers):
        inspect_result = MagicMock()
        inspect_result.returncode = 0
        inspect_result.stdout = "nginx:latest\n"
        with patch("server.routers.containers.subprocess.run", return_value=inspect_result):
            resp = client.post("/api/containers/nginx/pull", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "run_id" in data
        assert data["image"] == "nginx:latest"

    def test_no_runtime_returns_404(self, client, admin_headers):
        with patch(
            "server.routers.containers.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            resp = client.post("/api/containers/nginx/pull", headers=admin_headers)
        assert resp.status_code == 404


# ===========================================================================
# GET /api/compose/projects
# ===========================================================================

class TestComposeProjects:
    """List compose projects — viewer auth required."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/compose/projects")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/compose/projects", headers=viewer_headers)
        assert resp.status_code == 200

    def test_success_returns_list(self, client, operator_headers):
        fake_projects = json.dumps([
            {"Name": "web", "Status": "running", "ConfigFiles": "/srv/web/docker-compose.yml"}
        ])
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_projects
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.get("/api/compose/projects", headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_docker_unavailable_returns_empty_list(self, client, operator_headers):
        with patch(
            "server.routers.containers.subprocess.run",
            side_effect=Exception("docker not found"),
        ):
            resp = client.get("/api/compose/projects", headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_admin_can_access(self, client, admin_headers):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[]"
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.get("/api/compose/projects", headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# POST /api/compose/{project}/{action}
# ===========================================================================

class TestComposeAction:
    """Compose project actions — operator auth required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/compose/myproject/up")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/compose/myproject/up", headers=viewer_headers)
        assert resp.status_code == 403

    def test_invalid_action_returns_400(self, client, operator_headers):
        resp = client.post("/api/compose/myproject/destroy", headers=operator_headers)
        assert resp.status_code == 400

    def test_invalid_project_name_returns_400(self, client, operator_headers):
        resp = client.post("/api/compose/bad project!/up", headers=operator_headers)
        assert resp.status_code in (400, 404, 422)

    def test_up_action_success(self, client, operator_headers):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Started\n"
        mock_result.stderr = ""
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.post("/api/compose/web/up", headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_down_action_success(self, client, operator_headers):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Stopped\n"
        mock_result.stderr = ""
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.post("/api/compose/web/down", headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_restart_action_success(self, client, operator_headers):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Restarted\n"
        mock_result.stderr = ""
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.post("/api/compose/web/restart", headers=operator_headers)
        assert resp.status_code == 200

    def test_pull_action_success(self, client, operator_headers):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Pulled\n"
        mock_result.stderr = ""
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.post("/api/compose/web/pull", headers=operator_headers)
        assert resp.status_code == 200

    def test_failed_action_returns_success_false(self, client, operator_headers):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error: no such project"
        with patch("server.routers.containers.subprocess.run", return_value=mock_result):
            resp = client.post("/api/compose/missing/up", headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ===========================================================================
# POST /api/truenas/vm
# ===========================================================================

class TestTruenasVM:
    """TrueNAS VM control — operator auth required, TrueNAS must be configured."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/truenas/vm", json={"id": 1, "action": "start"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/truenas/vm",
            json={"id": 1, "action": "start"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_invalid_vm_id_returns_400(self, client, operator_headers):
        resp = client.post(
            "/api/truenas/vm",
            json={"id": "not-a-number", "action": "start"},
            headers=operator_headers,
        )
        assert resp.status_code == 400

    def test_invalid_action_returns_400(self, client, operator_headers):
        resp = client.post(
            "/api/truenas/vm",
            json={"id": 1, "action": "explode"},
            headers=operator_headers,
        )
        assert resp.status_code == 400

    def test_truenas_not_configured_returns_400(self, client, operator_headers):
        with patch(
            "server.routers.containers.read_yaml_settings",
            return_value={"truenasUrl": "", "truenasKey": ""},
        ):
            resp = client.post(
                "/api/truenas/vm",
                json={"id": 1, "action": "start"},
                headers=operator_headers,
            )
        assert resp.status_code == 400

    def test_truenas_api_failure_returns_502(self, client, operator_headers):
        with patch(
            "server.routers.containers.read_yaml_settings",
            return_value={"truenasUrl": "http://truenas.local", "truenasKey": "abc123"},
        ):
            with patch(
                "urllib.request.urlopen",
                side_effect=Exception("connection refused"),
            ):
                resp = client.post(
                    "/api/truenas/vm",
                    json={"id": 1, "action": "start"},
                    headers=operator_headers,
                )
        assert resp.status_code == 502

    def test_admin_can_control_vm(self, client, admin_headers):
        with patch(
            "server.routers.containers.read_yaml_settings",
            return_value={"truenasUrl": "", "truenasKey": ""},
        ):
            resp = client.post(
                "/api/truenas/vm",
                json={"id": 1, "action": "start"},
                headers=admin_headers,
            )
        assert resp.status_code == 400  # not configured, but auth passed
