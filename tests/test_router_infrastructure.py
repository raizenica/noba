# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for the infrastructure router (share/noba-web/server/routers/infrastructure.py)."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proc(returncode=0, stdout=b"", stderr=b""):
    """Return a minimal subprocess.CompletedProcess-like mock."""
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def _make_httpx_response(status_code=200, json_data=None, text=""):
    """Return a minimal httpx.Response-like mock."""
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data if json_data is not None else {}
    r.text = text
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        from httpx import HTTPStatusError
        r.raise_for_status.side_effect = HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=r
        )
    return r


def _seed_agent(hostname: str = "testhost") -> None:
    """Seed an agent directly into the in-memory store."""
    from server.agent_store import _agent_data, _agent_data_lock

    with _agent_data_lock:
        _agent_data[hostname] = {"hostname": hostname, "_received": time.time()}


_K8S_SETTINGS = {
    "k8sUrl": "https://k8s.local:6443",
    "k8sToken": "test-token-abc",
}

_PMX_SETTINGS = {
    "proxmoxUrl": "https://pve.local:8006",
    "proxmoxUser": "root",
    "proxmoxTokenName": "noba",
    "proxmoxTokenValue": "secret-uuid",
}


# ===========================================================================
# POST /api/service-control  (operator required)
# ===========================================================================

