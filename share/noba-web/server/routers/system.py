"""Noba – Infrastructure and system management endpoints."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse

from .. import deps as _deps  # noqa: F401 – runtime access to bg_collector
from ..agent_config import (
    RISK_LEVELS, check_role_permission, get_agent_capabilities,
    validate_command_params,
)
from ..agent_store import (
    _agent_cmd_lock, _agent_cmd_results, _agent_commands,
    _agent_data, _agent_data_lock, _AGENT_MAX_AGE,
    _agent_stream_lines, _agent_stream_lines_lock, _STREAM_LINES_MAX,
    _agent_streams, _agent_streams_lock,
    _agent_websockets, _agent_ws_lock,
    _CHUNK_SIZE, _MAX_TRANSFER_SIZE, _TRANSFER_DIR,
    _transfer_lock, _transfers,
)
from ..auth import token_store
from ..config import ALLOWED_ACTIONS, VERSION
from ..deps import (
    _client_ip, _get_auth, _int_param, _read_body, _require_admin,
    _require_operator, _safe_int, db,
)
from ..metrics import (
    bust_container_cache, collect_smart, get_listening_ports,
    get_network_connections, strip_ansi, validate_service_name,
)
from ..runner import job_runner
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

_WEB_DIR = Path(__file__).resolve().parent.parent.parent  # share/noba-web/

router = APIRouter()


# ── /api/recovery ─────────────────────────────────────────────────────────────
@router.post("/api/recovery/tailscale-reconnect")
async def api_recovery_tailscale(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    ip = _client_ip(request)
    try:
        result = subprocess.run(
            ["sudo", "-n", "tailscale", "up"], capture_output=True, text=True, timeout=15,
        )
        db.audit_log("recovery_tailscale", username, f"exit={result.returncode}", ip)
        return {"status": "ok" if result.returncode == 0 else "error",
                "output": result.stdout[:500], "error": result.stderr[:500]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/api/recovery/dns-flush")
async def api_recovery_dns(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    ip = _client_ip(request)
    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", "pihole-FTL"],
            capture_output=True, text=True, timeout=15,
        )
        db.audit_log("recovery_dns_flush", username, f"exit={result.returncode}", ip)
        return {"status": "ok" if result.returncode == 0 else "error",
                "output": result.stdout[:500], "error": result.stderr[:500]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/api/recovery/service-restart")
async def api_recovery_service(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    service = body.get("service", "")
    if not service or len(service) > 256 or not re.match(r'^[a-zA-Z0-9@._-]+$', service):
        raise HTTPException(400, "Invalid service name")
    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", service],
            capture_output=True, text=True, timeout=30,
        )
        db.audit_log("recovery_service_restart", username, f"service={service} exit={result.returncode}", ip)
        return {"status": "ok" if result.returncode == 0 else "error",
                "service": service, "output": result.stdout[:500]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── /api/sites/sync-status ───────────────────────────────────────────────────
@router.get("/api/sites/sync-status")
def api_sync_status(auth=Depends(_get_auth)):
    cfg = read_yaml_settings()
    site_map = cfg.get("siteMap", {})
    if not site_map:
        return {"services": [], "message": "No site mapping configured"}
    from collections import defaultdict  # noqa: PLC0415
    by_name: dict[str, dict] = defaultdict(dict)
    for svc_key, site in site_map.items():
        by_name[svc_key][site] = "configured"
    stats = _deps.bg_collector.get() or {}
    services = []
    for svc_key in sorted(by_name.keys()):
        sites = by_name[svc_key]
        live_data = stats.get(svc_key)
        services.append({
            "key": svc_key,
            "sites": sites,
            "online": live_data is not None and live_data != {},
        })
    return {"services": services}


# ── /api/smart ────────────────────────────────────────────────────────────────
@router.get("/api/smart")
def api_smart(auth=Depends(_get_auth)):
    return collect_smart()


# ── /api/container-control ────────────────────────────────────────────────────
@router.post("/api/container-control")
async def api_container_control(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    ct_name   = body.get("name",   "").strip()
    ct_action = body.get("action", "").strip()
    if ct_action not in ("start", "stop", "restart"):
        raise HTTPException(400, "Invalid action")
    if not ct_name or not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$", ct_name):
        raise HTTPException(400, "Invalid container name")
    for runtime in ("docker", "podman"):
        try:
            r = subprocess.run([runtime, ct_action, ct_name], capture_output=True, timeout=15)
            if r.returncode == 0:
                bust_container_cache()
                db.audit_log("container_control", username, f"{ct_action} {ct_name} via {runtime}", ip)
                return {"success": True, "runtime": runtime}
        except FileNotFoundError:
            continue
        except Exception as e:
            logger.error("Container control error: %s", e)
            db.audit_log("container_control", username, f"{ct_action} {ct_name} error: {e}", ip)
            raise HTTPException(500, "Container control error")
    raise HTTPException(404, "No container runtime found")


# ── Docker deep management ───────────────────────────────────────────────
@router.get("/api/containers/{name}/logs")
def api_container_logs(name: str, request: Request, auth=Depends(_require_operator)):
    """Stream container logs (last N lines)."""
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$", name):
        raise HTTPException(400, "Invalid container name")
    lines = _int_param(request, "lines", 100, 1, 5000)
    for runtime in ("docker", "podman"):
        try:
            r = subprocess.run([runtime, "logs", "--tail", str(lines), name],
                             capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                output = strip_ansi(r.stdout + r.stderr)
                return PlainTextResponse(output[-65536:] or "No logs.")
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Log fetch timed out")
    raise HTTPException(404, "No container runtime found")


@router.get("/api/containers/{name}/inspect")
def api_container_inspect(name: str, auth=Depends(_require_operator)):
    """Get detailed container info."""
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$", name):
        raise HTTPException(400, "Invalid container name")
    for runtime in ("docker", "podman"):
        try:
            r = subprocess.run([runtime, "inspect", name],
                             capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                data = json.loads(r.stdout)
                if isinstance(data, list) and data:
                    c = data[0]
                    config = c.get("Config", {})
                    host_config = c.get("HostConfig", {})
                    net = c.get("NetworkSettings", {})
                    state = c.get("State", {})
                    return {
                        "name": c.get("Name", "").lstrip("/"),
                        "image": config.get("Image", ""),
                        "created": c.get("Created", ""),
                        "status": state.get("Status", ""),
                        "started_at": state.get("StartedAt", ""),
                        "restart_count": c.get("RestartCount", 0),
                        "env": [e.split("=", 1)[0] + "=***" for e in config.get("Env", [])],
                        "ports": [
                            {"container": k, "host": (v or [{}])[0].get("HostPort", "")}
                            for k, v in (net.get("Ports") or {}).items()
                        ],
                        "mounts": [
                            {"source": m.get("Source", ""), "dest": m.get("Destination", ""), "mode": m.get("Mode", "")}
                            for m in c.get("Mounts", [])
                        ],
                        "networks": list((net.get("Networks") or {}).keys()),
                        "health": state.get("Health", {}).get("Status", ""),
                        "memory_limit": host_config.get("Memory", 0),
                        "cpu_shares": host_config.get("CpuShares", 0),
                        "restart_policy": host_config.get("RestartPolicy", {}).get("Name", ""),
                        "runtime": runtime,
                    }
        except FileNotFoundError:
            continue
    raise HTTPException(404, "Container not found")


@router.get("/api/containers/stats")
def api_container_stats(auth=Depends(_require_operator)):
    """Get per-container resource usage."""
    for runtime in ("docker", "podman"):
        try:
            r = subprocess.run(
                [runtime, "stats", "--no-stream", "--format",
                 "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}|{{.PIDs}}"],
                capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                stats = []
                for line in r.stdout.strip().splitlines():
                    parts = line.split("|")
                    if len(parts) >= 7:
                        stats.append({
                            "name": parts[0],
                            "cpu": parts[1].strip(),
                            "mem_usage": parts[2].strip(),
                            "mem_percent": parts[3].strip(),
                            "net_io": parts[4].strip(),
                            "block_io": parts[5].strip(),
                            "pids": parts[6].strip(),
                        })
                return stats
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Stats fetch timed out")
    return []


@router.post("/api/containers/{name}/pull")
async def api_container_pull(name: str, request: Request, auth=Depends(_require_admin)):
    """Pull the latest image for a container."""
    username, _ = auth
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$", name):
        raise HTTPException(400, "Invalid container name")
    for runtime in ("docker", "podman"):
        try:
            r = subprocess.run([runtime, "inspect", "--format", "{{.Config.Image}}", name],
                             capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                image = r.stdout.strip()
                def make_process(_run_id: int) -> subprocess.Popen | None:
                    return subprocess.Popen(
                        [runtime, "pull", image],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                run_id = job_runner.submit(make_process, trigger=f"image-pull:{image}",
                                          triggered_by=username)
                db.audit_log("container_pull", username, f"Pulling {image} for {name}", _client_ip(request))
                return {"success": True, "run_id": run_id, "image": image}
        except FileNotFoundError:
            continue
    raise HTTPException(404, "Container not found")


# ── /api/compose ──────────────────────────────────────────────────────────────
@router.get("/api/compose/projects")
def api_compose_projects(auth=Depends(_require_operator)):
    try:
        r = subprocess.run(["docker", "compose", "ls", "--format", "json"],
                          capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return json.loads(r.stdout)
    except Exception:
        pass
    return []


@router.post("/api/compose/{project}/{action}")
async def api_compose_action(project: str, action: str, request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    if action not in ("up", "down", "pull", "restart"):
        raise HTTPException(400, "Invalid action")
    if not re.match(r'^[a-zA-Z0-9_.-]+$', project):
        raise HTTPException(400, "Invalid project name")
    cmd = ["docker", "compose", "-p", project, action]
    if action == "up":
        cmd.append("-d")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        ok = r.returncode == 0
        db.audit_log("compose", username, f"{action} {project} -> {ok}", _client_ip(request))
        return {"success": ok, "output": r.stdout[-500:] if r.stdout else r.stderr[-500:]}
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Command timed out")


# ── /api/truenas/vm ───────────────────────────────────────────────────────────
@router.post("/api/truenas/vm")
async def api_truenas_vm(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    vm_id  = body.get("id")
    action = body.get("action")
    try:
        vm_id = int(vm_id)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid VM ID")
    if vm_id < 0 or action not in ALLOWED_ACTIONS:
        raise HTTPException(400, "Invalid request")
    cfg = read_yaml_settings()
    if not cfg.get("truenasUrl") or not cfg.get("truenasKey"):
        raise HTTPException(400, "TrueNAS API not configured")
    import urllib.request as _ur
    try:
        url = f"{cfg['truenasUrl'].rstrip('/')}/api/v2.0/vm/id/{vm_id}/{action}"
        req = _ur.Request(url, data=b"{}", headers={
            "Authorization": f"Bearer {cfg['truenasKey']}",
            "Content-Type":  "application/json",
        }, method="POST")
        with _ur.urlopen(req, timeout=5) as r:
            success = r.getcode() == 200
        db.audit_log("vm_action", username, f"VM {vm_id} {action} {success}", ip)
        return {"success": success}
    except Exception as e:
        logger.error("VM action failed: %s", e)
        db.audit_log("vm_action", username, f"VM {vm_id} {action} failed: {e}", ip)
        raise HTTPException(502, "VM action failed")


# ── /api/service-control ──────────────────────────────────────────────────────
@router.post("/api/service-control")
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
           else ["sudo", "-n", "systemctl", action, svc])
    try:
        r = subprocess.run(cmd, timeout=10, capture_output=True)
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
        raise HTTPException(500, "Service control error")


# ── Network analysis ─────────────────────────────────────────────────────────
@router.get("/api/network/connections")
def api_network_connections(auth=Depends(_require_operator)):
    """List active network connections."""
    return get_network_connections()


@router.get("/api/network/ports")
def api_network_ports(auth=Depends(_get_auth)):
    """List listening ports with process info."""
    return get_listening_ports()


@router.get("/api/network/interfaces")
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

    for cfg_key, (node_id, label, category) in integration_map.items():
        url = cfg.get(cfg_key, "")
        if url:
            data = stats.get(node_id)
            status = "online" if data and (isinstance(data, dict) and data.get("status") == "online") else "configured"
            nodes.append({"id": node_id, "label": label, "type": category, "status": status})
            edges.append({"from": "noba", "to": node_id})

    for svc in stats.get("services", []):
        sid = f"svc_{svc['name']}"
        nodes.append({"id": sid, "label": svc["name"], "type": "service", "status": svc.get("status", "unknown")})
        edges.append({"from": "noba", "to": sid})

    return {"nodes": nodes, "edges": edges}


# ── Disk usage prediction ────────────────────────────────────────────────────
@router.get("/api/disks/prediction")
def api_disk_prediction(request: Request, auth=Depends(_get_auth)):
    """Predict when each disk will be full based on usage trends."""
    results = []
    stats = _deps.bg_collector.get() or {}
    for disk in stats.get("disks", []):
        mount = disk.get("mount", "")
        trend = db.get_trend("disk_percent", range_hours=168, projection_hours=720)
        results.append({
            "mount": mount,
            "current_percent": disk.get("percent", 0),
            "full_at": trend.get("full_at"),
            "slope_per_day": round((trend.get("slope", 0) or 0) * 86400, 3),
            "r_squared": trend.get("r_squared", 0),
        })
    return results


# ── Uptime SLA dashboard ────────────────────────────────────────────────────
@router.get("/api/uptime")
def api_uptime_dashboard(auth=Depends(_get_auth)):
    """Get uptime statistics for all monitored services and integrations."""
    stats = _deps.bg_collector.get() or {}

    items = []
    for svc in stats.get("services", []):
        items.append({
            "name": svc["name"],
            "type": "service",
            "status": "up" if svc.get("status") == "active" else "down",
        })
    integration_checks = [
        ("pihole", "Pi-hole"), ("plex", "Plex"), ("jellyfin", "Jellyfin"),
        ("truenas", "TrueNAS"), ("proxmox", "Proxmox"), ("adguard", "AdGuard"),
        ("hass", "Home Assistant"), ("unifi", "UniFi"), ("nextcloud", "Nextcloud"),
        ("tautulli", "Tautulli"), ("overseerr", "Overseerr"), ("gitea", "Gitea"),
        ("gitlab", "GitLab"), ("traefik", "Traefik"), ("k8s", "Kubernetes"),
    ]
    for key, label in integration_checks:
        data = stats.get(key)
        if data is None:
            continue
        if isinstance(data, dict):
            status = "up" if data.get("status") == "online" else "down"
        else:
            status = "up" if data else "down"
        items.append({"name": label, "type": "integration", "status": status})
    for r in stats.get("radar", []):
        items.append({
            "name": r.get("ip", ""),
            "type": "host",
            "status": "up" if r.get("status") == "Up" else "down",
            "ms": r.get("ms", 0),
        })
    return items


# ── Systemd journal viewer ───────────────────────────────────────────────────
@router.get("/api/journal")
def api_journal(request: Request, auth=Depends(_require_operator)):
    """Query systemd journal with filters."""
    unit = request.query_params.get("unit", "")
    priority = request.query_params.get("priority", "")
    lines = _int_param(request, "lines", 50, 1, 500)
    since = request.query_params.get("since", "")
    grep_pattern = request.query_params.get("grep", "")

    cmd = ["journalctl", "--no-pager", "-n", str(lines), "--output", "short-iso"]
    if unit:
        if not re.match(r'^[a-zA-Z0-9_.@-]+$', unit):
            raise HTTPException(400, "Invalid unit name")
        cmd += ["-u", unit]
    if priority:
        if priority in ("0", "1", "2", "3", "4", "5", "6", "7",
                        "emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"):
            cmd += ["-p", priority]
    if since:
        if re.match(r'^\d+\s*(min|hour|day|sec)\s*ago$', since):
            cmd += ["--since", since]
    if grep_pattern:
        cmd += ["-g", grep_pattern[:100]]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return PlainTextResponse(r.stdout[-65536:] or "No entries.")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Journal query timed out")
    except FileNotFoundError:
        return PlainTextResponse("journalctl not available")


@router.get("/api/journal/units")
def api_journal_units(auth=Depends(_require_operator)):
    """List systemd units for the journal filter."""
    try:
        r = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--no-pager", "--plain", "--no-legend"],
            capture_output=True, text=True, timeout=5,
        )
        units = []
        for line in r.stdout.splitlines():
            parts = line.split()
            if parts:
                units.append({"name": parts[0], "status": parts[3] if len(parts) > 3 else ""})
        return units[:200]
    except Exception:
        return []


# ── Extended system info ─────────────────────────────────────────────────────
@router.get("/api/system/info")
def api_system_info(auth=Depends(_get_auth)):
    """Extended system information."""
    import platform

    from ..metrics import get_cpu_governor
    stats = _deps.bg_collector.get() or {}

    info = {
        "hostname": stats.get("hostname", ""),
        "os": stats.get("osName", ""),
        "kernel": stats.get("kernel", ""),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "cpu_model": stats.get("hwCpu", ""),
        "cpu_cores": os.cpu_count(),
        "gpu": stats.get("hwGpu", ""),
        "uptime": stats.get("uptime", ""),
        "load": stats.get("loadavg", ""),
        "ip": stats.get("defaultIp", ""),
        "governor": get_cpu_governor(),
        "noba_version": VERSION,
    }
    try:
        import psutil
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        info["ram_total_gb"] = round(vm.total / (1024**3), 1)
        info["ram_available_gb"] = round(vm.available / (1024**3), 1)
        info["swap_total_gb"] = round(sw.total / (1024**3), 1)
        info["swap_used_gb"] = round(sw.used / (1024**3), 1)
    except Exception:
        pass
    return info


@router.get("/api/system/health")
def api_system_health(auth=Depends(_get_auth)):
    """Comprehensive system health overview with score."""
    stats = _deps.bg_collector.get() or {}

    checks = []
    score = 100

    cpu = stats.get("cpuPercent", 0)
    if cpu > 90:
        checks.append({"name": "CPU", "status": "critical", "value": f"{cpu}%", "deduction": 30})
        score -= 30
    elif cpu > 75:
        checks.append({"name": "CPU", "status": "warning", "value": f"{cpu}%", "deduction": 10})
        score -= 10
    else:
        checks.append({"name": "CPU", "status": "ok", "value": f"{cpu}%", "deduction": 0})

    mem = stats.get("memPercent", 0)
    if mem > 90:
        checks.append({"name": "Memory", "status": "critical", "value": f"{mem}%", "deduction": 25})
        score -= 25
    elif mem > 80:
        checks.append({"name": "Memory", "status": "warning", "value": f"{mem}%", "deduction": 10})
        score -= 10
    else:
        checks.append({"name": "Memory", "status": "ok", "value": f"{mem}%", "deduction": 0})

    for disk in stats.get("disks", []):
        p = disk.get("percent", 0)
        mount = disk.get("mount", "?")
        if p >= 95:
            checks.append({"name": f"Disk {mount}", "status": "critical", "value": f"{p}%", "deduction": 20})
            score -= 20
        elif p >= 85:
            checks.append({"name": f"Disk {mount}", "status": "warning", "value": f"{p}%", "deduction": 5})
            score -= 5
        else:
            checks.append({"name": f"Disk {mount}", "status": "ok", "value": f"{p}%", "deduction": 0})

    temp_str = stats.get("cpuTemp", "N/A")
    if temp_str != "N/A":
        try:
            temp = int(temp_str.replace("\u00b0C", ""))
            if temp > 85:
                checks.append({"name": "CPU Temp", "status": "critical", "value": f"{temp}\u00b0C", "deduction": 15})
                score -= 15
            elif temp > 70:
                checks.append({"name": "CPU Temp", "status": "warning", "value": f"{temp}\u00b0C", "deduction": 5})
                score -= 5
            else:
                checks.append({"name": "CPU Temp", "status": "ok", "value": f"{temp}\u00b0C", "deduction": 0})
        except ValueError:
            pass

    failed_svcs = [s for s in stats.get("services", []) if s.get("status") == "failed"]
    if failed_svcs:
        for s in failed_svcs:
            checks.append({"name": f"Service: {s['name']}", "status": "critical", "value": "failed", "deduction": 10})
            score -= 10

    net = stats.get("netHealth", {})
    if net.get("configured") and net.get("wan") == "Down":
        checks.append({"name": "WAN", "status": "critical", "value": "Down", "deduction": 20})
        score -= 20

    alert_count = len(stats.get("alerts", []))
    if alert_count > 0:
        checks.append({"name": "Active Alerts", "status": "warning", "value": str(alert_count),
                        "deduction": min(alert_count * 3, 15)})
        score -= min(alert_count * 3, 15)

    score = max(0, score)
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"

    return {
        "score": score,
        "grade": grade,
        "checks": checks,
        "uptime": stats.get("uptime", "--"),
        "hostname": stats.get("hostname", "--"),
    }


# ── /api/health-score — Infrastructure Health Score (Feature 7) ──────────────
@router.get("/api/health-score")
async def api_health_score(auth=Depends(_get_auth)):
    """Compute infrastructure-wide health score (0-100) with category breakdown."""
    from ..health_score import compute_health_score

    stats = _deps.bg_collector.get() if _deps.bg_collector else {}
    with _agent_data_lock:
        agent_snapshot = dict(_agent_data)
    return await compute_health_score(db, agent_snapshot, stats)


@router.post("/api/system/cpu-governor")
async def api_cpu_governor(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    body = await _read_body(request)
    governor = body.get("governor", "").strip()
    allowed = ("performance", "powersave", "ondemand", "conservative", "schedutil")
    if governor not in allowed:
        raise HTTPException(400, f"Governor must be one of: {', '.join(allowed)}")
    try:
        r = subprocess.run(["sudo", "-n", "cpupower", "frequency-set", "-g", governor],
                          capture_output=True, timeout=10)
        ok = r.returncode == 0
    except Exception:
        ok = False
    db.audit_log("cpu_governor", username, f"Set {governor} -> {ok}", _client_ip(request))
    return {"success": ok}


# ── /api/processes ────────────────────────────────────────────────────────────
@router.get("/api/processes/history")
def api_process_history(auth=Depends(_get_auth)):
    """Get rolling history of top CPU and memory consumers."""
    from ..metrics import get_process_history
    return get_process_history()


@router.get("/api/processes/current")
def api_processes_current(auth=Depends(_get_auth)):
    """Get current process list with details."""
    import psutil as _psutil
    procs = []
    for p in _psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status", "username", "create_time"]):
        try:
            info = p.info
            if (info.get("cpu_percent", 0) or 0) > 0.1 or (info.get("memory_percent", 0) or 0) > 0.1:
                procs.append({
                    "pid": info.get("pid"),
                    "name": (info.get("name") or "")[:30],
                    "cpu": round(info.get("cpu_percent", 0) or 0, 1),
                    "mem": round(info.get("memory_percent", 0) or 0, 1),
                    "status": info.get("status", ""),
                    "user": (info.get("username") or "")[:20],
                })
        except Exception:
            continue
    procs.sort(key=lambda x: x["cpu"], reverse=True)
    return procs[:100]


# ── Kubernetes deep management ───────────────────────────────────────────
@router.get("/api/k8s/namespaces")
def api_k8s_namespaces(auth=Depends(_get_auth)):
    """List Kubernetes namespaces."""
    cfg = read_yaml_settings()
    url, token = cfg.get("k8sUrl", ""), cfg.get("k8sToken", "")
    if not url or not token:
        raise HTTPException(400, "Kubernetes not configured")
    import httpx as _httpx
    try:
        r = _httpx.get(f"{url.rstrip('/')}/api/v1/namespaces",
                      headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=10)
        r.raise_for_status()
        items = r.json().get("items", [])
        return [{"name": ns.get("metadata", {}).get("name", ""),
                 "status": ns.get("status", {}).get("phase", ""),
                 "created": ns.get("metadata", {}).get("creationTimestamp", "")}
                for ns in items]
    except Exception as e:
        raise HTTPException(502, f"K8s API error: {e}")


@router.get("/api/k8s/pods")
def api_k8s_pods(request: Request, auth=Depends(_get_auth)):
    """List pods with details, optionally filtered by namespace."""
    cfg = read_yaml_settings()
    url, token = cfg.get("k8sUrl", ""), cfg.get("k8sToken", "")
    if not url or not token:
        raise HTTPException(400, "Kubernetes not configured")
    namespace = request.query_params.get("namespace", "")
    path = f"/api/v1/namespaces/{namespace}/pods" if namespace else "/api/v1/pods"
    import httpx as _httpx
    try:
        r = _httpx.get(f"{url.rstrip('/')}{path}",
                      headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=10)
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
    except Exception as e:
        raise HTTPException(502, f"K8s API error: {e}")


@router.get("/api/k8s/pods/{namespace}/{name}/logs")
def api_k8s_pod_logs(namespace: str, name: str, request: Request, auth=Depends(_require_operator)):
    """Get pod logs."""
    cfg = read_yaml_settings()
    url, token = cfg.get("k8sUrl", ""), cfg.get("k8sToken", "")
    if not url or not token:
        raise HTTPException(400, "Kubernetes not configured")
    container = request.query_params.get("container", "")
    lines = _int_param(request, "lines", 100, 1, 5000)
    path = f"/api/v1/namespaces/{namespace}/pods/{name}/log?tailLines={lines}"
    if container:
        path += f"&container={container}"
    import httpx as _httpx
    try:
        r = _httpx.get(f"{url.rstrip('/')}{path}",
                      headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=15)
        r.raise_for_status()
        return PlainTextResponse(r.text[-65536:] or "No logs.")
    except Exception as e:
        raise HTTPException(502, f"K8s log fetch failed: {e}")


@router.get("/api/k8s/deployments")
def api_k8s_deployments(request: Request, auth=Depends(_get_auth)):
    """List deployments with replica info."""
    cfg = read_yaml_settings()
    url, token = cfg.get("k8sUrl", ""), cfg.get("k8sToken", "")
    if not url or not token:
        raise HTTPException(400, "Kubernetes not configured")
    namespace = request.query_params.get("namespace", "")
    path = f"/apis/apps/v1/namespaces/{namespace}/deployments" if namespace else "/apis/apps/v1/deployments"
    import httpx as _httpx
    try:
        r = _httpx.get(f"{url.rstrip('/')}{path}",
                      headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=10)
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
    except Exception as e:
        raise HTTPException(502, f"K8s API error: {e}")


@router.post("/api/k8s/deployments/{namespace}/{name}/scale")
async def api_k8s_scale(namespace: str, name: str, request: Request, auth=Depends(_require_admin)):
    """Scale a deployment."""
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
            verify=False, timeout=10,
        )
        r.raise_for_status()
        db.audit_log("k8s_scale", username, f"Scaled {namespace}/{name} to {replicas}", _client_ip(request))
        return {"success": True, "replicas": replicas}
    except Exception as e:
        raise HTTPException(502, f"K8s scale failed: {e}")


# ── Proxmox deep management ─────────────────────────────────────────────
def _pmx_headers(cfg: dict) -> dict:
    user = cfg.get("proxmoxUser", "")
    user_full = user if "@" in user else f"{user}@pam"
    tname = cfg.get("proxmoxTokenName", "")
    tval = cfg.get("proxmoxTokenValue", "")
    return {"Authorization": f"PVEAPIToken={user_full}!{tname}={tval}", "Accept": "application/json"}


@router.get("/api/proxmox/nodes/{node}/vms")
def api_pmx_node_vms(node: str, auth=Depends(_get_auth)):
    """List VMs and containers on a Proxmox node."""
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
                          headers=hdrs, verify=False, timeout=8)
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
        except Exception:
            pass
    return results


@router.get("/api/proxmox/nodes/{node}/vms/{vmid}/snapshots")
def api_pmx_snapshots(node: str, vmid: int, request: Request, auth=Depends(_get_auth)):
    """List VM snapshots."""
    cfg = read_yaml_settings()
    url = cfg.get("proxmoxUrl", "")
    if not url:
        raise HTTPException(400, "Proxmox not configured")
    vtype = request.query_params.get("type", "qemu")
    hdrs = _pmx_headers(cfg)
    import httpx as _httpx
    try:
        r = _httpx.get(f"{url.rstrip('/')}/api2/json/nodes/{node}/{vtype}/{vmid}/snapshot",
                      headers=hdrs, verify=False, timeout=8)
        r.raise_for_status()
        return [{"name": s.get("name", ""), "description": s.get("description", ""),
                 "snaptime": s.get("snaptime", 0), "parent": s.get("parent", "")}
                for s in r.json().get("data", [])]
    except Exception as e:
        raise HTTPException(502, f"Proxmox API error: {e}")


@router.post("/api/proxmox/nodes/{node}/vms/{vmid}/snapshot")
async def api_pmx_create_snapshot(node: str, vmid: int, request: Request, auth=Depends(_require_admin)):
    """Create a VM snapshot."""
    username, _ = auth
    body = await _read_body(request)
    snapname = body.get("name", "").strip()
    description = body.get("description", "")
    vtype = body.get("type", "qemu")
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
                       headers=hdrs, verify=False, timeout=30)
        r.raise_for_status()
        db.audit_log("pmx_snapshot", username, f"Created snapshot {snapname} for {vtype}/{vmid}", _client_ip(request))
        return {"success": True, "task": r.json().get("data", "")}
    except Exception as e:
        raise HTTPException(502, f"Snapshot creation failed: {e}")


@router.get("/api/proxmox/nodes/{node}/vms/{vmid}/console")
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
    username, role = token_store.validate(token)
    if not username or role != "admin":
        await ws.close(code=4001, reason="Unauthorized")
        return
    from ..terminal import terminal_handler
    await terminal_handler(ws, username)


# ── IaC Export endpoints ─────────────────────────────────────────────────────

@router.get("/api/export/ansible")
async def api_export_ansible(request: Request, auth=Depends(_require_operator)):
    """Generate an Ansible playbook from live agent data."""
    from ..iac_export import generate_ansible

    hostname = request.query_params.get("hostname") or None
    output = generate_ansible(
        db, _agent_data, _agent_data_lock, _AGENT_MAX_AGE, hostname,
    )
    return PlainTextResponse(output, media_type="text/yaml")


@router.get("/api/export/docker-compose")
async def api_export_docker_compose(request: Request, auth=Depends(_require_operator)):
    """Generate a docker-compose.yml from live agent container data."""
    from ..iac_export import generate_docker_compose

    hostname = request.query_params.get("hostname") or None
    if not hostname:
        raise HTTPException(400, "hostname parameter is required")
    output = generate_docker_compose(
        db, _agent_data, _agent_data_lock, _AGENT_MAX_AGE, hostname,
    )
    return PlainTextResponse(output, media_type="text/yaml")


@router.get("/api/export/shell")
async def api_export_shell(request: Request, auth=Depends(_require_operator)):
    """Generate a bash setup script from live agent data."""
    from ..iac_export import generate_shell_script

    hostname = request.query_params.get("hostname") or None
    if not hostname:
        raise HTTPException(400, "hostname parameter is required")
    output = generate_shell_script(
        db, _agent_data, _agent_data_lock, _AGENT_MAX_AGE, hostname,
    )
    return PlainTextResponse(output, media_type="text/x-shellscript")


# ── Agent helpers ─────────────────────────────────────────────────────────────

def _validate_agent_key(key: str) -> bool:
    """Check an agent key against configured keys (shared by report + WebSocket)."""
    if not key:
        return False
    cfg = read_yaml_settings()
    valid_keys = [k.strip() for k in cfg.get("agentKeys", "").split(",") if k.strip()]
    return bool(valid_keys and key in valid_keys)


# ── Agent endpoints ───────────────────────────────────────────────────────────
@router.post("/api/agent/report")
async def api_agent_report(request: Request):
    """Receive metrics from a NOBA agent.  Auth via X-Agent-Key header."""
    key = request.headers.get("X-Agent-Key", "")
    if not key:
        raise HTTPException(401, "Missing X-Agent-Key")
    cfg = read_yaml_settings()
    valid_keys = [k.strip() for k in cfg.get("agentKeys", "").split(",") if k.strip()]
    if not valid_keys or key not in valid_keys:
        raise HTTPException(403, "Invalid agent key")
    body = await _read_body(request)
    hostname = body.get("hostname", "unknown")[:253]
    body["_received"] = time.time()
    body["_ip"] = _client_ip(request)
    cmd_results = body.pop("_cmd_results", None)
    if cmd_results:
        with _agent_cmd_lock:
            existing = _agent_cmd_results.get(hostname, [])
            existing.extend(cmd_results)
            # Keep only last 50 results
            _agent_cmd_results[hostname] = existing[-50:]
        for cr in cmd_results:
            cr_id = cr.get("id", "")
            if cr_id:
                db.complete_command(cr_id, cr)
            # Auto-record security scan results
            if cr.get("type") == "security_scan" and cr.get("status") == "ok":
                try:
                    db.record_security_scan(
                        hostname,
                        int(cr.get("score", 0)),
                        cr.get("findings", []),
                    )
                except Exception:
                    pass
            # Persist discovered network devices
            if cr.get("type") == "network_discover" and cr.get("status") == "ok":
                for dev in cr.get("devices", []):
                    try:
                        db.upsert_network_device(
                            ip=dev.get("ip", ""),
                            mac=dev.get("mac"),
                            hostname=dev.get("hostname"),
                            open_ports=dev.get("open_ports"),
                            discovered_by=hostname,
                        )
                    except Exception as e:
                        logger.warning("Failed to persist discovered device: %s", e)
            # Persist backup verification results
            if cr.get("type") == "verify_backup":
                try:
                    details = cr.get("details")
                    db.record_backup_verification(
                        backup_path=cr.get("path", ""),
                        hostname=hostname,
                        verification_type=cr.get("verification_type", ""),
                        status=cr.get("status", "error"),
                        details=json.dumps(details) if details else None,
                    )
                except Exception as e:
                    logger.warning("Failed to persist backup verification: %s", e)
    # Store stream data if present
    stream_data = body.pop("_stream_data", None)
    if stream_data and isinstance(stream_data, dict):
        with _agent_stream_lines_lock:
            for stream_id, lines in stream_data.items():
                if isinstance(lines, list):
                    buf = _agent_stream_lines.setdefault(stream_id, [])
                    buf.extend(lines)
                    # Trim to max size
                    if len(buf) > _STREAM_LINES_MAX:
                        _agent_stream_lines[stream_id] = buf[-_STREAM_LINES_MAX:]
    with _agent_data_lock:
        stale = [h for h, d in _agent_data.items() if time.time() - d.get("_received", 0) > 86400]
        for h in stale:
            del _agent_data[h]
        _agent_data[hostname] = body
    try:
        db.upsert_agent(
            hostname=hostname,
            ip=body.get("_ip", ""),
            platform_name=body.get("platform", ""),
            arch=body.get("arch", ""),
            agent_version=body.get("agent_version", ""),
        )
    except Exception:
        pass
    try:
        agent_metrics = [
            (f"agent_{hostname}_cpu", body.get("cpu_percent", 0), ""),
            (f"agent_{hostname}_mem", body.get("mem_percent", 0), ""),
        ]
        for disk in body.get("disks", [])[:1]:
            agent_metrics.append((f"agent_{hostname}_disk", disk.get("percent", 0), disk.get("mount", "/")))
        db.insert_metrics(agent_metrics)
    except Exception:
        pass
    pending = []
    with _agent_cmd_lock:
        if hostname in _agent_commands:
            pending = _agent_commands.pop(hostname)
        stale_cmds = [h for h, cmds in _agent_commands.items()
                      if cmds and cmds[0].get("queued_at", 0) < time.time() - 600]
        for h in stale_cmds:
            del _agent_commands[h]
    return {"status": "ok", "commands": pending}


# ── Agent WebSocket (Phase 1b) ───────────────────────────────────────────────

_ws_logger = logging.getLogger("noba.agent.ws")


@router.websocket("/api/agent/ws")
async def agent_websocket(ws: WebSocket):
    """WebSocket endpoint for real-time agent communication."""
    key = ws.query_params.get("key", "")
    if not _validate_agent_key(key):
        await ws.close(code=4001, reason="Invalid agent key")
        return

    await ws.accept()
    hostname = None
    try:
        ident = await ws.receive_json()
        if ident.get("type") != "identify":
            await ws.close(code=4002, reason="Expected identify message")
            return
        hostname = ident.get("hostname", "")
        if not hostname:
            await ws.close(code=4002, reason="No hostname")
            return

        with _agent_ws_lock:
            old = _agent_websockets.get(hostname)
            _agent_websockets[hostname] = ws
        if old:
            try:
                await old.close(code=1000, reason="Replaced by new connection")
            except Exception:
                pass

        _ws_logger.info("[ws] Agent %s connected via WebSocket", hostname)

        # Send any queued commands immediately
        with _agent_cmd_lock:
            queued = _agent_commands.pop(hostname, [])
        for cmd in queued:
            await ws.send_json({"type": "command", "id": cmd.get("id", ""),
                                "cmd": cmd.get("type", ""), "params": cmd.get("params", {})})

        while True:
            msg = await ws.receive_json()
            msg_type = msg.get("type", "")

            # Detect results from old agents (pre-fix): the "type" key
            # contains the command name instead of "result" due to a dict
            # unpacking collision.  Normalise so the rest of the handler
            # works identically for old and new agents.
            is_result = msg_type == "result"
            if not is_result and msg_type in RISK_LEVELS and "id" in msg:
                # Old-format result: {"type": "disk_usage", "id": "...", ...}
                is_result = True
                msg["cmd"] = msg_type       # stash command type
                msg["type"] = "result"      # fix discriminator
                msg_type = "result"

            if is_result:
                with _agent_cmd_lock:
                    _agent_cmd_results.setdefault(hostname, []).append(msg)
                    if len(_agent_cmd_results[hostname]) > 50:
                        _agent_cmd_results[hostname] = _agent_cmd_results[hostname][-50:]
                # Complete command in history DB (same as HTTP report path)
                cmd_id = msg.get("id", "")
                if cmd_id:
                    try:
                        db.complete_command(cmd_id, msg)
                    except Exception:
                        pass
                # Auto-record security scan results via WebSocket
                cmd_name = msg.get("cmd", "")
                if cmd_name == "security_scan" and msg.get("status") == "ok":
                    try:
                        db.record_security_scan(
                            hostname,
                            int(msg.get("score", 0)),
                            msg.get("findings", []),
                        )
                    except Exception:
                        pass
                # Auto-record backup verification results via WebSocket
                if cmd_name == "verify_backup":
                    try:
                        details = msg.get("details")
                        db.record_backup_verification(
                            backup_path=msg.get("path", ""),
                            hostname=hostname,
                            verification_type=msg.get("verification_type", ""),
                            status=msg.get("status", "error"),
                            details=json.dumps(details) if details else None,
                        )
                    except Exception:
                        pass

            elif msg_type == "stream":
                cmd_id = msg.get("id", "")
                with _agent_cmd_lock:
                    stream_key = f"_stream_{hostname}_{cmd_id}"
                    buf = _agent_cmd_results.setdefault(stream_key, [])
                    buf.append(msg)
                    if len(buf) > 500:
                        _agent_cmd_results[stream_key] = buf[-500:]

            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        _ws_logger.warning("[ws] Error for %s: %s", hostname, exc)
    finally:
        if hostname:
            with _agent_ws_lock:
                if _agent_websockets.get(hostname) is ws:
                    del _agent_websockets[hostname]
            _ws_logger.info("[ws] Agent %s disconnected", hostname)


@router.get("/api/agents/{hostname}/stream/{cmd_id}")
def api_agent_stream(hostname: str, cmd_id: str, request: Request, auth=Depends(_get_auth)):
    """Poll for new log stream lines (or WebSocket stream output).

    Supports cursor-based polling via ``?after=N`` query parameter.
    Returns only new lines since cursor position and the updated cursor.
    """
    # First check if this is a live log stream
    after = _safe_int(request.query_params.get("after", "0"), 0)
    with _agent_stream_lines_lock:
        all_lines = _agent_stream_lines.get(cmd_id)
    if all_lines is not None:
        with _agent_stream_lines_lock:
            all_lines = _agent_stream_lines.get(cmd_id, [])
            new_lines = all_lines[after:]
            total = len(all_lines)
        with _agent_streams_lock:
            host_streams = _agent_streams.get(hostname, {})
            active = cmd_id in host_streams
        return {"lines": new_lines, "cursor": total, "active": active}
    # Stream registered but no data yet — still active, waiting for agent
    with _agent_streams_lock:
        host_streams = _agent_streams.get(hostname, {})
        if cmd_id in host_streams:
            return {"lines": [], "cursor": 0, "active": True}
    # Fall back to WebSocket command stream output
    stream_key = f"_stream_{hostname}_{cmd_id}"
    with _agent_cmd_lock:
        ws_data = _agent_cmd_results.get(stream_key, [])
    return {"lines": ws_data, "cursor": len(ws_data), "active": bool(ws_data)}


@router.get("/api/agents")
def api_agents(auth=Depends(_get_auth)):
    """List all reporting agents and their latest metrics."""
    now = time.time()
    with _agent_data_lock:
        agents = []
        for hostname, data in sorted(_agent_data.items()):
            age = now - data.get("_received", 0)
            agents.append({
                **{k: v for k, v in data.items() if not k.startswith("_")},
                "online": age < _AGENT_MAX_AGE,
                "last_seen_s": int(age),
            })
    return agents


@router.get("/api/agents/command-history")
def api_command_history(request: Request, auth=Depends(_get_auth)):
    """Get command execution history, optionally filtered by hostname."""
    hostname = request.query_params.get("hostname", "")
    limit = min(int(request.query_params.get("limit", "50")), 200)
    return db.get_command_history(hostname=hostname or None, limit=limit)


@router.get("/api/agents/{hostname}")
def api_agent_detail(hostname: str, auth=Depends(_get_auth)):
    """Get detailed metrics for a specific agent."""
    with _agent_data_lock:
        data = _agent_data.get(hostname)
    if not data:
        raise HTTPException(404, "Agent not found")
    age = time.time() - data.get("_received", 0)
    with _agent_cmd_lock:
        cmd_results = _agent_cmd_results.get(hostname, [])
    return {
        **{k: v for k, v in data.items() if not k.startswith("_")},
        "online": age < _AGENT_MAX_AGE,
        "last_seen_s": int(age),
        "cmd_results": cmd_results,
    }


@router.post("/api/agents/bulk-command")
async def api_bulk_command(request: Request, auth=Depends(_get_auth)):
    """Send a command to multiple agents at once."""
    username, role = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    hostnames = body.get("hostnames", [])
    cmd_type = body.get("type", "")
    params = body.get("params", {})

    risk = RISK_LEVELS.get(cmd_type)
    if not risk:
        raise HTTPException(400, f"Unknown command type: {cmd_type!r}")
    if not check_role_permission(role, risk):
        raise HTTPException(403, "Insufficient permissions")
    err = validate_command_params(cmd_type, params)
    if err:
        raise HTTPException(400, err)

    if not hostnames:
        with _agent_data_lock:
            hostnames = list(_agent_data.keys())

    results = {}
    for hostname in hostnames:
        cmd_id = secrets.token_hex(8)
        cmd = {"id": cmd_id, "type": cmd_type, "params": params,
               "queued_by": username, "queued_at": int(time.time())}
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)
        results[hostname] = cmd_id
    db.audit_log("agent_bulk_command", username,
                 f"type={cmd_type} targets={len(hostnames)}", ip)
    return {"status": "queued", "commands": results}


@router.post("/api/agents/{hostname}/command")
async def api_agent_command(hostname: str, request: Request, auth=Depends(_get_auth)):
    """Queue a command for an agent. Risk-tiered authorization."""
    username, role = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    cmd_type = body.get("type", "")
    params = body.get("params", {})

    risk = RISK_LEVELS.get(cmd_type)
    if not risk:
        raise HTTPException(400, f"Unknown command type: {cmd_type!r}")
    if not check_role_permission(role, risk):
        raise HTTPException(403, f"Insufficient permissions: {cmd_type} requires {risk} access")

    with _agent_data_lock:
        agent = _agent_data.get(hostname)
    if agent:
        version = agent.get("agent_version", "1.1.0")
        caps = get_agent_capabilities(version)
        if cmd_type not in caps:
            raise HTTPException(400, f"Agent v{version} does not support '{cmd_type}'")

    err = validate_command_params(cmd_type, params)
    if err:
        raise HTTPException(400, err)

    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": cmd_type, "params": params,
           "queued_by": username, "queued_at": int(time.time())}

    # Dual-path: try WebSocket first, fall back to queue
    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"type": "command", "id": cmd_id,
                                "cmd": cmd_type, "params": params})
            delivered = True
        except Exception:
            with _agent_ws_lock:
                _agent_websockets.pop(hostname, None)

    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)

    db.record_command(cmd_id, hostname, cmd_type, params, username)
    db.audit_log("agent_command", username,
                 f"host={hostname} type={cmd_type} id={cmd_id} ws={delivered}", ip)
    return {"status": "sent" if delivered else "queued", "id": cmd_id, "websocket": delivered}


@router.post("/api/agents/{hostname}/uninstall")
async def api_agent_uninstall(hostname: str, request: Request, auth=Depends(_require_admin)):
    """Queue uninstall command and mark agent for removal."""
    username, _ = auth
    ip = _client_ip(request)
    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": "uninstall_agent", "params": {"confirm": True},
           "queued_by": username, "queued_at": int(time.time())}
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)
    db.audit_log("agent_uninstall", username, f"host={hostname} id={cmd_id}", ip)
    return {"status": "queued", "id": cmd_id}


@router.get("/api/agents/{hostname}/results")
def api_agent_results(hostname: str, auth=Depends(_get_auth)):
    """Get command execution results for an agent."""
    with _agent_cmd_lock:
        return _agent_cmd_results.get(hostname, [])


@router.get("/api/agents/{hostname}/history")
def api_agent_history(hostname: str, request: Request, auth=Depends(_get_auth)):
    """Get historical metrics for an agent (CPU, RAM, disk)."""
    hours = min(int(request.query_params.get("hours", "24")), 168)
    metric = request.query_params.get("metric", "cpu")
    metric_key = f"agent_{hostname}_{metric}"
    return db.get_history(metric_key, range_hours=hours, resolution=120)


# ── Network traffic analysis endpoint ─────────────────────────────────────────

@router.get("/api/agents/{hostname}/network-stats")
async def api_agent_network_stats(hostname: str, request: Request, auth=Depends(_get_auth)):
    """Trigger network_stats command on an agent and return the results.

    Sends the command via WebSocket if the agent is connected, otherwise
    queues it for the next poll.  The endpoint also stores per-interface
    byte counters as metrics for historical trending.
    """
    username, role = auth
    ip = _client_ip(request)

    risk = RISK_LEVELS.get("network_stats", "low")
    if not check_role_permission(role, risk):
        raise HTTPException(403, "Insufficient permissions")

    # Check agent existence
    with _agent_data_lock:
        agent = _agent_data.get(hostname)
    if not agent:
        raise HTTPException(404, f"Agent '{hostname}' not found or offline")

    version = agent.get("agent_version", "1.1.0")
    caps = get_agent_capabilities(version)
    if "network_stats" not in caps:
        raise HTTPException(400, f"Agent v{version} does not support 'network_stats'")

    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": "network_stats", "params": {},
           "queued_by": username, "queued_at": int(time.time())}

    # Try WebSocket first for instant results
    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            import asyncio
            await ws.send_json({"type": "command", "id": cmd_id,
                                "cmd": "network_stats", "params": {}})
            delivered = True
            # Wait for result (up to 5s)
            for _ in range(50):
                with _agent_cmd_lock:
                    results = _agent_cmd_results.get(hostname, [])
                    match = [r for r in results if r.get("id") == cmd_id]
                    if match:
                        result = match[0]
                        # Store interface metrics for trending
                        try:
                            iface_metrics = []
                            for iface in result.get("interfaces", []):
                                iname = iface.get("name", "").replace(".", "_")
                                iface_metrics.append(
                                    (f"net_if_{hostname}_{iname}_rx", iface.get("rx_bytes", 0), "")
                                )
                                iface_metrics.append(
                                    (f"net_if_{hostname}_{iname}_tx", iface.get("tx_bytes", 0), "")
                                )
                            if iface_metrics:
                                db.insert_metrics(iface_metrics)
                        except Exception:
                            pass
                        db.audit_log("agent_network_stats", username,
                                     f"host={hostname} id={cmd_id}", ip)
                        return result
                await asyncio.sleep(0.1)
        except Exception:
            delivered = False

    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)

    db.record_command(cmd_id, hostname, "network_stats", {}, username)
    db.audit_log("agent_network_stats", username,
                 f"host={hostname} id={cmd_id} ws={delivered}", ip)
    return {"status": "queued", "id": cmd_id, "message": "Command queued; check results endpoint."}


# ── Agent log streaming endpoints ────────────────────────────────────────────

@router.post("/api/agents/{hostname}/stream-logs")
async def api_agent_stream_logs(hostname: str, request: Request, auth=Depends(_require_admin)):
    """Start a live log stream on a remote agent via follow_logs command."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    unit = body.get("unit", "")
    priority = body.get("priority", "")
    lines = _safe_int(body.get("lines", 50), 50)
    cmd_id = secrets.token_hex(8)
    cmd = {
        "id": cmd_id, "type": "follow_logs",
        "params": {"unit": unit, "priority": priority, "lines": lines},
        "queued_by": username, "queued_at": int(time.time()),
    }
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)
    with _agent_streams_lock:
        _agent_streams.setdefault(hostname, {})[cmd_id] = {"started": int(time.time())}
    db.audit_log("agent_stream_logs", username, f"host={hostname} id={cmd_id} unit={unit}", ip)
    return {"status": "queued", "stream_id": cmd_id}


