"""Noba – System operations, recovery, journal, backups, and IaC export endpoints."""
from __future__ import annotations

import logging
import os
import re
import secrets
import subprocess
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from .. import deps as _deps
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
        # Reject patterns with nested quantifiers (ReDoS risk)
        if re.search(r'\([^)]*[+*][^)]*\)[+*]', grep_pattern):
            raise HTTPException(400, "Unsafe regex pattern")
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


# ── IaC Export endpoints ─────────────────────────────────────────────────────

@router.get("/api/export/ansible")
async def api_export_ansible(request: Request, auth=Depends(_require_admin)):
    """Generate an Ansible playbook from live agent data."""
    from ..iac_export import generate_ansible

    hostname = request.query_params.get("hostname") or None
    output = generate_ansible(
        db, _agent_data, _agent_data_lock, _AGENT_MAX_AGE, hostname,
    )
    return PlainTextResponse(output, media_type="text/yaml")


@router.get("/api/export/docker-compose")
async def api_export_docker_compose(request: Request, auth=Depends(_require_admin)):
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
async def api_export_shell(request: Request, auth=Depends(_require_admin)):
    """Generate a bash setup script from live agent data."""
    from ..iac_export import generate_shell_script

    hostname = request.query_params.get("hostname") or None
    if not hostname:
        raise HTTPException(400, "hostname parameter is required")
    output = generate_shell_script(
        db, _agent_data, _agent_data_lock, _AGENT_MAX_AGE, hostname,
    )
    return PlainTextResponse(output, media_type="text/x-shellscript")


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
