# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""System metrics collection: psutil + /proc fallbacks."""
from __future__ import annotations

import os
import platform
import socket
import time

from utils import (
    _SKIP_FSTYPES,
    _SKIP_MOUNT_PREFIXES,
    _read_proc,
)

# VERSION is injected at runtime from __main__ via the collect_metrics() call
# We import it lazily to avoid circular imports
_VERSION_REF: list[str] = ["unknown"]


def _set_version(v: str) -> None:
    _VERSION_REF[0] = v


# ── /proc-based collectors (zero dependencies) ──────────────────────────────

def _collect_cpu_linux() -> tuple[float, int]:
    """Read CPU usage from /proc/stat (two samples, 1s apart)."""
    def parse_stat():
        line = _read_proc("/proc/stat").split("\n", 1)[0]
        parts = line.split()[1:]
        return [int(x) for x in parts]

    s1 = parse_stat()
    time.sleep(1)
    s2 = parse_stat()

    delta = [s2[i] - s1[i] for i in range(len(s1))]
    total = sum(delta) or 1
    idle = delta[3] + (delta[4] if len(delta) > 4 else 0)
    cpu_percent = round((1 - idle / total) * 100, 1)

    cpu_count = _read_proc("/proc/cpuinfo").count("processor\t")
    return cpu_percent, cpu_count or 1


def _collect_memory_linux() -> dict:
    """Read memory from /proc/meminfo."""
    info = {}
    for line in _read_proc("/proc/meminfo").split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            num = val.strip().split()[0]
            info[key.strip()] = int(num) * 1024

    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", info.get("MemFree", 0))
    used = total - available
    percent = round((used / total * 100) if total else 0, 1)
    return {"total": total, "used": used, "percent": percent}


def _collect_disks_linux() -> list[dict]:
    """Read disk usage from /proc/mounts + statvfs."""
    disks = []
    seen_devs = set()
    mounts_raw = _read_proc("/proc/mounts")
    for line in mounts_raw.split("\n"):
        parts = line.split()
        if len(parts) < 3:
            continue
        dev, mount, fstype = parts[0], parts[1], parts[2]
        if fstype in _SKIP_FSTYPES:
            continue
        if any(mount.startswith(p) for p in _SKIP_MOUNT_PREFIXES):
            continue
        if dev in seen_devs and not dev.startswith("/dev/"):
            continue
        seen_devs.add(dev)
        try:
            st = os.statvfs(mount)
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            used = total - free
            if total == 0:
                continue
            percent = round(used / total * 100, 1)
            disks.append({
                "mount": mount,
                "total": total,
                "used": used,
                "percent": percent,
                "fstype": fstype,
            })
        except (OSError, PermissionError):
            pass
    return disks


def _collect_network_linux() -> dict:
    """Read network I/O from /proc/net/dev."""
    total_rx, total_tx = 0, 0
    for line in _read_proc("/proc/net/dev").split("\n")[2:]:
        if ":" not in line:
            continue
        iface, data = line.split(":", 1)
        iface = iface.strip()
        if iface == "lo":
            continue
        parts = data.split()
        if len(parts) >= 9:
            total_rx += int(parts[0])
            total_tx += int(parts[8])
    return {"bytes_sent": total_tx, "bytes_recv": total_rx}


def _collect_temps_linux() -> dict:
    """Read temperatures from /sys/class/thermal and /sys/class/hwmon."""
    temps = {}
    base = "/sys/class/thermal"
    if os.path.isdir(base):
        for tz in sorted(os.listdir(base)):
            if not tz.startswith("thermal_zone"):
                continue
            temp_raw = _read_proc(f"{base}/{tz}/temp").strip()
            type_name = _read_proc(f"{base}/{tz}/type").strip() or tz
            if temp_raw:
                try:
                    temps[type_name] = round(int(temp_raw) / 1000, 1)
                except ValueError:
                    pass
    base = "/sys/class/hwmon"
    if os.path.isdir(base):
        for hw in sorted(os.listdir(base)):
            hw_path = f"{base}/{hw}"
            name = _read_proc(f"{hw_path}/name").strip() or hw
            for f in sorted(os.listdir(hw_path)):
                if f.startswith("temp") and f.endswith("_input"):
                    val = _read_proc(f"{hw_path}/{f}").strip()
                    label = _read_proc(f"{hw_path}/{f.replace('_input','_label')}").strip()
                    key = f"{name}_{label}" if label else name
                    if val:
                        try:
                            t = round(int(val) / 1000, 1)
                            if 0 < t < 150:
                                temps[key] = t
                        except ValueError:
                            pass
    return temps


