# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Agent command risk classification, capability registry, and validation."""
from __future__ import annotations

import re

# ── Risk level classification ──────────────────────────────────────────────────

RISK_LEVELS: dict[str, str] = {
    # Low risk — read-only / non-destructive informational commands
    "ping":             "low",
    "check_service":    "low",
    "get_logs":         "low",
    "network_test":     "low",
    "package_updates":  "low",
    "system_info":      "low",
    "disk_usage":       "low",
    "list_services":    "low",
    "list_users":       "low",
    "file_read":        "low",
    "file_list":        "low",
    "file_checksum":    "low",
    "file_stat":        "low",
    "container_list":   "low",
    "container_logs":   "low",
    "dns_lookup":       "low",
    "network_config":   "low",
    "network_stats":    "low",
    "endpoint_check":   "low",
    "follow_logs":      "low",
    "stop_stream":      "low",
    "get_stream":       "low",
    "discover_services": "low",
    "network_discover": "low",
    "security_scan":    "low",
    # Medium risk — controlled mutations with limited blast radius
    "verify_backup":    "medium",
    "restart_service":  "medium",
    "set_interval":     "medium",
    "service_control":  "medium",
    "file_transfer":    "medium",
    "file_push":        "medium",
    "container_control": "medium",
    # High risk — destructive, privileged, or irreversible operations
    "exec":             "high",
    "file_write":       "high",
    "file_delete":      "high",
    "update_agent":     "high",
    "package_install":  "high",
    "package_remove":   "high",
    "user_manage":      "high",
    "uninstall_agent":  "high",
    "reboot":           "high",
    "process_kill":     "high",
}

# ── Role permissions ───────────────────────────────────────────────────────────

# Maps role -> set of risk levels that role may execute
_ROLE_ALLOWED_RISKS: dict[str, frozenset[str]] = {
    "admin":    frozenset({"low", "medium", "high"}),
    "operator": frozenset({"low", "medium"}),
    "viewer":   frozenset(),
}


def check_role_permission(role: str, risk: str) -> bool:
    """Return True if *role* is permitted to execute a command of *risk* level."""
    return risk in _ROLE_ALLOWED_RISKS.get(role, frozenset())


# ── Version capability registry ────────────────────────────────────────────────

# Original nine commands shipped with v1.1.0
_V1_COMMANDS: frozenset[str] = frozenset({
    "exec",
    "restart_service",
    "update_agent",
    "set_interval",
    "ping",
    "get_logs",
    "check_service",
    "network_test",
    "package_updates",
})

# All 32 commands available in v2.0.0
_V2_COMMANDS: frozenset[str] = frozenset(RISK_LEVELS.keys())

AGENT_CAPABILITIES: dict[str, frozenset[str]] = {
    "1.1.0": _V1_COMMANDS,
    "v1.1.0": _V1_COMMANDS,
    "2.0.0": _V2_COMMANDS,
    "v2.0.0": _V2_COMMANDS,
    "2.1.0": _V2_COMMANDS,
    "v2.1.0": _V2_COMMANDS,
}


def get_agent_capabilities(version: str) -> frozenset[str]:
    """Return the set of commands supported by *version*.

    Handles both "2.0.0" and "v2.0.0" formats.  For unknown versions
    >= 2.0.0 (e.g. a newer agent), assume full v2 capabilities rather
    than falling back to the restrictive v1.1.0 baseline.
    """
    caps = AGENT_CAPABILITIES.get(version) or AGENT_CAPABILITIES.get(f"v{version}")
    if caps:
        return caps
    # Parse version to decide fallback: >= 2.0.0 gets v2 commands
    raw = version.lstrip("v")
    try:
        major = int(raw.split(".")[0])
        if major >= 2:
            return _V2_COMMANDS
    except (ValueError, IndexError):
        pass
    return _V1_COMMANDS


# ── Validation helpers ─────────────────────────────────────────────────────────

_RE_SERVICE  = re.compile(r"^[a-zA-Z0-9@._-]+$")
_RE_PACKAGE  = re.compile(r"^[a-zA-Z0-9._+-]+$")
_RE_USERNAME = re.compile(r"^[a-z_][a-z0-9_-]*$")

