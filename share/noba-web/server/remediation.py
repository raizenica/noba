# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Remediation action registry."""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import subprocess
import time
from urllib.parse import urlparse

from .yaml_config import read_yaml_settings

_RUN_ALLOWED_PREFIXES = (
    "systemctl restart", "systemctl reload", "systemctl start", "systemctl stop",
    "docker restart", "docker start", "docker stop",
    "podman restart", "podman start", "podman stop",
    "restic backup", "restic snapshots",
    "rclone sync", "rclone copy",
    "certbot renew",
)


def _resolve_safe_webhook_url(url: str) -> str | None:
    """Resolve URL and verify all IPs are public. Returns IP-pinned URL or None."""
    import socket

    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if not hostname:
            return None
        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return None
        try:
            addrs = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            return None
        safe_ip = None
        for _family, _, _, _, sockaddr in addrs:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return None
            if safe_ip is None:
                safe_ip = str(ip)
        if not safe_ip:
            return None
        # Return URL with hostname replaced by resolved IP to prevent DNS rebinding
        port = parsed.port
        port_str = f":{port}" if port else ""
        return f"{parsed.scheme}://{safe_ip}{port_str}{parsed.path}{'?' + parsed.query if parsed.query else ''}"
    except Exception:
        return None


def _is_safe_webhook_url(url: str) -> bool:
    """Block requests to private/internal networks (with DNS resolution)."""
    return _resolve_safe_webhook_url(url) is not None

logger = logging.getLogger("noba")

