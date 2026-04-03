# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Infrastructure management: network, K8s, Proxmox, services, terminal."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import subprocess
import time

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import PlainTextResponse

from .. import deps as _deps
from ..deps import handle_errors
from ..agent_config import RISK_LEVELS, check_role_permission
from ..agent_store import (
    _agent_cmd_lock, _agent_commands,
    _agent_data, _agent_data_lock, _agent_websockets, _agent_ws_lock,
)
from ..config import ALLOWED_ACTIONS
from ..deps import (
    _client_ip, _get_auth, _int_param, _read_body,
    _require_admin, _require_operator, db, ws_token_store,
)
from ..metrics import get_listening_ports, get_network_connections, strip_ansi, validate_service_name
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

router = APIRouter(tags=["infrastructure"])


def _k8s_verify(cfg: dict) -> str | bool:
    """Get the TLS verify setting for K8s API calls."""
    v = cfg.get("k8sVerifySsl", True)
    if isinstance(v, str) and os.path.isfile(v):
        return v  # CA bundle path
    return bool(v) if not isinstance(v, str) else v.lower() not in ("", "0", "false", "no")


def _pmx_verify(cfg: dict) -> str | bool:
    """Get the TLS verify setting for Proxmox API calls."""
    v = cfg.get("proxmoxVerifySsl", True)
    if isinstance(v, str) and os.path.isfile(v):
        return v
    return bool(v) if not isinstance(v, str) else v.lower() not in ("", "0", "false", "no")


def _validate_k8s_name(val: str, label: str = "name") -> str:
    """Validate a Kubernetes resource name or namespace to prevent path injection."""
    if not val or not re.match(r'^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$', val) or '/' in val or '..' in val:
        raise HTTPException(400, f"Invalid Kubernetes {label}: {val}")
    return val


