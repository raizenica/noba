"""Noba – System metrics using psutil + targeted subprocess calls."""
from __future__ import annotations

import glob
import ipaddress
import json
import logging
import os
import re
import subprocess
import threading
import time
from collections import deque

import psutil

from .config import VERSION

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


# ── Network I/O ───────────────────────────────────────────────────────────────
_net_prev: tuple | None = None
_net_prev_t: float | None = None
_net_lock = threading.Lock()


def get_net_io() -> tuple[float, float]:
    global _net_prev, _net_prev_t
    with _net_lock:
        try:
            counters = psutil.net_io_counters()
            rx, tx = counters.bytes_recv, counters.bytes_sent
            now = time.time()
            if _net_prev is None:
                _net_prev = (rx, tx)
                _net_prev_t = now
                return 0.0, 0.0
            dt = now - _net_prev_t
            if dt < 0.05:
                return 0.0, 0.0
            rx_bps = max(0.0, (rx - _net_prev[0]) / dt)
            tx_bps = max(0.0, (tx - _net_prev[1]) / dt)
            _net_prev = (rx, tx)
            _net_prev_t = now
            return rx_bps, tx_bps
        except Exception:
            return 0.0, 0.0


def human_bps(bps: float) -> str:
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024:
            return f"{bps:.1f} {unit}"
        bps /= 1024
    return f"{bps:.1f} TB/s"


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

    s["kernel"]   = _run(["uname", "-r"], cache_key="uname-r", cache_ttl=3600)
    s["hostname"]  = _run(["hostname"],    cache_key="hostname",  cache_ttl=3600)
    s["defaultIp"] = _run(
        ["bash", "-c", "ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \\K[\\d.]+'"],
        timeout=1,
    )

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


# ── Hardware ──────────────────────────────────────────────────────────────────
def collect_hardware() -> dict:
    s: dict = {}
    s["hwCpu"] = _run(
        ["bash", "-c", "lscpu | grep 'Model name' | head -1 | cut -d: -f2 | xargs"],
        cache_key="lscpu", cache_ttl=3600,
    )
    raw_gpu = _run(
        ["bash", "-c", "lspci | grep -i 'vga\\|3d' | cut -d: -f3"],
        cache_key="lspci", cache_ttl=3600,
    )
    s["hwGpu"] = raw_gpu.replace("\n", "<br>") if raw_gpu else "Unknown GPU"

    # CPU temperature — try psutil first, fall back to sensors
    cpu_temp = None
    try:
        temps = psutil.sensors_temperatures()
        for key in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"):
            if key in temps and temps[key]:
                cpu_temp = int(temps[key][0].current)
                break
    except Exception:
        pass

    if cpu_temp is None:
        raw = _run(["sensors"], timeout=2, cache_key="sensors", cache_ttl=5)
        m = re.search(r"(?:Tctl|Package id \d+|Core 0|temp1).*?\+?(\d+\.?\d*)[°℃]", raw)
        cpu_temp = int(float(m.group(1))) if m else None

    s["cpuTemp"] = f"{cpu_temp}°C" if cpu_temp is not None else "N/A"

    # GPU temperature
    gpu_t = _run(
        ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
        timeout=2, cache_key="nvidia-temp", cache_ttl=5,
    )
    if not gpu_t:
        raw = _run(
            ["bash", "-c", "cat /sys/class/drm/card*/device/hwmon/hwmon*/temp1_input 2>/dev/null | head -1"],
            timeout=1,
        )
        gpu_t = f"{int(raw) // 1000}°C" if raw else "N/A"
    else:
        gpu_t = f"{gpu_t}°C"
    s["gpuTemp"] = gpu_t

    s["battery"] = _collect_battery()
    return s