# Action type definitions: {type: {risk, params, description, timeout_s, settle_s, reversible}}
ACTION_TYPES = {
    # ── Existing 12 (backfilled with reversible + settle_s) ──────────────────
    "restart_container": {
        "risk": "low",
        "params": {"container": str},
        "description": "Docker/Podman restart by container name",
        "timeout_s": 30,
        "settle_s": 5,
        "reversible": False,
        "has_health_check": True,
    },
    "restart_service": {
        "risk": "low",
        "params": {"service": str},
        "description": "systemd service restart",
        "timeout_s": 30,
        "settle_s": 5,
        "reversible": False,
        "has_health_check": True,
    },
    "flush_dns": {
        "risk": "low",
        "params": {},
        "description": "Clear DNS cache on Pi-hole/AdGuard",
        "timeout_s": 15,
        "settle_s": 2,
        "reversible": False,
    },
    "clear_cache": {
        "risk": "low",
        "params": {"target": str},
        "description": "Purge application caches",
        "timeout_s": 15,
        "settle_s": 2,
        "reversible": False,
    },
    "trigger_backup": {
        "risk": "medium",
        "params": {"source": str},
        "description": "Initiate backup job",
        "timeout_s": 300,
        "settle_s": 0,
        "reversible": False,
    },
    "failover_dns": {
        "risk": "high",
        "params": {"primary": str, "secondary": str},
        "description": "Switch DNS to backup pair",
        "timeout_s": 30,
        "settle_s": 10,
        "reversible": True,
        "reverse_action": "failover_dns",
        "has_rollback": True,
    },
    "scale_container": {
        "risk": "medium",
        "params": {"container": str, "cpu_limit": str, "mem_limit": str},
        "description": "Adjust container resource limits",
        "timeout_s": 30,
        "settle_s": 5,
        "reversible": True,
        "reverse_action": "scale_container",
    },
    "run_playbook": {
        "risk": "high",
        "params": {"playbook_id": str},
        "description": "Execute a maintenance playbook (automation)",
        "timeout_s": 600,
        "settle_s": 0,
        "reversible": False,
    },
    "run": {
        "risk": "high",
        "params": {"command": str},
        "description": "Execute a shell command",
        "timeout_s": 60,
        "settle_s": 0,
        "reversible": False,
    },
    "webhook": {
        "risk": "low",
        "params": {"url": str},
        "description": "Fire an HTTP webhook",
        "timeout_s": 10,
        "settle_s": 0,
        "reversible": False,
    },
    "automation": {
        "risk": "medium",
        "params": {"automation_id": str},
        "description": "Trigger a stored automation by ID",
        "timeout_s": 300,
        "settle_s": 0,
        "reversible": False,
    },
    "agent_command": {
        "risk": "medium",
        "params": {"hostname": str, "command": str},
        "description": "Send command to a remote agent",
        "timeout_s": 30,
        "settle_s": 0,
        "reversible": False,
    },

    # ── New Low-risk (15) ────────────────────────────────────────────────────
    "service_reload": {
        "risk": "low",
        "params": {"service": str},
        "description": "Reload service config without full restart",
        "timeout_s": 15,
        "settle_s": 2,
        "reversible": False,
    },
    "service_reset_failed": {
        "risk": "low",
        "params": {"service": str},
        "description": "Reset failed state on a systemd service unit",
        "timeout_s": 15,
        "settle_s": 2,
        "reversible": False,
    },
    "container_pause": {
        "risk": "low",
        "params": {"container": str},
        "description": "Pause a running container (freeze processes)",
        "timeout_s": 15,
        "settle_s": 2,
        "reversible": True,
        "reverse_action": "container_pause",
    },
    "container_image_pull": {
        "risk": "low",
        "params": {"container": str},
        "description": "Pull the latest image for a container",
        "timeout_s": 60,
        "settle_s": 0,
        "reversible": False,
    },
    "process_kill": {
        "risk": "low",
        "params": {"pid": int},
        "description": "Send SIGTERM to a process by PID",
        "timeout_s": 10,
        "settle_s": 2,
        "reversible": False,
    },
    "nice_adjust": {
        "risk": "low",
        "params": {"pid": int, "priority": int},
        "description": "Adjust scheduling priority (nice) of a process",
        "timeout_s": 5,
        "settle_s": 0,
        "reversible": True,
        "reverse_action": "nice_adjust",
    },
    "log_rotate": {
        "risk": "low",
        "params": {"service": str},
        "description": "Force log rotation for a service",
        "timeout_s": 30,
        "settle_s": 0,
        "reversible": False,
    },
    "temp_cleanup": {
        "risk": "low",
        "params": {"path": str, "max_age_hours": int},
        "description": "Remove temporary files older than max_age_hours",
        "timeout_s": 60,
        "settle_s": 0,
        "reversible": False,
    },
    "dns_cache_clear": {
        "risk": "low",
        "params": {"instance_id": str},
        "description": "Clear DNS resolver cache on a specific instance",
        "timeout_s": 15,
        "settle_s": 2,
        "reversible": False,
    },
    "event_log_clear": {
        "risk": "low",
        "params": {"log_name": str},
        "description": "Clear a Windows Event Log channel",
        "timeout_s": 30,
        "settle_s": 0,
        "reversible": False,
    },
    "sfc_scan": {
        "risk": "low",
        "params": {},
        "description": "Run Windows System File Checker (sfc /scannow)",
        "timeout_s": 300,
        "settle_s": 0,
        "reversible": False,
    },
    "journal_vacuum": {
        "risk": "low",
        "params": {"max_size": str},
        "description": "Vacuum systemd journal to stay under max_size",
        "timeout_s": 30,
        "settle_s": 0,
        "reversible": False,
    },
    "package_cache_clean": {
        "risk": "low",
        "params": {},
        "description": "Clean package manager cache (apt/dnf/apk)",
        "timeout_s": 60,
        "settle_s": 0,
        "reversible": False,
    },
    "windows_update_check": {
        "risk": "low",
        "params": {},
        "description": "Trigger a Windows Update availability check",
        "timeout_s": 120,
        "settle_s": 0,
        "reversible": False,
    },
    "disk_cleanup": {
        "risk": "low",
        "params": {"mount": str},
        "description": "Run fstrim or Windows cleanmgr on a mount point",
        "timeout_s": 120,
        "settle_s": 0,
        "reversible": False,
    },

    # ── New Medium-risk (18) ─────────────────────────────────────────────────
    "container_recreate": {
        "risk": "medium",
        "params": {"container": str},
        "description": "Stop, remove, and recreate a container from its image",
        "timeout_s": 120,
        "settle_s": 10,
        "reversible": False,
    },
    "service_dependency_restart": {
        "risk": "medium",
        "params": {"service": str},
        "description": "Restart a service and all its declared dependencies",
        "timeout_s": 120,
        "settle_s": 10,
        "reversible": False,
    },
    "storage_cleanup": {
        "risk": "medium",
        "params": {"targets": list},
        "description": "Clean up storage targets (old images, volumes, logs)",
        "timeout_s": 300,
        "settle_s": 0,
        "reversible": False,
    },
    "cert_renew": {
        "risk": "medium",
        "params": {"domain": str},
        "description": "Renew TLS certificate for a domain via ACME/certbot",
        "timeout_s": 120,
        "settle_s": 5,
        "reversible": False,
    },
    "vpn_reconnect": {
        "risk": "medium",
        "params": {"interface": str},
        "description": "Drop and re-establish a VPN tunnel interface",
        "timeout_s": 30,
        "settle_s": 5,
        "reversible": False,
    },
    "zfs_scrub": {
        "risk": "medium",
        "params": {"pool": str},
        "description": "Initiate a ZFS scrub on a storage pool",
        "timeout_s": 600,
        "settle_s": 0,
        "reversible": False,
    },
    "btrfs_scrub": {
        "risk": "medium",
        "params": {"mount": str},
        "description": "Initiate a Btrfs scrub on a mount point",
        "timeout_s": 600,
        "settle_s": 0,
        "reversible": False,
    },
    "chkdsk": {
        "risk": "medium",
        "params": {"volume": str},
        "description": "Schedule chkdsk on a Windows volume",
        "timeout_s": 600,
        "settle_s": 0,
        "reversible": False,
    },
    "fsck_schedule": {
        "risk": "medium",
        "params": {"device": str},
        "description": "Schedule fsck on next boot for a block device",
        "timeout_s": 10,
        "settle_s": 0,
        "reversible": False,
    },
    "backup_verify": {
        "risk": "medium",
        "params": {"backup_set": str},
        "description": "Verify integrity of a backup set",
        "timeout_s": 300,
        "settle_s": 0,
        "reversible": False,
    },
    "servarr_queue_cleanup": {
        "risk": "medium",
        "params": {"instance_id": str},
        "description": "Remove stalled/failed items from Servarr queue",
        "timeout_s": 30,
        "settle_s": 0,
        "reversible": False,
    },
    "media_library_scan": {
        "risk": "medium",
        "params": {"instance_id": str},
        "description": "Trigger a full library rescan on a media server",
        "timeout_s": 60,
        "settle_s": 0,
        "reversible": False,
    },
    "network_interface_restart": {
        "risk": "medium",
        "params": {"nic": str},
        "description": "Bring a network interface down then up",
        "timeout_s": 15,
        "settle_s": 5,
        "reversible": False,
    },
    "compose_restart": {
        "risk": "medium",
        "params": {"project": str},
        "description": "Run docker compose restart on a compose project",
        "timeout_s": 120,
        "settle_s": 10,
        "reversible": False,
    },
    "scheduled_task_repair": {
        "risk": "medium",
        "params": {"task": str},
        "description": "Re-register or repair a Windows Scheduled Task",
        "timeout_s": 30,
        "settle_s": 0,
        "reversible": False,
    },
    "iis_app_pool_recycle": {
        "risk": "medium",
        "params": {"pool_name": str},
        "description": "Recycle an IIS application pool",
        "timeout_s": 30,
        "settle_s": 5,
        "reversible": False,
    },
    "wsl_restart": {
        "risk": "medium",
        "params": {},
        "description": "Shutdown and restart the WSL2 virtual machine",
        "timeout_s": 30,
        "settle_s": 5,
        "reversible": False,
    },
    "memory_pressure_relief": {
        "risk": "medium",
        "params": {},
        "description": "Drop page/slab caches to relieve memory pressure",
        "timeout_s": 60,
        "settle_s": 5,
        "reversible": False,
    },

    # ── New High-risk (10) ───────────────────────────────────────────────────
    "host_reboot": {
        "risk": "high",
        "params": {"hostname": str},
        "description": "Schedule an immediate host reboot (1-minute delay)",
        "timeout_s": 120,
        "settle_s": 60,
        "reversible": False,
    },
    "vm_restart": {
        "risk": "high",
        "params": {"vm_id": str, "platform": str},
        "description": "Hard-restart a virtual machine via hypervisor API",
        "timeout_s": 60,
        "settle_s": 30,
        "reversible": False,
    },
    "vm_migrate": {
        "risk": "high",
        "params": {"vm_id": str, "target_node": str},
        "description": "Live-migrate a VM to a different cluster node",
        "timeout_s": 300,
        "settle_s": 30,
        "reversible": True,
        "reverse_action": "vm_migrate",
    },
    "package_security_patch": {
        "risk": "high",
        "params": {"hostname": str},
        "description": "Apply security-only package upgrades on a host",
        "timeout_s": 600,
        "settle_s": 0,
        "reversible": False,
    },
    "snapshot_rollback": {
        "risk": "high",
        "params": {"target": str, "snapshot": str},
        "description": "Roll back a VM or volume to a named snapshot",
        "timeout_s": 120,
        "settle_s": 30,
        "reversible": False,
    },
    "firewall_rule_add": {
        "risk": "high",
        "params": {"rule": str},
        "description": "Insert a firewall rule (iptables/nftables/Windows Firewall)",
        "timeout_s": 15,
        "settle_s": 5,
        "reversible": True,
        "reverse_action": "firewall_rule_remove",
    },
    "driver_rollback": {
        "risk": "high",
        "params": {"device": str},
        "description": "Roll back a device driver to its previous version",
        "timeout_s": 120,
        "settle_s": 30,
        "reversible": False,
    },
    "raid_rebuild": {
        "risk": "high",
        "params": {"array": str, "disk": str},
        "description": "Initiate RAID array rebuild with a replacement disk",
        "timeout_s": 600,
        "settle_s": 0,
        "reversible": False,
    },
    "group_policy_refresh": {
        "risk": "high",
        "params": {},
        "description": "Force Group Policy refresh on a Windows host (gpupdate /force)",
        "timeout_s": 60,
        "settle_s": 10,
        "reversible": False,
    },
    "ad_replication_force": {
        "risk": "high",
        "params": {},
        "description": "Force AD replication between domain controllers",
        "timeout_s": 120,
        "settle_s": 10,
        "reversible": False,
    },
}