@router.delete("/api/agents/{hostname}/stream-logs/{cmd_id}")
async def api_agent_stop_stream(hostname: str, cmd_id: str, auth=Depends(_require_admin)):
    """Stop a running log stream on a remote agent."""
    username, _ = auth
    stop_id = secrets.token_hex(8)
    cmd = {
        "id": stop_id, "type": "stop_stream",
        "params": {"stream_id": cmd_id},
        "queued_by": username, "queued_at": int(time.time()),
    }
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)
    with _agent_streams_lock:
        host_streams = _agent_streams.get(hostname, {})
        host_streams.pop(cmd_id, None)
    # Clean up server-side line buffer
    with _agent_stream_lines_lock:
        _agent_stream_lines.pop(cmd_id, None)
    return {"status": "queued", "id": stop_id}


@router.get("/api/agents/{hostname}/streams")
def api_agent_active_streams(hostname: str, auth=Depends(_get_auth)):
    """List active log streams for an agent."""
    with _agent_streams_lock:
        streams = _agent_streams.get(hostname, {})
    return {"streams": [{"stream_id": sid, **info} for sid, info in streams.items()]}


@router.get("/api/sla/summary")
def api_sla_summary(request: Request, auth=Depends(_get_auth)):
    """SLA uptime summary across all agents and key services."""
    hours = min(int(request.query_params.get("hours", "720")), 8760)
    incidents = db.get_incidents(limit=1000, hours=hours)
    total_seconds = hours * 3600
    downtime_by_source: dict[str, int] = {}
    for inc in incidents:
        source = inc.get("source", "unknown")
        duration = (inc.get("resolved_at") or int(time.time())) - inc.get("timestamp", 0)
        downtime_by_source[source] = downtime_by_source.get(source, 0) + max(duration, 0)
    sla = []
    with _agent_data_lock:
        for hostname in _agent_data:
            down = downtime_by_source.get(hostname, 0)
            uptime_pct = round(max(0, (total_seconds - down) / total_seconds * 100), 2)
            sla.append({"name": hostname, "type": "agent", "uptime_pct": uptime_pct,
                        "downtime_s": down, "incidents": sum(1 for i in incidents if i.get("source") == hostname)})
    for source, down in downtime_by_source.items():
        if not any(s["name"] == source for s in sla):
            uptime_pct = round(max(0, (total_seconds - down) / total_seconds * 100), 2)
            sla.append({"name": source, "type": "service", "uptime_pct": uptime_pct,
                        "downtime_s": down, "incidents": sum(1 for i in incidents if i.get("source") == source)})
    sla.sort(key=lambda s: s["uptime_pct"])
    return {"period_hours": hours, "sla": sla}