# Absolute paths that must never be written/deleted by an agent command
PATH_DENYLIST: frozenset[str] = frozenset({
    "/etc/shadow",
    "/etc/passwd",
    "/etc/sudoers",
    "/etc/hosts",
    "/etc/ssh/sshd_config",
    "/root/.ssh/authorized_keys",
    "/boot/grub/grub.cfg",
    "/proc",
    "/sys",
    "/dev",
})

# Regex patterns that match denied path prefixes/substrings
PATH_DENY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)\.\.(/|$)"),          # directory traversal
    re.compile(r"\x00"),                      # null byte injection
    re.compile(r"^/proc/"),                   # kernel proc fs
    re.compile(r"^/sys/"),                    # kernel sys fs
    re.compile(r"^/dev/"),                    # device nodes
    re.compile(r"^/run/secrets/"),            # container secrets
)

# Groups that confer elevated privileges — warn/reject in user_manage
_DANGEROUS_GROUPS: frozenset[str] = frozenset({"sudo", "wheel", "root", "adm", "shadow"})


def _validate_path(path: str) -> str | None:
    """Return an error string if *path* should be rejected, else None."""
    if not path:
        return "Path must not be empty"
    if "\x00" in path:
        return "Path contains null byte"
    if ".." in path.split("/"):
        return "Path traversal ('..') is not allowed"
    if path in PATH_DENYLIST:
        return f"Path '{path}' is on the denylist"
    for pat in PATH_DENY_PATTERNS:
        if pat.search(path):
            return f"Path '{path}' matches a denied pattern"
    return None