# IMPORTANT: cmd strings in FALLBACK_CHAINS are for capability matching ONLY.
# They are NEVER executed directly via subprocess. Actual execution uses
# the registered _HANDLERS functions which apply _safe_name() validation.
# Do NOT add code that passes these cmd strings to subprocess/shell.
FALLBACK_CHAINS: dict[str, list[dict[str, str]]] = {
    "service_restart": [
        {"requires": "systemctl", "cmd": "systemctl restart {service}"},
        {"requires": "rc-service", "cmd": "rc-service {service} restart"},
        {"requires": "service", "cmd": "service {service} restart"},
        {"requires": "powershell", "cmd": "Restart-Service {service}"},
    ],
    "restart_service": [  # alias for backward compat
        {"requires": "systemctl", "cmd": "systemctl restart {service}"},
        {"requires": "rc-service", "cmd": "rc-service {service} restart"},
        {"requires": "service", "cmd": "service {service} restart"},
        {"requires": "powershell", "cmd": "Restart-Service {service}"},
    ],
    "service_reload": [
        {"requires": "systemctl", "cmd": "systemctl reload {service}"},
        {"requires": "rc-service", "cmd": "rc-service {service} reload"},
        {"requires": "powershell", "cmd": "Restart-Service {service}"},
    ],
    "process_kill": [
        {"requires": "kill", "cmd": "kill -TERM {pid}"},
        {"requires": "powershell", "cmd": "Stop-Process -Id {pid} -Force"},
    ],
    "network_interface_restart": [
        {"requires": "ip", "cmd": "ip link set {nic} down && ip link set {nic} up"},
        {"requires": "ifconfig", "cmd": "ifconfig {nic} down && ifconfig {nic} up"},
        {"requires": "powershell", "cmd": "Restart-NetAdapter -Name '{nic}'"},
    ],
    "disk_cleanup": [
        {"requires": "fstrim", "cmd": "fstrim -v {mount}"},
        {"requires": "powershell", "cmd": "cleanmgr /sagerun:1"},
    ],
    "package_cache_clean": [
        {"requires": "apt", "cmd": "apt clean"},
        {"requires": "dnf", "cmd": "dnf clean all"},
        {"requires": "apk", "cmd": "apk cache clean"},
    ],
    "package_security_patch": [
        {"requires": "apt", "cmd": "apt upgrade -y --only-upgrade"},
        {"requires": "dnf", "cmd": "dnf upgrade --security -y"},
        {"requires": "apk", "cmd": "apk upgrade"},
        {"requires": "powershell", "cmd": "Install-WindowsUpdate -AcceptAll"},
    ],
    "host_reboot": [
        {"requires": "shutdown", "cmd": "shutdown -r +1"},
        {"requires": "powershell", "cmd": "Restart-Computer -Force"},
    ],
}