def _collect_processes_linux() -> list[dict]:
    """Read top processes from /proc/[pid]/stat."""
    procs = []
    try:
        for pid_dir in os.listdir("/proc"):
            if not pid_dir.isdigit():
                continue
            try:
                stat = _read_proc(f"/proc/{pid_dir}/stat")
                if not stat:
                    continue
                name_start = stat.index("(") + 1
                name_end = stat.rindex(")")
                name = stat[name_start:name_end]
                parts = stat[name_end + 2:].split()
                if len(parts) < 12:
                    continue
                utime = int(parts[11])
                stime = int(parts[12])
                rss_pages = int(parts[21]) if len(parts) > 21 else 0
                procs.append({
                    "pid": int(pid_dir),
                    "name": name[:30],
                    "cpu_ticks": utime + stime,
                    "rss": rss_pages * os.sysconf("SC_PAGE_SIZE"),
                })
            except (OSError, ValueError, IndexError):
                pass
    except OSError:
        pass
    procs.sort(key=lambda p: p["rss"], reverse=True)
    mem = _collect_memory_linux()
    total_mem = mem.get("total", 1)
    return [
        {"pid": p["pid"], "name": p["name"], "cpu": 0.0,
         "mem": round(p["rss"] / total_mem * 100, 1)}
        for p in procs[:5]
    ]


def _collect_uptime_linux() -> int:
    """Read uptime from /proc/uptime."""
    raw = _read_proc("/proc/uptime").split()
    return int(float(raw[0])) if raw else 0


def _collect_load_linux() -> tuple[float, float, float]:
    """Read load average from /proc/loadavg."""
    raw = _read_proc("/proc/loadavg").split()
    if len(raw) >= 3:
        return float(raw[0]), float(raw[1]), float(raw[2])
    return 0.0, 0.0, 0.0


# ── psutil-based collectors (optional, cross-platform) ──────────────────────

def _collect_psutil() -> dict | None:
    """Collect metrics using psutil if available."""
    try:
        import psutil
    except ImportError:
        return None

    cpu_percent = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    net = psutil.net_io_counters()
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)

    disks = []
    for part in psutil.disk_partitions(all=False):
        if part.fstype in _SKIP_FSTYPES:
            continue
        if any(part.mountpoint.startswith(p) for p in _SKIP_MOUNT_PREFIXES):
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            if usage.total == 0:
                continue
            disks.append({
                "mount": part.mountpoint,
                "total": usage.total,
                "used": usage.used,
                "percent": usage.percent,
                "fstype": part.fstype,
            })
        except (PermissionError, OSError):
            pass

    temps = {}
    try:
        for name, entries in psutil.sensors_temperatures().items():
            for entry in entries:
                if entry.current > 0:
                    key = f"{name}_{entry.label}" if entry.label else name
                    temps[key] = round(entry.current, 1)
    except (AttributeError, RuntimeError):
        pass

    top_procs = []
    try:
        for proc in sorted(
            psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
            key=lambda p: p.info.get("cpu_percent", 0) or 0, reverse=True,
        )[:5]:
            info = proc.info
            top_procs.append({
                "pid": info.get("pid", 0),
                "name": info.get("name", ""),
                "cpu": round(info.get("cpu_percent", 0) or 0, 1),
                "mem": round(info.get("memory_percent", 0) or 0, 1),
            })
    except (psutil.Error, OSError):
        pass

    return {
        "cpu_percent": cpu_percent,
        "cpu_count": psutil.cpu_count() or 1,
        "load_1m": round(load[0], 2),
        "load_5m": round(load[1], 2),
        "load_15m": round(load[2], 2),
        "mem_total": mem.total,
        "mem_used": mem.used,
        "mem_percent": round(mem.percent, 1),
        "disks": disks,
        "net_bytes_sent": net.bytes_sent,
        "net_bytes_recv": net.bytes_recv,
        "temperatures": temps,
        "top_processes": top_procs,
        "uptime_s": int(time.time() - psutil.boot_time()),
    }


# ── Main collector ───────────────────────────────────────────────────────────

def collect_metrics() -> dict:
    """Collect system metrics. Uses psutil if available, falls back to /proc."""
    data = _collect_psutil()
    if data is None:
        cpu_percent, cpu_count = _collect_cpu_linux()
        mem = _collect_memory_linux()
        load = _collect_load_linux()
        net = _collect_network_linux()
        data = {
            "cpu_percent": cpu_percent,
            "cpu_count": cpu_count,
            "load_1m": load[0],
            "load_5m": load[1],
            "load_15m": load[2],
            "mem_total": mem["total"],
            "mem_used": mem["used"],
            "mem_percent": mem["percent"],
            "disks": _collect_disks_linux(),
            "net_bytes_sent": net["bytes_sent"],
            "net_bytes_recv": net["bytes_recv"],
            "temperatures": _collect_temps_linux(),
            "top_processes": _collect_processes_linux(),
            "uptime_s": _collect_uptime_linux(),
        }

    data["hostname"] = socket.gethostname()
    data["platform"] = platform.system()
    data["arch"] = platform.machine()
    data["timestamp"] = int(time.time())
    data["agent_version"] = _VERSION_REF[0]
    return data
