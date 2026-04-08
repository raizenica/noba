# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Disk usage, I/O, cloud storage metrics."""
from __future__ import annotations

import logging
import threading
import time

import psutil

from .util import _run

logger = logging.getLogger("noba")

# ── Disk I/O tracking ────────────────────────────────────────────────────────
_disk_io_prev: dict = {}
_disk_io_ts: float = 0.0
_disk_io_lock = threading.Lock()


# ── Storage ───────────────────────────────────────────────────────────────────
def collect_storage() -> dict:
    disks = []
    try:
        for part in psutil.disk_partitions(all=False):
            mount = part.mountpoint
            if any(mount.startswith(p) for p in ("/var/lib/snapd", "/boot", "/run", "/snap")):
                continue
            if not part.device.startswith("/dev/"):
                continue
            try:
                usage = psutil.disk_usage(mount)
                pct   = round(usage.percent)
                disks.append({
                    "mount":    mount,
                    "percent":  pct,
                    "barClass": "danger" if pct >= 90 else "warning" if pct >= 75 else "success",
                    "size":     f"{usage.total // (1024**2)} MiB",
                    "used":     f"{usage.used  // (1024**2)} MiB",
                })
            except Exception:
                pass
    except Exception:
        pass

    # ZFS pools
    pools = []
    for line in _run(
        ["zpool", "list", "-H", "-o", "name,health"],
        timeout=3, cache_key="zpool", cache_ttl=15
    ).splitlines():
        if "\t" in line:
            n, h = line.split("\t", 1)
            pools.append({"name": n.strip(), "health": h.strip()})

    return {"disks": disks, "zfs": {"pools": pools}}


# ── Disk I/O ─────────────────────────────────────────────────────────────────
def collect_disk_io() -> dict:
    global _disk_io_prev, _disk_io_ts
    try:
        counters = psutil.disk_io_counters(perdisk=True)
        now = time.time()
        result = []
        with _disk_io_lock:
            if _disk_io_prev and now > _disk_io_ts:
                dt = now - _disk_io_ts
                for dev, c in counters.items():
                    if dev.startswith(("loop", "ram", "dm-")):
                        continue
                    prev = _disk_io_prev.get(dev)
                    if prev:
                        read_bps = max(0, (c.read_bytes - prev.read_bytes) / dt)
                        write_bps = max(0, (c.write_bytes - prev.write_bytes) / dt)
                        result.append({"device": dev, "read_bps": round(read_bps), "write_bps": round(write_bps)})
            _disk_io_prev = counters
            _disk_io_ts = now
        return {"diskIo": result}
    except Exception:
        return {"diskIo": []}


# ── rclone remotes ────────────────────────────────────────────────────────────
def get_rclone_remotes() -> dict:
    try:
        out = _run(["rclone", "listremotes"], timeout=3, cache_key="rclone_remotes", cache_ttl=10)
        lst = [
            {"name": line.strip().rstrip(":"), "label": "Cloud"}
            for line in out.splitlines() if line.strip()
        ]
        return {"available": True, "remotes": lst}
    except Exception:
        return {"available": False, "remotes": []}
