# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – CPU, memory, load metrics."""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from collections import deque

import psutil

from .util import _read_file

logger = logging.getLogger("noba")

# ── CPU ───────────────────────────────────────────────────────────────────────
_cpu_history: deque = deque(maxlen=20)
_cpu_lock = threading.Lock()


def get_cpu_percent() -> float:
    pct = round(psutil.cpu_percent(interval=None), 1)
    with _cpu_lock:
        _cpu_history.append(pct)
    return pct


def get_cpu_history() -> list:
    with _cpu_lock:
        return list(_cpu_history)


def get_cpu_governor() -> str:
    return _read_file("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", "unknown").strip()


# ── System info ───────────────────────────────────────────────────────────────
def collect_system() -> dict:
    s: dict = {}
    try:
        for line in _read_file("/etc/os-release").splitlines():
            if line.startswith("PRETTY_NAME="):
                s["osName"] = line.split("=", 1)[1].strip().strip('"')
                break
    except Exception:
        s["osName"] = "Linux"

    s["kernel"]   = os.uname().release
    s["hostname"]  = socket.gethostname()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1)
            sock.connect(("1.1.1.1", 80))
            s["defaultIp"] = sock.getsockname()[0]
    except Exception:
        s["defaultIp"] = ""

    try:
        up = psutil.boot_time()
        up_s = time.time() - up
        d, rem = divmod(int(up_s), 86400)
        h, rem = divmod(rem, 3600)
        s["uptime"] = (f"{d}d " if d else "") + f"{h}h {rem // 60}m"
    except Exception:
        s["uptime"] = "--"

    try:
        la = os.getloadavg()
        s["loadavg"] = " ".join(f"{x:.2f}" for x in la)
    except Exception:
        s["loadavg"] = "--"

    try:
        vm = psutil.virtual_memory()
        used_mib = (vm.total - vm.available) // (1024 * 1024)
        tot_mib  = vm.total // (1024 * 1024)
        s["memory"]     = f"{used_mib} MiB / {tot_mib} MiB"
        s["memPercent"] = round(vm.percent)
    except Exception:
        s["memPercent"] = 0

    return s
