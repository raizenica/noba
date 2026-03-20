#!/usr/bin/env python3
"""NOBA Agent — Zero-dependency system telemetry collector.

Collects CPU, memory, disk, network, temperature, and top process metrics
and reports them to the NOBA Command Center via authenticated HTTP POST.

Works on any Linux system with Python 3.6+ and NO external dependencies.
Uses /proc and /sys directly. Optionally uses psutil if available for
cross-platform support (FreeBSD, macOS).

Usage:
    python3 agent.py --server http://noba:8080 --key YOUR_API_KEY
    python3 agent.py --config /etc/noba-agent.yaml
    python3 agent.py --dry-run     # Print metrics, don't send
    python3 agent.py --once        # Single report then exit
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ── Configuration ────────────────────────────────────────────────────────────
VERSION = "2.0.0"
DEFAULT_INTERVAL = 30
DEFAULT_CONFIG = "/etc/noba-agent.yaml"
# Mount types to exclude from disk reporting
_SKIP_FSTYPES = frozenset({
    "squashfs", "tmpfs", "devtmpfs", "devfs", "overlay", "aufs",
    "proc", "sysfs", "cgroup", "cgroup2", "debugfs", "tracefs",
    "securityfs", "pstore", "bpf", "fusectl", "configfs",
    "hugetlbfs", "mqueue", "efivarfs", "fuse.portal",
})
_SKIP_MOUNT_PREFIXES = ("/snap/", "/sys/", "/proc/", "/dev/", "/run/")

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


# ── Subprocess helper ─────────────────────────────────────────────────────────

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


# ── Path safety ───────────────────────────────────────────────────────────────
_PATH_DENYLIST = frozenset({"/etc/shadow", "/etc/gshadow", "/proc/kcore"})
_PATH_DENY_PATTERNS = ("/.ssh/id_",)
_BACKUP_DIR = os.path.expanduser("~/.noba-agent/backups")


def _safe_path(path):
    """Validate a path against deny lists. Returns error string or None if OK."""
    if "\0" in path:
        return "Null byte in path"
    real = os.path.realpath(path)
    for denied in _PATH_DENYLIST:
        if real == denied or real.startswith(denied + "/"):
            return f"Denied path: {real}"
    for pat in _PATH_DENY_PATTERNS:
        if pat in real:
            return f"Denied pattern: {pat}"
    return None


# ── WebSocket client (stdlib RFC 6455) ────────────────────────────────────────

class _WebSocketClient:
    """Minimal RFC 6455 WebSocket client using only Python stdlib."""

    def __init__(self, url: str, headers: dict | None = None):
        self.url = url
        self.headers = headers or {}
        self._sock: socket.socket | None = None
        self._connected = False

    def connect(self) -> None:
        """Perform HTTP Upgrade handshake."""
        import base64

        parsed = urllib.parse.urlparse(self.url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"

        raw = socket.create_connection((host, port), timeout=10)
        if parsed.scheme == "wss":
            import ssl
            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=host)

        ws_key = base64.b64encode(os.urandom(16)).decode()
        lines = [
            f"GET {path} HTTP/1.1",
            f"Host: {host}:{port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {ws_key}",
            "Sec-WebSocket-Version: 13",
        ]
        for k, v in self.headers.items():
            lines.append(f"{k}: {v}")
        lines.append("")
        lines.append("")
        raw.sendall("\r\n".join(lines).encode())

        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = raw.recv(4096)
            if not chunk:
                raise ConnectionError("Connection closed during handshake")
            resp += chunk

        status_line = resp.split(b"\r\n")[0]
        if b"101" not in status_line:
            raise ConnectionError(f"WebSocket upgrade failed: {status_line!r}")

        self._sock = raw
        self._connected = True

    def send_json(self, obj: dict) -> None:
        """Send a JSON message as a masked text frame."""
        data = json.dumps(obj).encode()
        self._send_frame(0x1, data)

    def recv_json(self, timeout: float | None = None) -> dict | None:
        """Receive a JSON message. Returns None on timeout or close."""
        if self._sock is None:
            return None
        if timeout is not None:
            self._sock.settimeout(timeout)
        try:
            data = self._recv_frame()
            if data is None:
                return None
            return json.loads(data)
        except socket.timeout:
            return None
        finally:
            if self._sock is not None and timeout is not None:
                self._sock.settimeout(None)

    def close(self) -> None:
        """Send close frame and shut down."""
        if self._connected:
            try:
                self._send_frame(0x8, b"")
            except Exception:
                pass
            self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _send_frame(self, opcode: int, data: bytes) -> None:
        """Send a masked WebSocket frame (RFC 6455 section 5.2)."""
        import struct as _struct

        if self._sock is None:
            raise ConnectionError("Not connected")

        frame = bytearray()
        frame.append(0x80 | opcode)
        length = len(data)
        mask_bit = 0x80

        if length < 126:
            frame.append(mask_bit | length)
        elif length < 65536:
            frame.append(mask_bit | 126)
            frame.extend(_struct.pack("!H", length))
        else:
            frame.append(mask_bit | 127)
            frame.extend(_struct.pack("!Q", length))

        mask = os.urandom(4)
        frame.extend(mask)
        masked = bytearray(b ^ mask[i % 4] for i, b in enumerate(data))
        frame.extend(masked)
        self._sock.sendall(frame)

    def _recv_frame(self) -> bytes | None:
        """Receive a WebSocket frame, handle control frames transparently."""
        import struct as _struct

        header = self._recv_exact(2)
        if not header:
            return None

        opcode = header[0] & 0x0F
        is_masked = bool(header[1] & 0x80)
        length = header[1] & 0x7F

        if length == 126:
            raw_len = self._recv_exact(2)
            if raw_len is None:
                return None
            length = _struct.unpack("!H", raw_len)[0]
        elif length == 127:
            raw_len = self._recv_exact(8)
            if raw_len is None:
                return None
            length = _struct.unpack("!Q", raw_len)[0]

        if is_masked:
            mask = self._recv_exact(4)
            if mask is None:
                return None
            payload = self._recv_exact(length)
            if payload is None:
                return None
            data = bytearray(b ^ mask[i % 4] for i, b in enumerate(payload))
        else:
            data = self._recv_exact(length)
            if data is None:
                return None

        if opcode == 0x8:  # Close
            self._connected = False
            return None
        if opcode == 0x9:  # Ping -> pong
            self._send_frame(0xA, bytes(data))
            return self._recv_frame()
        if opcode == 0xA:  # Pong -> ignore
            return self._recv_frame()
        return bytes(data)

    def _recv_exact(self, n: int) -> bytes | None:
        """Read exactly n bytes."""
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)


def load_config(path: str | None = None) -> dict:
    """Load config from YAML file, simple key:value file, or environment."""
    cfg = {
        "server": os.environ.get("NOBA_SERVER", ""),
        "api_key": os.environ.get("NOBA_AGENT_KEY", ""),
        "interval": int(os.environ.get("NOBA_AGENT_INTERVAL", str(DEFAULT_INTERVAL))),
        "hostname": os.environ.get("NOBA_AGENT_HOSTNAME", ""),
        "tags": os.environ.get("NOBA_AGENT_TAGS", ""),
    }
    if path and os.path.exists(path):
        try:
            import yaml
            with open(path) as f:
                file_cfg = yaml.safe_load(f) or {}
            for k, v in file_cfg.items():
                if v is not None and str(v):
                    cfg[k] = v
        except ImportError:
            # Fallback: parse simple key: value without yaml
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if ":" in line and not line.startswith("#"):
                        k, v = line.split(":", 1)
                        cfg[k.strip()] = v.strip()
    if isinstance(cfg.get("interval"), str):
        cfg["interval"] = int(cfg["interval"])
    return cfg


# ── /proc-based collectors (zero dependencies) ──────────────────────────────

def _read_proc(path: str) -> str:
    """Read a /proc or /sys file, return empty string on failure."""
    try:
        with open(path) as f:
            return f.read()
    except (OSError, PermissionError):
        return ""


def _collect_cpu_linux() -> tuple[float, int]:
    """Read CPU usage from /proc/stat (two samples, 1s apart)."""
    def parse_stat():
        line = _read_proc("/proc/stat").split("\n", 1)[0]  # "cpu  user nice system idle ..."
        parts = line.split()[1:]
        return [int(x) for x in parts]

    s1 = parse_stat()
    time.sleep(1)
    s2 = parse_stat()

    delta = [s2[i] - s1[i] for i in range(len(s1))]
    total = sum(delta) or 1
    idle = delta[3] + (delta[4] if len(delta) > 4 else 0)  # idle + iowait
    cpu_percent = round((1 - idle / total) * 100, 1)

    cpu_count = _read_proc("/proc/cpuinfo").count("processor\t")
    return cpu_percent, cpu_count or 1


def _collect_memory_linux() -> dict:
    """Read memory from /proc/meminfo."""
    info = {}
    for line in _read_proc("/proc/meminfo").split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            # Value is in kB
            num = val.strip().split()[0]
            info[key.strip()] = int(num) * 1024  # Convert to bytes

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
        # Skip noise
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
    # thermal_zone
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
    # hwmon
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
                # Extract name from between parens
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
    # Sort by RSS (memory) as a proxy since we can't easily get CPU% without two samples
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
    # Try psutil first (better data, cross-platform)
    data = _collect_psutil()
    if data is None:
        # Fall back to /proc (Linux only, zero dependencies)
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
    data["agent_version"] = VERSION
    return data


# ── Command execution ────────────────────────────────────────────────────────

# Safety: max output size, max execution time
_CMD_MAX_OUTPUT = 65536
_CMD_TIMEOUT = 30


def _cmd_exec(params: dict, ctx: dict) -> dict:
    """Execute a shell command. Streams output line-by-line if WebSocket callback present."""
    cmd = params.get("command", "")
    if not cmd:
        return {"status": "error", "error": "No command provided"}
    timeout = min(params.get("timeout", _CMD_TIMEOUT), 60)
    cmd_id = ctx.get("_current_cmd_id", "")
    ws_send = ctx.get("_ws_send")  # Optional: WebSocket send callback

    if ws_send and cmd_id:
        # Streaming mode: read output line-by-line and send via WebSocket
        try:
            proc = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            output_lines: list[str] = []
            total_size = 0
            for line in proc.stdout:
                output_lines.append(line)
                total_size += len(line)
                try:
                    ws_send({"type": "stream", "id": cmd_id, "line": line.rstrip()})
                except Exception:
                    pass
                if total_size > _CMD_MAX_OUTPUT:
                    proc.kill()
                    break
            proc.wait(timeout=timeout)
            output = "".join(output_lines)[:_CMD_MAX_OUTPUT]
            return {
                "status": "ok" if proc.returncode == 0 else "error",
                "exit_code": proc.returncode,
                "stdout": output,
                "stderr": "",
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"status": "error", "error": f"Timeout after {timeout}s"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # Batch mode: run and capture
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "exit_code": result.returncode,
            "stdout": result.stdout[:_CMD_MAX_OUTPUT],
            "stderr": result.stderr[:_CMD_MAX_OUTPUT],
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_restart_service(params: dict, ctx: dict) -> dict:
    """Restart a systemd service."""
    import re
    service = params.get("service", "")
    if not service or not re.match(r'^[a-zA-Z0-9@._-]+$', service) or len(service) > 128:
        return {"status": "error", "error": "Invalid service name"}
    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", service],
            capture_output=True, text=True, timeout=30,
        )
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "exit_code": result.returncode,
            "output": (result.stdout + result.stderr)[:_CMD_MAX_OUTPUT],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_update_agent(params: dict, ctx: dict) -> dict:
    """Download updated agent.py from the server and restart."""
    server = ctx.get("server", "")
    api_key = ctx.get("api_key", "")
    if not server:
        return {"status": "error", "error": "No server configured"}
    url = f"{server.rstrip('/')}/api/agent/update"
    req = urllib.request.Request(url, headers={"X-Agent-Key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                return {"status": "error", "error": f"HTTP {resp.status}"}
            new_code = resp.read()
        # Validate it's Python
        if not new_code.startswith(b"#!/") and b"def main" not in new_code:
            return {"status": "error", "error": "Invalid agent code"}
        # Write to a temp file, then replace
        agent_path = os.path.abspath(__file__)
        tmp_path = agent_path + ".new"
        with open(tmp_path, "wb") as f:
            f.write(new_code)
        os.replace(tmp_path, agent_path)
        # Restart via systemd if available
        import subprocess
        subprocess.Popen(
            ["sudo", "-n", "systemctl", "restart", "noba-agent"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return {"status": "ok", "message": "Agent updated, restarting..."}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_set_interval(params: dict, ctx: dict) -> dict:
    """Change the collection interval."""
    new_interval = params.get("interval", 0)
    if not isinstance(new_interval, int) or new_interval < 5 or new_interval > 3600:
        return {"status": "error", "error": "Interval must be 5-3600 seconds"}
    ctx["interval"] = new_interval
    return {"status": "ok", "interval": new_interval}


def _cmd_ping(_params: dict, _ctx: dict) -> dict:
    """Simple connectivity check."""
    return {"status": "ok", "pong": int(time.time()), "version": VERSION}


def _cmd_get_logs(params: dict, _ctx: dict) -> dict:
    """Fetch recent journalctl logs for a service or system-wide."""
    unit = params.get("unit", "")
    lines = min(params.get("lines", 50), 200)
    priority = params.get("priority", "")  # e.g., "err" for errors only
    cmd = ["journalctl", "--no-pager", "-n", str(lines)]
    if unit:
        import re
        if not re.match(r'^[a-zA-Z0-9@._-]+$', unit):
            return {"status": "error", "error": "Invalid unit name"}
        cmd.extend(["-u", unit])
    if priority:
        cmd.extend(["-p", priority])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return {"status": "ok", "stdout": result.stdout[:_CMD_MAX_OUTPUT]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_check_service(params: dict, _ctx: dict) -> dict:
    """Get detailed systemd service status."""
    import re
    service = params.get("service", "")
    if not service or not re.match(r'^[a-zA-Z0-9@._-]+$', service):
        return {"status": "error", "error": "Invalid service name"}
    try:
        result = subprocess.run(
            ["systemctl", "status", service, "--no-pager"],
            capture_output=True, text=True, timeout=10,
        )
        return {"status": "ok", "stdout": result.stdout[:_CMD_MAX_OUTPUT], "exit_code": result.returncode}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_network_test(params: dict, _ctx: dict) -> dict:
    """Ping or traceroute from the agent's perspective."""
    import re
    target = params.get("target", "")
    mode = params.get("mode", "ping")  # "ping" or "trace"
    if not target or not re.match(r'^[a-zA-Z0-9._:-]+$', target):
        return {"status": "error", "error": "Invalid target"}
    if mode == "trace":
        cmd = ["traceroute", "-n", "-m", "10", "-w", "2", target]
    else:
        cmd = ["ping", "-c", "4", "-W", "2", target]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return {"status": "ok", "stdout": result.stdout[:_CMD_MAX_OUTPUT]}
    except FileNotFoundError:
        return {"status": "error", "error": f"{mode} not installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_package_updates(params: dict, _ctx: dict) -> dict:
    """Check for available package updates."""
    for cmd in [
        ["apt", "list", "--upgradable"],
        ["dnf", "check-update"],
        ["pkg", "version", "-vIL="],
    ]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            lines = [ln for ln in result.stdout.strip().split("\n") if ln.strip() and "Listing" not in ln]
            return {"status": "ok", "count": len(lines), "stdout": "\n".join(lines[:50])}
        except FileNotFoundError:
            continue
    return {"status": "error", "error": "No supported package manager found"}


# ── New command handlers (v2.0) ──────────────────────────────────────────────

# -- System commands ----------------------------------------------------------

def _cmd_system_info(_params: dict, _ctx: dict) -> dict:
    """Return detailed system information."""
    try:
        ips = []
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_UNSPEC):
            addr = info[4][0]
            if addr not in ("127.0.0.1", "::1") and addr not in ips:
                ips.append(addr)
    except socket.gaierror:
        ips = []
    uptime = 0
    if _PLATFORM == "linux":
        raw = _read_proc("/proc/uptime").split()
        uptime = int(float(raw[0])) if raw else 0
    elif _PLATFORM == "darwin":
        out = _safe_run(["sysctl", "-n", "kern.boottime"], timeout=5)
        # format: { sec = 123456789, usec = 0 } ...
        if "sec" in out:
            try:
                sec = int(out.split("sec = ")[1].split(",")[0])
                uptime = int(time.time()) - sec
            except (IndexError, ValueError):
                pass
    return {
        "status": "ok",
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "arch": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "uptime_s": uptime,
        "ips": ips,
    }