@router.get("/api/agent/update")
def api_agent_update(request: Request):
    """Serve the latest agent.py for self-update. Auth via X-Agent-Key."""
    key = request.headers.get("X-Agent-Key", "")
    if not key:
        raise HTTPException(401, "Missing X-Agent-Key")
    cfg = read_yaml_settings()
    valid_keys = [k.strip() for k in cfg.get("agentKeys", "").split(",") if k.strip()]
    if not valid_keys or key not in valid_keys:
        raise HTTPException(403, "Invalid agent key")
    agent_path = _WEB_DIR.parent / "noba-agent" / "agent.py"
    if not agent_path.exists():
        raise HTTPException(404, "Agent file not found")
    return FileResponse(agent_path, media_type="text/x-python")


@router.get("/api/agent/install-script")
def api_agent_install_script(request: Request):
    """Generate a one-liner install script. Auth via X-Agent-Key."""
    key = request.headers.get("X-Agent-Key", "") or request.query_params.get("key", "")
    if not key:
        raise HTTPException(401, "Missing agent key")
    cfg = read_yaml_settings()
    valid_keys = [k.strip() for k in cfg.get("agentKeys", "").split(",") if k.strip()]
    if not valid_keys or key not in valid_keys:
        raise HTTPException(403, "Invalid agent key")
    host = request.headers.get("X-Forwarded-Host", request.headers.get("Host", "localhost:8080"))
    scheme = request.headers.get("X-Forwarded-Proto", "http")
    server_url = f"{scheme}://{host}"
    script = f"""#!/bin/bash
# NOBA Agent -- Auto-installer
set -e
INSTALL_DIR="/opt/noba-agent"
SERVER="{server_url}"
KEY="{key}"
HOSTNAME="$(hostname)"

echo "[noba] Installing agent on $HOSTNAME..."
sudo mkdir -p "$INSTALL_DIR"
curl -sf "$SERVER/api/agent/update" -H "X-Agent-Key: $KEY" -o "$INSTALL_DIR/agent.py"
sudo chmod +x "$INSTALL_DIR/agent.py"

# Install psutil if possible
command -v apt-get &>/dev/null && sudo apt-get install -y python3-psutil 2>/dev/null || true
command -v dnf &>/dev/null && sudo dnf install -y python3-psutil 2>/dev/null || true

# Write config
sudo tee /etc/noba-agent.yaml > /dev/null <<EOF
server: $SERVER
api_key: $KEY
interval: 30
hostname: $HOSTNAME
EOF

# Install systemd service
sudo tee /etc/systemd/system/noba-agent.service > /dev/null <<EOF
[Unit]
Description=NOBA Agent
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=$(command -v python3) $INSTALL_DIR/agent.py --config /etc/noba-agent.yaml
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now noba-agent
echo "[noba] Agent installed and running on $HOSTNAME"
"""
    return Response(content=script, media_type="text/x-shellscript",
                    headers={"Content-Disposition": "inline"})


