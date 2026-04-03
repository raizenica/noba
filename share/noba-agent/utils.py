# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Shared utility helpers: path validation, subprocess safety, platform detection."""
from __future__ import annotations

import os
import platform
import subprocess

# ── Platform detection ────────────────────────────────────────────────────────
_PLATFORM = platform.system().lower()
_HAS_SYSTEMD = os.path.isdir("/run/systemd/system") if _PLATFORM == "linux" else False


def _detect_container_runtime():
    for rt in ("podman", "docker"):
        for d in ("/usr/bin", "/usr/local/bin"):
            if os.path.isfile(f"{d}/{rt}"):
                return rt
    return None


def _detect_pkg_manager():
    for mgr in ("apt-get", "dnf", "yum", "pkg", "brew"):
        for d in ("/usr/bin", "/usr/local/bin", "/usr/sbin"):
            if os.path.isfile(f"{d}/{mgr}"):
                return mgr.replace("-get", "")
    return None


# ── Path safety ───────────────────────────────────────────────────────────────
_BACKUP_DIR = os.path.expanduser("~/.noba-agent/backups")
_SAFE_WRITE_DIRS = (
    "/opt/noba-agent/",
    "/tmp/noba-",
    os.path.expanduser("~/.noba-agent/"),
    _BACKUP_DIR,
)
_SAFE_READ_DENYLIST = frozenset({"/etc/shadow", "/etc/gshadow", "/proc/kcore"})
_SAFE_READ_DENY_PATTERNS = ("/.ssh/id_", "/private/key")


def _safe_path(path, *, write=False):
    """Validate path safety. Write ops use allowlist; read ops use denylist.

    Security measures:
    - Rejects null bytes
    - Resolves symlinks with realpath() to prevent symlink attacks
    - Normalizes paths to prevent .. traversal
    - Write ops: strict allowlist of permitted directories
    - Read ops: denylist of sensitive paths
    """
    if "\0" in path:
        return "Null byte in path"

    try:
        real = os.path.realpath(path)
    except (OSError, ValueError) as e:
        return f"Invalid path: {e}"

    normalized = os.path.normpath(path)
    if normalized.startswith("..") or "/../" in path:
        return "Path traversal not allowed"

    if write:
        allowed = False
        for safe_dir in _SAFE_WRITE_DIRS:
            safe_real = os.path.realpath(safe_dir)
            if real.startswith(safe_real) or normalized.startswith(safe_dir):
                allowed = True
                break
        if not allowed:
            return f"Write denied: path must be under {', '.join(_SAFE_WRITE_DIRS)}"
    else:
        for denied in _SAFE_READ_DENYLIST:
            if real == denied or real.startswith(denied + "/"):
                return f"Denied path: {real}"
        for pat in _SAFE_READ_DENY_PATTERNS:
            if pat in real:
                return f"Denied pattern: {pat}"
    return None


# ── Subprocess helper ─────────────────────────────────────────────────────────
_CMD_MAX_OUTPUT = 65536


def _safe_run(cmd, timeout=30):
    """Run a subprocess with safety limits, return combined output."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        return out[:_CMD_MAX_OUTPUT]
    except subprocess.TimeoutExpired:
        return "[timeout]"
    except Exception as e:
        return f"[error: {e}]"


# ── /proc helpers ─────────────────────────────────────────────────────────────
def _read_proc(path: str) -> str:
    """Read a /proc or /sys file, return empty string on failure."""
    try:
        with open(path) as f:
            return f.read()
    except (OSError, PermissionError):
        return ""


# ── Mount type filter ─────────────────────────────────────────────────────────
_SKIP_FSTYPES = frozenset({
    "squashfs", "tmpfs", "devtmpfs", "devfs", "overlay", "aufs",
    "proc", "sysfs", "cgroup", "cgroup2", "debugfs", "tracefs",
    "securityfs", "pstore", "bpf", "fusectl", "configfs",
    "hugetlbfs", "mqueue", "efivarfs", "fuse.portal",
})
_SKIP_MOUNT_PREFIXES = ("/snap/", "/sys/", "/proc/", "/dev/", "/run/")