def validate_action(action_type, params):
    """Validate action type and params. Returns error string or None."""
    defn = ACTION_TYPES.get(action_type)
    if not defn:
        return f"Unknown action type: {action_type}"
    for key, _expected_type in defn["params"].items():
        if key not in params:
            return f"Missing required param: {key}"
    return None


# ── Action → agent command mapping for remote dispatch ──────────────────────
_AGENT_COMMAND_MAP: dict[str, tuple] = {
    # action_type → (agent_cmd_type, params_transformer)
    "restart_container": ("container_control", lambda p: {
        "container": p.get("container", ""),
        "action": "restart",
    }),
    "scale_container": ("container_control", lambda p: {
        "container": p.get("container", ""),
        "action": p.get("action", "start"),
    }),
    "restart_service": ("restart_service", lambda p: {
        "service": p.get("service", ""),
    }),
    "flush_dns": ("restart_service", lambda p: {
        "service": p.get("service", "pihole-FTL"),
    }),
    "agent_command": ("exec", lambda p: {
        "command": p.get("command", ""),
    }),
}


def _try_agent_dispatch(action_type: str, params: dict, target: str) -> dict | None:
    """Attempt to dispatch an action to a remote agent.

    Returns the result dict if dispatched, or None to fall through to local.
    """
    from .agent_store import get_online_agents, queue_agent_command_and_wait

    mapping = _AGENT_COMMAND_MAP.get(action_type)
    if not mapping:
        return None  # no remote mapping — fall through to local

    online = get_online_agents()
    if target not in online:
        logger.debug("Target %r not online, falling through to local", target)
        return None

    cmd_type, transform = mapping
    cmd_params = transform(params)

    logger.info("Dispatching heal action %s to agent %s as %s", action_type, target, cmd_type)
    result = queue_agent_command_and_wait(
        target, cmd_type, cmd_params, timeout=30, queued_by="healing_pipeline",
    )
    if result is None:
        return {"success": False, "output": f"Agent command timed out on {target}"}
    status = result.get("status", "error")
    output = result.get("output", result.get("stdout", ""))
    return {"success": status == "ok", "output": f"[{target}] {cmd_type}: {output}"[:500]}


