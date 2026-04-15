# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Default healing rules with escalation chains.

Provides sensible out-of-the-box escalation chains for common failure
scenarios. These are used when:
1. Built-in threshold alerts fire (CPU, disk, service, memory)
2. User-defined alertRules don't specify an escalation_chain

Rules start at 'notify' trust by default — they must earn promotion
to 'execute' through the trust governor. Users can override autonomy
in settings.

Each chain escalates through increasingly aggressive actions:
step 1 (low-risk, fast) → step 2 (medium-risk) → step 3 (high-risk, needs approval)
"""
from __future__ import annotations

# Default chains keyed by scenario pattern.
# The pipeline matches on rule_id prefix to find the right chain.
DEFAULT_CHAINS: dict[str, dict] = {
    # ── CPU critical ──────────────────────────────────────────────
    "cpu_critical": {
        "condition": "cpuPercent > 90",
        "target": "system",
        "severity": "danger",
        "default_autonomy": "notify",
        "escalation_chain": [
            {
                "action": "process_kill",
                "params": {},  # executor identifies top CPU process
                "verify_timeout": 15,
            },
            {
                "action": "nice_adjust",
                "params": {"priority": 19},
                "verify_timeout": 15,
            },
            {
                "action": "clear_cache",
                "params": {"target": "system"},
                "verify_timeout": 15,
            },
        ],
    },

    # ── CPU high (warning) ────────────────────────────────────────
    "cpu_high": {
        "condition": "cpuPercent > 75",
        "target": "system",
        "severity": "warning",
        "default_autonomy": "notify",
        "escalation_chain": [
            {
                "action": "nice_adjust",
                "params": {"priority": 10},
                "verify_timeout": 15,
            },
        ],
    },

    # ── Disk critical (>= 90%) ────────────────────────────────────
    "disk_critical": {
        "condition": "disk_percent >= 90",
        "target": "disk",
        "severity": "danger",
        "default_autonomy": "notify",
        "escalation_chain": [
            {
                "action": "temp_cleanup",
                "params": {"path": "/tmp", "max_age_hours": 24},
                "verify_timeout": 30,
            },
            {
                "action": "journal_vacuum",
                "params": {"max_size": "500M"},
                "verify_timeout": 15,
            },
            {
                "action": "log_rotate",
                "params": {"service": "all"},
                "verify_timeout": 30,
            },
            {
                "action": "storage_cleanup",
                "params": {"targets": ["docker_images", "package_cache", "old_logs"]},
                "verify_timeout": 60,
            },
        ],
    },

    # ── Disk high (>= 80%) ────────────────────────────────────────
    "disk_high": {
        "condition": "disk_percent >= 80",
        "target": "disk",
        "severity": "warning",
        "default_autonomy": "notify",
        "escalation_chain": [
            {
                "action": "temp_cleanup",
                "params": {"path": "/tmp", "max_age_hours": 48},
                "verify_timeout": 30,
            },
            {
                "action": "package_cache_clean",
                "params": {},
                "verify_timeout": 30,
            },
        ],
    },

    # ── Service failed ────────────────────────────────────────────
    "service_failed": {
        "condition": "service_status == failed",
        "target": "service",
        "severity": "danger",
        "default_autonomy": "notify",
        "escalation_chain": [
            {
                "action": "service_reset_failed",
                "params": {},  # service name injected by caller
                "verify_timeout": 10,
            },
            {
                "action": "restart_service",
                "params": {},
                "verify_timeout": 30,
            },
            {
                "action": "service_dependency_restart",
                "params": {},
                "verify_timeout": 60,
            },
        ],
    },

    # ── Container stopped/crashed ─────────────────────────────────
    "container_down": {
        "condition": "container_status != running",
        "target": "container",
        "severity": "danger",
        "default_autonomy": "notify",
        "escalation_chain": [
            {
                "action": "restart_container",
                "params": {},  # container name injected by caller
                "verify_timeout": 30,
            },
            {
                "action": "container_recreate",
                "params": {},
                "verify_timeout": 120,
            },
        ],
    },

    # ── Memory critical (> 90%) ───────────────────────────────────
    "memory_critical": {
        "condition": "memPercent > 90",
        "target": "system",
        "severity": "danger",
        "default_autonomy": "notify",
        "escalation_chain": [
            {
                "action": "clear_cache",
                "params": {"target": "system"},
                "verify_timeout": 15,
            },
            {
                "action": "memory_pressure_relief",
                "params": {},
                "verify_timeout": 30,
            },
            {
                "action": "process_kill",
                "params": {},  # kills top memory consumer
                "verify_timeout": 15,
            },
        ],
    },

    # ── Temperature critical ──────────────────────────────────────
    "temp_critical": {
        "condition": "cpu_temp > 85",
        "target": "system",
        "severity": "danger",
        "default_autonomy": "notify",
        "escalation_chain": [
            {
                "action": "nice_adjust",
                "params": {"priority": 19},
                "verify_timeout": 15,
            },
            {
                "action": "process_kill",
                "params": {},
                "verify_timeout": 15,
            },
        ],
    },

    # ── DNS down ──────────────────────────────────────────────────
    "dns_down": {
        "condition": "dns_status == offline",
        "target": "dns",
        "severity": "danger",
        "default_autonomy": "notify",
        "escalation_chain": [
            {
                "action": "flush_dns",
                "params": {},
                "verify_timeout": 15,
            },
            {
                "action": "restart_service",
                "params": {"service": "pihole-FTL"},
                "verify_timeout": 30,
            },
            {
                "action": "restart_container",
                "params": {"container": "pihole"},
                "verify_timeout": 30,
            },
        ],
    },

    # ── VPN disconnected ──────────────────────────────────────────
    "vpn_down": {
        "condition": "vpn_status == disconnected",
        "target": "vpn",
        "severity": "warning",
        "default_autonomy": "notify",
        "escalation_chain": [
            {
                "action": "vpn_reconnect",
                "params": {"interface": "tailscale0"},
                "verify_timeout": 30,
            },
        ],
    },

    # ── Backup stale (> 48h) ──────────────────────────────────────
    "backup_stale": {
        "condition": "backup_age_hours > 48",
        "target": "backup",
        "severity": "warning",
        "default_autonomy": "notify",
        "escalation_chain": [
            {
                "action": "trigger_backup",
                "params": {"source": "default"},
                "verify_timeout": 300,
            },
            {
                "action": "backup_verify",
                "params": {"backup_set": "latest"},
                "verify_timeout": 300,
            },
        ],
    },
}


def get_chain_for_scenario(scenario: str) -> dict | None:
    """Get the default chain for a scenario pattern.

    scenario: one of the keys in DEFAULT_CHAINS (e.g., 'cpu_critical',
    'service_failed', 'container_down', 'disk_critical')
    """
    return DEFAULT_CHAINS.get(scenario)


def get_chain_for_rule_id(rule_id: str) -> list | None:
    """Try to match a rule_id to a default chain.

    Matches on prefix/pattern: 'cpu_crit' -> cpu_critical,
    'svc_nginx' -> service_failed, 'disk_crit_/' -> disk_critical, etc.
    """
    rule_lower = rule_id.lower()

    if "cpu_crit" in rule_lower or "cpu_critical" in rule_lower:
        return DEFAULT_CHAINS["cpu_critical"]["escalation_chain"]
    if "cpu_high" in rule_lower:
        return DEFAULT_CHAINS["cpu_high"]["escalation_chain"]
    if "disk_crit" in rule_lower:
        return DEFAULT_CHAINS["disk_critical"]["escalation_chain"]
    if "disk_high" in rule_lower:
        return DEFAULT_CHAINS["disk_high"]["escalation_chain"]
    if "svc_" in rule_lower or "service_fail" in rule_lower:
        return DEFAULT_CHAINS["service_failed"]["escalation_chain"]
    if "container" in rule_lower:
        return DEFAULT_CHAINS["container_down"]["escalation_chain"]
    if "mem" in rule_lower and ("crit" in rule_lower or "high" in rule_lower):
        return DEFAULT_CHAINS["memory_critical"]["escalation_chain"]
    if "temp_crit" in rule_lower:
        return DEFAULT_CHAINS["temp_critical"]["escalation_chain"]
    if "dns" in rule_lower:
        return DEFAULT_CHAINS["dns_down"]["escalation_chain"]
    if "vpn" in rule_lower:
        return DEFAULT_CHAINS["vpn_down"]["escalation_chain"]
    if "backup" in rule_lower:
        return DEFAULT_CHAINS["backup_stale"]["escalation_chain"]

    return None