def _cmd_disk_usage(params: dict, _ctx: dict) -> dict:
    """Return disk usage for a given path."""
    path = params.get("path", "/")
    if not os.path.exists(path):
        return {"status": "error", "error": f"Path not found: {path}"}
    try:
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = total - free
        percent = round(used / total * 100, 1) if total else 0
        return {
            "status": "ok",
            "path": path,
            "total": total,
            "used": used,
            "free": free,
            "percent": percent,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_reboot(params: dict, _ctx: dict) -> dict:
    """Reboot the system with optional delay."""
    delay = params.get("delay", 0)
    if _PLATFORM in ("linux", "darwin"):
        cmd = ["sudo", "-n", "shutdown", "-r", f"+{delay}"]
    elif _PLATFORM == "windows":
        cmd = ["shutdown", "/r", "/t", str(delay * 60)]
    else:
        return {"status": "error", "error": f"Unsupported platform: {_PLATFORM}"}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "output": (result.stdout + result.stderr)[:_CMD_MAX_OUTPUT],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_process_kill(params: dict, _ctx: dict) -> dict:
    """Kill a process by PID or name."""
    pid = params.get("pid")
    name = params.get("name", "")
    sig = params.get("signal", "TERM")
    sig_num = getattr(signal, f"SIG{sig.upper()}", signal.SIGTERM)
    if pid:
        try:
            os.kill(int(pid), sig_num)
            return {"status": "ok", "pid": pid, "signal": sig}
        except ProcessLookupError:
            return {"status": "error", "error": f"No such process: {pid}"}
        except PermissionError:
            return {"status": "error", "error": f"Permission denied for PID {pid}"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    elif name:
        import re
        if not re.match(r'^[a-zA-Z0-9._-]+$', name):
            return {"status": "error", "error": "Invalid process name"}
        out = _safe_run(["pkill", f"-{sig.upper()}", name], timeout=10)
        return {"status": "ok", "name": name, "signal": sig, "output": out}
    return {"status": "error", "error": "Provide 'pid' or 'name'"}


# -- Service commands ---------------------------------------------------------

def _cmd_list_services(_params: dict, _ctx: dict) -> dict:
    """List system services."""
    if _PLATFORM == "linux" and _HAS_SYSTEMD:
        out = _safe_run(
            ["systemctl", "list-units", "--type=service", "--all", "--no-pager",
             "--plain", "--no-legend"],
            timeout=15,
        )
    elif _PLATFORM == "darwin":
        out = _safe_run(["launchctl", "list"], timeout=15)
    elif _PLATFORM == "windows":
        out = _safe_run(["sc", "query", "type=", "service", "state=", "all"], timeout=15)
    elif _PLATFORM == "linux":
        out = _safe_run(["service", "--status-all"], timeout=15)
    else:
        return {"status": "error", "error": f"Unsupported platform: {_PLATFORM}"}
    return {"status": "ok", "output": out}


def _cmd_service_control(params: dict, _ctx: dict) -> dict:
    """Control a system service (start/stop/enable/disable)."""
    import re
    service = params.get("service", "")
    action = params.get("action", "")
    if not service or not re.match(r'^[a-zA-Z0-9@._-]+$', service) or len(service) > 128:
        return {"status": "error", "error": "Invalid service name"}
    if action not in ("start", "stop", "restart", "enable", "disable", "status"):
        return {"status": "error", "error": f"Invalid action: {action}"}
    if _PLATFORM == "linux" and _HAS_SYSTEMD:
        if action in ("start", "stop", "restart", "enable", "disable"):
            cmd = ["sudo", "-n", "systemctl", action, service]
        else:
            cmd = ["systemctl", action, service, "--no-pager"]
    elif _PLATFORM == "darwin":
        if action == "start":
            cmd = ["sudo", "-n", "launchctl", "load", service]
        elif action == "stop":
            cmd = ["sudo", "-n", "launchctl", "unload", service]
        else:
            cmd = ["launchctl", "list", service]
    elif _PLATFORM == "linux":
        # BSD-style init or non-systemd
        cmd = ["sudo", "-n", "service", service, action]
    else:
        return {"status": "error", "error": f"Unsupported platform: {_PLATFORM}"}
    out = _safe_run(cmd, timeout=30)
    return {"status": "ok", "service": service, "action": action, "output": out}


# -- Network commands ---------------------------------------------------------

def _cmd_network_config(_params: dict, _ctx: dict) -> dict:
    """Return network configuration."""
    parts = []
    if _PLATFORM == "linux":
        parts.append(_safe_run(["ip", "addr"], timeout=10))
        parts.append(_safe_run(["ip", "route"], timeout=10))
        resolv = ""
        try:
            with open("/etc/resolv.conf") as f:
                resolv = f.read()
        except OSError:
            pass
        parts.append(resolv)
    elif _PLATFORM == "darwin":
        parts.append(_safe_run(["ifconfig"], timeout=10))
        parts.append(_safe_run(["netstat", "-rn"], timeout=10))
    elif _PLATFORM == "windows":
        parts.append(_safe_run(["ipconfig", "/all"], timeout=10))
    else:
        parts.append(_safe_run(["ifconfig"], timeout=10))
        parts.append(_safe_run(["netstat", "-rn"], timeout=10))
    combined = "\n---\n".join(p for p in parts if p)
    return {"status": "ok", "output": combined[:_CMD_MAX_OUTPUT]}


def _cmd_dns_lookup(params: dict, _ctx: dict) -> dict:
    """DNS lookup for a hostname."""
    host = params.get("host", "")
    rtype = params.get("type", "A").upper()
    if not host:
        return {"status": "error", "error": "No host provided"}
    # Use socket for A/AAAA
    if rtype in ("A", "AAAA"):
        family = socket.AF_INET if rtype == "A" else socket.AF_INET6
        try:
            results = socket.getaddrinfo(host, None, family)
            addrs = list({r[4][0] for r in results})
            return {"status": "ok", "host": host, "type": rtype, "addresses": addrs}
        except socket.gaierror as e:
            return {"status": "error", "error": str(e)}
    # Fall back to nslookup for MX, TXT, NS, etc.
    out = _safe_run(["nslookup", f"-type={rtype}", host], timeout=10)
    return {"status": "ok", "host": host, "type": rtype, "output": out}


# -- File commands ------------------------------------------------------------

def _cmd_file_read(params: dict, _ctx: dict) -> dict:
    """Read a file with optional offset and line limit."""
    path = params.get("path", "")
    if not path:
        return {"status": "error", "error": "No path provided"}
    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    offset = params.get("offset", 0)
    max_lines = params.get("lines", 0)
    try:
        with open(path, "r", errors="replace") as f:
            if offset:
                f.seek(offset)
            if max_lines and max_lines > 0:
                content = "".join(f.readline() for _ in range(max_lines))
            else:
                content = f.read(_CMD_MAX_OUTPUT)
        return {"status": "ok", "path": path, "size": len(content), "content": content[:_CMD_MAX_OUTPUT]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_file_write(params: dict, _ctx: dict) -> dict:
    """Write content to a file (max 1MB), backing up existing files first."""
    path = params.get("path", "")
    content = params.get("content", "")
    if not path:
        return {"status": "error", "error": "No path provided"}
    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    if len(content) > 1048576:
        return {"status": "error", "error": "Content exceeds 1MB limit"}
    # Backup existing file
    if os.path.exists(path):
        try:
            os.makedirs(_BACKUP_DIR, exist_ok=True)
            bname = os.path.basename(path) + f".{int(time.time())}.bak"
            bpath = os.path.join(_BACKUP_DIR, bname)
            import shutil
            shutil.copy2(path, bpath)
        except Exception:
            pass  # Best-effort backup
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return {"status": "ok", "path": path, "bytes_written": len(content)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_file_delete(params: dict, _ctx: dict) -> dict:
    """Delete a file, backing it up first."""
    path = params.get("path", "")
    if not path:
        return {"status": "error", "error": "No path provided"}
    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    if not os.path.exists(path):
        return {"status": "error", "error": f"File not found: {path}"}
    # Backup before deletion
    try:
        os.makedirs(_BACKUP_DIR, exist_ok=True)
        bname = os.path.basename(path) + f".{int(time.time())}.deleted"
        bpath = os.path.join(_BACKUP_DIR, bname)
        import shutil
        shutil.copy2(path, bpath)
    except Exception:
        pass
    try:
        os.remove(path)
        return {"status": "ok", "path": path, "deleted": True}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_file_list(params: dict, _ctx: dict) -> dict:
    """List directory contents using glob patterns."""
    import glob as glob_mod
    path = params.get("path", ".")
    pattern = params.get("pattern", "*")
    max_entries = min(params.get("max", 500), 500)
    full_pattern = os.path.join(path, pattern)
    try:
        entries = []
        for i, match in enumerate(sorted(glob_mod.glob(full_pattern))):
            if i >= max_entries:
                break
            try:
                st = os.stat(match)
                entries.append({
                    "path": match,
                    "size": st.st_size,
                    "is_dir": os.path.isdir(match),
                    "mtime": int(st.st_mtime),
                })
            except OSError:
                entries.append({"path": match, "size": 0, "is_dir": False, "mtime": 0})
        return {"status": "ok", "path": path, "count": len(entries), "entries": entries}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_file_checksum(params: dict, _ctx: dict) -> dict:
    """Compute checksum of a file (SHA256 or MD5)."""
    path = params.get("path", "")
    algo = params.get("algorithm", "sha256").lower()
    if not path:
        return {"status": "error", "error": "No path provided"}
    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    if algo not in ("sha256", "md5"):
        return {"status": "error", "error": f"Unsupported algorithm: {algo}"}
    try:
        h = hashlib.new(algo)
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return {"status": "ok", "path": path, "algorithm": algo, "checksum": h.hexdigest()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_file_stat(params: dict, _ctx: dict) -> dict:
    """Return os.stat information for a path."""
    path = params.get("path", "")
    if not path:
        return {"status": "error", "error": "No path provided"}
    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    try:
        st = os.stat(path)
        return {
            "status": "ok",
            "path": path,
            "size": st.st_size,
            "mode": oct(st.st_mode),
            "uid": st.st_uid,
            "gid": st.st_gid,
            "mtime": int(st.st_mtime),
            "ctime": int(st.st_ctime),
            "is_dir": os.path.isdir(path),
            "is_link": os.path.islink(path),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# -- User commands ------------------------------------------------------------

def _cmd_list_users(_params: dict, _ctx: dict) -> dict:
    """List system users (UID >= 1000, excluding nologin)."""
    if _PLATFORM in ("linux", "darwin", "freebsd"):
        users = []
        try:
            with open("/etc/passwd") as f:
                for line in f:
                    parts = line.strip().split(":")
                    if len(parts) < 7:
                        continue
                    uid = int(parts[2])
                    shell = parts[6]
                    if uid >= 1000 and "nologin" not in shell and "false" not in shell:
                        users.append({
                            "username": parts[0],
                            "uid": uid,
                            "gid": int(parts[3]),
                            "home": parts[5],
                            "shell": shell,
                        })
        except Exception as e:
            return {"status": "error", "error": str(e)}
        return {"status": "ok", "users": users}
    elif _PLATFORM == "windows":
        out = _safe_run(["net", "user"], timeout=10)
        return {"status": "ok", "output": out}
    return {"status": "error", "error": f"Unsupported platform: {_PLATFORM}"}


def _cmd_user_manage(params: dict, _ctx: dict) -> dict:
    """Manage users: add, delete, or modify."""
    import re
    action = params.get("action", "")
    username = params.get("username", "")
    if not username or not re.match(r'^[a-z_][a-z0-9_-]{0,31}$', username):
        return {"status": "error", "error": "Invalid username"}
    if action not in ("add", "delete", "modify"):
        return {"status": "error", "error": f"Invalid action: {action}"}
    groups = params.get("groups", "")
    if action == "add":
        cmd = ["sudo", "-n", "useradd", "-m"]
        if groups:
            cmd.extend(["-G", groups])
        cmd.append(username)
    elif action == "delete":
        cmd = ["sudo", "-n", "userdel", "-r", username]
    elif action == "modify":
        cmd = ["sudo", "-n", "usermod"]
        if groups:
            cmd.extend(["-aG", groups])
        cmd.append(username)
    else:
        return {"status": "error", "error": f"Unknown action: {action}"}
    out = _safe_run(cmd, timeout=15)
    return {"status": "ok", "action": action, "username": username, "output": out}


# -- Container commands -------------------------------------------------------

def _cmd_container_list(params: dict, _ctx: dict) -> dict:
    """List containers using docker/podman."""
    rt = _detect_container_runtime()
    if not rt:
        return {"status": "error", "error": "No container runtime found"}
    all_flag = params.get("all", False)
    cmd = [rt, "ps", "--format", "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}", "--no-trunc"]
    if all_flag:
        cmd.append("-a")
    out = _safe_run(cmd, timeout=15)
    if out.startswith("["):
        return {"status": "error", "error": out}
    containers = []
    for line in out.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 4)
        if len(parts) >= 4:
            containers.append({
                "id": parts[0][:12],
                "name": parts[1],
                "image": parts[2],
                "status": parts[3],
                "ports": parts[4] if len(parts) > 4 else "",
            })
    return {"status": "ok", "runtime": rt, "containers": containers}


def _cmd_container_control(params: dict, _ctx: dict) -> dict:
    """Control a container: start/stop/restart."""
    import re
    rt = _detect_container_runtime()
    if not rt:
        return {"status": "error", "error": "No container runtime found"}
    container = params.get("container", "")
    action = params.get("action", "")
    if not container or not re.match(r'^[a-zA-Z0-9._-]+$', container):
        return {"status": "error", "error": "Invalid container name"}
    if action not in ("start", "stop", "restart"):
        return {"status": "error", "error": f"Invalid action: {action}"}
    out = _safe_run([rt, action, container], timeout=30)
    return {"status": "ok", "runtime": rt, "container": container, "action": action, "output": out}


def _cmd_container_logs(params: dict, _ctx: dict) -> dict:
    """Get container logs."""
    import re
    rt = _detect_container_runtime()
    if not rt:
        return {"status": "error", "error": "No container runtime found"}
    container = params.get("container", "")
    tail = min(params.get("tail", 100), 1000)
    if not container or not re.match(r'^[a-zA-Z0-9._-]+$', container):
        return {"status": "error", "error": "Invalid container name"}
    out = _safe_run([rt, "logs", "--tail", str(tail), container], timeout=15)
    return {"status": "ok", "runtime": rt, "container": container, "output": out}


# -- Agent management --------------------------------------------------------

def _cmd_uninstall_agent(params: dict, _ctx: dict) -> dict:
    """Uninstall the NOBA agent: stop service, remove files."""
    if not params.get("confirm"):
        return {"status": "error", "error": "Set confirm=true to uninstall"}
    steps = []
    # Stop and disable systemd service
    if _HAS_SYSTEMD:
        _safe_run(["sudo", "-n", "systemctl", "stop", "noba-agent"], timeout=10)
        _safe_run(["sudo", "-n", "systemctl", "disable", "noba-agent"], timeout=10)
        svc_file = "/etc/systemd/system/noba-agent.service"
        if os.path.exists(svc_file):
            try:
                os.remove(svc_file)
                steps.append("Removed service file")
            except OSError:
                _safe_run(["sudo", "-n", "rm", "-f", svc_file], timeout=5)
                steps.append("Removed service file (sudo)")
        _safe_run(["sudo", "-n", "systemctl", "daemon-reload"], timeout=10)
        steps.append("Stopped and disabled service")
    # Remove agent script
    agent_path = os.path.abspath(__file__)
    try:
        os.remove(agent_path)
        steps.append(f"Removed {agent_path}")
    except OSError:
        steps.append(f"Could not remove {agent_path}")
    # Remove config
    config_path = DEFAULT_CONFIG
    if os.path.exists(config_path):
        try:
            os.remove(config_path)
            steps.append(f"Removed {config_path}")
        except OSError:
            pass
    return {"status": "ok", "steps": steps}


# -- File transfer commands (Phase 1c) ----------------------------------------

def _cmd_file_transfer(params: dict, ctx: dict) -> dict:
    """Upload a file from agent to server in chunks."""
    import secrets as _secrets

    path = params.get("path", "")
    if not path:
        return {"status": "error", "error": "No path provided"}
    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    if not os.path.isfile(path):
        return {"status": "error", "error": f"Not a file: {path}"}

    file_size = os.path.getsize(path)
    max_size = 50 * 1024 * 1024  # 50 MB
    if file_size > max_size:
        return {"status": "error", "error": f"File too large: {file_size} > {max_size}"}

    # Compute SHA256
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(65536)
            if not block:
                break
            h.update(block)
    checksum = f"sha256:{h.hexdigest()}"

    # Chunk and upload
    chunk_size = 256 * 1024
    total_chunks = (file_size + chunk_size - 1) // chunk_size or 1
    transfer_id = _secrets.token_hex(16)
    server = ctx.get("server", "")
    api_key = ctx.get("api_key", "")
    url = f"{server.rstrip('/')}/api/agent/file-upload"
    hostname = socket.gethostname()

    for i in range(total_chunks):
        with open(path, "rb") as f:
            f.seek(i * chunk_size)
            chunk = f.read(chunk_size)

        headers = {
            "Content-Type": "application/octet-stream",
            "X-Agent-Key": api_key,
            "X-Transfer-Id": transfer_id,
            "X-Chunk-Index": str(i),
            "X-Total-Chunks": str(total_chunks),
            "X-Filename": os.path.basename(path),
            "X-File-Checksum": checksum,
            "X-Agent-Hostname": hostname,
        }
        req = urllib.request.Request(url, data=chunk, headers=headers, method="POST")

        retries = 0
        last_err = ""
        while retries < 3:
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    if resp.status == 200:
                        break
                    last_err = f"Chunk {i}: HTTP {resp.status}"
            except Exception as e:
                last_err = f"Chunk {i} attempt {retries}: {e}"
            retries += 1

        if retries >= 3:
            return {"status": "error", "error": f"Failed to upload chunk {i}: {last_err}"}

    return {
        "status": "ok",
        "transfer_id": transfer_id,
        "path": path,
        "size": file_size,
        "chunks": total_chunks,
        "checksum": checksum,
    }


def _cmd_file_push(params: dict, ctx: dict) -> dict:
    """Download a file from server and write to destination path."""
    import shutil

    dest_path = params.get("path", "")
    transfer_id = params.get("transfer_id", "")
    if not dest_path:
        return {"status": "error", "error": "No destination path provided"}
    if not transfer_id:
        return {"status": "error", "error": "No transfer_id provided"}
    err = _safe_path(dest_path)
    if err:
        return {"status": "error", "error": err}

    server = ctx.get("server", "")
    api_key = ctx.get("api_key", "")
    url = f"{server.rstrip('/')}/api/agent/file-download/{transfer_id}"

    req = urllib.request.Request(
        url,
        headers={"X-Agent-Key": api_key},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                return {"status": "error", "error": f"HTTP {resp.status}"}

            expected_checksum = resp.headers.get("X-File-Checksum", "")
            data = resp.read()

            # Verify checksum
            if expected_checksum.startswith("sha256:"):
                actual = hashlib.sha256(data).hexdigest()
                expected = expected_checksum.split(":", 1)[1]
                if actual != expected:
                    return {"status": "error", "error": f"Checksum mismatch: {actual} != {expected}"}

            # Backup existing file
            if os.path.exists(dest_path):
                try:
                    os.makedirs(_BACKUP_DIR, exist_ok=True)
                    bname = os.path.basename(dest_path) + f".{int(time.time())}.bak"
                    shutil.copy2(dest_path, os.path.join(_BACKUP_DIR, bname))
                except Exception:
                    pass

            # Write file
            parent = os.path.dirname(dest_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(data)

            return {
                "status": "ok",
                "path": dest_path,
                "size": len(data),
                "checksum": expected_checksum,
            }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def execute_commands(commands: list, ctx: dict) -> list:
    """Execute a list of commands and return results."""
    results = []
    handlers = {
        # Original 9 commands
        "exec": _cmd_exec,
        "restart_service": _cmd_restart_service,
        "update_agent": _cmd_update_agent,
        "set_interval": _cmd_set_interval,
        "ping": _cmd_ping,
        "get_logs": _cmd_get_logs,
        "check_service": _cmd_check_service,
        "network_test": _cmd_network_test,
        "package_updates": _cmd_package_updates,
        # System commands
        "system_info": _cmd_system_info,
        "disk_usage": _cmd_disk_usage,
        "reboot": _cmd_reboot,
        "process_kill": _cmd_process_kill,
        # Service commands
        "list_services": _cmd_list_services,
        "service_control": _cmd_service_control,
        # Network commands
        "network_config": _cmd_network_config,
        "dns_lookup": _cmd_dns_lookup,
        # File commands
        "file_read": _cmd_file_read,
        "file_write": _cmd_file_write,
        "file_delete": _cmd_file_delete,
        "file_list": _cmd_file_list,
        "file_checksum": _cmd_file_checksum,
        "file_stat": _cmd_file_stat,
        # User commands
        "list_users": _cmd_list_users,
        "user_manage": _cmd_user_manage,
        # Container commands
        "container_list": _cmd_container_list,
        "container_control": _cmd_container_control,
        "container_logs": _cmd_container_logs,
        # File transfer commands (Phase 1c)
        "file_transfer": _cmd_file_transfer,
        "file_push": _cmd_file_push,
        # Agent management
        "uninstall_agent": _cmd_uninstall_agent,
    }
    for cmd in commands[:20]:  # Max 20 commands per cycle
        cmd_type = cmd.get("type", "")
        cmd_id = cmd.get("id", "")
        params = cmd.get("params", {})
        handler = handlers.get(cmd_type)
        if handler:
            try:
                result = handler(params, ctx)
            except Exception as e:
                result = {"status": "error", "error": str(e)}
        else:
            result = {"status": "error", "error": f"Unknown command: {cmd_type}"}
        results.append({"id": cmd_id, "type": cmd_type, **result})
    return results


# ── Reporting ────────────────────────────────────────────────────────────────

def report(server: str, api_key: str, metrics: dict) -> tuple[bool, list]:
    """Send metrics to NOBA server. Returns (success, pending_commands)."""
    url = f"{server.rstrip('/')}/api/agent/report"
    data = json.dumps(metrics).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Agent-Key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                body = json.loads(resp.read())
                return True, body.get("commands", [])
            return False, []
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return False, []


# ── WebSocket background thread ──────────────────────────────────────────────

def _ws_thread(server: str, api_key: str, hostname: str, ctx: dict) -> None:
    """Background thread: maintain WebSocket connection for instant commands."""
    ws_url = server.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url.rstrip('/')}/api/agent/ws?key={urllib.parse.quote(api_key)}"

    backoff = 5
    max_backoff = 60

    while not ctx.get("_stop"):
        ws = None
        try:
            ws = _WebSocketClient(ws_url)
            ws.connect()
            print(f"[agent] WebSocket connected to {server}")
            backoff = 5

            ws.send_json({
                "type": "identify",
                "hostname": hostname,
                "agent_version": VERSION,
            })

            while not ctx.get("_stop"):
                msg = ws.recv_json(timeout=30)
                if msg is None:
                    ws.send_json({"type": "ping"})
                    continue

                if msg.get("type") == "command":
                    cmd_obj = {
                        "type": msg.get("cmd", ""),
                        "id": msg.get("id", ""),
                        "params": msg.get("params", {}),
                    }
                    cmd_ctx = {
                        **ctx,
                        "_current_cmd_id": msg.get("id", ""),
                        "_ws_send": lambda m: ws.send_json(m),
                    }
                    results = execute_commands([cmd_obj], cmd_ctx)
                    for r in results:
                        ws.send_json({"type": "result", **r})

                elif msg.get("type") == "pong":
                    pass

        except Exception as exc:
            if not ctx.get("_stop"):
                print(f"[agent] WebSocket error: {exc}", file=sys.stderr)
        finally:
            if ws:
                ws.close()

        if ctx.get("_stop"):
            break

        time.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)


# ── Main Loop ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NOBA Agent — System Telemetry Collector")
    parser.add_argument("--server", help="NOBA server URL (e.g., http://noba:8080)")
    parser.add_argument("--key", help="Agent API key")
    parser.add_argument("--interval", type=int, help=f"Collection interval in seconds (default: {DEFAULT_INTERVAL})")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Config file path")
    parser.add_argument("--hostname", help="Override hostname")
    parser.add_argument("--once", action="store_true", help="Collect and report once, then exit")
    parser.add_argument("--dry-run", action="store_true", help="Collect and print, don't send")
    parser.add_argument("--version", action="version", version=f"NOBA Agent {VERSION}")
    args = parser.parse_args()

    cfg = load_config(args.config if os.path.exists(args.config or "") else None)
    server = args.server or cfg.get("server", "")
    api_key = args.key or cfg.get("api_key", "")
    interval = args.interval or cfg.get("interval", DEFAULT_INTERVAL)
    hostname_override = args.hostname or cfg.get("hostname", "")

    if not server and not args.dry_run:
        print("Error: --server or NOBA_SERVER required", file=sys.stderr)
        sys.exit(1)

    try:
        import psutil
        backend = f"psutil {psutil.__version__}"
    except ImportError:
        backend = "/proc (zero-dep)"

    print(f"[agent] NOBA Agent v{VERSION} on {hostname_override or socket.gethostname()}")
    print(f"[agent] Backend: {backend}")
    print(f"[agent] Server: {server or '(dry-run)'}")
    print(f"[agent] Interval: {interval}s")

    consecutive_failures = 0
    max_backoff = 300  # 5 minutes max between retries
    cmd_results = []  # Results from previous cycle's commands
    ctx = {"server": server, "api_key": api_key, "interval": interval}

    # Start WebSocket thread for real-time commands
    ws_ctx = {**ctx, "_stop": False}
    if server and not args.dry_run and not args.once:
        import threading
        agent_hostname = hostname_override or socket.gethostname()
        ws_t = threading.Thread(
            target=_ws_thread,
            args=(server, api_key, agent_hostname, ws_ctx),
            daemon=True,
        )
        ws_t.start()
        print("[agent] WebSocket thread started")

    while True:
        try:
            metrics = collect_metrics()
            if hostname_override:
                metrics["hostname"] = hostname_override
            if cfg.get("tags"):
                metrics["tags"] = cfg["tags"]
            # Attach command results from previous cycle
            if cmd_results:
                metrics["_cmd_results"] = cmd_results
                cmd_results = []

            if args.dry_run:
                print(json.dumps(metrics, indent=2))
                break

            ok, commands = report(server, api_key, metrics)
            if ok:
                if consecutive_failures > 0:
                    print(f"[agent] Connection restored after {consecutive_failures} failures")
                consecutive_failures = 0
                # Execute any pending commands from server
                if commands:
                    print(f"[agent] Received {len(commands)} command(s)")
                    cmd_results = execute_commands(commands, ctx)
                    # Check if interval was changed
                    if ctx.get("interval") != interval:
                        interval = ctx["interval"]
                        print(f"[agent] Interval changed to {interval}s")
            else:
                consecutive_failures += 1
                if consecutive_failures <= 3 or consecutive_failures % 10 == 0:
                    print(f"[agent] Report failed (attempt {consecutive_failures})", file=sys.stderr)

            if args.once:
                sys.exit(0 if ok else 1)

            # Backoff on repeated failures
            if consecutive_failures > 3:
                backoff = min(interval * (2 ** min(consecutive_failures - 3, 5)), max_backoff)
                time.sleep(backoff)
            else:
                time.sleep(interval)

        except KeyboardInterrupt:
            ws_ctx["_stop"] = True
            print("\n[agent] Stopped")
            break
        except Exception as e:
            consecutive_failures += 1
            if consecutive_failures <= 3:
                print(f"[agent] Error: {e}", file=sys.stderr)
            if args.once:
                sys.exit(1)
            time.sleep(min(interval * 2, max_backoff))


if __name__ == "__main__":
    main()