@router.post("/api/agents/deploy")
async def api_agent_deploy(request: Request, auth=Depends(_require_admin)):
    """Remote deploy: SSH into a node and install the agent."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    target_host = body.get("host", "")
    ssh_user = body.get("ssh_user", "")
    ssh_pass = body.get("ssh_pass", "")
    target_port = _safe_int(body.get("ssh_port", 22), 22)
    if target_port < 1 or target_port > 65535:
        target_port = 22

    if not target_host or not ssh_user:
        raise HTTPException(400, "host and ssh_user are required")

    if not re.match(r'^[a-zA-Z0-9._:-]+$', target_host):
        raise HTTPException(400, "Invalid hostname")
    if not re.match(r'^[a-zA-Z0-9._-]+$', ssh_user) or len(ssh_user) > 64:
        raise HTTPException(400, "Invalid ssh_user")

    cfg = read_yaml_settings()
    agent_keys = cfg.get("agentKeys", "")
    if not agent_keys:
        raise HTTPException(400, "No agent keys configured. Set agentKeys in settings first.")
    agent_key = agent_keys.split(",")[0].strip()

    host_header = request.headers.get("Host", "localhost:8080")
    server_url = f"http://{host_header}"

    agent_path = _WEB_DIR.parent / "noba-agent" / "agent.py"
    if not agent_path.exists():
        raise HTTPException(500, "Agent file not found on server")

    import shutil
    if not shutil.which("sshpass"):
        raise HTTPException(400, "sshpass not installed on server. Use the install script method instead.")

    ssh_opts = "-o StrictHostKeyChecking=no -o ConnectTimeout=10"
    target = f"{ssh_user}@{target_host}"
    env = {**os.environ, "SSHPASS": ssh_pass} if ssh_pass else os.environ
    ssh_cmd = f"sshpass -e ssh -p {target_port}" if ssh_pass else f"ssh -p {target_port}"
    scp_cmd = f"sshpass -e scp -P {target_port}" if ssh_pass else f"scp -P {target_port}"

    try:
        result = subprocess.run(
            f"{scp_cmd} {ssh_opts} {agent_path} {target}:/tmp/noba-agent.py",
            shell=True, capture_output=True, text=True, timeout=30, env=env,
        )
        if result.returncode != 0:
            return {"status": "error", "step": "copy", "error": result.stderr[:500]}

        install_cmds = f"""
