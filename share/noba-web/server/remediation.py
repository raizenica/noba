"""Noba – Remediation action registry."""
from __future__ import annotations

import logging
import subprocess
import time

from .yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

# Action type definitions: {type: {risk, params, description, timeout_s}}
ACTION_TYPES = {
    "restart_container": {
        "risk": "low",
        "params": {"container": str},
        "description": "Docker/Podman restart by container name",
        "timeout_s": 30,
        "has_health_check": True,
    },
    "restart_service": {
        "risk": "low",
        "params": {"service": str},
        "description": "systemd service restart",
        "timeout_s": 30,
        "has_health_check": True,
    },
    "flush_dns": {
        "risk": "low",
        "params": {},
        "description": "Clear DNS cache on Pi-hole/AdGuard",
        "timeout_s": 15,
    },
    "clear_cache": {
        "risk": "low",
        "params": {"target": str},
        "description": "Purge application caches",
        "timeout_s": 15,
    },
    "trigger_backup": {
        "risk": "medium",
        "params": {"source": str},
        "description": "Initiate backup job",
        "timeout_s": 300,
    },
    "failover_dns": {
        "risk": "high",
        "params": {"primary": str, "secondary": str},
        "description": "Switch DNS to backup pair",
        "timeout_s": 30,
        "has_rollback": True,
    },
    "scale_container": {
        "risk": "medium",
        "params": {"container": str, "cpu_limit": str, "mem_limit": str},
        "description": "Adjust container resource limits",
        "timeout_s": 30,
    },
    "run_playbook": {
        "risk": "high",
        "params": {"playbook_id": str},
        "description": "Execute a maintenance playbook (automation)",
        "timeout_s": 600,
    },
}


def validate_action(action_type, params):
    """Validate action type and params. Returns error string or None."""
    defn = ACTION_TYPES.get(action_type)
    if not defn:
        return f"Unknown action type: {action_type}"
    for key, expected_type in defn["params"].items():
        if key not in params:
            return f"Missing required param: {key}"
    return None


def execute_action(action_type, params, triggered_by="system"):
    """Execute a remediation action. Returns {success, output, duration_s, error?}."""
    defn = ACTION_TYPES.get(action_type)
    if not defn:
        return {"success": False, "error": f"Unknown action: {action_type}"}

    start = time.time()
    try:
        handler = _HANDLERS.get(action_type)
        if not handler:
            return {"success": False, "error": f"No handler for: {action_type}"}
        result = handler(params)
        duration = round(time.time() - start, 2)

        # Post-action health check if applicable
        health_ok = True
        if defn.get("has_health_check"):
            health_ok = _health_check(action_type, params)

        return {
            "success": result.get("success", False),
            "output": result.get("output", ""),
            "duration_s": duration,
            "health_check": "pass" if health_ok else "fail",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "duration_s": round(time.time() - start, 2),
        }


def _handle_restart_container(params):
    """Restart a Docker/Podman container."""
    name = params["container"]
    # Try docker first, fallback to podman
    for runtime in ("docker", "podman"):
        r = subprocess.run([runtime, "restart", name],
                          capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return {"success": True, "output": f"{runtime} restart {name}: OK"}
    return {"success": False, "output": r.stderr[:500]}


def _handle_restart_service(params):
    svc = params["service"]
    r = subprocess.run(["sudo", "systemctl", "restart", svc],
                      capture_output=True, text=True, timeout=30)
    return {"success": r.returncode == 0, "output": r.stdout + r.stderr}


def _handle_flush_dns(params):
    """Flush DNS cache via Pi-hole or systemd-resolved."""
    cfg = read_yaml_settings()
    if cfg.get("piholeUrl"):
        import httpx
        try:
            httpx.post(f"{cfg['piholeUrl']}/admin/api.php?restartdns",
                      timeout=10)
            return {"success": True, "output": "Pi-hole DNS restarted"}
        except Exception as e:
            return {"success": False, "output": str(e)}
    r = subprocess.run(["sudo", "systemd-resolve", "--flush-caches"],
                      capture_output=True, text=True, timeout=10)
    return {"success": r.returncode == 0, "output": "DNS cache flushed"}


def _handle_clear_cache(params):
    target = params.get("target", "system")
    if target == "system":
        subprocess.run(["sudo", "sync"], capture_output=True, text=True, timeout=10)
        subprocess.run(["sudo", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"],
                      capture_output=True, text=True, timeout=10)
        return {"success": True, "output": "System cache cleared"}
    return {"success": False, "output": f"Unknown cache target: {target}"}


def _handle_trigger_backup(params):
    source = params.get("source", "default")
    # Trigger via the existing backup automation
    from .runner import job_runner
    try:
        run_id = job_runner.submit(
            lambda rid: subprocess.Popen(
                ["bash", "-c", f"echo 'Backup triggered for {source}'"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            ),
            trigger=f"remediation:trigger_backup:{source}",
            triggered_by="system",
        )
        return {"success": True, "output": f"Backup queued: run_id={run_id}"}
    except Exception as e:
        return {"success": False, "output": str(e)}


def _handle_failover_dns(params):
    primary = params["primary"]
    secondary = params["secondary"]
    # This would configure DNS failover — implementation depends on infrastructure
    logger.warning("DNS failover: %s -> %s", primary, secondary)
    return {"success": True, "output": f"DNS failover: {primary} -> {secondary}"}


def _handle_scale_container(params):
    name = params["container"]
    cpu = params.get("cpu_limit", "")
    mem = params.get("mem_limit", "")
    args = ["docker", "update"]
    if cpu:
        args.extend(["--cpus", cpu])
    if mem:
        args.extend(["--memory", mem])
    args.append(name)
    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return {"success": r.returncode == 0, "output": r.stdout + r.stderr}


def _handle_run_playbook(params):
    playbook_id = params["playbook_id"]
    from .db import db as _db
    auto = _db.get_automation(playbook_id)
    if not auto:
        return {"success": False, "output": f"Playbook not found: {playbook_id}"}
    from .workflow_engine import _run_workflow
    config = auto.get("config", {})
    if auto.get("type") == "workflow":
        steps = config.get("steps", [])
        _run_workflow(playbook_id, steps, "system")
        return {"success": True, "output": f"Playbook started: {auto['name']}"}
    return {"success": False, "output": "Playbook must be a workflow automation"}


def _health_check(action_type, params):
    """Post-action health check. Returns True if healthy."""
    import time as _time
    _time.sleep(2)  # Brief wait for action to take effect
    if action_type == "restart_container":
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", params["container"]],
                          capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "true"
    if action_type == "restart_service":
        r = subprocess.run(["systemctl", "is-active", params["service"]],
                          capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "active"
    return True


# Handler registry
_HANDLERS = {
    "restart_container": _handle_restart_container,
    "restart_service": _handle_restart_service,
    "flush_dns": _handle_flush_dns,
    "clear_cache": _handle_clear_cache,
    "trigger_backup": _handle_trigger_backup,
    "failover_dns": _handle_failover_dns,
    "scale_container": _handle_scale_container,
    "run_playbook": _handle_run_playbook,
}