def _collect_battery() -> dict:
    try:
        bat = psutil.sensors_battery()
        if bat is None:
            return {"percent": 100, "status": "Desktop", "desktop": True, "timeRemaining": ""}
        pct    = round(bat.percent)
        status = "Charging" if bat.power_plugged else "Discharging"
        tr = ""
        if bat.secsleft and bat.secsleft > 0 and not bat.power_plugged:
            h, m = divmod(bat.secsleft // 60, 60)
            tr = f"{h}h {m}m"
        elif bat.power_plugged and bat.secsleft and bat.secsleft > 0:
            h, m = divmod(bat.secsleft // 60, 60)
            tr = f"{h}h {m}m to full"
        return {"percent": pct, "status": status, "desktop": False, "timeRemaining": tr}
    except Exception:
        # Fall back to /sys if psutil fails
        bats = glob.glob("/sys/class/power_supply/BAT*")
        if not bats:
            return {"percent": 100, "status": "Desktop", "desktop": True, "timeRemaining": ""}
        try:
            b = bats[0]
            pct  = int(_read_file(f"{b}/capacity", "0"))
            stat = _read_file(f"{b}/status", "Unknown")
            return {"percent": pct, "status": stat, "desktop": False, "timeRemaining": ""}
        except Exception:
            return {"percent": 0, "status": "Error", "desktop": False, "timeRemaining": ""}


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


# ── Network / processes ───────────────────────────────────────────────────────
def collect_network() -> dict:
    rx_bps, tx_bps = get_net_io()

    # Process list via psutil — no subprocess needed
    try:
        procs = [
            (p.info["name"] or "", p.info["cpu_percent"] or 0.0, p.info["memory_percent"] or 0.0)
            for p in psutil.process_iter(["name", "cpu_percent", "memory_percent"])
        ]
        top_cpu = [
            {"name": p[0][:16], "val": f"{p[1]:.1f}%"}
            for p in sorted(procs, key=lambda x: x[1], reverse=True)[:5]
        ]
        top_mem = [
            {"name": p[0][:16], "val": f"{p[2]:.1f}%"}
            for p in sorted(procs, key=lambda x: x[2], reverse=True)[:5]
        ]
    except Exception:
        top_cpu = top_mem = []

    return {
        "netRx":    human_bps(rx_bps),
        "netTx":    human_bps(tx_bps),
        "netRxRaw": rx_bps,
        "netTxRaw": tx_bps,
        "topCpu":   top_cpu,
        "topMem":   top_mem,
    }


# ── Services ──────────────────────────────────────────────────────────────────
def get_service_status(svc: str) -> tuple[str, bool]:
    svc = svc.strip()
    if not validate_service_name(svc):
        return "invalid", False
    for scope, is_user in (["--user"], True), ([], False):
        cmd = ["systemctl"] + ([scope] if isinstance(scope, str) else scope) + [
            "show", "-p", "ActiveState,LoadState", svc
        ]
        out = _run(cmd, timeout=2)
        d = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        if d.get("LoadState") not in (None, "", "not-found"):
            state = d.get("ActiveState", "unknown")
            if state == "inactive" and svc.endswith(".service"):
                t = _run(
                    ["systemctl"] + ([scope] if isinstance(scope, str) else scope) + [
                        "show", "-p", "ActiveState",
                        svc.replace(".service", ".timer"),
                    ],
                    timeout=1,
                )
                if "ActiveState=active" in t:
                    return "timer-active", is_user
            return state, is_user
    return "not-found", False


# ── Ping ──────────────────────────────────────────────────────────────────────
def ping_host(ip: str) -> tuple[str, bool, int]:
    ip = ip.strip()
    if not validate_ip(ip):
        return ip, False, 0
    try:
        t0 = time.time()
        r  = subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True, timeout=2.5)
        return ip, r.returncode == 0, round((time.time() - t0) * 1000)
    except Exception:
        return ip, False, 0


# ── Containers ────────────────────────────────────────────────────────────────
def get_containers() -> list:
    for cmd in (
        ["podman", "ps", "-a", "--format", "json"],
        ["docker", "ps", "-a", "--format", "{{json .}}"],
    ):
        out = _run(cmd, timeout=4, cache_key=" ".join(cmd), cache_ttl=10)
        if not out:
            continue
        try:
            items = (
                json.loads(out)
                if out.lstrip().startswith("[")
                else [json.loads(l) for l in out.splitlines() if l.strip()]
            )
            res = []
            for c in items[:16]:
                name = c.get("Names", c.get("Name", "?"))
                if isinstance(name, list):
                    name = name[0] if name else "?"
                cid = (c.get("Id", c.get("ID", "")) or "")[:12]
                res.append({
                    "id":     cid,
                    "name":   name,
                    "image":  c.get("Image", c.get("Repository", "?")).split("/")[-1][:32],
                    "state":  (c.get("State",  c.get("Status",  "?")) or "?").lower().split()[0],
                    "status": (c.get("Status", c.get("State",   "?")) or "?").lower().split()[0],
                })
            return res
        except Exception:
            continue
    return []


def bust_container_cache() -> None:
    _cache.bust("ps")


# ── SMART ─────────────────────────────────────────────────────────────────────
def collect_smart() -> list:
    cached = _cache.get("smart_data", 300)
    if cached is not None:
        return cached

    results = []
    devs = sorted({
        f"/dev/{os.path.basename(p)}"
        for p in glob.glob("/sys/block/*")
        if any(os.path.basename(p).startswith(pfx) for pfx in ("sd", "hd", "nvme", "vd"))
    })
    for dev in devs:
        try:
            raw = subprocess.check_output(
                ["smartctl", "-a", "-j", dev], timeout=10, stderr=subprocess.DEVNULL
            )
            d = json.loads(raw)
        except FileNotFoundError:
            break
        except subprocess.TimeoutExpired:
            results.append({"device": dev, "error": "timeout"})
            continue
        except Exception as e:
            results.append({"device": dev, "error": str(e)})
            continue

        model   = d.get("model_name") or d.get("model_family", "")
        serial  = d.get("serial_number", "")
        cap     = d.get("user_capacity", {}).get("bytes", 0)
        smart_ok = d.get("smart_status", {}).get("passed", True)
        temp     = d.get("temperature", {}).get("current")
        poh      = None
        attrs: dict = {}

        for attr in d.get("ata_smart_attributes", {}).get("table", []):
            aid      = attr.get("id")
            raw_val  = attr.get("raw", {}).get("value", 0)
            norm_val = attr.get("value", 0)
            if   aid == 5:   attrs["reallocated_sectors"]   = raw_val
            elif aid == 9:   poh                            = raw_val
            elif aid == 177: attrs["wear_leveling_count"]   = norm_val
            elif aid == 194:
                if temp is None: temp = raw_val
            elif aid == 197: attrs["pending_sectors"]       = raw_val
            elif aid == 198: attrs["uncorrectable_sectors"] = raw_val
            elif aid == 231: attrs["ssd_life_left_pct"]     = norm_val
            elif aid == 233: attrs["nand_writes_gb"]        = raw_val

        nvme = d.get("nvme_smart_health_information_log", {})
        if nvme:
            if temp is None: temp = nvme.get("temperature")
            attrs["available_spare_pct"] = nvme.get("available_spare")
            attrs["percentage_used"]     = nvme.get("percentage_used")
            poh = nvme.get("power_on_hours", poh)

        risk = 0
        if not smart_ok:                                        risk = 100
        if attrs.get("uncorrectable_sectors", 0) > 0:          risk = max(risk, 75)
        if attrs.get("reallocated_sectors",    0) > 0:         risk = max(risk, 60)
        if attrs.get("pending_sectors",        0) > 0:         risk = max(risk, 50)
        if attrs.get("percentage_used", 0) > 90:               risk = max(risk, 50)
        if attrs.get("available_spare_pct", 100) < 10:         risk = max(risk, 50)
        if isinstance(temp, (int, float)) and temp > 55:       risk = max(risk, 40)

        results.append({
            "device":         dev,
            "model":          model,
            "serial":         serial,
            "capacity_bytes": cap,
            "smart_ok":       smart_ok,
            "temp_c":         temp,
            "power_on_hours": poh,
            "risk_score":     risk,
            "attributes":     attrs,
        })

    _cache.set("smart_data", results)
    return results


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