sudo mkdir -p /opt/noba-agent
sudo cp /tmp/noba-agent.py /opt/noba-agent/agent.py
sudo chmod +x /opt/noba-agent/agent.py
command -v apt-get >/dev/null && sudo apt-get install -y python3-psutil 2>/dev/null || true
command -v dnf >/dev/null && sudo dnf install -y python3-psutil 2>/dev/null || true
sudo tee /etc/noba-agent.yaml > /dev/null <<AGENTCFG
server: {server_url}
api_key: {agent_key}
interval: 30
hostname: $(hostname)
AGENTCFG
sudo tee /etc/systemd/system/noba-agent.service > /dev/null <<SVC
[Unit]
Description=NOBA Agent
After=network-online.target
[Service]
Type=simple
ExecStart=$(command -v python3 || echo /usr/bin/python3) /opt/noba-agent/agent.py --config /etc/noba-agent.yaml
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
SVC
sudo systemctl daemon-reload
sudo systemctl enable --now noba-agent 2>&1
systemctl is-active noba-agent
"""
        result = subprocess.run(
            f'{ssh_cmd} {ssh_opts} {target} "bash -s"',
            input=install_cmds, shell=True, capture_output=True, text=True,
            timeout=60, env=env,
        )
        success = "active" in result.stdout
        db.audit_log("agent_deploy", username, f"host={target_host} user={ssh_user} ok={success}", ip)
        return {
            "status": "ok" if success else "error",
            "host": target_host,
            "output": result.stdout[:1000],
            "error": result.stderr[:500] if not success else "",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "SSH connection timed out"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── File transfer endpoints (Phase 1c) ──────────────────────────────────────
@router.post("/api/agent/file-upload")
async def api_agent_file_upload(request: Request):
    """Receive a file chunk from an agent."""
    key = request.headers.get("X-Agent-Key", "")
    if not _validate_agent_key(key):
        raise HTTPException(401, "Invalid agent key")

    transfer_id = request.headers.get("X-Transfer-Id", "")
    chunk_index_raw = request.headers.get("X-Chunk-Index", "-1")
    total_chunks_raw = request.headers.get("X-Total-Chunks", "0")
    filename = request.headers.get("X-Filename", "unknown")
    checksum = request.headers.get("X-File-Checksum", "")
    hostname = request.headers.get("X-Agent-Hostname", "unknown")

    try:
        chunk_index = int(chunk_index_raw)
        total_chunks = int(total_chunks_raw)
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid chunk headers")

    if not transfer_id or chunk_index < 0 or total_chunks <= 0:
        raise HTTPException(400, "Missing transfer headers")

    body = await request.body()
    if len(body) > _CHUNK_SIZE + 1024:
        raise HTTPException(413, "Chunk too large")

    # Initialize transfer on first chunk
    with _transfer_lock:
        if transfer_id not in _transfers:
            _transfers[transfer_id] = {
                "hostname": hostname,
                "filename": filename,
                "checksum": checksum,
                "total_chunks": total_chunks,
                "received_chunks": set(),
                "created_at": int(time.time()),
                "direction": "upload",
            }

    # Write chunk to disk
    chunk_path = os.path.join(_TRANSFER_DIR, f"{transfer_id}.chunk{chunk_index}")
    with open(chunk_path, "wb") as f:
        f.write(body)

    with _transfer_lock:
        _transfers[transfer_id]["received_chunks"].add(chunk_index)
        received = len(_transfers[transfer_id]["received_chunks"])
        complete = received == total_chunks

    result: dict = {"status": "ok", "received": chunk_index, "progress": f"{received}/{total_chunks}"}

    # If all chunks received, reassemble and verify
    if complete:
        final_path = os.path.join(_TRANSFER_DIR, f"{transfer_id}_{filename}")
        with open(final_path, "wb") as out:
            for i in range(total_chunks):
                cp = os.path.join(_TRANSFER_DIR, f"{transfer_id}.chunk{i}")
                with open(cp, "rb") as chunk_f:
                    out.write(chunk_f.read())
                os.remove(cp)

        # Verify checksum
        if checksum.startswith("sha256:"):
            expected = checksum.split(":", 1)[1]
            h = hashlib.sha256()
            with open(final_path, "rb") as f:
                while True:
                    block = f.read(65536)
                    if not block:
                        break
                    h.update(block)
            actual = h.hexdigest()
            if actual != expected:
                os.remove(final_path)
                with _transfer_lock:
                    _transfers.pop(transfer_id, None)
                raise HTTPException(422, f"Checksum mismatch: expected {expected}, got {actual}")

        with _transfer_lock:
            _transfers[transfer_id]["final_path"] = final_path
            _transfers[transfer_id]["complete"] = True

        result["complete"] = True
        result["path"] = final_path

    return result


@router.get("/api/agent/file-download/{transfer_id}")
async def api_agent_file_download(transfer_id: str, request: Request):
    """Serve a file to an agent for file_push command."""
    key = request.headers.get("X-Agent-Key", "")
    if not _validate_agent_key(key):
        raise HTTPException(401, "Invalid agent key")

    with _transfer_lock:
        transfer = _transfers.get(transfer_id)
    if not transfer:
        raise HTTPException(404, "Transfer not found")
    if transfer.get("direction") != "download":
        raise HTTPException(400, "Not a download transfer")

    file_path = transfer.get("final_path", "")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(404, "File not found")

    return FileResponse(
        file_path,
        filename=transfer.get("filename", "download"),
        media_type="application/octet-stream",
        headers={"X-File-Checksum": transfer.get("checksum", "")},
    )


@router.post("/api/agents/{hostname}/transfer")
async def api_agent_transfer(hostname: str, request: Request, auth=Depends(_require_admin)):
    """Initiate a file push to an agent. Admin uploads the file first."""
    username, _ = auth
    ip = _client_ip(request)

    dest_path = request.query_params.get("path", "")
    if not dest_path:
        raise HTTPException(400, "Destination path required (?path=...)")

    body = await request.body()
    if len(body) > _MAX_TRANSFER_SIZE:
        raise HTTPException(413, f"File too large (max {_MAX_TRANSFER_SIZE // 1024 // 1024}MB)")

    checksum = f"sha256:{hashlib.sha256(body).hexdigest()}"

    transfer_id = secrets.token_hex(16)
    filename = os.path.basename(dest_path) or "file"
    file_path = os.path.join(_TRANSFER_DIR, f"{transfer_id}_{filename}")
    with open(file_path, "wb") as f:
        f.write(body)

    with _transfer_lock:
        _transfers[transfer_id] = {
            "hostname": hostname,
            "filename": filename,
            "checksum": checksum,
            "final_path": file_path,
            "created_at": int(time.time()),
            "direction": "download",
            "dest_path": dest_path,
            "complete": True,
        }

    # Queue file_push command for the agent
    cmd_id = secrets.token_hex(8)
    cmd = {
        "id": cmd_id,
        "type": "file_push",
        "params": {"path": dest_path, "transfer_id": transfer_id},
        "queued_by": username,
        "queued_at": int(time.time()),
    }

    # Try WebSocket first, fall back to queue
    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"type": "command", "cmd": "file_push", **cmd})
            delivered = True
        except Exception:
            pass
    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)

    db.audit_log("agent_file_push", username,
                 f"host={hostname} path={dest_path} id={transfer_id}", ip)
    return {"status": "queued", "transfer_id": transfer_id, "cmd_id": cmd_id}


# ── Incident endpoints ───────────────────────────────────────────────────────
@router.get("/api/incidents")
def api_incidents(request: Request, auth=Depends(_get_auth)):
    hours = _safe_int(request.query_params.get("hours", "24"), 24)
    return db.get_incidents(limit=200, hours=min(hours, 168))


@router.post("/api/incidents/{incident_id}/resolve")
def api_resolve_incident(incident_id: int, request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    db.resolve_incident(incident_id)
    db.audit_log("incident_resolved", username, f"id={incident_id}", _client_ip(request))
    return {"status": "ok"}


# ── Network discovery endpoints ───────────────────────────────────────────────

@router.get("/api/network/devices")
def api_network_devices(auth=Depends(_get_auth)):
    """List all discovered network devices."""
    return db.list_network_devices()


@router.post("/api/network/discover/{hostname}")
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
def api_delete_network_device(device_id: int, request: Request, auth=Depends(_require_operator)):
    """Remove a discovered network device."""
    username, _ = auth
    ok = db.delete_network_device(device_id)
    if not ok:
        raise HTTPException(404, f"Device {device_id} not found")
    db.audit_log("network_device_delete", username,
                 f"device_id={device_id}", _client_ip(request))
    return {"status": "ok"}


# ── Status page endpoints ────────────────────────────────────────────────────
@router.get("/status")
def public_status_page():
    """Public-facing status page -- no auth required."""
    return FileResponse(_WEB_DIR / "status.html")


@router.get("/api/status/public")
def api_public_status():
    """Public status data -- no auth required.

    Returns components with live status, active incidents, and 90-day uptime history.
    Falls back to legacy metric-driven services when no components are configured.
    """
    # Components from the DB
    components = db.list_status_components()
    collector_data = (_deps.bg_collector.get() if _deps.bg_collector else None) or {}

    # Enrich components with live status from collector
    enriched: list[dict] = []
    for comp in components:
        if not comp["enabled"]:
            continue
        status = "operational"
        if comp["service_key"]:
            val = collector_data.get(comp["service_key"])
            if val is None:
                status = "unknown"
            elif isinstance(val, dict) and val.get("status"):
                status = "operational" if val["status"] in ("online", "enabled", "ok") else "degraded"
            elif isinstance(val, list) and len(val) > 0:
                status = "operational"
            else:
                status = "operational" if val else "unknown"
        enriched.append({
            "id": comp["id"], "name": comp["name"],
            "group_name": comp["group_name"], "status": status,
        })

    # Legacy fallback: if no components configured, use statusPageServices from YAML
    if not enriched:
        cfg = read_yaml_settings()
        status_services = [s.strip() for s in cfg.get("statusPageServices", "").split(",") if s.strip()]
        for svc in status_services:
            val = collector_data.get(svc)
            if val is None:
                status = "unknown"
            elif isinstance(val, dict) and val.get("status"):
                status = "operational" if val["status"] in ("online", "enabled", "ok") else "degraded"
            elif isinstance(val, list) and len(val) > 0:
                status = "operational"
            else:
                status = "operational" if val else "unknown"
            enriched.append({"name": svc, "group_name": "Default", "status": status})

    # Active incidents
    active_incidents = db.list_status_incidents(limit=20, include_resolved=False)
    # Enrich with updates
    for inc in active_incidents:
        detail = db.get_status_incident(inc["id"])
        inc["updates"] = detail["updates"] if detail else []

    # Determine overall status
    overall = "operational"
    has_active = len(active_incidents) > 0
    any_critical = any(i["severity"] == "critical" for i in active_incidents)
    any_major = any(i["severity"] == "major" for i in active_incidents)
    if any_critical:
        overall = "major_outage"
    elif any_major or any(s["status"] == "degraded" for s in enriched):
        overall = "degraded"
    elif has_active:
        overall = "degraded"

    # 90-day uptime history
    uptime_history = db.get_status_uptime_history(days=90)

    return {
        "components": enriched,
        "services": enriched,  # backward compat
        "active_incidents": active_incidents,
        "uptime_history": uptime_history,
        "overall": overall,
        "timestamp": int(time.time()),
    }


@router.get("/api/status/incidents")
def api_public_status_incidents():
    """Public: list recent status incidents with their updates."""
    incidents = db.list_status_incidents(limit=50, include_resolved=True)
    for inc in incidents:
        detail = db.get_status_incident(inc["id"])
        inc["updates"] = detail["updates"] if detail else []
    return {"incidents": incidents}


# ── Status page admin endpoints ──────────────────────────────────────────────
@router.post("/api/status/components")
async def api_create_status_component(request: Request, auth=Depends(_require_admin)):
    """Admin: create a status page component."""
    username, _ = auth
    body = await _read_body(request)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    comp_id = db.create_status_component(
        name=name,
        group_name=body.get("group_name", "Default"),
        service_key=body.get("service_key"),
        display_order=int(body.get("display_order", 0)),
    )
    if not comp_id:
        raise HTTPException(500, "Failed to create component")
    db.audit_log("status_component_create", username, f"id={comp_id} name={name}", _client_ip(request))
    return {"id": comp_id, "status": "ok"}


@router.put("/api/status/components/{comp_id}")
async def api_update_status_component(comp_id: int, request: Request, auth=Depends(_require_admin)):
    """Admin: update a status page component."""
    username, _ = auth
    body = await _read_body(request)
    ok = db.update_status_component(comp_id, **{
        k: v for k, v in body.items()
        if k in ("name", "group_name", "service_key", "display_order", "enabled")
    })
    if not ok:
        raise HTTPException(404, "Component not found or no changes")
    db.audit_log("status_component_update", username, f"id={comp_id}", _client_ip(request))
    return {"status": "ok"}


@router.delete("/api/status/components/{comp_id}")
def api_delete_status_component(comp_id: int, request: Request, auth=Depends(_require_admin)):
    """Admin: delete a status page component."""
    username, _ = auth
    ok = db.delete_status_component(comp_id)
    if not ok:
        raise HTTPException(404, "Component not found")
    db.audit_log("status_component_delete", username, f"id={comp_id}", _client_ip(request))
    return {"status": "ok"}


@router.get("/api/status/components")
def api_list_status_components(auth=Depends(_get_auth)):
    """Authenticated: list all status components (for admin UI)."""
    return {"components": db.list_status_components()}


@router.post("/api/status/incidents/create")
async def api_create_status_incident(request: Request, auth=Depends(_require_admin)):
    """Admin: create a status page incident."""
    username, _ = auth
    body = await _read_body(request)
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title is required")
    severity = body.get("severity", "minor")
    if severity not in ("minor", "major", "critical"):
        raise HTTPException(400, "severity must be minor, major, or critical")
    message = (body.get("message") or "").strip()
    incident_id = db.create_status_incident(
        title=title, severity=severity, message=message, created_by=username,
    )
    if not incident_id:
        raise HTTPException(500, "Failed to create incident")
    db.audit_log("status_incident_create", username, f"id={incident_id} title={title}", _client_ip(request))
    return {"id": incident_id, "status": "ok"}


@router.post("/api/status/incidents/{incident_id}/update")
async def api_add_status_update(incident_id: int, request: Request, auth=Depends(_require_admin)):
    """Admin: add an update to a status incident."""
    username, _ = auth
    body = await _read_body(request)
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message is required")
    status = body.get("status", "investigating")
    if status not in ("investigating", "identified", "monitoring", "resolved"):
        raise HTTPException(400, "status must be investigating, identified, monitoring, or resolved")
    update_id = db.add_status_update(
        incident_id=incident_id, message=message, status=status, created_by=username,
    )
    if not update_id:
        raise HTTPException(404, "Incident not found or failed to add update")
    db.audit_log("status_incident_update", username, f"incident={incident_id} status={status}", _client_ip(request))
    return {"id": update_id, "status": "ok"}


@router.put("/api/status/incidents/{incident_id}/resolve")
def api_resolve_status_incident(incident_id: int, request: Request, auth=Depends(_require_admin)):
    """Admin: resolve a status incident."""
    username, _ = auth
    ok = db.resolve_status_incident(incident_id, created_by=username)
    if not ok:
        raise HTTPException(404, "Incident not found")
    db.audit_log("status_incident_resolve", username, f"id={incident_id}", _client_ip(request))
    return {"status": "ok"}


# ── Incident War Room endpoints ──────────────────────────────────────────────
@router.get("/api/incidents/{incident_id}/messages")
def api_get_incident_messages(incident_id: int, auth=Depends(_get_auth)):
    """Get the war room message thread for a status incident."""
    incident = db.get_status_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    messages = db.get_incident_messages(incident_id)
    return {"incident_id": incident_id, "messages": messages}


@router.post("/api/incidents/{incident_id}/messages")
async def api_post_incident_message(
    incident_id: int, request: Request, auth=Depends(_require_operator),
):
    """Post a message to the incident war room (operator+)."""
    username, _ = auth
    incident = db.get_status_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    body = await _read_body(request)
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message is required")
    msg_type = body.get("msg_type", "comment")
    if msg_type not in ("comment", "system", "action", "note"):
        raise HTTPException(400, "msg_type must be comment, system, action, or note")
    msg_id = db.add_incident_message(incident_id, username, message, msg_type=msg_type)
    if not msg_id:
        raise HTTPException(500, "Failed to post message")
    db.audit_log("incident_message", username, f"incident={incident_id}", _client_ip(request))
    return {"id": msg_id, "status": "ok"}


@router.put("/api/incidents/{incident_id}/assign")
async def api_assign_incident(
    incident_id: int, request: Request, auth=Depends(_require_operator),
):
    """Assign a status incident to a user (operator+)."""
    username, _ = auth
    incident = db.get_status_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    body = await _read_body(request)
    assigned_to = (body.get("assigned_to") or "").strip()
    if not assigned_to:
        raise HTTPException(400, "assigned_to is required")
    ok = db.assign_incident(incident_id, assigned_to)
    if not ok:
        raise HTTPException(500, "Failed to assign incident")
    # Post system message about the assignment
    db.add_incident_message(
        incident_id, username,
        f"Assigned incident to {assigned_to}",
        msg_type="system",
    )
    db.audit_log(
        "incident_assign", username,
        f"incident={incident_id} assigned_to={assigned_to}",
        _client_ip(request),
    )
    return {"status": "ok", "assigned_to": assigned_to}


# ── Endpoint monitor endpoints ────────────────────────────────────────────────
@router.get("/api/endpoints")
def api_list_endpoints(auth=Depends(_get_auth)):
    """List all endpoint monitors with latest status."""
    return db.get_endpoint_monitors()


@router.post("/api/endpoints")
async def api_create_endpoint(request: Request, auth=Depends(_require_admin)):
    """Create a new endpoint monitor."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    if not name or not url:
        raise HTTPException(400, "Name and URL are required")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL must start with http:// or https://")
    kwargs = {}
    if "method" in body:
        m = str(body["method"]).upper()
        if m in ("GET", "HEAD"):
            kwargs["method"] = m
    for int_field in ("expected_status", "check_interval", "timeout", "notify_cert_days"):
        if int_field in body:
            try:
                kwargs[int_field] = int(body[int_field])
            except (TypeError, ValueError):
                pass
    if "agent_hostname" in body:
        kwargs["agent_hostname"] = body["agent_hostname"] or None
    if "enabled" in body:
        kwargs["enabled"] = bool(body["enabled"])
    monitor_id = db.create_endpoint_monitor(name, url, **kwargs)
    if monitor_id is None:
        raise HTTPException(500, "Failed to create monitor")
    db.audit_log("endpoint_create", username, f"id={monitor_id} name={name} url={url}", ip)
    return {"status": "ok", "id": monitor_id}


