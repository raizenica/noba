# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – System operations, recovery, journal, backups, and IaC export endpoints."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import subprocess
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from .. import deps as _deps
from ..deps import handle_errors
from ..agent_config import RISK_LEVELS, check_role_permission
from ..agent_store import (
    _agent_cmd_lock, _agent_commands,
    _agent_data, _agent_data_lock, _AGENT_MAX_AGE,
    _agent_websockets, _agent_ws_lock,
)

from ..config import VERSION
from ..deps import (
    _client_ip, _get_auth, _int_param, _read_body,
    _require_admin, _require_operator, _safe_int, db,
)
from ..metrics import collect_smart
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

router = APIRouter(tags=["operations"])


# ── /api/recovery ─────────────────────────────────────────────────────────────
@router.post("/api/recovery/tailscale-reconnect")
@handle_errors
async def api_recovery_tailscale(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip = _client_ip(request)
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["sudo", "-n", "tailscale", "up"], capture_output=True, text=True, timeout=15,
        )
        db.audit_log("recovery_tailscale", username, f"exit={result.returncode}", ip)
        return {"status": "ok" if result.returncode == 0 else "error",
                "output": result.stdout[:500], "error": result.stderr[:500]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/api/recovery/dns-flush")
@handle_errors
async def api_recovery_dns(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip = _client_ip(request)
    dns_svc = read_yaml_settings().get("dnsService", "pihole-FTL")
    if not dns_svc or not re.match(r'^[a-zA-Z0-9@._-]+$', dns_svc):
        return {"status": "error", "error": f"Invalid dnsService name in config: {dns_svc!r}"}
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["sudo", "-n", "systemctl", "--no-ask-password", "restart", dns_svc],
            capture_output=True, text=True, timeout=15,
        )
        db.audit_log("recovery_dns_flush", username, f"exit={result.returncode}", ip)
        return {"status": "ok" if result.returncode == 0 else "error",
                "output": result.stdout[:500], "error": result.stderr[:500]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/api/recovery/service-restart")
@handle_errors
async def api_recovery_service(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    service = body.get("service", "")
    if not service or len(service) > 256 or not re.match(r'^[a-zA-Z0-9@._-]+$', service):
        raise HTTPException(400, "Invalid service name")
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["sudo", "-n", "systemctl", "--no-ask-password", "restart", service],
            capture_output=True, text=True, timeout=30,
        )
        db.audit_log("recovery_service_restart", username, f"service={service} exit={result.returncode}", ip)
        return {"status": "ok" if result.returncode == 0 else "error",
                "service": service, "output": result.stdout[:500]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── /api/sites/sync-status ───────────────────────────────────────────────────
@router.get("/api/sites/sync-status")
@handle_errors
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
@handle_errors
def api_smart(auth=Depends(_get_auth)):
    return collect_smart()


# ── Systemd journal viewer ───────────────────────────────────────────────────
@router.get("/api/journal")
@handle_errors
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
        # Reject patterns with nested quantifiers (ReDoS risk)
        if re.search(r'\([^)]*[+*][^)]*\)[+*]', grep_pattern):
            raise HTTPException(400, "Unsafe regex pattern")
        # Validate regex is syntactically correct
        import re as _re
        try:
            _re.compile(grep_pattern[:100])
        except _re.error:
            raise HTTPException(400, "Invalid regex pattern") from None
        cmd += ["-g", grep_pattern[:100]]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return PlainTextResponse(r.stdout[-65536:] or "No entries.")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Journal query timed out") from None
    except FileNotFoundError:
        return PlainTextResponse("journalctl not available")


@router.get("/api/journal/units")
@handle_errors
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
@handle_errors
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
@handle_errors
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
@handle_errors
async def api_cpu_governor(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    body = await _read_body(request)
    governor = body.get("governor", "").strip()
    allowed = ("performance", "powersave", "ondemand", "conservative", "schedutil")
    if governor not in allowed:
        raise HTTPException(400, f"Governor must be one of: {', '.join(allowed)}")
    try:
        r = await asyncio.to_thread(subprocess.run, ["sudo", "-n", "cpupower", "frequency-set", "-g", governor],
                          capture_output=True, timeout=10)
        ok = r.returncode == 0
    except Exception:
        ok = False
    db.audit_log("cpu_governor", username, f"Set {governor} -> {ok}", _client_ip(request))
    return {"success": ok}


# ── /api/processes ────────────────────────────────────────────────────────────
@router.get("/api/processes/history")
@handle_errors
def api_process_history(auth=Depends(_get_auth)):
    """Get rolling history of top CPU and memory consumers."""
    from ..metrics import get_process_history
    return get_process_history()


@router.get("/api/processes/current")
@handle_errors
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


# ── IaC Export endpoints ─────────────────────────────────────────────────────


async def _ensure_agent_discovery(hostname: str, timeout: float = 15.0) -> str | None:
    """Dispatch discover_services + container_list and merge results into agent data.

    Returns None on success, or a warning string if discovery timed out.
    Skips silently if agent is offline or already has data.
    """
    from ..agent_store import _agent_cmd_results, _agent_cmd_lock

    with _agent_data_lock:
        agent = _agent_data.get(hostname)
    if not agent:
        return None  # agent offline

    has_services = bool(agent.get("services"))
    has_containers = bool(agent.get("containers"))
    if has_services and has_containers:
        return None  # already have data

    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if not ws:
        return "Agent has no WebSocket connection - discovery skipped, export may be incomplete"

    # Send commands and track IDs
    cmd_ids = {}
    for cmd_type in ("discover_services", "container_list"):
        try:
            cmd_id = secrets.token_hex(8)
            await ws.send_json({"type": "command", "id": cmd_id,
                                "cmd": cmd_type, "params": {}})
            cmd_ids[cmd_id] = cmd_type
        except Exception:
            pass

    if not cmd_ids:
        return "Failed to send discovery commands"

    # Poll _agent_cmd_results for responses (same pattern as network_stats)
    deadline = time.time() + timeout
    found: dict[str, dict] = {}
    while time.time() < deadline and len(found) < len(cmd_ids):
        await asyncio.sleep(0.5)
        with _agent_cmd_lock:
            results = _agent_cmd_results.get(hostname, [])
            for r in results:
                rid = r.get("id", "")
                if rid in cmd_ids and rid not in found:
                    found[rid] = r

    # Merge discovered data into _agent_data
    for cmd_id, result in found.items():
        cmd_type = cmd_ids[cmd_id]
        if result.get("status") != "ok":
            continue
        with _agent_data_lock:
            agent = _agent_data.get(hostname)
            if not agent:
                continue
            if cmd_type == "container_list":
                agent["containers"] = result.get("containers", [])
            elif cmd_type == "discover_services":
                agent["services"] = result.get("services", [])

    missing = [cmd_ids[cid] for cid in cmd_ids if cid not in found]
    if missing:
        return f"Discovery partial - missing: {', '.join(missing)}"
    return None


async def _run_export_with_discovery(
    request: Request, fmt: str, hostname: str | None, discover: bool,
) -> PlainTextResponse:
    """Shared logic for IaC export endpoints (all formats)."""
    from ..iac_export import generate_ansible, generate_docker_compose, generate_shell_script

    if fmt in ("docker-compose", "shell") and not hostname:
        raise HTTPException(400, "hostname parameter is required")

    warning = None
    if discover and hostname:
        warning = await _ensure_agent_discovery(hostname)
    elif discover and not hostname:
        with _agent_data_lock:
            hosts = list(_agent_data.keys())
        warnings = []
        for h in hosts:
            w = await _ensure_agent_discovery(h, timeout=10.0)
            if w:
                warnings.append(f"{h}: {w}")
        warning = "; ".join(warnings) if warnings else None

    generators = {
        "ansible": (generate_ansible, "text/yaml"),
        "docker-compose": (generate_docker_compose, "text/yaml"),
        "shell": (generate_shell_script, "text/x-shellscript"),
    }
    gen_fn, media = generators[fmt]
    output = gen_fn(db, _agent_data, _agent_data_lock, _AGENT_MAX_AGE, hostname)
    resp = PlainTextResponse(output, media_type=media)
    if warning:
        resp.headers["X-Noba-Discovery-Warning"] = warning
    return resp


@router.get("/api/export/ansible")
@handle_errors
async def api_export_ansible(request: Request, auth=Depends(_get_auth)):
    """Generate an Ansible playbook from cached agent data (read-only)."""
    hostname = request.query_params.get("hostname") or None
    return await _run_export_with_discovery(request, "ansible", hostname, discover=False)


@router.post("/api/export/ansible")
@handle_errors
async def api_export_ansible_discover(request: Request, auth=Depends(_require_operator)):
    """Generate an Ansible playbook, optionally running agent discovery first."""
    body = await _read_body(request)
    hostname = body.get("hostname") or None
    discover = body.get("discover", False)
    return await _run_export_with_discovery(request, "ansible", hostname, discover=bool(discover))


@router.get("/api/export/docker-compose")
@handle_errors
async def api_export_docker_compose(request: Request, auth=Depends(_get_auth)):
    """Generate a docker-compose.yml from cached agent container data (read-only)."""
    hostname = request.query_params.get("hostname") or None
    return await _run_export_with_discovery(request, "docker-compose", hostname, discover=False)


@router.post("/api/export/docker-compose")
@handle_errors
async def api_export_docker_compose_discover(request: Request, auth=Depends(_require_operator)):
    """Generate a docker-compose.yml, optionally running agent discovery first."""
    body = await _read_body(request)
    hostname = body.get("hostname") or None
    discover = body.get("discover", False)
    return await _run_export_with_discovery(request, "docker-compose", hostname, discover=bool(discover))


@router.get("/api/export/shell")
@handle_errors
async def api_export_shell(request: Request, auth=Depends(_get_auth)):
    """Generate a bash setup script from cached agent data (read-only)."""
    hostname = request.query_params.get("hostname") or None
    return await _run_export_with_discovery(request, "shell", hostname, discover=False)


@router.post("/api/export/shell")
@handle_errors
async def api_export_shell_discover(request: Request, auth=Depends(_require_operator)):
    """Generate a bash setup script, optionally running agent discovery first."""
    body = await _read_body(request)
    hostname = body.get("hostname") or None
    discover = body.get("discover", False)
    return await _run_export_with_discovery(request, "shell", hostname, discover=bool(discover))


# ── Backup Verification (Feature 4) ───────────────────────────────────────

@router.get("/api/backup/verifications")
@handle_errors
def api_backup_verifications(request: Request, auth=Depends(_get_auth)):
    """Return backup verification history."""
    hostname = request.query_params.get("hostname", "") or None
    limit = min(_safe_int(request.query_params.get("limit", "100"), 100), 500)
    return db.list_backup_verifications(hostname=hostname, limit=limit)


@router.post("/api/backup/verify")
@handle_errors
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
@handle_errors
def api_backup_321_status(auth=Depends(_get_auth)):
    """Return 3-2-1 backup compliance status."""
    return db.get_backup_321_status()


@router.put("/api/backup/321-status")
@handle_errors
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


# ── Self-update ──────────────────────────────────────────────────────────────

def _find_repo_dir() -> str | None:
    """Locate the noba git repo. Checks NOBA_REPO_DIR env, then common locations."""
    from pathlib import Path
    explicit = os.environ.get("NOBA_REPO_DIR")
    if explicit and os.path.isdir(os.path.join(explicit, ".git")):
        return explicit
    for candidate in [
        Path.home() / "noba",
        Path.home() / "projects" / "noba",
        Path(__file__).resolve().parents[4],  # share/noba-web/server/routers -> repo root
    ]:
        if (candidate / ".git").is_dir():
            return str(candidate)
    return None


def _git(repo_dir: str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command in the repo directory."""
    return subprocess.run(
        ["git", *args],
        cwd=repo_dir, capture_output=True, text=True, timeout=timeout,
    )


def _is_docker() -> bool:
    """Detect if running inside a Docker/Podman container."""
    return os.path.isfile("/.dockerenv") or os.path.isfile("/run/.containerenv")


@router.get("/api/system/update/check")
@handle_errors
async def api_update_check(auth=Depends(_require_operator)):
    """Check if a newer version is available on the remote."""
    # Docker containers can't self-update via git — return instructions instead
    if _is_docker():
        latest = None
        try:
            import httpx as _httpx
            r = await asyncio.to_thread(
                _httpx.get,
                "https://api.github.com/repos/raizenica/noba-ce/releases/latest",
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                latest = data.get("tag_name", "").lstrip("v")
        except Exception:
            pass
        return {
            "update_available": bool(latest and latest != VERSION),
            "current_version": VERSION,
            "remote_version": latest or VERSION,
            "docker": True,
            "docker_image": "ghcr.io/raizenica/noba-ce",
            "docker_instructions": [
                "docker pull ghcr.io/raizenica/noba-ce:latest",
                "docker stop noba && docker rm noba",
                "docker run -d --name noba -p 8080:8080 -v noba-data:/app/config ghcr.io/raizenica/noba-ce:latest",
            ],
        }

    repo_dir = _find_repo_dir()
    if not repo_dir:
        return {
            "update_available": False,
            "current_version": VERSION,
            "error": "Git repository not found. Set NOBA_REPO_DIR environment variable.",
        }

    try:
        # Fetch latest from remote without modifying working tree
        fetch = await asyncio.to_thread(_git, repo_dir, "fetch", "--quiet", "origin", timeout=15)
        if fetch.returncode != 0:
            return {
                "update_available": False,
                "current_version": VERSION,
                "error": f"git fetch failed: {fetch.stderr.strip()}",
            }

        # Get current branch
        branch_result = await asyncio.to_thread(_git, repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
        branch = branch_result.stdout.strip() or "main"

        # Count commits behind
        behind = await asyncio.to_thread(_git, repo_dir, "rev-list", "--count", f"HEAD..origin/{branch}")
        commits_behind = int(behind.stdout.strip()) if behind.returncode == 0 else 0

        # Get remote version from config.py
        remote_version = VERSION
        if commits_behind > 0:
            ver_result = await asyncio.to_thread(
                _git, repo_dir, "show", f"origin/{branch}:share/noba-web/server/config.py",
            )
            if ver_result.returncode == 0:
                import re as _re
                m = _re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', ver_result.stdout)
                if m:
                    remote_version = m.group(1)

            # Get recent commit summaries for changelog
            log_result = await asyncio.to_thread(
                _git, repo_dir, "log", "--oneline", f"HEAD..origin/{branch}", "--max-count=20",
            )
            changelog = log_result.stdout.strip().splitlines() if log_result.returncode == 0 else []
        else:
            changelog = []

        return {
            "update_available": commits_behind > 0,
            "current_version": VERSION,
            "remote_version": remote_version,
            "commits_behind": commits_behind,
            "branch": branch,
            "changelog": changelog,
            "repo_dir": repo_dir,
        }
    except subprocess.TimeoutExpired:
        return {
            "update_available": False,
            "current_version": VERSION,
            "error": "Update check timed out",
        }
    except Exception as exc:
        logger.error("Update check failed: %s", exc)
        return {
            "update_available": False,
            "current_version": VERSION,
            "error": str(exc),
        }


@router.post("/api/system/update/apply")
@handle_errors
async def api_update_apply(request: Request, auth=Depends(_require_admin)):
    """Pull latest code, re-install, and schedule a service restart."""
    username, _ = auth
    ip = _client_ip(request)
    repo_dir = _find_repo_dir()
    if not repo_dir:
        raise HTTPException(400, "Git repository not found. Set NOBA_REPO_DIR.")

    steps: list[dict] = []

    try:
        # Step 1: git pull
        pull = await asyncio.to_thread(_git, repo_dir, "pull", "--ff-only", "origin", timeout=60)
        steps.append({
            "step": "git pull",
            "success": pull.returncode == 0,
            "output": (pull.stdout + pull.stderr).strip()[:500],
        })
        if pull.returncode != 0:
            raise HTTPException(500, f"git pull failed: {pull.stderr.strip()}")

        # Step 2: rebuild frontend (if npm is available)
        build_script = os.path.join(repo_dir, "scripts", "build-frontend.sh")
        if os.path.isfile(build_script):
            build = await asyncio.to_thread(
                subprocess.run,
                ["bash", build_script],
                cwd=repo_dir, capture_output=True, text=True, timeout=120,
            )
            steps.append({
                "step": "build frontend",
                "success": build.returncode == 0,
                "output": (build.stdout + build.stderr).strip()[-500:],
            })

        # Step 3: re-install
        install_script = os.path.join(repo_dir, "install.sh")
        if os.path.isfile(install_script):
            install = await asyncio.to_thread(
                subprocess.run,
                ["bash", install_script, "--auto-approve", "--skip-deps", "--no-restart"],
                cwd=repo_dir, capture_output=True, text=True, timeout=120,
            )
            steps.append({
                "step": "install",
                "success": install.returncode == 0,
                "output": (install.stdout + install.stderr).strip()[-500:],
            })
            if install.returncode != 0:
                detail = (install.stdout + install.stderr).strip()[-500:]
                raise HTTPException(500, f"install.sh failed: {detail}")

        db.audit_log("system_update", username, f"Updated from repo {repo_dir}", ip=ip)

        # Step 4: schedule restart (give time for response to reach client)
        import threading
        def _restart():
            time.sleep(2)
            try:
                subprocess.run(
                    ["systemctl", "--user", "restart", "noba-web.service"],
                    timeout=10,
                )
            except Exception as exc:
                logger.error("Service restart failed: %s", exc)

        threading.Thread(target=_restart, daemon=True, name="update-restart").start()

        return {
            "status": "ok",
            "message": "Update applied. Service restarting in 2 seconds...",
            "steps": steps,
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Update step timed out") from None
    except Exception as exc:
        logger.error("System update failed: %s", exc)
        raise HTTPException(500, "Update failed — check server logs") from None
