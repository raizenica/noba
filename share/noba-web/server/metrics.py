"""Noba – System metrics using psutil + targeted subprocess calls."""
from __future__ import annotations

import glob
import ipaddress
import json
import logging
import os
import socket
import re
import subprocess
import threading
import time
from collections import deque

import psutil


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

# ── Disk I/O / per-NIC tracking ──────────────────────────────────────────────
_disk_io_prev: dict = {}
_disk_io_ts: float = 0.0
_disk_io_lock = threading.Lock()
_pernic_prev: dict = {}
_pernic_ts: float = 0.0
_pernic_lock = threading.Lock()


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


# ── Hardware ──────────────────────────────────────────────────────────────────
def collect_hardware() -> dict:
    s: dict = {}
    cpu_model = ""
    try:
        for line in _read_file("/proc/cpuinfo").splitlines():
            if line.startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    except Exception:
        pass
    s["hwCpu"] = cpu_model or "Unknown CPU"
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


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


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

    # Top I/O processes
    top_io = []
    try:
        io_procs = []
        for p in psutil.process_iter(["name", "io_counters"]):
            try:
                io = p.info.get("io_counters")
                if io:
                    total = io.read_bytes + io.write_bytes
                    if total > 0:
                        io_procs.append({"name": p.info["name"][:20], "val": _fmt_bytes(total), "_total": total})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        top_io = [{"name": p["name"], "val": p["val"]} for p in sorted(io_procs, key=lambda x: x["_total"], reverse=True)[:5]]
    except Exception:
        pass

    return {
        "netRx":    human_bps(rx_bps),
        "netTx":    human_bps(tx_bps),
        "netRxRaw": rx_bps,
        "netTxRaw": tx_bps,
        "topCpu":   top_cpu,
        "topMem":   top_mem,
        "topIo":    top_io,
    }


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


# ── Per-interface network ────────────────────────────────────────────────────
def collect_per_interface_net() -> dict:
    global _pernic_prev, _pernic_ts
    try:
        counters = psutil.net_io_counters(pernic=True)
        now = time.time()
        result = []
        with _pernic_lock:
            if _pernic_prev and now > _pernic_ts:
                dt = now - _pernic_ts
                for nic, c in counters.items():
                    if nic == "lo" or nic.startswith(("veth", "br-", "docker", "virbr")):
                        continue
                    prev = _pernic_prev.get(nic)
                    if prev:
                        rx_bps = max(0, (c.bytes_recv - prev.bytes_recv) / dt)
                        tx_bps = max(0, (c.bytes_sent - prev.bytes_sent) / dt)
                        result.append({"name": nic, "rx_bps": round(rx_bps), "tx_bps": round(tx_bps)})
            _pernic_prev = counters
            _pernic_ts = now
        return {"netInterfaces": result}
    except Exception:
        return {"netInterfaces": []}


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
                else [json.loads(line) for line in out.splitlines() if line.strip()]
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
                    "state":  ((c.get("State",  c.get("Status",  "?")) or "?").lower().split() or ["?"])[0],
                    "status": ((c.get("Status", c.get("State",   "?")) or "?").lower().split() or ["?"])[0],
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
            if aid == 5:
                attrs["reallocated_sectors"] = raw_val
            elif aid == 9:
                poh = raw_val
            elif aid == 177:
                attrs["wear_leveling_count"] = norm_val
            elif aid == 194:
                if temp is None:
                    temp = raw_val
            elif aid == 197:
                attrs["pending_sectors"] = raw_val
            elif aid == 198:
                attrs["uncorrectable_sectors"] = raw_val
            elif aid == 231:
                attrs["ssd_life_left_pct"] = norm_val
            elif aid == 233:
                attrs["nand_writes_gb"] = raw_val

        nvme = d.get("nvme_smart_health_information_log", {})
        if nvme:
            if temp is None:
                temp = nvme.get("temperature")
            attrs["available_spare_pct"] = nvme.get("available_spare")
            attrs["percentage_used"]     = nvme.get("percentage_used")
            poh = nvme.get("power_on_hours", poh)

        risk = 0
        if not smart_ok:
            risk = 100
        if attrs.get("uncorrectable_sectors", 0) > 0:
            risk = max(risk, 75)
        if attrs.get("reallocated_sectors", 0) > 0:
            risk = max(risk, 60)
        if attrs.get("pending_sectors", 0) > 0:
            risk = max(risk, 50)
        if attrs.get("percentage_used", 0) > 90:
            risk = max(risk, 50)
        if attrs.get("available_spare_pct", 100) < 10:
            risk = max(risk, 50)
        if isinstance(temp, (int, float)) and temp > 55:
            risk = max(risk, 40)

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