class TestServiceControl:
    """POST /api/service-control — operator auth, subprocess mocked."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/service-control",
                           json={"service": "nginx", "action": "restart"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/service-control",
                           json={"service": "nginx", "action": "restart"},
                           headers=viewer_headers)
        assert resp.status_code == 403

    def test_invalid_action_returns_400(self, client, operator_headers):
        resp = client.post("/api/service-control",
                           json={"service": "nginx", "action": "kill"},
                           headers=operator_headers)
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"]

    def test_invalid_service_name_returns_400(self, client, operator_headers):
        resp = client.post("/api/service-control",
                           json={"service": "../etc/passwd", "action": "restart"},
                           headers=operator_headers)
        assert resp.status_code == 400
        assert "Invalid service name" in resp.json()["detail"]

    def test_empty_service_returns_400(self, client, operator_headers):
        resp = client.post("/api/service-control",
                           json={"service": "", "action": "start"},
                           headers=operator_headers)
        assert resp.status_code == 400

    def test_operator_success_system_service(self, client, operator_headers):
        with patch("server.routers.infrastructure.subprocess.run",
                   return_value=_make_proc(0)) as mock_run:
            resp = client.post("/api/service-control",
                               json={"service": "nginx", "action": "restart"},
                               headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        cmd = mock_run.call_args[0][0]
        assert "sudo" in cmd
        assert "nginx" in cmd
        assert "restart" in cmd

    def test_operator_user_service_flag(self, client, operator_headers):
        with patch("server.routers.infrastructure.subprocess.run",
                   return_value=_make_proc(0)) as mock_run:
            resp = client.post("/api/service-control",
                               json={"service": "myapp", "action": "start", "is_user": True},
                               headers=operator_headers)
        assert resp.status_code == 200
        cmd = mock_run.call_args[0][0]
        assert "--user" in cmd
        assert "sudo" not in cmd

    def test_subprocess_nonzero_returns_422(self, client, operator_headers):
        with patch("server.routers.infrastructure.subprocess.run",
                   return_value=_make_proc(1, b"", b"Unit not found")):
            resp = client.post("/api/service-control",
                               json={"service": "ghost", "action": "stop"},
                               headers=operator_headers)
        assert resp.status_code == 422

    def test_subprocess_exception_returns_500(self, client, operator_headers):
        with patch("server.routers.infrastructure.subprocess.run",
                   side_effect=OSError("no systemctl")):
            resp = client.post("/api/service-control",
                               json={"service": "nginx", "action": "restart"},
                               headers=operator_headers)
        assert resp.status_code == 500

    def test_admin_can_also_control_services(self, client, admin_headers):
        with patch("server.routers.infrastructure.subprocess.run",
                   return_value=_make_proc(0)):
            resp = client.post("/api/service-control",
                               json={"service": "docker", "action": "start"},
                               headers=admin_headers)
        assert resp.status_code == 200

    def test_all_allowed_actions(self, client, operator_headers):
        for action in ("start", "stop", "restart", "poweroff"):
            with patch("server.routers.infrastructure.subprocess.run",
                       return_value=_make_proc(0)):
                resp = client.post("/api/service-control",
                                   json={"service": "nginx", "action": action},
                                   headers=operator_headers)
            assert resp.status_code == 200, f"action={action} failed"


# ===========================================================================
# GET /api/network/connections  (operator required)
# ===========================================================================

class TestNetworkConnections:
    """GET /api/network/connections — mocks get_network_connections."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/network/connections")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/network/connections", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_200(self, client, operator_headers):
        fake = [{"laddr": "0.0.0.0:80", "raddr": "1.2.3.4:54321", "status": "ESTABLISHED"}]
        with patch("server.routers.infrastructure.get_network_connections",
                   return_value=fake):
            resp = client.get("/api/network/connections", headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["status"] == "ESTABLISHED"

    def test_admin_returns_200(self, client, admin_headers):
        with patch("server.routers.infrastructure.get_network_connections",
                   return_value=[]):
            resp = client.get("/api/network/connections", headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/network/ports  (user auth)
# ===========================================================================

class TestNetworkPorts:
    """GET /api/network/ports — mocks get_listening_ports."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/network/ports")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/network/ports", headers=viewer_headers)
        assert resp.status_code == 403

    def test_returns_port_list(self, client, operator_headers):
        fake = [{"port": 22, "proto": "tcp", "pid": 1234, "process": "sshd"}]
        with patch("server.routers.infrastructure.get_listening_ports",
                   return_value=fake):
            resp = client.get("/api/network/ports", headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["port"] == 22


# ===========================================================================
# GET /api/network/interfaces  (user auth)
# ===========================================================================

class TestNetworkInterfaces:
    """GET /api/network/interfaces — mocks psutil."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/network/interfaces")
        assert resp.status_code == 401

    def test_viewer_returns_200(self, client, viewer_headers):
        fake_addr = MagicMock()
        fake_addr.family = MagicMock()
        fake_addr.family.name = "AF_INET"
        fake_addr.address = "192.168.1.10"

        fake_stat = MagicMock()
        fake_stat.isup = True
        fake_stat.speed = 1000
        fake_stat.mtu = 1500

        fake_psutil = MagicMock()
        fake_psutil.net_if_addrs.return_value = {"eth0": [fake_addr]}
        fake_psutil.net_if_stats.return_value = {"eth0": fake_stat}

        with patch.dict("sys.modules", {"psutil": fake_psutil}):
            with patch("server.routers.infrastructure.subprocess.run",
                       return_value=_make_proc(0)):
                resp = client.get("/api/network/interfaces", headers=viewer_headers)
        assert resp.status_code == 200

    def test_loopback_excluded(self, client, admin_headers):
        fake_addr = MagicMock()
        fake_addr.family = MagicMock()
        fake_addr.family.name = "AF_INET"
        fake_addr.address = "127.0.0.1"

        fake_psutil = MagicMock()
        fake_psutil.net_if_addrs.return_value = {"lo": [fake_addr]}
        fake_psutil.net_if_stats.return_value = {}

        with patch.dict("sys.modules", {"psutil": fake_psutil}):
            resp = client.get("/api/network/interfaces", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert all(iface["name"] != "lo" for iface in data)


# ===========================================================================
# GET /api/services/map  (user auth)
# ===========================================================================

class TestServicesMap:
    """GET /api/services/map — builds dependency graph."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/services/map")
        assert resp.status_code == 401

    def test_viewer_returns_200_with_noba_node(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value={}):
            resp = client.get("/api/services/map", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        node_ids = [n["id"] for n in data["nodes"]]
        assert "noba" in node_ids

    def test_configured_integrations_add_nodes(self, client, admin_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value={"proxmoxUrl": "https://pve.local:8006",
                                 "k8sUrl": "https://k8s.local:6443"}):
            resp = client.get("/api/services/map", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        node_ids = [n["id"] for n in data["nodes"]]
        assert "proxmox" in node_ids
        assert "k8s" in node_ids

    def test_empty_config_returns_only_noba(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value={}):
            resp = client.get("/api/services/map", headers=viewer_headers)
        data = resp.json()
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["id"] == "noba"


# ===========================================================================
# GET /api/disks/prediction  (user auth)
# ===========================================================================

_DISK_MOCK_RESULT = {
    "metrics": {
        "disk_percent": {
            "regression": {"slope": 0.0001, "intercept": 40.0, "r_squared": 0.9},
            "seasonal": None,
            "projection": [],
            "residual_std": 0.5,
        }
    },
    "combined": {
        "full_at": "2026-06-01T00:00:00+00:00",
        "primary_metric": "disk_percent",
        "r_squared": 0.9,
        "confidence": "high",
        "slope_per_day": 8.64,
    },
}


class TestDiskPrediction:
    """GET /api/disks/prediction — returns predict_capacity shape."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/disks/prediction")
        assert resp.status_code == 401

    def test_viewer_returns_200_with_metrics_and_combined(self, client, viewer_headers):
        with patch("server.prediction.predict_capacity", return_value=_DISK_MOCK_RESULT):
            resp = client.get("/api/disks/prediction", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "metrics" in data
        assert "combined" in data

    def test_disk_data_returns_prediction_fields(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_DISK_MOCK_RESULT):
            resp = client.get("/api/disks/prediction", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "disk_percent" in data["metrics"]
        assert "confidence" in data["combined"]
        assert "full_at" in data["combined"]


# ===========================================================================
# K8s routes
# ===========================================================================

class TestK8sNotConfigured:
    """K8s endpoints return 400 when not configured."""

    def test_namespaces_not_configured(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value={}):
            resp = client.get("/api/k8s/namespaces", headers=viewer_headers)
        assert resp.status_code == 400
        assert "not configured" in resp.json()["detail"]

    def test_pods_not_configured(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value={}):
            resp = client.get("/api/k8s/pods", headers=viewer_headers)
        assert resp.status_code == 400

    def test_deployments_not_configured(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value={}):
            resp = client.get("/api/k8s/deployments", headers=viewer_headers)
        assert resp.status_code == 400

    def test_pod_logs_not_configured(self, client, operator_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value={}):
            resp = client.get("/api/k8s/pods/default/mypod/logs",
                              headers=operator_headers)
        assert resp.status_code == 400

    def test_scale_not_configured(self, client, admin_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value={}):
            resp = client.post(
                "/api/k8s/deployments/default/myapp/scale",
                json={"replicas": 2},
                headers=admin_headers,
            )
        assert resp.status_code == 400


class TestK8sNamespaces:
    """GET /api/k8s/namespaces."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/k8s/namespaces")
        assert resp.status_code == 401

    def test_success(self, client, viewer_headers):
        fake_resp = _make_httpx_response(200, {
            "items": [
                {"metadata": {"name": "default", "creationTimestamp": "2024-01-01"},
                 "status": {"phase": "Active"}},
            ]
        })
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            with patch("httpx.get", return_value=fake_resp):
                resp = client.get("/api/k8s/namespaces", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["name"] == "default"
        assert data[0]["status"] == "Active"

    def test_httpx_error_returns_502(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            with patch("httpx.get", side_effect=Exception("timeout")):
                resp = client.get("/api/k8s/namespaces", headers=viewer_headers)
        assert resp.status_code == 502
        assert "K8s API error" in resp.json()["detail"]


class TestK8sPods:
    """GET /api/k8s/pods."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/k8s/pods")
        assert resp.status_code == 401

    def test_success_all_namespaces(self, client, viewer_headers):
        fake_pod = {
            "metadata": {"name": "mypod", "namespace": "default",
                         "creationTimestamp": "2024-01-01"},
            "spec": {"nodeName": "node1"},
            "status": {"phase": "Running", "podIP": "10.0.0.5",
                       "containerStatuses": []},
        }
        fake_resp = _make_httpx_response(200, {"items": [fake_pod]})
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            with patch("httpx.get", return_value=fake_resp):
                resp = client.get("/api/k8s/pods", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["name"] == "mypod"
        assert data[0]["phase"] == "Running"

    def test_namespace_filter_uses_namespaced_path(self, client, viewer_headers):
        fake_resp = _make_httpx_response(200, {"items": []})
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            with patch("httpx.get", return_value=fake_resp) as mock_get:
                client.get("/api/k8s/pods?namespace=kube-system",
                           headers=viewer_headers)
        call_url = mock_get.call_args[0][0]
        assert "kube-system" in call_url

    def test_httpx_error_returns_502(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            with patch("httpx.get", side_effect=Exception("conn refused")):
                resp = client.get("/api/k8s/pods", headers=viewer_headers)
        assert resp.status_code == 502


class TestK8sPodLogs:
    """GET /api/k8s/pods/{ns}/{name}/logs — operator required."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/k8s/pods/default/mypod/logs")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            resp = client.get("/api/k8s/pods/default/mypod/logs",
                              headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_success(self, client, operator_headers):
        fake_resp = _make_httpx_response(200, text="log line 1\nlog line 2\n")
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            with patch("httpx.get", return_value=fake_resp):
                resp = client.get("/api/k8s/pods/default/mypod/logs",
                                  headers=operator_headers)
        assert resp.status_code == 200
        assert "log line" in resp.text

    def test_container_param_appended_to_path(self, client, operator_headers):
        fake_resp = _make_httpx_response(200, text="")
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            with patch("httpx.get", return_value=fake_resp) as mock_get:
                client.get(
                    "/api/k8s/pods/default/mypod/logs?container=mycontainer",
                    headers=operator_headers,
                )
        call_url = mock_get.call_args[0][0]
        assert "mycontainer" in call_url

    def test_httpx_error_returns_502(self, client, operator_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            with patch("httpx.get", side_effect=Exception("timeout")):
                resp = client.get("/api/k8s/pods/default/mypod/logs",
                                  headers=operator_headers)
        assert resp.status_code == 502


class TestK8sDeployments:
    """GET /api/k8s/deployments."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/k8s/deployments")
        assert resp.status_code == 401

    def test_success(self, client, viewer_headers):
        fake_deploy = {
            "metadata": {"name": "myapp", "namespace": "default"},
            "spec": {"replicas": 3},
            "status": {"readyReplicas": 3, "availableReplicas": 3, "updatedReplicas": 3},
        }
        fake_resp = _make_httpx_response(200, {"items": [fake_deploy]})
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            with patch("httpx.get", return_value=fake_resp):
                resp = client.get("/api/k8s/deployments", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["name"] == "myapp"
        assert data[0]["replicas"] == 3

    def test_namespace_filter(self, client, viewer_headers):
        fake_resp = _make_httpx_response(200, {"items": []})
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            with patch("httpx.get", return_value=fake_resp) as mock_get:
                client.get("/api/k8s/deployments?namespace=prod",
                           headers=viewer_headers)
        call_url = mock_get.call_args[0][0]
        assert "prod" in call_url

    def test_httpx_error_returns_502(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            with patch("httpx.get", side_effect=Exception("error")):
                resp = client.get("/api/k8s/deployments", headers=viewer_headers)
        assert resp.status_code == 502


class TestK8sScale:
    """POST /api/k8s/deployments/{ns}/{name}/scale — admin required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/k8s/deployments/default/myapp/scale",
                           json={"replicas": 2})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            resp = client.post(
                "/api/k8s/deployments/default/myapp/scale",
                json={"replicas": 2},
                headers=viewer_headers,
            )
        assert resp.status_code == 403

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            resp = client.post(
                "/api/k8s/deployments/default/myapp/scale",
                json={"replicas": 2},
                headers=operator_headers,
            )
        assert resp.status_code != 403

    def test_admin_success(self, client, admin_headers):
        fake_resp = _make_httpx_response(200, {"spec": {"replicas": 2}})
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            with patch("httpx.patch", return_value=fake_resp):
                resp = client.post(
                    "/api/k8s/deployments/default/myapp/scale",
                    json={"replicas": 2},
                    headers=admin_headers,
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["replicas"] == 2

    def test_out_of_range_replicas_returns_400(self, client, admin_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            resp = client.post(
                "/api/k8s/deployments/default/myapp/scale",
                json={"replicas": 200},
                headers=admin_headers,
            )
        assert resp.status_code == 400

    def test_negative_replicas_returns_400(self, client, admin_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            resp = client.post(
                "/api/k8s/deployments/default/myapp/scale",
                json={"replicas": -1},
                headers=admin_headers,
            )
        assert resp.status_code == 400

    def test_httpx_error_returns_502(self, client, admin_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_K8S_SETTINGS):
            with patch("httpx.patch", side_effect=Exception("timeout")):
                resp = client.post(
                    "/api/k8s/deployments/default/myapp/scale",
                    json={"replicas": 1},
                    headers=admin_headers,
                )
        assert resp.status_code == 502


# ===========================================================================
# Proxmox routes
# ===========================================================================

class TestProxmoxNotConfigured:
    """Proxmox endpoints return 400 when not configured."""

    def test_snapshots_not_configured(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value={}):
            resp = client.get("/api/proxmox/nodes/pve1/vms/100/snapshots",
                              headers=viewer_headers)
        assert resp.status_code == 400
        assert "not configured" in resp.json()["detail"]

    def test_create_snapshot_not_configured(self, client, admin_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value={}):
            resp = client.post("/api/proxmox/nodes/pve1/vms/100/snapshot",
                               json={"name": "snap1"},
                               headers=admin_headers)
        assert resp.status_code == 400

    def test_console_not_configured(self, client, operator_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value={}):
            resp = client.get("/api/proxmox/nodes/pve1/vms/100/console",
                              headers=operator_headers)
        assert resp.status_code == 400


class TestProxmoxSnapshots:
    """GET /api/proxmox/nodes/{node}/vms/{vmid}/snapshots."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/proxmox/nodes/pve1/vms/100/snapshots")
        assert resp.status_code == 401

    def test_success(self, client, viewer_headers):
        fake_resp = _make_httpx_response(200, {
            "data": [
                {"name": "clean", "description": "initial",
                 "snaptime": 1700000000, "parent": ""},
            ]
        })
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_PMX_SETTINGS):
            with patch("httpx.get", return_value=fake_resp):
                resp = client.get("/api/proxmox/nodes/pve1/vms/100/snapshots",
                                  headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["name"] == "clean"
        assert data[0]["snaptime"] == 1700000000

    def test_type_param_used_in_url(self, client, viewer_headers):
        fake_resp = _make_httpx_response(200, {"data": []})
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_PMX_SETTINGS):
            with patch("httpx.get", return_value=fake_resp) as mock_get:
                client.get("/api/proxmox/nodes/pve1/vms/100/snapshots?type=lxc",
                           headers=viewer_headers)
        call_url = mock_get.call_args[0][0]
        assert "lxc" in call_url

    def test_httpx_error_returns_502(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_PMX_SETTINGS):
            with patch("httpx.get", side_effect=Exception("conn refused")):
                resp = client.get("/api/proxmox/nodes/pve1/vms/100/snapshots",
                                  headers=viewer_headers)
        assert resp.status_code == 502


class TestProxmoxCreateSnapshot:
    """POST /api/proxmox/nodes/{node}/vms/{vmid}/snapshot — admin required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/proxmox/nodes/pve1/vms/100/snapshot",
                           json={"name": "snap1"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_PMX_SETTINGS):
            resp = client.post("/api/proxmox/nodes/pve1/vms/100/snapshot",
                               json={"name": "snap1"},
                               headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_PMX_SETTINGS):
            resp = client.post("/api/proxmox/nodes/pve1/vms/100/snapshot",
                               json={"name": "snap1"},
                               headers=operator_headers)
        assert resp.status_code == 403

    def test_invalid_snapshot_name_returns_400(self, client, admin_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_PMX_SETTINGS):
            resp = client.post("/api/proxmox/nodes/pve1/vms/100/snapshot",
                               json={"name": "bad name!"},
                               headers=admin_headers)
        assert resp.status_code == 400
        assert "Invalid snapshot name" in resp.json()["detail"]

    def test_empty_name_returns_400(self, client, admin_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_PMX_SETTINGS):
            resp = client.post("/api/proxmox/nodes/pve1/vms/100/snapshot",
                               json={"name": ""},
                               headers=admin_headers)
        assert resp.status_code == 400

    def test_admin_success(self, client, admin_headers):
        fake_resp = _make_httpx_response(200, {"data": "UPID:pve1:001:snap"})
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_PMX_SETTINGS):
            with patch("httpx.post", return_value=fake_resp):
                resp = client.post(
                    "/api/proxmox/nodes/pve1/vms/100/snapshot",
                    json={"name": "mysnap", "description": "test snapshot"},
                    headers=admin_headers,
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "task" in data

    def test_httpx_error_returns_502(self, client, admin_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_PMX_SETTINGS):
            with patch("httpx.post", side_effect=Exception("timeout")):
                resp = client.post(
                    "/api/proxmox/nodes/pve1/vms/100/snapshot",
                    json={"name": "mysnap"},
                    headers=admin_headers,
                )
        assert resp.status_code == 502


class TestProxmoxConsole:
    """GET /api/proxmox/nodes/{node}/vms/{vmid}/console — operator required."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/proxmox/nodes/pve1/vms/100/console")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_PMX_SETTINGS):
            resp = client.get("/api/proxmox/nodes/pve1/vms/100/console",
                              headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_console_url(self, client, operator_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_PMX_SETTINGS):
            resp = client.get("/api/proxmox/nodes/pve1/vms/100/console",
                              headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "url" in data
        assert "pve.local" in data["url"]
        assert "100" in data["url"]
        assert "pve1" in data["url"]

    def test_lxc_type_in_url(self, client, operator_headers):
        with patch("server.routers.infrastructure.read_yaml_settings",
                   return_value=_PMX_SETTINGS):
            resp = client.get(
                "/api/proxmox/nodes/pve1/vms/100/console?type=lxc",
                headers=operator_headers,
            )
        assert resp.status_code == 200
        assert "lxc" in resp.json()["url"]


# ===========================================================================
# Network discovery endpoints
# ===========================================================================

class TestNetworkDevices:
    """GET /api/network/devices — DB-backed, user auth."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/network/devices")
        assert resp.status_code == 401

    def test_viewer_returns_200_list(self, client, viewer_headers):
        resp = client.get("/api/network/devices", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_operator_returns_200(self, client, operator_headers):
        resp = client.get("/api/network/devices", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_returns_200(self, client, admin_headers):
        resp = client.get("/api/network/devices", headers=admin_headers)
        assert resp.status_code == 200


class TestNetworkDiscover:
    """POST /api/network/discover/{hostname} — operator required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/network/discover/myhost")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/network/discover/myhost", headers=viewer_headers)
        assert resp.status_code == 403

    def test_unknown_agent_returns_404(self, client, operator_headers):
        # _clean_agent_state (autouse) ensures store is empty
        resp = client.post("/api/network/discover/nonexistent-host",
                           headers=operator_headers)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_known_agent_queues_command(self, client, operator_headers):
        _seed_agent("discover-host")
        resp = client.post("/api/network/discover/discover-host",
                           headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("sent", "queued")
        assert "id" in data

    def test_response_has_websocket_field(self, client, operator_headers):
        _seed_agent("ws-host")
        resp = client.post("/api/network/discover/ws-host",
                           headers=operator_headers)
        assert resp.status_code == 200
        assert "websocket" in resp.json()

    def test_admin_can_also_discover(self, client, admin_headers):
        _seed_agent("admin-host")
        resp = client.post("/api/network/discover/admin-host",
                           headers=admin_headers)
        assert resp.status_code == 200


class TestDeleteNetworkDevice:
    """DELETE /api/network/devices/{id} — operator required."""

    def test_no_auth_returns_401(self, client):
        resp = client.delete("/api/network/devices/1")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.delete("/api/network/devices/1", headers=viewer_headers)
        assert resp.status_code == 403

    def test_nonexistent_device_returns_404(self, client, operator_headers):
        resp = client.delete("/api/network/devices/999999",
                             headers=operator_headers)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_admin_nonexistent_also_404(self, client, admin_headers):
        resp = client.delete("/api/network/devices/888888",
                             headers=admin_headers)
        assert resp.status_code == 404

    def test_operator_delete_success(self, client, operator_headers):
        with patch("server.routers.infrastructure.db") as mock_db:
            mock_db.delete_network_device.return_value = True
            mock_db.audit_log = MagicMock()
            resp = client.delete("/api/network/devices/42",
                                 headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_db.delete_network_device.assert_called_once_with(42)
