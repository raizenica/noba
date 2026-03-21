"""Noba – Container and VM management endpoints."""
from __future__ import annotations

import json
import logging
import re
import subprocess

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from ..config import ALLOWED_ACTIONS
from ..deps import _client_ip, _int_param, _read_body, _require_admin, _require_operator, db
from ..metrics import bust_container_cache, strip_ansi
from ..runner import job_runner
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

router = APIRouter(tags=["containers"])


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