# ── Certificate expiry ────────────────────────────────────────────────────────
def check_cert_expiry(hosts: list[str]) -> list[dict]:
    import ssl
    import socket as _socket
    from datetime import datetime, timezone
    results = []
    for host in hosts:
        try:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(_socket.socket(), server_hostname=host) as s:
                s.settimeout(5)
                s.connect((host, 443))
                cert = s.getpeercert()
            expires_str = cert.get("notAfter", "")
            expires = datetime.strptime(expires_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days = (expires - datetime.now(timezone.utc)).days
            issuer = dict(x[0] for x in cert.get("issuer", ())).get("organizationName", "")
            results.append({"host": host, "expires": expires.isoformat(), "days": days, "issuer": issuer})
        except Exception as e:
            results.append({"host": host, "error": str(e), "days": None})
    return results


# ── Domain expiry (WHOIS) ────────────────────────────────────────────────────
def check_domain_expiry(domains: list[str]) -> list[dict]:
    from datetime import datetime, timezone
    results = []
    for domain in domains:
        try:
            out = _run(["whois", domain], timeout=10, ignore_rc=True)
            exp_date = None
            for line in out.splitlines():
                low = line.lower()
                if "expir" in low and ":" in line:
                    val = line.split(":", 1)[1].strip()
                    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%d-%b-%Y"):
                        try:
                            exp_date = datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
                            break
                        except ValueError:
                            continue
                    if exp_date:
                        break
            if exp_date:
                days = (exp_date - datetime.now(timezone.utc)).days
                results.append({"domain": domain, "expires": exp_date.isoformat(), "days": days})
            else:
                results.append({"domain": domain, "error": "Could not parse expiry"})
        except Exception as e:
            results.append({"domain": domain, "error": str(e)})
    return results


# ── VPN / WireGuard status ───────────────────────────────────────────────────
def get_vpn_status() -> dict | None:
    raw = _run(["wg", "show", "all", "dump"], timeout=3, ignore_rc=True)
    if not raw:
        return None
    peers = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) >= 8:
            peers.append({
                "interface": parts[0],
                "endpoint": parts[3] if parts[3] != "(none)" else "",
                "last_handshake": int(parts[5]) if parts[5] != "0" else 0,
                "rx_bytes": int(parts[6]),
                "tx_bytes": int(parts[7]),
            })
    return {"peers": peers, "peer_count": len(peers)} if peers else None


# ── CPU governor ─────────────────────────────────────────────────────────────
def get_cpu_governor() -> str:
    return _read_file("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", "unknown").strip()


# ── Wake-on-LAN ─────────────────────────────────────────────────────────────
def send_wol(mac: str) -> bool:
    mac = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(mac) != 12:
        return False
    try:
        mac_bytes = bytes.fromhex(mac)
        magic = b"\xff" * 6 + mac_bytes * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(magic, ("<broadcast>", 9))
        return True
    except Exception:
        return False


# ── Game server probe ────────────────────────────────────────────────────────
def check_docker_updates() -> list[dict]:
    """Check running containers for available image updates."""
    import hashlib
    results = []
    # Get running containers with their image digests
    out = _run(["docker", "ps", "--format", "{{.Names}}|{{.Image}}"], timeout=10, ignore_rc=True)
    if not out:
        return results
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, image = line.split("|", 1)
        try:
            # Get local digest
            local = _run(["docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=5)
            # Try to get remote digest (without pulling)
            remote = _run(["docker", "manifest", "inspect", image, "--verbose"], timeout=15, ignore_rc=True)
            has_update = False
            if remote and local:
                # Simple heuristic: if manifest inspect succeeds and content differs
                remote_hash = hashlib.md5(remote.encode()).hexdigest()[:12]  # noqa: S324
                has_update = remote_hash not in local
            results.append({
                "name": name,
                "image": image,
                "has_update": has_update,
            })
        except Exception:
            results.append({"name": name, "image": image, "has_update": False})
    return results


_device_presence: dict[str, dict] = {}
_device_presence_lock = threading.Lock()


def check_device_presence(ips: list[str]) -> list[dict]:
    """Ping a list of IPs and track online/offline transitions."""
    results = []
    for ip in ips:
        parts = ip.split("|")
        addr = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else addr
        if not validate_ip(addr):
            continue
        _, up, ms = ping_host(addr)
        with _device_presence_lock:
            prev = _device_presence.get(addr, {})
            was_up = prev.get("up", None)
            changed = was_up is not None and was_up != up
            _device_presence[addr] = {"up": up, "ms": ms, "name": name, "changed": changed}
        results.append({
            "ip": addr,
            "name": name,
            "status": "online" if up else "offline",
            "ms": ms if up else 0,
            "changed": changed,
        })
    return results


def get_ipmi_sensors(host: str, user: str = "", password: str = "") -> list[dict]:
    """Query IPMI sensors from a remote BMC."""
    cmd = ["ipmitool"]
    if host:
        cmd += ["-H", host, "-I", "lanplus"]
        if user:
            cmd += ["-U", user]
        if password:
            cmd += ["-P", password]
    cmd += ["sdr", "list"]
    out = _run(cmd, timeout=10, ignore_rc=True)
    if not out:
        return []
    sensors = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3:
            name = parts[0]
            value = parts[1]
            status = parts[2]
            sensors.append({
                "name": name,
                "value": value,
                "status": status.lower(),
            })
    return sensors


def probe_game_server(host: str, port: int) -> dict:
    try:
        t0 = time.time()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect((host, port))
        ms = round((time.time() - t0) * 1000)
        return {"host": host, "port": port, "status": "online", "ms": ms}
    except Exception:
        return {"host": host, "port": port, "status": "offline", "ms": 0}