@router.put("/api/endpoints/{monitor_id}")
async def api_update_endpoint(monitor_id: int, request: Request, auth=Depends(_require_admin)):
    """Update an endpoint monitor."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    kwargs = {}
    if "name" in body:
        kwargs["name"] = str(body["name"]).strip()
    if "url" in body:
        u = str(body["url"]).strip()
        if not u.startswith(("http://", "https://")):
            raise HTTPException(400, "URL must start with http:// or https://")
        kwargs["url"] = u
    if "method" in body:
        m = str(body["method"]).upper()
        if m in ("GET", "HEAD"):
            kwargs["method"] = m
    for int_field in ("expected_status", "check_interval", "timeout", "notify_cert_days"):
        if int_field in body:
            try:
                kwargs[int_field] = int(body[int_field])
            except (TypeError, ValueError):
                pass
    if "agent_hostname" in body:
        kwargs["agent_hostname"] = body["agent_hostname"] or None
    if "enabled" in body:
        kwargs["enabled"] = bool(body["enabled"])
    ok = db.update_endpoint_monitor(monitor_id, **kwargs)
    if not ok:
        raise HTTPException(404, "Monitor not found or no changes")
    db.audit_log("endpoint_update", username, f"id={monitor_id}", ip)
    return {"status": "ok"}


@router.delete("/api/endpoints/{monitor_id}")
async def api_delete_endpoint(monitor_id: int, request: Request, auth=Depends(_require_admin)):
    """Delete an endpoint monitor."""
    username, _ = auth
    ip = _client_ip(request)
    ok = db.delete_endpoint_monitor(monitor_id)
    if not ok:
        raise HTTPException(404, "Monitor not found")
    db.audit_log("endpoint_delete", username, f"id={monitor_id}", ip)
    return {"status": "ok"}


@router.post("/api/endpoints/{monitor_id}/check")
async def api_check_endpoint_now(monitor_id: int, request: Request, auth=Depends(_require_operator)):
    """Trigger an immediate endpoint check."""
    username, _ = auth
    ip = _client_ip(request)
    monitor = db.get_endpoint_monitor(monitor_id)
    if not monitor:
        raise HTTPException(404, "Monitor not found")

    from ..scheduler import _run_endpoint_check
    result = _run_endpoint_check(monitor)
    db.audit_log("endpoint_check_now", username,
                 f"id={monitor_id} name={monitor['name']} result={result.get('last_status', '?')}", ip)
    return result


# ── Custom dashboard endpoints ─────────────────────────────────────────────────
@router.get("/api/dashboards")
def api_list_dashboards(auth=Depends(_get_auth)):
    """List dashboards visible to the current user (own + shared)."""
    username, _ = auth
    return db.get_dashboards(owner=username)


@router.post("/api/dashboards")
async def api_create_dashboard(request: Request, auth=Depends(_get_auth)):
    """Create a new custom dashboard."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    name = (body.get("name") or "").strip()
    config_json = body.get("config_json", "")
    if not name:
        raise HTTPException(400, "Dashboard name is required")
    if not config_json:
        raise HTTPException(400, "Dashboard config is required")
    # Validate that config_json is valid JSON
    try:
        json.loads(config_json) if isinstance(config_json, str) else None
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(400, "config_json must be valid JSON")
    if isinstance(config_json, (dict, list)):
        config_json = json.dumps(config_json)
    shared = bool(body.get("shared", False))
    dashboard_id = db.create_dashboard(name, username, config_json, shared=shared)
    if dashboard_id is None:
        raise HTTPException(500, "Failed to create dashboard")
    db.audit_log("dashboard_create", username, f"id={dashboard_id} name={name}", ip)
    return {"status": "ok", "id": dashboard_id}