def execute_action(action_type, params, triggered_by="system",
                   trigger_type="manual", trigger_id=None, target=None,
                   approved_by=None):
    """Execute a remediation action. Returns {success, output, duration_s, error?}."""
    from .db import db as _db

    defn = ACTION_TYPES.get(action_type)
    if not defn:
        error_msg = f"Unknown action: {action_type}"
        _db.insert_action_audit(
            trigger_type=trigger_type, trigger_id=trigger_id,
            action_type=action_type, action_params=params,
            target=target, outcome="error", error=error_msg,
        )
        return {"success": False, "error": error_msg}

    start = time.time()
    try:
        # ── Remote agent dispatch ────────────────────────────────────
        # If the target is a known online agent, dispatch the action as
        # an agent command instead of running it locally.
        if target and target not in ("", "localhost", "self"):
            remote_result = _try_agent_dispatch(action_type, params, target)
            if remote_result is not None:
                result = remote_result
                duration = round(time.time() - start, 2)
                outcome = "success" if result.get("success", False) else "failure"
                logger.info(
                    "Action executed (remote): %s on %s", action_type, target,
                    extra={"action_type": action_type, "target": target, "outcome": outcome},
                )
                _db.insert_action_audit(
                    trigger_type=trigger_type, trigger_id=trigger_id,
                    action_type=action_type, action_params=params,
                    target=target, outcome=outcome, duration_s=duration,
                    output=result.get("output", ""),
                )
                return {**result, "duration_s": duration, "remote": True}

        handler = _HANDLERS.get(action_type)
        if not handler:
            error_msg = f"No handler for: {action_type}"
            _db.insert_action_audit(
                trigger_type=trigger_type, trigger_id=trigger_id,
                action_type=action_type, action_params=params,
                target=target, outcome="error", error=error_msg,
            )
            return {"success": False, "error": error_msg}
        result = handler(params)
        duration = round(time.time() - start, 2)

        # Post-action health check if applicable
        health_ok = True
        if defn.get("has_health_check"):
            health_ok = _health_check(action_type, params)

        outcome = "success" if result.get("success", False) else "failure"
        logger.info(
            "Action executed: %s", action_type,
            extra={"action_type": action_type, "target": target, "outcome": outcome},
        )
        _db.insert_action_audit(
            trigger_type=trigger_type, trigger_id=trigger_id,
            action_type=action_type, action_params=params,
            target=target, outcome=outcome, duration_s=duration,
            output=result.get("output", ""),
            approved_by=approved_by,
        )
        return {
            "success": result.get("success", False),
            "output": result.get("output", ""),
            "duration_s": duration,
            "health_check": "pass" if health_ok else "fail",
        }
    except Exception as e:
        duration = round(time.time() - start, 2)
        _db.insert_action_audit(
            trigger_type=trigger_type, trigger_id=trigger_id,
            action_type=action_type, action_params=params,
            target=target, outcome="error", duration_s=duration,
            approved_by=approved_by, error="Action execution failed",
        )
        logger.error("Remediation action %s on %s failed: %s", action_type, target, e)
        return {
            "success": False,
            "error": "Action execution failed",
            "duration_s": duration,
        }