# ── /api/service-control ──────────────────────────────────────────────────────
@router.post("/api/service-control")
@handle_errors
async def api_service_control(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    svc        = body.get("service", "").strip()
    action     = body.get("action",  "").strip()
    is_user_v  = body.get("is_user", False)
    is_user    = is_user_v is True or str(is_user_v).lower() in ("true", "1", "yes", "t", "y")
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(400, f'Action "{action}" not allowed')
    if not svc or not validate_service_name(svc):
        raise HTTPException(400, "Invalid service name")
    cmd = (["systemctl", "--user", action, svc] if is_user
           else ["sudo", "-n", "systemctl", "--no-ask-password", action, svc])
    try:
        r = await asyncio.to_thread(subprocess.run, cmd, timeout=10, capture_output=True)
        success = r.returncode == 0
        db.audit_log("service_control", username, f"{action} {svc} (user={is_user}) -> {success}", ip)
        if not success:
            stderr = strip_ansi(r.stderr.decode().strip())
            raise HTTPException(422, stderr or f"systemctl {action} {svc} failed")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Service control error: %s", e)
        db.audit_log("service_control", username, f"{action} {svc} failed: {e}", ip)
        raise HTTPException(500, "Service control error") from None


# ── Network analysis ─────────────────────────────────────────────────────────
@router.get("/api/network/connections")
@handle_errors
def api_network_connections(auth=Depends(_require_operator)):
    """List active network connections."""
    return get_network_connections()


@router.get("/api/network/ports")
@handle_errors
def api_network_ports(auth=Depends(_require_operator)):
    """List listening ports with process info."""
    return get_listening_ports()


@router.get("/api/network/interfaces")
@handle_errors
def api_network_interfaces(auth=Depends(_get_auth)):
    """Get network interface details."""
    import psutil as _psutil
    interfaces = []
    addrs = _psutil.net_if_addrs()
    stats = _psutil.net_if_stats()
    for name, addr_list in addrs.items():
        if name == "lo":
            continue
        stat = stats.get(name)
        ips = [a.address for a in addr_list if a.family.name == "AF_INET"]
        interfaces.append({
            "name": name,
            "ip": ips[0] if ips else "",
            "up": stat.isup if stat else False,
            "speed": stat.speed if stat else 0,
            "mtu": stat.mtu if stat else 0,
        })
    return interfaces


# ── Service dependency map ───────────────────────────────────────────────────
@router.get("/api/services/map")
@handle_errors
def api_service_map(auth=Depends(_get_auth)):
    """Build a service dependency map from network connections and configured integrations."""
    stats = _deps.bg_collector.get() or {}
    cfg = read_yaml_settings()

    nodes = []
    edges = []

    nodes.append({"id": "noba", "label": "NOBA", "type": "core", "status": "online"})

    integration_map = {
        "piholeUrl": ("pihole", "Pi-hole", "dns"),
        "plexUrl": ("plex", "Plex", "media"),
        "jellyfinUrl": ("jellyfin", "Jellyfin", "media"),
        "truenasUrl": ("truenas", "TrueNAS", "storage"),
        "proxmoxUrl": ("proxmox", "Proxmox", "infra"),
        "hassUrl": ("hass", "Home Assistant", "automation"),
        "unifiUrl": ("unifi", "UniFi", "network"),
        "kumaUrl": ("kuma", "Uptime Kuma", "monitoring"),
        "radarrUrl": ("radarr", "Radarr", "media"),
        "sonarrUrl": ("sonarr", "Sonarr", "media"),
        "qbitUrl": ("qbit", "qBittorrent", "media"),
        "tautulliUrl": ("tautulli", "Tautulli", "media"),
        "overseerrUrl": ("overseerr", "Overseerr", "media"),
        "nextcloudUrl": ("nextcloud", "Nextcloud", "storage"),
        "traefikUrl": ("traefik", "Traefik", "network"),
        "k8sUrl": ("k8s", "Kubernetes", "infra"),
        "giteaUrl": ("gitea", "Gitea", "dev"),
        "gitlabUrl": ("gitlab", "GitLab", "dev"),
        "paperlessUrl": ("paperless", "Paperless", "docs"),
        "adguardUrl": ("adguard", "AdGuard", "dns"),
    }

    # Core node health from local system stats
    nodes[0]["cpu"] = round(stats.get("cpuPercent", 0), 1)
    nodes[0]["mem"] = round(stats.get("memPercent", 0))
    nodes[0]["uptime"] = stats.get("uptime", "")

    for cfg_key, (node_id, label, category) in integration_map.items():
        url = cfg.get(cfg_key, "")
        if url:
            data = stats.get(node_id)
            status = "online" if data and (isinstance(data, dict) and data.get("status") == "online") else "configured"
            node = {"id": node_id, "label": label, "type": category, "status": status}
            if isinstance(data, dict):
                if "cpu" in data:
                    node["cpu"] = round(data["cpu"], 1)
                if "memory" in data:
                    node["mem"] = round(data["memory"])
                elif "mem" in data:
                    node["mem"] = round(data["mem"])
                if "version" in data:
                    node["version"] = data["version"]
            nodes.append(node)
            edges.append({"from": "noba", "to": node_id})

    for svc in stats.get("services", []):
        sid = f"svc_{svc['name']}"
        nodes.append({"id": sid, "label": svc["name"], "type": "service", "status": svc.get("status", "unknown")})
        edges.append({"from": "noba", "to": sid})

    return {"nodes": nodes, "edges": edges}


# ── Disk usage prediction ────────────────────────────────────────────────────
@router.get("/api/disks/prediction")
@handle_errors
def api_disk_prediction(request: Request, auth=Depends(_get_auth)):
    """Disk capacity prediction with confidence intervals."""
    from ..prediction import predict_capacity
    try:
        result = predict_capacity(["disk_percent"], range_hours=168, projection_hours=720)
        return result
    except HTTPException:
        raise
    except Exception:
        # Fallback to simple trend, normalized to match predict_capacity shape
        trend = db.get_trend("disk_percent", range_hours=168, projection_hours=720)
        return {
            "metrics": {"disk_percent": {"regression": {"slope": trend.get("slope", 0), "r_squared": trend.get("r_squared", 0)}, "projection": trend.get("projection", [])}},
            "combined": {"full_at": trend.get("full_at"), "confidence": "low", "primary_metric": "disk_percent"},
        }


# ── Kubernetes deep management ───────────────────────────────────────────
@router.get("/api/k8s/namespaces")
@handle_errors
def api_k8s_namespaces(auth=Depends(_get_auth)):
    """List Kubernetes namespaces."""
    cfg = read_yaml_settings()
    url, token = cfg.get("k8sUrl", ""), cfg.get("k8sToken", "")
    if not url or not token:
        raise HTTPException(400, "Kubernetes not configured")
    import httpx as _httpx
    try:
        r = _httpx.get(f"{url.rstrip('/')}/api/v1/namespaces",
                      headers={"Authorization": f"Bearer {token}"}, verify=_k8s_verify(cfg), timeout=10)
        r.raise_for_status()
        items = r.json().get("items", [])
        return [{"name": ns.get("metadata", {}).get("name", ""),
                 "status": ns.get("status", {}).get("phase", ""),
                 "created": ns.get("metadata", {}).get("creationTimestamp", "")}
                for ns in items]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("K8s API error: %s", e)
        raise HTTPException(502, "K8s API error") from None


@router.get("/api/k8s/pods")
@handle_errors
def api_k8s_pods(request: Request, auth=Depends(_get_auth)):
    """List pods with details, optionally filtered by namespace."""
    cfg = read_yaml_settings()
    url, token = cfg.get("k8sUrl", ""), cfg.get("k8sToken", "")
    if not url or not token:
        raise HTTPException(400, "Kubernetes not configured")
    namespace = request.query_params.get("namespace", "")
    if namespace:
        namespace = _validate_k8s_name(namespace, "namespace")
    path = f"/api/v1/namespaces/{namespace}/pods" if namespace else "/api/v1/pods"
    import httpx as _httpx
    try:
        r = _httpx.get(f"{url.rstrip('/')}{path}",
                      headers={"Authorization": f"Bearer {token}"}, verify=_k8s_verify(cfg), timeout=10)
        r.raise_for_status()
        items = r.json().get("items", [])
        pods = []
        for pod in items[:200]:
            meta = pod.get("metadata", {})
            spec = pod.get("spec", {})
            status = pod.get("status", {})
            containers = []
            for cs in status.get("containerStatuses", []):
                containers.append({
                    "name": cs.get("name", ""),
                    "ready": cs.get("ready", False),
                    "restarts": cs.get("restartCount", 0),
                    "state": list(cs.get("state", {}).keys())[0] if cs.get("state") else "unknown",
                    "image": cs.get("image", ""),
                })
            pods.append({
                "name": meta.get("name", ""),
                "namespace": meta.get("namespace", ""),
                "node": spec.get("nodeName", ""),
                "phase": status.get("phase", ""),
                "ip": status.get("podIP", ""),
                "created": meta.get("creationTimestamp", ""),
                "containers": containers,
            })
        return pods
    except HTTPException:
        raise
    except Exception as e:
        logger.error("K8s API error: %s", e)
        raise HTTPException(502, "K8s API error") from None


@router.get("/api/k8s/pods/{namespace}/{name}/logs")
@handle_errors
def api_k8s_pod_logs(namespace: str, name: str, request: Request, auth=Depends(_require_operator)):
    """Get pod logs."""
    namespace = _validate_k8s_name(namespace, "namespace")
    name = _validate_k8s_name(name, "name")
    cfg = read_yaml_settings()
    url, token = cfg.get("k8sUrl", ""), cfg.get("k8sToken", "")
    if not url or not token:
        raise HTTPException(400, "Kubernetes not configured")
    container = request.query_params.get("container", "")
    if container:
        container = _validate_k8s_name(container, "container")
    lines = _int_param(request, "lines", 100, 1, 5000)
    path = f"/api/v1/namespaces/{namespace}/pods/{name}/log?tailLines={lines}"
    if container:
        path += f"&container={container}"
    import httpx as _httpx
    try:
        r = _httpx.get(f"{url.rstrip('/')}{path}",
                      headers={"Authorization": f"Bearer {token}"}, verify=_k8s_verify(cfg), timeout=15)
        r.raise_for_status()
        return PlainTextResponse(r.text[-65536:] or "No logs.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("K8s log fetch failed: %s", e)
        raise HTTPException(502, "K8s log fetch failed") from None


@router.get("/api/k8s/deployments")
@handle_errors
def api_k8s_deployments(request: Request, auth=Depends(_get_auth)):
    """List deployments with replica info."""
    cfg = read_yaml_settings()
    url, token = cfg.get("k8sUrl", ""), cfg.get("k8sToken", "")
    if not url or not token:
        raise HTTPException(400, "Kubernetes not configured")
    namespace = request.query_params.get("namespace", "")
    if namespace:
        namespace = _validate_k8s_name(namespace, "namespace")
    path = f"/apis/apps/v1/namespaces/{namespace}/deployments" if namespace else "/apis/apps/v1/deployments"
    import httpx as _httpx
    try:
        r = _httpx.get(f"{url.rstrip('/')}{path}",
                      headers={"Authorization": f"Bearer {token}"}, verify=_k8s_verify(cfg), timeout=10)
        r.raise_for_status()
        items = r.json().get("items", [])
        return [{
            "name": d.get("metadata", {}).get("name", ""),
            "namespace": d.get("metadata", {}).get("namespace", ""),
            "replicas": d.get("spec", {}).get("replicas", 0),
            "ready": d.get("status", {}).get("readyReplicas", 0),
            "available": d.get("status", {}).get("availableReplicas", 0),
            "updated": d.get("status", {}).get("updatedReplicas", 0),
        } for d in items[:100]]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("K8s API error: %s", e)
        raise HTTPException(502, "K8s API error") from None


@router.post("/api/k8s/deployments/{namespace}/{name}/scale")
@handle_errors
async def api_k8s_scale(namespace: str, name: str, request: Request, auth=Depends(_require_operator)):
    """Scale a deployment."""
    namespace = _validate_k8s_name(namespace, "namespace")
    name = _validate_k8s_name(name, "name")
    username, _ = auth
    body = await _read_body(request)
    replicas = int(body.get("replicas", 1))
    if replicas < 0 or replicas > 100:
        raise HTTPException(400, "Replicas must be 0-100")
    cfg = read_yaml_settings()
    url, token = cfg.get("k8sUrl", ""), cfg.get("k8sToken", "")
    if not url or not token:
        raise HTTPException(400, "Kubernetes not configured")
    import httpx as _httpx
    try:
        r = _httpx.patch(
            f"{url.rstrip('/')}/apis/apps/v1/namespaces/{namespace}/deployments/{name}/scale",
            json={"spec": {"replicas": replicas}},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/merge-patch+json"},
            verify=_k8s_verify(cfg), timeout=10,
        )
        r.raise_for_status()
        db.audit_log("k8s_scale", username, f"Scaled {namespace}/{name} to {replicas}", _client_ip(request))
        return {"success": True, "replicas": replicas}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("K8s scale failed: %s", e)
        raise HTTPException(502, "K8s scale failed") from None


# ── Proxmox deep management ─────────────────────────────────────────────
def _pmx_headers(cfg: dict) -> dict:
    user = cfg.get("proxmoxUser", "")
    user_full = user if "@" in user else f"{user}@pam"
    tname = cfg.get("proxmoxTokenName", "")
    tval = cfg.get("proxmoxTokenValue", "")
    # If tname already contains '!' it's a full token ID (e.g. "root@pam!noba-api"),
    # so use it directly.  Otherwise prepend user_full!.
    token_id = tname if "!" in tname else f"{user_full}!{tname}"
    return {"Authorization": f"PVEAPIToken={token_id}={tval}", "Accept": "application/json"}


def _validate_pmx_node(node: str) -> None:
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$', node):
        raise HTTPException(400, "Invalid Proxmox node name")


@router.get("/api/proxmox/nodes/{node}/vms")
@handle_errors
def api_pmx_node_vms(node: str, auth=Depends(_get_auth)):
    """List VMs and containers on a Proxmox node."""
    _validate_pmx_node(node)
    cfg = read_yaml_settings()
    url = cfg.get("proxmoxUrl", "")
    if not url:
        raise HTTPException(400, "Proxmox not configured")
    hdrs = _pmx_headers(cfg)
    import httpx as _httpx
    results = []
    for ep, vtype in (("qemu", "qemu"), ("lxc", "lxc")):
        try:
            r = _httpx.get(f"{url.rstrip('/')}/api2/json/nodes/{node}/{ep}",
                          headers=hdrs, verify=_pmx_verify(cfg), timeout=8)
            r.raise_for_status()
            for vm in r.json().get("data", [])[:50]:
                mmem = vm.get("maxmem", 1) or 1
                results.append({
                    "vmid": vm.get("vmid"), "name": vm.get("name", ""),
                    "type": vtype, "status": vm.get("status", ""),
                    "cpu": round(vm.get("cpu", 0) * 100, 1),
                    "mem_percent": round(vm.get("mem", 0) / mmem * 100, 1),
                    "uptime": vm.get("uptime", 0),
                    "disk": vm.get("disk", 0), "maxdisk": vm.get("maxdisk", 0),
                })
        except HTTPException:
            raise
        except Exception:
            pass
    return results


@router.get("/api/proxmox/nodes/{node}/vms/{vmid}/snapshots")
@handle_errors
def api_pmx_snapshots(node: str, vmid: int, request: Request, auth=Depends(_get_auth)):
    """List VM snapshots."""
    _validate_pmx_node(node)
    cfg = read_yaml_settings()
    url = cfg.get("proxmoxUrl", "")
    if not url:
        raise HTTPException(400, "Proxmox not configured")
    vtype = request.query_params.get("type", "qemu")
    if vtype not in ("qemu", "lxc"):
        raise HTTPException(400, "type must be 'qemu' or 'lxc'")
    hdrs = _pmx_headers(cfg)
    import httpx as _httpx
    try:
        r = _httpx.get(f"{url.rstrip('/')}/api2/json/nodes/{node}/{vtype}/{vmid}/snapshot",
                      headers=hdrs, verify=_pmx_verify(cfg), timeout=8)
        r.raise_for_status()
        return [{"name": s.get("name", ""), "description": s.get("description", ""),
                 "snaptime": s.get("snaptime", 0), "parent": s.get("parent", "")}
                for s in r.json().get("data", [])]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Proxmox API error: %s", e)
        raise HTTPException(502, "Proxmox API error") from None


@router.post("/api/proxmox/nodes/{node}/vms/{vmid}/snapshot")
@handle_errors
async def api_pmx_create_snapshot(node: str, vmid: int, request: Request, auth=Depends(_require_admin)):
    """Create a VM snapshot."""
    _validate_pmx_node(node)
    username, _ = auth
    body = await _read_body(request)
    snapname = body.get("name", "").strip()
    description = body.get("description", "")
    vtype = body.get("type", "qemu")
    if vtype not in ("qemu", "lxc"):
        raise HTTPException(400, "type must be 'qemu' or 'lxc'")
    if not snapname or not re.match(r'^[a-zA-Z0-9_-]+$', snapname):
        raise HTTPException(400, "Invalid snapshot name")
    cfg = read_yaml_settings()
    url = cfg.get("proxmoxUrl", "")
    if not url:
        raise HTTPException(400, "Proxmox not configured")
    hdrs = _pmx_headers(cfg)
    import httpx as _httpx
    try:
        r = _httpx.post(f"{url.rstrip('/')}/api2/json/nodes/{node}/{vtype}/{vmid}/snapshot",
                       json={"snapname": snapname, "description": description},
                       headers=hdrs, verify=_pmx_verify(cfg), timeout=30)
        r.raise_for_status()
        db.audit_log("pmx_snapshot", username, f"Created snapshot {snapname} for {vtype}/{vmid}", _client_ip(request))
        return {"success": True, "task": r.json().get("data", "")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Snapshot creation failed: %s", e)
        raise HTTPException(502, "Snapshot creation failed") from None


@router.get("/api/proxmox/nodes/{node}/vms/{vmid}/console")
@handle_errors
def api_pmx_console_url(node: str, vmid: int, request: Request, auth=Depends(_require_operator)):
    """Get a noVNC console URL for a VM."""
    cfg = read_yaml_settings()
    url = cfg.get("proxmoxUrl", "")
    if not url:
        raise HTTPException(400, "Proxmox not configured")
    vtype = request.query_params.get("type", "qemu")
    console_url = f"{url.rstrip('/')}/?console={vtype}&vmid={vmid}&node={node}&resize=scale"
    return {"url": console_url}


# ── /api/terminal (WebSocket) ────────────────────────────────────────────────
@router.websocket("/api/terminal")
async def ws_terminal(ws: WebSocket):
    """WebSocket terminal -- admin only."""
    token = ws.query_params.get("token", "")
    username, role = ws_token_store.consume(token)
    if not username or role != "admin":
        await ws.close(code=4001, reason="Unauthorized")
        return
    from ..terminal import terminal_handler
    await terminal_handler(ws, username, role)


# ── Network discovery endpoints ───────────────────────────────────────────────

@router.get("/api/network/devices")
@handle_errors
def api_network_devices(auth=Depends(_get_auth)):
    """List all discovered network devices."""
    return db.list_network_devices()


@router.post("/api/network/discover/{hostname}")
@handle_errors
async def api_network_discover(hostname: str, request: Request, auth=Depends(_require_operator)):
    """Trigger network discovery on a specific agent."""
    username, role = auth
    ip = _client_ip(request)

    risk = RISK_LEVELS.get("network_discover")
    if not risk:
        raise HTTPException(400, "Unknown command type: 'network_discover'")
    if not check_role_permission(role, risk):
        raise HTTPException(403, "Insufficient permissions for network_discover")

    with _agent_data_lock:
        agent = _agent_data.get(hostname)
    if not agent:
        raise HTTPException(404, f"Agent '{hostname}' not found or offline")

    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": "network_discover", "params": {},
           "queued_by": username, "queued_at": int(time.time())}

    # Try WebSocket first, fall back to queue
    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"type": "command", "id": cmd_id,
                                "cmd": "network_discover", "params": {}})
            delivered = True
        except HTTPException:
            raise
        except Exception:
            with _agent_ws_lock:
                _agent_websockets.pop(hostname, None)

    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)

    db.record_command(cmd_id, hostname, "network_discover", {}, username)
    db.audit_log("network_discover", username,
                 f"host={hostname} id={cmd_id} ws={delivered}", ip)
    return {"status": "sent" if delivered else "queued", "id": cmd_id, "websocket": delivered}


@router.delete("/api/network/devices/{device_id}")
@handle_errors
def api_delete_network_device(device_id: int, request: Request, auth=Depends(_require_operator)):
    """Remove a discovered network device."""
    username, _ = auth
    ok = db.delete_network_device(device_id)
    if not ok:
        raise HTTPException(404, f"Device {device_id} not found")
    db.audit_log("network_device_delete", username,
                 f"device_id={device_id}", _client_ip(request))
    return {"status": "ok"}