@router.put("/api/dashboards/{dashboard_id}")
async def api_update_dashboard(dashboard_id: int, request: Request, auth=Depends(_get_auth)):
    """Update a custom dashboard (owner or admin only)."""
    username, role = auth
    ip = _client_ip(request)
    existing = db.get_dashboard(dashboard_id)
    if not existing:
        raise HTTPException(404, "Dashboard not found")
    if existing["owner"] != username and role != "admin":
        raise HTTPException(403, "Only the owner or an admin can update this dashboard")
    body = await _read_body(request)
    kwargs = {}
    if "name" in body:
        n = str(body["name"]).strip()
        if n:
            kwargs["name"] = n
    if "config_json" in body:
        cj = body["config_json"]
        if isinstance(cj, (dict, list)):
            cj = json.dumps(cj)
        try:
            json.loads(cj)
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(400, "config_json must be valid JSON")
        kwargs["config_json"] = cj
    if "shared" in body:
        kwargs["shared"] = bool(body["shared"])
    ok = db.update_dashboard(dashboard_id, **kwargs)
    if not ok:
        raise HTTPException(404, "Dashboard not found or no changes")
    db.audit_log("dashboard_update", username, f"id={dashboard_id}", ip)
    return {"status": "ok"}


@router.delete("/api/dashboards/{dashboard_id}")
async def api_delete_dashboard(dashboard_id: int, request: Request, auth=Depends(_get_auth)):
    """Delete a custom dashboard (owner or admin only)."""
    username, role = auth
    ip = _client_ip(request)
    existing = db.get_dashboard(dashboard_id)
    if not existing:
        raise HTTPException(404, "Dashboard not found")
    if existing["owner"] != username and role != "admin":
        raise HTTPException(403, "Only the owner or an admin can delete this dashboard")
    ok = db.delete_dashboard(dashboard_id)
    if not ok:
        raise HTTPException(404, "Dashboard not found")
    db.audit_log("dashboard_delete", username, f"id={dashboard_id}", ip)
    return {"status": "ok"}


# ── Service dependency topology endpoints ──────────────────────────────────────
@router.get("/api/dependencies")
def api_list_dependencies(auth=Depends(_get_auth)):
    """List all service dependencies as graph data (nodes + edges)."""
    deps = db.list_dependencies()
    # Build node set from all mentioned services
    node_set: set[str] = set()
    edges = []
    for d in deps:
        node_set.add(d["source_service"])
        node_set.add(d["target_service"])
        edges.append({
            "id": d["id"],
            "source": d["source_service"],
            "target": d["target_service"],
            "type": d["dependency_type"],
            "auto_discovered": d["auto_discovered"],
        })
    # Determine node health from agent data
    nodes = []
    for name in sorted(node_set):
        health = "unknown"
        with _agent_data_lock:
            agent = _agent_data.get(name)
        if agent:
            age = time.time() - agent.get("last_seen", 0)
            if age < _AGENT_MAX_AGE:
                cpu = agent.get("cpu_percent", 0) or 0
                mem = agent.get("mem_percent", 0) or 0
                if cpu > 90 or mem > 95:
                    health = "critical"
                elif cpu > 70 or mem > 80:
                    health = "warning"
                else:
                    health = "healthy"
            else:
                health = "offline"
        nodes.append({"id": name, "label": name, "health": health})
    return {"nodes": nodes, "edges": edges, "dependencies": deps}


@router.post("/api/dependencies")
async def api_create_dependency(request: Request, auth=Depends(_require_admin)):
    """Create a manual service dependency."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    source = (body.get("source") or "").strip()
    target = (body.get("target") or "").strip()
    dep_type = (body.get("type") or "requires").strip()
    if not source or not target:
        raise HTTPException(400, "Both 'source' and 'target' are required")
    if source == target:
        raise HTTPException(400, "A service cannot depend on itself")
    if dep_type not in ("requires", "optional", "network"):
        raise HTTPException(400, "Invalid dependency type")
    dep_id = db.create_dependency(source, target, dependency_type=dep_type)
    if dep_id is None:
        raise HTTPException(500, "Failed to create dependency")
    db.audit_log("dependency_create", username,
                 f"id={dep_id} {source}->{target} type={dep_type}", ip)
    return {"status": "ok", "id": dep_id}


@router.delete("/api/dependencies/{dep_id}")
def api_delete_dependency(dep_id: int, request: Request, auth=Depends(_require_admin)):
    """Delete a service dependency."""
    username, _ = auth
    ip = _client_ip(request)
    ok = db.delete_dependency(dep_id)
    if not ok:
        raise HTTPException(404, "Dependency not found")
    db.audit_log("dependency_delete", username, f"id={dep_id}", ip)
    return {"status": "ok"}


@router.get("/api/dependencies/impact/{service}")
def api_impact_analysis(service: str, auth=Depends(_get_auth)):
    """Return all services transitively dependent on the given service."""
    affected = db.get_impact_analysis(service)
    return {"service": service, "affected": affected, "count": len(affected)}


@router.post("/api/dependencies/discover/{hostname}")
async def api_discover_services(hostname: str, request: Request,
                                auth=Depends(_require_admin)):
    """Trigger discover_services command on a remote agent."""
    username, _ = auth
    ip = _client_ip(request)
    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": "discover_services", "params": {}}
    # Try WebSocket delivery first
    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"commands": [cmd]})
            delivered = True
        except Exception:
            pass
    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)
    db.record_command(cmd_id, hostname, "discover_services", {}, username)
    db.audit_log("discover_services", username,
                 f"host={hostname} id={cmd_id} ws={delivered}", ip)
    return {"status": "sent" if delivered else "queued", "id": cmd_id}


# ── Config drift / baseline endpoints ─────────────────────────────────────────
@router.get("/api/baselines")
def api_list_baselines(auth=Depends(_get_auth)):
    """List all config baselines with latest drift status summary."""
    return db.list_baselines()


@router.post("/api/baselines")
async def api_create_baseline(request: Request, auth=Depends(_require_admin)):
    """Create a new config baseline."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    path = (body.get("path") or "").strip()
    expected_hash = (body.get("expected_hash") or "").strip()
    agent_group = (body.get("agent_group") or "__all__").strip()
    if not path:
        raise HTTPException(400, "File path is required")
    if not expected_hash:
        raise HTTPException(400, "Expected hash is required")
    baseline_id = db.create_baseline(path, expected_hash, agent_group=agent_group)
    if baseline_id is None:
        raise HTTPException(500, "Failed to create baseline")
    db.audit_log("baseline_create", username,
                 f"id={baseline_id} path={path} group={agent_group}", ip)
    return {"status": "ok", "id": baseline_id}


@router.delete("/api/baselines/{baseline_id}")
async def api_delete_baseline(baseline_id: int, request: Request,
                              auth=Depends(_require_admin)):
    """Delete a config baseline and all its drift check history."""
    username, _ = auth
    ip = _client_ip(request)
    ok = db.delete_baseline(baseline_id)
    if not ok:
        raise HTTPException(404, "Baseline not found")
    db.audit_log("baseline_delete", username, f"id={baseline_id}", ip)
    return {"status": "ok"}


@router.post("/api/baselines/{baseline_id}/set-from/{hostname}")
async def api_baseline_set_from_agent(baseline_id: int, hostname: str,
                                      request: Request,
                                      auth=Depends(_require_admin)):
    """Set a baseline's expected hash from an agent's current file checksum.

    Sends a file_checksum command to the agent and waits for the result,
    then updates the baseline with the hash.
    """
    username, _ = auth
    ip = _client_ip(request)
    baseline = db.get_baseline(baseline_id)
    if not baseline:
        raise HTTPException(404, "Baseline not found")
    # Send file_checksum command to the agent
    cmd_id = secrets.token_hex(8)
    cmd = {
        "id": cmd_id,
        "type": "file_checksum",
        "params": {"path": baseline["path"], "algorithm": "sha256"},
    }
    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"type": "command", "id": cmd_id,
                                "cmd": "file_checksum",
                                "params": cmd["params"]})
            delivered = True
        except Exception:
            pass
    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)
    db.record_command(cmd_id, hostname, "file_checksum", cmd["params"], username)
    # Poll for result (up to 15s)
    import asyncio
    deadline = time.time() + 15
    agent_result = None
    while time.time() < deadline:
        with _agent_cmd_lock:
            results = _agent_cmd_results.get(hostname, [])
            for i, r in enumerate(results):
                if isinstance(r, dict) and r.get("id") == cmd_id:
                    agent_result = results.pop(i)
                    break
        if agent_result is not None:
            break
        await asyncio.sleep(0.5)
    if agent_result is None:
        raise HTTPException(504, "Agent did not respond in time")
    if agent_result.get("status") != "ok":
        raise HTTPException(502, agent_result.get("error", "Agent error"))
    new_hash = agent_result.get("checksum", "")
    if not new_hash:
        raise HTTPException(502, "Agent returned empty checksum")
    db.complete_command(cmd_id, agent_result)
    db.update_baseline(baseline_id, new_hash)
    db.audit_log("baseline_set_from_agent", username,
                 f"id={baseline_id} host={hostname} hash={new_hash[:16]}...", ip)
    return {"status": "ok", "expected_hash": new_hash}


@router.post("/api/baselines/check")
async def api_trigger_drift_check(request: Request, auth=Depends(_require_operator)):
    """Trigger an immediate drift check across all baselines."""
    username, _ = auth
    ip = _client_ip(request)
    from ..scheduler import drift_checker
    import threading
    threading.Thread(
        target=drift_checker.run_check_now, daemon=True, name="drift-check-manual"
    ).start()
    db.audit_log("drift_check_trigger", username, "manual", ip)
    return {"status": "ok", "message": "Drift check started"}


@router.get("/api/baselines/{baseline_id}/results")
def api_baseline_results(baseline_id: int, auth=Depends(_get_auth)):
    """Get drift check results per agent for a specific baseline."""
    baseline = db.get_baseline(baseline_id)
    if not baseline:
        raise HTTPException(404, "Baseline not found")
    results = db.get_drift_results(baseline_id=baseline_id)
    return {
        "baseline": baseline,
        "results": results,
    }


# ── AI / LLM endpoints ────────────────────────────────────────────────────────

def _get_llm_client():
    """Create an LLMClient from current settings. Returns None if not configured."""
    from ..llm import LLMClient
    cfg = read_yaml_settings()
    if not cfg.get("llmEnabled"):
        return None
    return LLMClient(cfg)


def _build_ai_context() -> str:
    """Build ops context string for the LLM system prompt."""
    from ..llm import build_ops_context
    with _agent_data_lock:
        snapshot = dict(_agent_data)
    return build_ops_context(read_yaml_settings, db, snapshot, _AGENT_MAX_AGE)