def validate_command_params(cmd_type: str, params: dict) -> str | None:  # noqa: C901
    """Validate the parameters for *cmd_type*.

    Returns an error string describing the first problem found, or None
    when the parameters are acceptable.
    """
    # ── Service commands ───────────────────────────────────────────────────────
    if cmd_type in ("check_service", "restart_service", "service_control"):
        svc = params.get("service", "")
        if not svc:
            return "Parameter 'service' is required"
        if not _RE_SERVICE.match(svc):
            return f"Invalid service name '{svc}' — must match ^[a-zA-Z0-9@._-]+$"
        if len(svc) > 256:
            return "Service name exceeds maximum length of 256 characters"

    # ── Log retrieval ──────────────────────────────────────────────────────────
    elif cmd_type == "get_logs":
        svc = params.get("service")
        if svc is not None and not _RE_SERVICE.match(str(svc)):
            return f"Invalid service name '{svc}'"
        lines = params.get("lines")
        if lines is not None:
            try:
                n = int(lines)
                if n < 1 or n > 10_000:
                    return "Parameter 'lines' must be between 1 and 10000"
            except (TypeError, ValueError):
                return "Parameter 'lines' must be an integer"

    # ── Package commands ───────────────────────────────────────────────────────
    elif cmd_type in ("package_install", "package_remove"):
        pkg = params.get("package", "")
        if not pkg:
            return "Parameter 'package' is required"
        if not _RE_PACKAGE.match(pkg):
            return f"Invalid package name '{pkg}' — must match ^[a-zA-Z0-9._+-]+$"
        if len(pkg) > 256:
            return "Package name exceeds maximum length of 256 characters"

    # ── File read / list / stat / checksum ────────────────────────────────────
    elif cmd_type in ("file_read", "file_list", "file_stat", "file_checksum"):
        path = params.get("path", "")
        err = _validate_path(path)
        if err:
            return err

    # ── File write ────────────────────────────────────────────────────────────
    elif cmd_type == "file_write":
        path = params.get("path", "")
        err = _validate_path(path)
        if err:
            return err
        if "content" not in params:
            return "Parameter 'content' is required for file_write"

    # ── File delete ───────────────────────────────────────────────────────────
    elif cmd_type == "file_delete":
        path = params.get("path", "")
        err = _validate_path(path)
        if err:
            return err

    # ── File transfer / push ──────────────────────────────────────────────────
    elif cmd_type in ("file_transfer", "file_push"):
        for field in ("source", "destination"):
            val = params.get(field, "")
            err = _validate_path(val)
            if err:
                return f"Invalid '{field}': {err}"

    # ── Container control ─────────────────────────────────────────────────────
    elif cmd_type == "container_control":
        container = params.get("container", "")
        if not container:
            return "Parameter 'container' is required"
        action = params.get("action", "")
        allowed_actions = {"start", "stop", "restart", "pause", "unpause", "remove"}
        if action not in allowed_actions:
            return f"Invalid container action '{action}' — must be one of {sorted(allowed_actions)}"

    # ── Container logs ────────────────────────────────────────────────────────
    elif cmd_type == "container_logs":
        container = params.get("container", "")
        if not container:
            return "Parameter 'container' is required"
        lines = params.get("lines")
        if lines is not None:
            try:
                n = int(lines)
                if n < 1 or n > 10_000:
                    return "Parameter 'lines' must be between 1 and 10000"
            except (TypeError, ValueError):
                return "Parameter 'lines' must be an integer"

    # ── User management ───────────────────────────────────────────────────────
    elif cmd_type == "user_manage":
        username = params.get("username", "")
        if not username:
            return "Parameter 'username' is required"
        if not _RE_USERNAME.match(username):
            return f"Invalid username '{username}' — must match ^[a-z_][a-z0-9_-]*$"
        action = params.get("action", "")
        allowed_actions = {"create", "delete", "modify", "lock", "unlock"}
        if action not in allowed_actions:
            return f"Invalid user action '{action}' — must be one of {sorted(allowed_actions)}"
        groups = params.get("groups", [])
        if isinstance(groups, list):
            dangerous = [g for g in groups if g in _DANGEROUS_GROUPS]
            if dangerous:
                return (
                    f"Groups {dangerous} grant elevated privileges — "
                    "use a dedicated privilege-escalation workflow instead"
                )

    # ── Arbitrary exec ────────────────────────────────────────────────────────
    elif cmd_type == "exec":
        command = params.get("command", "")
        if not command:
            return "Parameter 'command' is required"
        if len(command) > 4096:
            return "Command exceeds maximum length of 4096 characters"

    # ── Process kill ──────────────────────────────────────────────────────────
    elif cmd_type == "process_kill":
        pid = params.get("pid")
        if pid is None:
            return "Parameter 'pid' is required"
        try:
            n = int(pid)
            if n < 1:
                return "Parameter 'pid' must be a positive integer"
        except (TypeError, ValueError):
            return "Parameter 'pid' must be an integer"

    # ── DNS lookup ────────────────────────────────────────────────────────────
    elif cmd_type == "dns_lookup":
        host = params.get("host", "")
        if not host:
            return "Parameter 'host' is required"
        if len(host) > 253:
            return "Hostname exceeds maximum length of 253 characters"

    # ── set_interval ──────────────────────────────────────────────────────────
    elif cmd_type == "set_interval":
        interval = params.get("interval")
        if interval is None:
            return "Parameter 'interval' is required"
        try:
            n = int(interval)
            if n < 5:
                return "Parameter 'interval' must be at least 5 seconds"
            if n > 86_400:
                return "Parameter 'interval' must not exceed 86400 seconds (24 h)"
        except (TypeError, ValueError):
            return "Parameter 'interval' must be an integer"

    # ── Endpoint check ────────────────────────────────────────────────────────
    elif cmd_type == "endpoint_check":
        url = params.get("url", "")
        if not url:
            return "Parameter 'url' is required"
        if not url.startswith(("http://", "https://")):
            return "Parameter 'url' must start with http:// or https://"
        if len(url) > 2048:
            return "URL exceeds maximum length of 2048 characters"

    # ── Backup verification ─────────────────────────────────────────────────
    elif cmd_type == "verify_backup":
        path = params.get("path", "")
        err = _validate_path(path)
        if err:
            return err
        vtype = params.get("verification_type", "")
        allowed_types = {"checksum", "restore_test", "db_integrity"}
        if vtype and vtype not in allowed_types:
            return f"Invalid verification_type '{vtype}' — must be one of {sorted(allowed_types)}"

    # ── uninstall_agent — requires explicit confirmation ───────────────────────
    elif cmd_type == "uninstall_agent":
        if params.get("confirm") is not True:
            return "Parameter 'confirm' must be true to uninstall the agent"

    # All other recognised commands (ping, system_info, disk_usage, …) need no
    # additional parameter validation beyond the risk/capability checks above.

    return None