def _safe_name(val, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$', max_len=253):
    """Validate a container/service name against a safe pattern."""
    if not val or not isinstance(val, str) or len(val) > max_len:
        raise ValueError("Invalid name: too long or empty")
    if not re.match(pattern, val):
        raise ValueError("Invalid name: contains unsafe characters")
    return val


def _handle_restart_container(params):
    """Restart a Docker/Podman container."""
    name = _safe_name(params["container"])
    # Try docker first, fallback to podman
    for runtime in ("docker", "podman"):
        r = subprocess.run([runtime, "restart", name],
                          capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return {"success": True, "output": f"{runtime} restart {name}: OK"}
    return {"success": False, "output": r.stderr[:500]}


def _handle_restart_service(params):
    svc = _safe_name(params["service"], pattern=r'^[a-zA-Z0-9@._\-]+$')
    r = subprocess.run(["sudo", "-n", "systemctl", "--no-ask-password", "restart", svc],
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
            logger.error("DNS flush via Pi-hole failed: %s", e)
            return {"success": False, "output": "DNS flush failed"}
    r = subprocess.run(["sudo", "-n", "systemd-resolve", "--flush-caches"],
                      capture_output=True, text=True, timeout=10)
    return {"success": r.returncode == 0, "output": "DNS cache flushed"}


def _handle_clear_cache(params):
    target = params.get("target", "system")
    if target == "system":
        subprocess.run(["sudo", "-n", "sync"], capture_output=True, text=True, timeout=10)
        subprocess.run(["sudo", "-n", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"],
                      capture_output=True, text=True, timeout=10)
        return {"success": True, "output": "System cache cleared"}
    return {"success": False, "output": f"Unknown cache target: {target}"}


def _handle_trigger_backup(params):
    source = params.get("source", "default")
    # Look for a user-defined backup automation to trigger
    from .db import db as _db
    from .runner import job_runner
    try:
        autos = _db.get_automations()
        backup_auto = None
        for a in autos:
            name = (a.get("name") or "").lower()
            atype = (a.get("type") or "").lower()
            if "backup" in name or atype == "script" and "backup" in (a.get("command") or "").lower():
                backup_auto = a
                break
        if backup_auto:
            cmd = backup_auto.get("command", "")
            run_id = job_runner.submit(
                lambda rid: subprocess.Popen(
                    cmd if isinstance(cmd, list) else ["bash", "-c", cmd],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                ),
                trigger=f"remediation:trigger_backup:{source}",
                triggered_by="system",
            )
            return {"success": True, "output": f"Backup automation '{backup_auto.get('name')}' triggered: run_id={run_id}"}
    except Exception as e:
        logger.warning("trigger_backup automation lookup failed: %s", e)
    # Fallback: check for backup script in SCRIPT_DIR
    from .config import SCRIPT_DIR
    backup_script = os.path.join(SCRIPT_DIR, "backup-to-nas.sh")
    if os.path.isfile(backup_script):
        try:
            run_id = job_runner.submit(
                lambda rid: subprocess.Popen(
                    ["bash", backup_script],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                ),
                trigger=f"remediation:trigger_backup:{source}",
                triggered_by="system",
            )
            return {"success": True, "output": f"Backup script triggered: run_id={run_id}"}
        except Exception as e:
            logger.error("Backup trigger failed: %s", e)
            return {"success": False, "output": "Backup trigger failed"}
    return {"success": False, "output": "No backup automation or script found. Configure a backup automation first."}


def _handle_failover_dns(params):
    primary = params.get("primary", "")
    secondary = params.get("secondary", "")
    if not primary or not secondary:
        return {"success": False, "output": "Missing 'primary' and/or 'secondary' DNS server params"}
    # Attempt actual resolv.conf update on Linux systems
    resolv = "/etc/resolv.conf"
    try:
        with open(resolv) as f:
            original = f.read()
        # Replace the primary nameserver with the secondary
        new_lines = []
        replaced = False
        for line in original.splitlines():
            if line.strip().startswith("nameserver") and primary in line and not replaced:
                new_lines.append(f"nameserver {secondary}")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            # Primary not found in resolv.conf — prepend secondary
            new_lines.insert(0, f"nameserver {secondary}")
        result = subprocess.run(
            ["sudo", "-n", "tee", resolv],
            input="\n".join(new_lines) + "\n",
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            logger.info("DNS failover applied: %s -> %s", primary, secondary)
            return {"success": True, "output": f"DNS failover applied: {primary} -> {secondary}"}
        # sudo not available or denied
        logger.warning("DNS failover: sudo write failed: %s", result.stderr.strip())
        return {"success": False, "output": f"DNS failover requires sudo access: {result.stderr.strip()}"}
    except FileNotFoundError:
        return {"success": False, "output": f"{resolv} not found — DNS failover not supported on this platform"}
    except Exception as e:
        logger.error("DNS failover failed: %s", e)
        return {"success": False, "output": f"DNS failover failed: {e}"}


def _handle_scale_container(params):
    name = _safe_name(params["container"])
    cpu = params.get("cpu_limit", "")
    mem = params.get("mem_limit", "")
    # Validate cpu/mem formats to prevent argument injection
    if cpu and not re.match(r'^\d+(\.\d+)?$', cpu):
        return {"success": False, "output": f"Invalid cpu_limit: {cpu}"}
    if mem and not re.match(r'^\d+[kmgKMG]?$', mem):
        return {"success": False, "output": f"Invalid mem_limit: {mem}"}
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


def _handle_run(params):
    import shlex
    command = params.get("command", "")
    if not command:
        return {"success": False, "error": "No command specified"}
    if not any(command.strip().startswith(prefix) for prefix in _RUN_ALLOWED_PREFIXES):
        return {"success": False, "error": f"Command not in allowlist: {command.split()[0]}"}
    # Validate all arguments after the allowed prefix to prevent abuse
    parts = shlex.split(command)
    for arg in parts[1:]:
        if arg.startswith("-"):
            continue  # flags are ok
        # Validate service/container/path names — block shell metacharacters
        if not re.match(r'^[a-zA-Z0-9@._/:\-]+$', arg):
            return {"success": False, "error": f"Invalid argument: {arg!r}"}
    r = subprocess.run(parts, timeout=60, capture_output=True, text=True)
    return {"success": r.returncode == 0, "output": (r.stdout + r.stderr)[:500]}


def _handle_webhook(params):
    import urllib.request
    url = params.get("url", "")
    if not url or not url.startswith(("http://", "https://")):
        return {"success": False, "output": "Invalid URL"}
    # Resolve DNS once and pin the IP to prevent DNS rebinding (TOCTOU)
    pinned_url = _resolve_safe_webhook_url(url)
    if not pinned_url:
        return {"success": False, "error": f"URL blocked by SSRF protection: {url}"}
    method = params.get("method", "POST").upper()
    req = urllib.request.Request(pinned_url, method=method)
    # Set Host header to original hostname for correct virtual host routing
    parsed = urlparse(url)
    req.add_header("Host", parsed.hostname or "")
    for k, v in (params.get("headers") or {}).items():
        req.add_header(str(k).replace("\n", ""), str(v).replace("\n", ""))
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ok = 200 <= r.getcode() < 300
            return {"success": ok, "output": f"HTTP {r.getcode()}"}
    except Exception as e:
        logger.error("Webhook call failed: %s", e)
        return {"success": False, "output": "Webhook call failed"}


def _handle_automation(params):
    auto_id = params.get("automation_id", "")
    if not auto_id:
        return {"success": False, "output": "No automation_id"}
    from .db import db as _db
    auto = _db.get_automation(auto_id)
    if not auto:
        return {"success": False, "output": f"Automation not found: {auto_id}"}
    from .runner import job_runner
    from .workflow_engine import _AUTO_BUILDERS, _run_workflow
    if auto["type"] == "workflow":
        steps = auto["config"].get("steps", [])
        if steps:
            _run_workflow(auto["id"], steps, "remediation")
            return {"success": True, "output": f"Workflow started: {auto['name']}"}
        return {"success": False, "output": "Workflow has no steps"}
    builder = _AUTO_BUILDERS.get(auto["type"])
    if not builder:
        return {"success": False, "output": f"Unknown automation type: {auto['type']}"}
    config = auto["config"]
    try:
        job_runner.submit(
            lambda _rid: builder(config),
            automation_id=auto["id"],
            trigger="remediation",
            triggered_by="remediation",
        )
        return {"success": True, "output": f"Automation triggered: {auto['name']}"}
    except RuntimeError as exc:
        logger.error("Automation trigger failed: %s", exc)
        return {"success": False, "output": "Automation trigger failed"}


def _handle_agent_command(params):
    from .agent_store import queue_agent_command_and_wait
    hostname = params.get("hostname", "")
    cmd_type = params.get("command", "")
    cmd_params = params.get("params", {})
    timeout = int(params.get("timeout", 30))
    if not hostname or not cmd_type:
        return {"success": False, "output": "Missing hostname or command"}
    result = queue_agent_command_and_wait(
        hostname, cmd_type, cmd_params, timeout=timeout, queued_by="remediation",
    )
    if result is None:
        return {"success": False, "output": "Agent command timed out"}
    status = result.get("status", "error")
    return {"success": status != "error", "output": f"Agent command: {status}"}


def _health_check(action_type, params):
    """Post-action health check. Returns True if healthy."""
    import time as _time
    _time.sleep(2)  # Brief wait for action to take effect
    if action_type == "restart_container":
        try:
            name = _safe_name(params["container"])
        except ValueError:
            return False
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name],
                          capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "true"
    if action_type == "restart_service":
        try:
            svc = _safe_name(params["service"], pattern=r'^[a-zA-Z0-9@._\-]+$')
        except ValueError:
            return False
        r = subprocess.run(["systemctl", "is-active", svc],
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
    "run": _handle_run,
    "webhook": _handle_webhook,
    "automation": _handle_automation,
    "agent_command": _handle_agent_command,
}
