"""Noba – Infrastructure and system management endpoints."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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

logger = logging.getLogger("noba.agent.ws")


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

        logger.info("[ws] Agent %s connected via WebSocket", hostname)

        # Send any queued commands immediately
        with _agent_cmd_lock:
            queued = _agent_commands.pop(hostname, [])
        for cmd in queued:
            await ws.send_json({"type": "command", "id": cmd.get("id", ""),
                                "cmd": cmd.get("type", ""), "params": cmd.get("params", {})})

        while True:
            msg = await ws.receive_json()
            msg_type = msg.get("type", "")

            if msg_type == "result":
                with _agent_cmd_lock:
                    _agent_cmd_results.setdefault(hostname, []).append(msg)
                    if len(_agent_cmd_results[hostname]) > 50:
                        _agent_cmd_results[hostname] = _agent_cmd_results[hostname][-50:]

            elif msg_type == "stream":
                cmd_id = msg.get("id", "")
                with _agent_cmd_lock:
                    stream_key = f"_stream_{hostname}_{cmd_id}"
                    _agent_cmd_results.setdefault(stream_key, []).append(msg)

            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("[ws] Error for %s: %s", hostname, exc)
    finally:
        if hostname:
            with _agent_ws_lock:
                if _agent_websockets.get(hostname) is ws:
                    del _agent_websockets[hostname]
            logger.info("[ws] Agent %s disconnected", hostname)


@router.get("/api/agents/{hostname}/stream/{cmd_id}")
def api_agent_stream(hostname: str, cmd_id: str, auth=Depends(_get_auth)):
    """Get streaming output lines for a command sent via WebSocket."""
    stream_key = f"_stream_{hostname}_{cmd_id}"
    with _agent_cmd_lock:
        return _agent_cmd_results.get(stream_key, [])


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
    import secrets
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
    import secrets
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
    import secrets
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
    import secrets
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


# ── Status page endpoints ────────────────────────────────────────────────────
@router.get("/status")
def public_status_page():
    """Public-facing status page -- no auth required."""
    return FileResponse(_WEB_DIR / "status.html")


@router.get("/api/status/public")
def api_public_status():
    """Public status data -- no auth required.  Only exposes configured services."""
    cfg = read_yaml_settings()
    status_services = [s.strip() for s in cfg.get("statusPageServices", "").split(",") if s.strip()]
    if not status_services:
        return {"services": [], "overall": "operational", "message": "No services configured for status page"}

    data = _deps.bg_collector.get() or {}
    services = []
    for svc in status_services:
        val = data.get(svc)
        if val is None:
            status = "unknown"
        elif isinstance(val, dict) and val.get("status"):
            status = "operational" if val["status"] in ("online", "enabled", "ok") else "degraded"
        elif isinstance(val, list) and len(val) > 0:
            status = "operational"
        else:
            status = "operational" if val else "unknown"
        services.append({"name": svc, "status": status})

    overall = "operational"
    if any(s["status"] == "degraded" for s in services):
        overall = "degraded"
    if all(s["status"] in ("unknown", "degraded") for s in services):
        overall = "major_outage"

    return {"services": services, "overall": overall, "timestamp": int(time.time())}