@router.get("/api/ai/status")
def api_ai_status(auth=Depends(_get_auth)):
    """Return AI/LLM configuration status."""
    cfg = read_yaml_settings()
    return {
        "enabled": bool(cfg.get("llmEnabled")),
        "provider": cfg.get("llmProvider", ""),
        "model": cfg.get("llmModel", ""),
    }


@router.post("/api/ai/chat")
async def api_ai_chat(request: Request, auth=Depends(_require_operator)):
    """Send a message to the AI assistant with optional conversation history."""
    from ..llm import extract_actions
    client = _get_llm_client()
    if not client:
        raise HTTPException(503, "LLM not configured")
    body = await _read_body(request)
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(400, "message is required")
    history = body.get("history", [])
    # Build messages list from history + current message
    messages: list[dict] = []
    for h in history[-20:]:  # Cap history at 20 turns
        role = h.get("role", "user")
        content = h.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    system = _build_ai_context()
    try:
        response = await client.chat(messages, system)
        actions = extract_actions(response)
        return {"response": response, "actions": actions}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI chat error: %s", e)
        raise HTTPException(502, f"LLM request failed: {e}")


@router.post("/api/ai/analyze-alert/{alert_id}")
async def api_ai_analyze_alert(alert_id: int, auth=Depends(_require_operator)):
    """Ask the AI to analyze a specific alert."""
    from ..llm import extract_actions
    client = _get_llm_client()
    if not client:
        raise HTTPException(503, "LLM not configured")
    # Fetch alert details
    alerts = db.get_alert_history(limit=100)
    alert = None
    for a in alerts:
        if a.get("id") == alert_id:
            alert = a
            break
    if not alert:
        raise HTTPException(404, "Alert not found")
    prompt = (
        f"Analyze this infrastructure alert and suggest remediation steps:\n\n"
        f"**Rule:** {alert.get('rule_id', 'unknown')}\n"
        f"**Severity:** {alert.get('severity', 'unknown')}\n"
        f"**Message:** {alert.get('message', 'N/A')}\n"
        f"**Time:** {alert.get('timestamp', 'unknown')}\n"
        f"**Resolved:** {'Yes' if alert.get('resolved_at') else 'No'}\n\n"
        f"What is likely causing this? What should the operator do? "
        f"If a command can fix it, include it as [ACTION:cmd:host:params]."
    )
    system = _build_ai_context()
    try:
        response = await client.chat([{"role": "user", "content": prompt}], system)
        actions = extract_actions(response)
        return {"response": response, "actions": actions}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI analyze-alert error: %s", e)
        raise HTTPException(502, f"LLM request failed: {e}")


@router.post("/api/ai/analyze-logs")
async def api_ai_analyze_logs(request: Request, auth=Depends(_require_operator)):
    """Ask the AI to analyze a log excerpt."""
    from ..llm import extract_actions
    client = _get_llm_client()
    if not client:
        raise HTTPException(503, "LLM not configured")
    body = await _read_body(request)
    logs = body.get("logs", "").strip()
    if not logs:
        raise HTTPException(400, "logs field is required")
    # Truncate to ~8000 chars to stay within reasonable token limits
    if len(logs) > 8000:
        logs = logs[:8000] + "\n... (truncated)"
    prompt = (
        f"Analyze these log entries and identify any issues, errors, or anomalies. "
        f"Explain what happened and suggest fixes.\n\n```\n{logs}\n```\n\n"
        f"If a command can fix the issue, include it as [ACTION:cmd:host:params]."
    )
    system = _build_ai_context()
    try:
        response = await client.chat([{"role": "user", "content": prompt}], system)
        actions = extract_actions(response)
        return {"response": response, "actions": actions}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI analyze-logs error: %s", e)
        raise HTTPException(502, f"LLM request failed: {e}")


@router.post("/api/ai/summarize-incident/{incident_id}")
async def api_ai_summarize_incident(incident_id: int, auth=Depends(_require_operator)):
    """Generate an AI summary/report for an incident."""
    from ..llm import extract_actions
    client = _get_llm_client()
    if not client:
        raise HTTPException(503, "LLM not configured")
    incidents = db.get_incidents(limit=200, hours=168)
    incident = None
    for inc in incidents:
        if inc.get("id") == incident_id:
            incident = inc
            break
    if not incident:
        raise HTTPException(404, "Incident not found")
    prompt = (
        f"Generate a brief incident report for the following event:\n\n"
        f"**ID:** {incident.get('id')}\n"
        f"**Severity:** {incident.get('severity', 'unknown')}\n"
        f"**Source:** {incident.get('source', 'unknown')}\n"
        f"**Title:** {incident.get('title', 'N/A')}\n"
        f"**Details:** {incident.get('details', 'N/A')}\n"
        f"**Status:** {'Resolved' if incident.get('resolved_at') else 'Open'}\n\n"
        f"Include: root cause hypothesis, impact assessment, and recommended next steps. "
        f"If a command can help, include it as [ACTION:cmd:host:params]."
    )
    system = _build_ai_context()
    try:
        response = await client.chat([{"role": "user", "content": prompt}], system)
        actions = extract_actions(response)
        return {"response": response, "actions": actions}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI summarize-incident error: %s", e)
        raise HTTPException(502, f"LLM request failed: {e}")


# ── Security Posture Scoring ──────────────────────────────────────────────────

@router.get("/api/security/score")
def api_security_score(auth=Depends(_get_auth)):
    """Return aggregate security score + per-agent scores."""
    return db.get_aggregate_security_score()


@router.get("/api/security/findings")
def api_security_findings(request: Request, auth=Depends(_get_auth)):
    """Return security findings with optional hostname/severity filters."""
    hostname = request.query_params.get("hostname", "") or None
    severity = request.query_params.get("severity", "") or None
    limit = min(_safe_int(request.query_params.get("limit", "200"), 200), 500)
    return db.get_security_findings(hostname=hostname, severity=severity, limit=limit)


@router.get("/api/security/history")
def api_security_history(request: Request, auth=Depends(_get_auth)):
    """Return historical security scores for charting."""
    hostname = request.query_params.get("hostname", "") or None
    limit = min(_safe_int(request.query_params.get("limit", "50"), 50), 200)
    return db.get_security_score_history(hostname=hostname, limit=limit)


@router.post("/api/security/scan/{hostname}")
async def api_security_scan(hostname: str, request: Request, auth=Depends(_get_auth)):
    """Trigger a security scan on a specific agent."""
    username, role = auth
    ip = _client_ip(request)
    cmd_type = "security_scan"
    risk = RISK_LEVELS.get(cmd_type, "low")
    if not check_role_permission(role, risk):
        raise HTTPException(403, "Insufficient permissions")

    with _agent_data_lock:
        agent = _agent_data.get(hostname)
    if not agent:
        raise HTTPException(404, f"Agent '{hostname}' not found")

    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": cmd_type, "params": {},
           "queued_by": username, "queued_at": int(time.time())}

    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"type": "command", "id": cmd_id,
                                "cmd": cmd_type, "params": {}})
            delivered = True
        except Exception:
            with _agent_ws_lock:
                _agent_websockets.pop(hostname, None)

    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)

    db.record_command(cmd_id, hostname, cmd_type, {}, username)
    db.audit_log("security_scan", username,
                 f"host={hostname} id={cmd_id} ws={delivered}", ip)
    return {"status": "sent" if delivered else "queued", "id": cmd_id, "hostname": hostname}


@router.post("/api/security/scan-all")
async def api_security_scan_all(request: Request, auth=Depends(_get_auth)):
    """Trigger security scan on all online agents."""
    username, role = auth
    ip = _client_ip(request)
    cmd_type = "security_scan"
    risk = RISK_LEVELS.get(cmd_type, "low")
    if not check_role_permission(role, risk):
        raise HTTPException(403, "Insufficient permissions")

    now = time.time()
    results = {}
    with _agent_data_lock:
        online = [
            h for h, d in _agent_data.items()
            if (now - d.get("_received", 0)) < _AGENT_MAX_AGE
        ]

    for hostname in online:
        cmd_id = secrets.token_hex(8)
        cmd = {"id": cmd_id, "type": cmd_type, "params": {},
               "queued_by": username, "queued_at": int(time.time())}

        delivered = False
        with _agent_ws_lock:
            ws = _agent_websockets.get(hostname)
        if ws:
            try:
                await ws.send_json({"type": "command", "id": cmd_id,
                                    "cmd": cmd_type, "params": {}})
                delivered = True
            except Exception:
                with _agent_ws_lock:
                    _agent_websockets.pop(hostname, None)

        if not delivered:
            with _agent_cmd_lock:
                _agent_commands.setdefault(hostname, []).append(cmd)

        db.record_command(cmd_id, hostname, cmd_type, {}, username)
        results[hostname] = {"id": cmd_id, "websocket": delivered}

    db.audit_log("security_scan_all", username,
                 f"targets={len(online)}", ip)
    return {"status": "queued", "agents": results, "count": len(online)}


@router.post("/api/security/record")
async def api_security_record(request: Request, auth=Depends(_get_auth)):
    """Record security scan results from an agent (called internally after scan completes)."""
    body = await _read_body(request)
    hostname = body.get("hostname", "")
    score = body.get("score")
    findings = body.get("findings", [])
    if not hostname or score is None:
        raise HTTPException(400, "hostname and score are required")
    db.record_security_scan(hostname, int(score), findings)
    return {"status": "ok"}


# ── Backup Verification (Feature 4) ───────────────────────────────────────

@router.get("/api/backup/verifications")
def api_backup_verifications(request: Request, auth=Depends(_get_auth)):
    """Return backup verification history."""
    hostname = request.query_params.get("hostname", "") or None
    limit = min(_safe_int(request.query_params.get("limit", "100"), 100), 500)
    return db.list_backup_verifications(hostname=hostname, limit=limit)


@router.post("/api/backup/verify")
async def api_backup_verify(request: Request, auth=Depends(_require_operator)):
    """Trigger a backup verification on a specific agent."""
    username, role = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    hostname = body.get("hostname", "")
    path = body.get("path", "")
    vtype = body.get("verification_type", "checksum")

    if not hostname:
        raise HTTPException(400, "hostname is required")
    if not path:
        raise HTTPException(400, "path is required")
    if vtype not in ("checksum", "restore_test", "db_integrity"):
        raise HTTPException(400, f"Invalid verification_type: {vtype}")

    cmd_type = "verify_backup"
    risk = RISK_LEVELS.get(cmd_type)
    if not risk:
        raise HTTPException(400, f"Unknown command type: '{cmd_type}'")
    if not check_role_permission(role, risk):
        raise HTTPException(403, "Insufficient permissions for verify_backup")

    with _agent_data_lock:
        agent = _agent_data.get(hostname)
    if not agent:
        raise HTTPException(404, f"Agent '{hostname}' not found")

    cmd_id = secrets.token_hex(8)
    params = {"path": path, "verification_type": vtype}
    cmd = {"id": cmd_id, "type": cmd_type, "params": params,
           "queued_by": username, "queued_at": int(time.time())}

    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"type": "command", "id": cmd_id,
                                "cmd": cmd_type, "params": params})
            delivered = True
        except Exception:
            with _agent_ws_lock:
                _agent_websockets.pop(hostname, None)

    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)

    db.record_command(cmd_id, hostname, cmd_type, params, username)
    db.audit_log("verify_backup", username,
                 f"host={hostname} path={path} type={vtype} id={cmd_id} ws={delivered}", ip)
    return {"status": "sent" if delivered else "queued", "id": cmd_id,
            "hostname": hostname, "path": path, "verification_type": vtype}


@router.get("/api/backup/321-status")
def api_backup_321_status(auth=Depends(_get_auth)):
    """Return 3-2-1 backup compliance status."""
    return db.get_backup_321_status()


@router.put("/api/backup/321-status")
async def api_backup_321_update(request: Request, auth=Depends(_require_operator)):
    """Update 3-2-1 backup compliance tracking for a backup."""
    username, _ = auth
    body = await _read_body(request)
    backup_name = body.get("backup_name", "")
    if not backup_name:
        raise HTTPException(400, "backup_name is required")

    row_id = db.update_backup_321_status(
        backup_name,
        copies=body.get("copies"),
        media_types=body.get("media_types"),
        has_offsite=body.get("has_offsite"),
        last_verified=body.get("last_verified"),
    )
    if row_id is None:
        raise HTTPException(500, "Failed to update 3-2-1 status")
    db.audit_log("backup_321_update", username, f"name={backup_name}")
    return {"status": "ok", "id": row_id}


@router.post("/api/ai/test")
async def api_ai_test(auth=Depends(_require_admin)):
    """Test the LLM connection by sending a simple prompt."""
    client = _get_llm_client()
    if not client:
        raise HTTPException(503, "LLM not configured")
    try:
        response = await client.chat(
            [{"role": "user", "content": "Reply with exactly: NOBA AI connection successful."}],
            system="You are a connection test. Reply with exactly the text requested.",
        )
        return {"status": "ok", "response": response.strip()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI test error: %s", e)
        raise HTTPException(502, f"LLM connection test failed: {e}")
