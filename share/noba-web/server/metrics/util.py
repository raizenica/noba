# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Shared metric infrastructure: cache, subprocess helper, validators, formatters."""
from __future__ import annotations

import ipaddress
import logging
import re
import subprocess
import threading
import time


logger = logging.getLogger("noba")

ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


def _read_file(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return default


# ── TTL cache (subprocess + expensive calls) ──────────────────────────────────
class TTLCache:
    def __init__(self, max_size: int = 256) -> None:
        self._store: dict = {}
        self._lock = threading.Lock()
        self._max = max_size

    def get(self, key: str, ttl: float = 30) -> object:
        with self._lock:
            entry = self._store.get(key)
            if entry and (time.time() - entry["t"]) < ttl:
                return entry["v"]
        return None

    def set(self, key: str, val: object) -> None:
        with self._lock:
            if len(self._store) >= self._max:
                oldest = min(self._store, key=lambda k: self._store[k]["t"])
                del self._store[oldest]
            self._store[key] = {"v": val, "t": time.time()}

    def bust(self, pattern: str) -> None:
        """Delete all keys containing pattern."""
        with self._lock:
            keys = [k for k in self._store if pattern in k]
            for k in keys:
                del self._store[k]


_cache = TTLCache()


def _run(cmd: list, timeout: float = 3, cache_key: str | None = None,
         cache_ttl: float = 30, ignore_rc: bool = False) -> str:
    if cache_key:
        hit = _cache.get(cache_key, cache_ttl)
        if hit is not None:
            return hit
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        if r.returncode != 0 and not ignore_rc:
            return ""
        out = r.stdout.strip()
        if cache_key and out:
            _cache.set(cache_key, out)
        return out
    except Exception:
        return ""


# ── Validation helpers ────────────────────────────────────────────────────────
def validate_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def validate_service_name(name: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9_.@-]+$", name))


# ── Byte formatters ───────────────────────────────────────────────────────────
def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"
