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
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# ── Configuration ────────────────────────────────────────────────────────────
VERSION = "2.1.0"
DEFAULT_INTERVAL = 30
DEFAULT_CONFIG = (
    os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"), "noba-agent", "agent.yaml")
    if platform.system().lower() == "windows"
    else "/etc/noba-agent.yaml"
)
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

    # On Windows, wrap in powershell for richer output
    if _PLATFORM == "windows":
        shell_cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
    else:
        shell_cmd = cmd  # shell=True on Linux/macOS

    if ws_send and cmd_id:
        # Streaming mode: read output line-by-line and send via WebSocket
        try:
            proc = subprocess.Popen(
                shell_cmd, shell=(_PLATFORM != "windows"),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
            shell_cmd, shell=(_PLATFORM != "windows"),
            capture_output=True, text=True, timeout=timeout,
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
    """Restart a service (systemd on Linux, sc on Windows)."""
    import re
    service = params.get("service", "")
    if not service or not re.match(r'^[a-zA-Z0-9@._\- ]+$', service) or len(service) > 128:
        return {"status": "error", "error": "Invalid service name"}
    try:
        if _PLATFORM == "windows":
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"Restart-Service '{service}' -Force"],
                capture_output=True, text=True, timeout=30,
            )
        else:
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
    """Fetch recent logs (journalctl on Linux, wevtutil on Windows)."""
    unit = params.get("unit", "")
    lines = min(params.get("lines", 50), 200)
    priority = params.get("priority", "")  # e.g., "err" for errors only

    if _PLATFORM == "windows":
        log_name = unit or "System"
        import re
        if not re.match(r'^[a-zA-Z0-9@._\- ]+$', log_name):
            return {"status": "error", "error": "Invalid log name"}
        cmd = ["powershell", "-NoProfile", "-Command",
               f"Get-EventLog -LogName '{log_name}' -Newest {lines} | Format-Table -AutoSize | Out-String -Width 300"]
        if priority:
            level_map = {"emerg": "1", "alert": "1", "crit": "1", "err": "Error",
                         "warning": "Warning", "notice": "Information", "info": "Information"}
            entry_type = level_map.get(priority, priority)
            cmd = ["powershell", "-NoProfile", "-Command",
                   f"Get-EventLog -LogName '{log_name}' -Newest {lines} -EntryType {entry_type} | Format-Table -AutoSize | Out-String -Width 300"]
    else:
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
    """Get service status (systemd on Linux, sc on Windows)."""
    import re
    service = params.get("service", "")
    if not service or not re.match(r'^[a-zA-Z0-9@._\- ]+$', service):
        return {"status": "error", "error": "Invalid service name"}
    try:
        if _PLATFORM == "windows":
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"Get-Service '{service}' | Format-List *"],
                capture_output=True, text=True, timeout=10,
            )
        else:
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
    if _PLATFORM == "windows":
        if mode == "trace":
            cmd = ["tracert", "-d", "-h", "10", "-w", "2000", target]
        else:
            cmd = ["ping", "-n", "4", "-w", "2000", target]
    else:
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


# ── Live log streaming ───────────────────────────────────────────────────────

# Active stream processes keyed by cmd_id
_active_streams: dict[str, subprocess.Popen] = {}
_active_streams_lock = threading.Lock()
# Buffered output lines keyed by cmd_id (list of strings)
_stream_buffers: dict[str, list[str]] = {}
_stream_buffers_lock = threading.Lock()
# Max lines kept in buffer per stream (older lines are dropped)
_STREAM_BUFFER_MAX = 500


def _stream_reader(cmd_id: str, proc: subprocess.Popen) -> None:
    """Background thread: reads lines from a Popen stdout and buffers them."""
    try:
        for raw_line in iter(proc.stdout.readline, ""):
            if not raw_line:
                break
            line = raw_line.rstrip("\n")
            with _stream_buffers_lock:
                buf = _stream_buffers.setdefault(cmd_id, [])
                buf.append(line)
                # Trim buffer to keep memory bounded
                if len(buf) > _STREAM_BUFFER_MAX:
                    _stream_buffers[cmd_id] = buf[-_STREAM_BUFFER_MAX:]
    except (OSError, ValueError):
        pass
    finally:
        # Clean up when process ends
        with _active_streams_lock:
            _active_streams.pop(cmd_id, None)


def _cmd_follow_logs(params: dict, ctx: dict) -> dict:
    """Start streaming journalctl -f output. Returns immediately; lines buffer in background."""
    import re
    unit = params.get("unit", "")
    priority = params.get("priority", "")
    lines = min(int(params.get("lines", 50)), 500)
    cmd_id = ctx.get("_cmd_id", ctx.get("_current_cmd_id", ""))
    if not cmd_id:
        return {"status": "error", "error": "No command ID provided"}

    cmd = ["journalctl", "-f", "--no-pager", "-n", str(lines)]
    if unit:
        if not re.match(r'^[a-zA-Z0-9@._-]+$', unit):
            return {"status": "error", "error": "Invalid unit name"}
        cmd.extend(["-u", unit])
    if priority:
        if not re.match(r'^[a-zA-Z0-9]+$', priority):
            return {"status": "error", "error": "Invalid priority"}
        cmd.extend(["-p", priority])

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
    except FileNotFoundError:
        return {"status": "error", "error": "journalctl not found"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

    with _active_streams_lock:
        _active_streams[cmd_id] = proc
    with _stream_buffers_lock:
        _stream_buffers[cmd_id] = []

    t = threading.Thread(target=_stream_reader, args=(cmd_id, proc), daemon=True)
    t.start()

    return {"status": "ok", "stream_id": cmd_id, "message": "Log stream started"}


def _cmd_stop_stream(params: dict, _ctx: dict) -> dict:
    """Stop a running log stream by its stream_id (the cmd_id of the follow_logs command)."""
    stream_id = params.get("stream_id", "")
    if not stream_id:
        return {"status": "error", "error": "No stream_id provided"}

    with _active_streams_lock:
        proc = _active_streams.pop(stream_id, None)
    if proc is None:
        return {"status": "error", "error": "Stream not found or already stopped"}

    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    # Clean up buffer
    with _stream_buffers_lock:
        _stream_buffers.pop(stream_id, None)

    return {"status": "ok", "message": f"Stream {stream_id} stopped"}


def _cmd_get_stream(params: dict, _ctx: dict) -> dict:
    """Retrieve buffered stream lines and flush them."""
    stream_id = params.get("stream_id", "")
    if not stream_id:
        return {"status": "error", "error": "No stream_id provided"}

    with _stream_buffers_lock:
        lines = _stream_buffers.get(stream_id, [])
        # Flush after reading
        _stream_buffers[stream_id] = []

    # Check if stream is still active
    with _active_streams_lock:
        active = stream_id in _active_streams

    return {"status": "ok", "lines": lines, "active": active}


def collect_stream_data() -> dict[str, list[str]]:
    """Collect and flush buffered lines from all active streams."""
    data = {}
    with _stream_buffers_lock:
        for stream_id in list(_stream_buffers):
            lines = _stream_buffers.get(stream_id, [])
            if lines:
                data[stream_id] = lines[:]
                _stream_buffers[stream_id] = []
    return data


def has_active_streams() -> bool:
    """Check if there are any active stream processes running."""
    with _active_streams_lock:
        return len(_active_streams) > 0


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
        out = _safe_run(["powershell", "-NoProfile", "-Command",
                         "Get-Service | Format-Table Name,Status,DisplayName -AutoSize | Out-String -Width 300"], timeout=15)
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
    if _PLATFORM == "windows":
        if action == "status":
            cmd = ["powershell", "-NoProfile", "-Command", f"Get-Service '{service}' | Format-List *"]
        elif action == "start":
            cmd = ["powershell", "-NoProfile", "-Command", f"Start-Service '{service}'"]
        elif action == "stop":
            cmd = ["powershell", "-NoProfile", "-Command", f"Stop-Service '{service}' -Force"]
        elif action == "restart":
            cmd = ["powershell", "-NoProfile", "-Command", f"Restart-Service '{service}' -Force"]
        elif action == "enable":
            cmd = ["powershell", "-NoProfile", "-Command", f"Set-Service '{service}' -StartupType Automatic"]
        elif action == "disable":
            cmd = ["powershell", "-NoProfile", "-Command", f"Set-Service '{service}' -StartupType Disabled"]
        else:
            return {"status": "error", "error": f"Unsupported action on Windows: {action}"}
    elif _PLATFORM == "linux" and _HAS_SYSTEMD:
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

# Previous interface readings for rate calculation (keyed by interface name)
_prev_net_readings: dict[str, dict] = {}
_prev_net_readings_lock = threading.Lock()


def _cmd_network_stats(_params: dict, _ctx: dict) -> dict:
    """Return per-interface traffic stats and per-process TCP connections."""
    # 1. Per-interface byte counters from /proc/net/dev
    interfaces: list[dict] = []
    now = time.time()
    for line in _read_proc("/proc/net/dev").split("\n")[2:]:
        if ":" not in line:
            continue
        iface, data = line.split(":", 1)
        iface = iface.strip()
        if iface == "lo":
            continue
        parts = data.split()
        if len(parts) < 9:
            continue
        rx_bytes = int(parts[0])
        tx_bytes = int(parts[8])
        rx_rate = 0.0
        tx_rate = 0.0
        with _prev_net_readings_lock:
            prev = _prev_net_readings.get(iface)
            if prev:
                dt = now - prev["time"]
                if dt > 0:
                    rx_rate = round((rx_bytes - prev["rx"]) / dt, 1)
                    tx_rate = round((tx_bytes - prev["tx"]) / dt, 1)
                    # Clamp negative rates (counter reset)
                    if rx_rate < 0:
                        rx_rate = 0.0
                    if tx_rate < 0:
                        tx_rate = 0.0
            _prev_net_readings[iface] = {"rx": rx_bytes, "tx": tx_bytes, "time": now}
        interfaces.append({
            "name": iface,
            "rx_bytes": rx_bytes,
            "tx_bytes": tx_bytes,
            "rx_rate": rx_rate,
            "tx_rate": tx_rate,
        })

    # 2. Per-process TCP connections from ss -tnp
    connections: list[dict] = []
    top_talkers_map: dict[str, int] = {}
    try:
        result = subprocess.run(
            ["ss", "-tnp"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines()[1:]:  # skip header
            parts = line.split()
            if len(parts) < 6:
                continue
            state = parts[0]
            local = parts[3]
            remote = parts[4]
            # Parse users:(("process",pid=123,fd=4)) from last field(s)
            pid = 0
            process = ""
            rest = " ".join(parts[5:])
            if "pid=" in rest:
                try:
                    pid = int(rest.split("pid=")[1].split(",")[0].split(")")[0])
                except (IndexError, ValueError):
                    pass
            if '("' in rest:
                try:
                    process = rest.split('("')[1].split('"')[0]
                except (IndexError, ValueError):
                    pass
            connections.append({
                "pid": pid,
                "process": process,
                "local": local,
                "remote": remote,
                "state": state,
            })
            if process:
                top_talkers_map[process] = top_talkers_map.get(process, 0) + 1
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass

    # 3. Top talkers sorted by connection count
    top_talkers = sorted(
        [{"process": p, "connections": c} for p, c in top_talkers_map.items()],
        key=lambda x: x["connections"],
        reverse=True,
    )[:20]

    return {
        "status": "ok",
        "interfaces": interfaces,
        "connections": connections[:200],  # cap at 200 entries
        "top_talkers": top_talkers,
    }


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


def _cmd_endpoint_check(params: dict, _ctx: dict) -> dict:
    """HTTP health check with optional TLS certificate inspection."""
    import ssl
    import urllib.parse

    url = params.get("url", "")
    if not url:
        return {"status": "error", "error": "No URL provided"}
    method = params.get("method", "GET").upper()
    if method not in ("GET", "HEAD"):
        method = "GET"
    timeout = min(params.get("timeout", 10), 30)

    result: dict = {"status": "ok"}
    start = time.time()

    try:
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", f"NOBA-Agent/{VERSION}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.status
            elapsed_ms = int((time.time() - start) * 1000)
            result["status_code"] = status_code
            result["response_ms"] = elapsed_ms
    except urllib.error.HTTPError as e:
        elapsed_ms = int((time.time() - start) * 1000)
        result["status_code"] = e.code
        result["response_ms"] = elapsed_ms
    except urllib.error.URLError as e:
        elapsed_ms = int((time.time() - start) * 1000)
        result["status"] = "error"
        result["error"] = str(e.reason)
        result["response_ms"] = elapsed_ms
        result["status_code"] = 0
        return result
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        result["status"] = "error"
        result["error"] = str(e)
        result["response_ms"] = elapsed_ms
        result["status_code"] = 0
        return result

    # Extract TLS cert info for HTTPS URLs
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        try:
            hostname = parsed.hostname or ""
            port = parsed.port or 443
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(
                socket.socket(socket.AF_INET, socket.SOCK_STREAM),
                server_hostname=hostname,
            ) as ssock:
                ssock.settimeout(timeout)
                ssock.connect((hostname, port))
                cert = ssock.getpeercert()
            if cert:
                import datetime
                not_after = cert.get("notAfter", "")
                if not_after:
                    # Format: 'Sep  9 12:00:00 2025 GMT'
                    expiry_dt = datetime.datetime.strptime(
                        not_after, "%b %d %H:%M:%S %Y %Z"
                    )
                    days_left = (expiry_dt - datetime.datetime.utcnow()).days
                    result["cert_expiry_days"] = days_left
                issuer = dict(x[0] for x in cert.get("issuer", ()))
                result["cert_issuer"] = issuer.get("organizationName", "")
        except Exception:
            # TLS cert extraction is best-effort; don't fail the check
            pass

    return result


def _cmd_discover_services(_params: dict, _ctx: dict) -> dict:
    """Discover running services, listening ports, and established connections.

    Uses /proc/net/tcp + ss for port scanning and systemctl for unit
    dependencies.  Returns a service list with ports and connections.
    """
    services: list[dict] = []

    # 1. Listening ports via ss -tlnp
    try:
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines()[1:]:  # skip header
                parts = line.split()
                if len(parts) < 6:
                    continue
                local_addr = parts[3]
                # Extract port from addr:port or [::]:port
                if "]:" in local_addr:
                    port_str = local_addr.rsplit(":", 1)[-1]
                elif ":" in local_addr:
                    port_str = local_addr.rsplit(":", 1)[-1]
                else:
                    continue
                try:
                    port = int(port_str)
                except (ValueError, TypeError):
                    continue
                # Extract process name from users:(("name",pid=...,...))
                proc_name = ""
                for p in parts:
                    if "users:" in p:
                        # Format: users:(("sshd",pid=1234,fd=3))
                        start = p.find('(("')
                        if start >= 0:
                            end = p.find('"', start + 3)
                            if end >= 0:
                                proc_name = p[start + 3:end]
                        break
                svc_name = proc_name or f"port-{port}"
                # Avoid duplicates
                existing = next((s for s in services if s["name"] == svc_name), None)
                if existing:
                    if port not in existing.get("ports", []):
                        existing.setdefault("ports", []).append(port)
                else:
                    services.append({
                        "name": svc_name,
                        "port": port,
                        "ports": [port],
                        "connections": [],
                    })
    except Exception:
        pass  # ss not available

    # 2. Established connections via ss -tnp
    try:
        result = subprocess.run(
            ["ss", "-tnp"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) < 5:
                    continue
                state = parts[0]
                if state != "ESTAB":
                    continue
                local_addr = parts[3]
                peer_addr = parts[4]
                # Extract local port
                local_port_str = local_addr.rsplit(":", 1)[-1] if ":" in local_addr else ""
                try:
                    local_port = int(local_port_str)
                except (ValueError, TypeError):
                    continue
                # Extract remote host:port
                if "]:" in peer_addr:
                    remote_host = peer_addr[:peer_addr.rfind(":")]
                    remote_port_str = peer_addr.rsplit(":", 1)[-1]
                elif ":" in peer_addr:
                    remote_host = peer_addr.rsplit(":", 1)[0]
                    remote_port_str = peer_addr.rsplit(":", 1)[-1]
                else:
                    continue
                try:
                    remote_port = int(remote_port_str)
                except (ValueError, TypeError):
                    continue
                # Find matching service by local port
                for svc in services:
                    if local_port in svc.get("ports", [svc.get("port")]):
                        conn_entry = {
                            "remote_host": remote_host,
                            "remote_port": remote_port,
                        }
                        if conn_entry not in svc["connections"]:
                            svc["connections"].append(conn_entry)
                        break
    except Exception:
        pass

    # 3. Systemd unit dependencies (if available)
    if _HAS_SYSTEMD:
        try:
            result = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--state=running",
                 "--no-pager", "--no-legend", "--plain"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if parts:
                        unit_name = parts[0].replace(".service", "")
                        existing = next(
                            (s for s in services if s["name"] == unit_name),
                            None,
                        )
                        if not existing:
                            services.append({
                                "name": unit_name,
                                "port": 0,
                                "ports": [],
                                "connections": [],
                            })
        except Exception:
            pass

    return {"status": "ok", "services": services}


# ── Network auto-discovery ────────────────────────────────────────────────

def _cmd_network_discover(_params: dict, _ctx: dict) -> dict:
    """Discover devices on the local network via ARP + mDNS + port probing.

    - ARP scan: parses ``ip neigh`` output
    - mDNS: tries ``avahi-browse -apt --no-db-lookup -t`` (skipped if missing)
    - Port probe: connects to common ports with a 0.3 s timeout

    Returns ``{devices: [{ip, mac, hostname, open_ports}]}``.
    """
    devices: dict[str, dict] = {}  # keyed by IP

    # ── 1. ARP neighbours via ``ip neigh`` ───────────────────────────────────
    try:
        result = subprocess.run(
            ["ip", "neigh"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) < 4:
                    continue
                ip_addr = parts[0]
                mac_addr = ""
                # typical: 192.168.1.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE
                if "lladdr" in parts:
                    idx = parts.index("lladdr")
                    if idx + 1 < len(parts):
                        mac_addr = parts[idx + 1].lower()
                state = parts[-1].upper()
                if state in ("FAILED", "INCOMPLETE"):
                    continue
                devices[ip_addr] = {
                    "ip": ip_addr,
                    "mac": mac_addr,
                    "hostname": "",
                    "open_ports": [],
                }
    except Exception:
        pass

    # ── 2. mDNS discovery via avahi-browse ───────────────────────────────────
    try:
        result = subprocess.run(
            ["avahi-browse", "-apt", "--no-db-lookup", "-t"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                # Format: +;eth0;IPv4;hostname;_http._tcp;local;host.local;192.168.1.x;80;...
                fields = line.split(";")
                if len(fields) < 8:
                    continue
                if fields[0] not in ("+", "="):
                    continue
                ip_addr = fields[7] if len(fields) > 7 else ""
                mdns_host = fields[3] if len(fields) > 3 else ""
                if not ip_addr:
                    continue
                if ip_addr in devices:
                    if mdns_host and not devices[ip_addr]["hostname"]:
                        devices[ip_addr]["hostname"] = mdns_host
                else:
                    devices[ip_addr] = {
                        "ip": ip_addr,
                        "mac": "",
                        "hostname": mdns_host,
                        "open_ports": [],
                    }
    except FileNotFoundError:
        pass  # avahi-browse not installed
    except Exception:
        pass

    # ── 3. Reverse DNS for devices without a hostname ────────────────────────
    for dev in devices.values():
        if not dev["hostname"]:
            try:
                host, _, _ = socket.gethostbyaddr(dev["ip"])
                dev["hostname"] = host
            except (socket.herror, socket.gaierror, OSError):
                pass

    # ── 4. Port probing ──────────────────────────────────────────────────────
    probe_ports = [
        22, 80, 443, 8080, 8443, 3000, 5000, 8000, 8888, 9090,
        3306, 5432, 6379, 1883, 8883, 53, 67, 68, 161,
        445, 139, 548, 631, 5353, 9100,
    ]
    for dev in devices.values():
        open_ports: list[int] = []
        for port in probe_ports:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.3)
                err = s.connect_ex((dev["ip"], port))
                s.close()
                if err == 0:
                    open_ports.append(port)
            except Exception:
                pass
        dev["open_ports"] = sorted(open_ports)

    return {"status": "ok", "devices": list(devices.values())}


# ── Security posture scanning ────────────────────────────────────────────────

def _cmd_security_scan(_params: dict, _ctx: dict) -> dict:
    """Scan the host for common security misconfigurations.

    Checks SSH config, firewall status, auto-updates, sensitive file
    permissions, and insecure service ports.  Returns an overall score
    (0-100) and a list of findings with severity and remediation advice.
    """
    findings: list[dict] = []

    # ── 1. SSH configuration ─────────────────────────────────────────
    _check_ssh_config(findings)

    # ── 2. Firewall status ───────────────────────────────────────────
    _check_firewall(findings)

    # ── 3. Automatic updates ─────────────────────────────────────────
    _check_auto_updates(findings)

    # ── 4. Sensitive file permissions ────────────────────────────────
    _check_sensitive_files(findings)

    # ── 5. Insecure service ports (telnet:23, ftp:21) ────────────────
    _check_insecure_ports(findings)

    # ── Score calculation ────────────────────────────────────────────
    score = _calculate_security_score(findings)

    return {"status": "ok", "score": score, "findings": findings}


def _check_ssh_config(findings: list[dict]) -> None:
    """Check /etc/ssh/sshd_config for weak settings."""
    ssh_config = "/etc/ssh/sshd_config"
    if not os.path.isfile(ssh_config):
        findings.append({
            "severity": "low",
            "category": "ssh",
            "description": "SSH server config not found — sshd may not be installed",
            "remediation": "No action needed if SSH is not required on this host.",
        })
        return

    try:
        with open(ssh_config) as f:
            content = f.read()
    except PermissionError:
        findings.append({
            "severity": "low",
            "category": "ssh",
            "description": "Cannot read /etc/ssh/sshd_config (permission denied)",
            "remediation": "Run the agent with sufficient privileges to audit SSH config.",
        })
        return

    lines = content.lower().splitlines()
    # Build a dict of active (non-commented) settings
    active: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        if len(parts) == 2:
            active[parts[0]] = parts[1]

    # PermitRootLogin
    root_login = active.get("permitrootlogin", "")
    if root_login in ("yes", ""):
        findings.append({
            "severity": "high",
            "category": "ssh",
            "description": "SSH PermitRootLogin is enabled (or defaults to yes)",
            "remediation": "Set 'PermitRootLogin no' or 'PermitRootLogin prohibit-password' in /etc/ssh/sshd_config.",
        })

    # PasswordAuthentication
    pass_auth = active.get("passwordauthentication", "")
    if pass_auth == "yes":
        findings.append({
            "severity": "medium",
            "category": "ssh",
            "description": "SSH PasswordAuthentication is enabled — prefer key-based auth",
            "remediation": "Set 'PasswordAuthentication no' in /etc/ssh/sshd_config and use SSH keys.",
        })
    elif pass_auth == "":
        # Default varies by distro — flag as informational
        findings.append({
            "severity": "low",
            "category": "ssh",
            "description": "SSH PasswordAuthentication not explicitly set — default may allow passwords",
            "remediation": "Explicitly set 'PasswordAuthentication no' in /etc/ssh/sshd_config.",
        })


def _check_firewall(findings: list[dict]) -> None:
    """Check whether a firewall is active (iptables, nftables, or ufw)."""
    fw_active = False

    # Try ufw first
    try:
        r = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and "active" in r.stdout.lower():
            fw_active = True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try nftables
    if not fw_active:
        try:
            r = subprocess.run(["nft", "list", "tables"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                fw_active = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Try iptables
    if not fw_active:
        try:
            r = subprocess.run(["iptables", "-L", "-n"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                # Check if there are non-default rules (more than just policy lines)
                rule_lines = [
                    ln for ln in r.stdout.splitlines()
                    if ln.strip() and not ln.startswith("Chain") and not ln.startswith("target")
                ]
                if rule_lines:
                    fw_active = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    if not fw_active:
        findings.append({
            "severity": "high",
            "category": "firewall",
            "description": "No active firewall detected (checked ufw, nftables, iptables)",
            "remediation": "Enable a firewall: 'ufw enable' or configure nftables/iptables rules.",
        })


def _check_auto_updates(findings: list[dict]) -> None:
    """Check whether automatic security updates are configured."""
    auto_update = False

    # Debian/Ubuntu: unattended-upgrades
    if os.path.isfile("/etc/apt/apt.conf.d/20auto-upgrades"):
        try:
            with open("/etc/apt/apt.conf.d/20auto-upgrades") as f:
                content = f.read().lower()
            if 'unattended-upgrade "1"' in content or "unattended-upgrade \"1\"" in content:
                auto_update = True
        except (PermissionError, OSError):
            pass

    # Fedora/RHEL: dnf-automatic
    if not auto_update and os.path.isfile("/etc/dnf/automatic.conf"):
        try:
            with open("/etc/dnf/automatic.conf") as f:
                content = f.read().lower()
            if "apply_updates = yes" in content or "apply_updates=yes" in content:
                auto_update = True
        except (PermissionError, OSError):
            pass

    # RHEL/CentOS 7: yum-cron
    if not auto_update and os.path.isfile("/etc/yum/yum-cron.conf"):
        try:
            with open("/etc/yum/yum-cron.conf") as f:
                content = f.read().lower()
            if "apply_updates = yes" in content or "apply_updates=yes" in content:
                auto_update = True
        except (PermissionError, OSError):
            pass

    # Check if any auto-update service is enabled via systemd
    if not auto_update and _HAS_SYSTEMD:
        for svc in ("unattended-upgrades", "dnf-automatic-install.timer",
                     "dnf-automatic.timer", "yum-cron"):
            try:
                r = subprocess.run(
                    ["systemctl", "is-enabled", svc],
                    capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0 and "enabled" in r.stdout.lower():
                    auto_update = True
                    break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

    if not auto_update:
        findings.append({
            "severity": "medium",
            "category": "updates",
            "description": "Automatic security updates are not configured",
            "remediation": (
                "Enable unattended-upgrades (Debian/Ubuntu), dnf-automatic (Fedora/RHEL), "
                "or yum-cron (CentOS 7)."
            ),
        })


def _check_sensitive_files(findings: list[dict]) -> None:
    """Check permissions on sensitive system files."""
    checks = [
        ("/etc/shadow", 0o640, "Shadow password file"),
        ("/etc/gshadow", 0o640, "Group shadow file"),
    ]
    for path, max_perm, label in checks:
        if not os.path.exists(path):
            continue
        try:
            mode = os.stat(path).st_mode & 0o777
            if mode > max_perm:
                # Check if world-readable
                if mode & 0o004:
                    sev = "high"
                    desc = f"{label} ({path}) is world-readable (mode {oct(mode)})"
                elif mode & 0o040:
                    sev = "medium"
                    desc = f"{label} ({path}) has excessive group permissions (mode {oct(mode)})"
                else:
                    sev = "low"
                    desc = f"{label} ({path}) permissions ({oct(mode)}) exceed recommended {oct(max_perm)}"
                findings.append({
                    "severity": sev,
                    "category": "file_permissions",
                    "description": desc,
                    "remediation": f"Run: chmod {oct(max_perm)[2:]} {path}",
                })
        except PermissionError:
            pass


def _check_insecure_ports(findings: list[dict]) -> None:
    """Check for services listening on commonly insecure ports."""
    insecure_ports = {
        21: ("FTP", "high"),
        23: ("Telnet", "high"),
        69: ("TFTP", "medium"),
        161: ("SNMP", "medium"),
        445: ("SMB", "medium"),
    }
    listening: set[int] = set()

    # Parse /proc/net/tcp for listening sockets
    for proto_file in ("/proc/net/tcp", "/proc/net/tcp6"):
        if not os.path.isfile(proto_file):
            continue
        try:
            with open(proto_file) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    # State 0A = LISTEN
                    if parts[3] != "0A":
                        continue
                    # local_address is hex ip:port
                    port_hex = parts[1].split(":")[-1]
                    try:
                        port = int(port_hex, 16)
                        listening.add(port)
                    except ValueError:
                        continue
        except (PermissionError, OSError):
            pass

    for port, (service_name, severity) in insecure_ports.items():
        if port in listening:
            findings.append({
                "severity": severity,
                "category": "insecure_services",
                "description": f"{service_name} service running on port {port}",
                "remediation": f"Disable {service_name} if not needed, or restrict access with firewall rules.",
            })


def _calculate_security_score(findings: list[dict]) -> int:
    """Calculate a 0-100 security score based on findings.

    Starts at 100, deducts points per finding:
      high   -> -20 each (capped at -60)
      medium -> -10 each (capped at -30)
      low    ->  -5 each (capped at -15)
    """
    deductions = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = f.get("severity", "low")
        if sev == "high":
            deductions["high"] += 20
        elif sev == "medium":
            deductions["medium"] += 10
        else:
            deductions["low"] += 5

    # Cap deductions per severity tier
    total = min(deductions["high"], 60) + min(deductions["medium"], 30) + min(deductions["low"], 15)
    return max(0, 100 - total)


# ── Backup verification ──────────────────────────────────────────────────

def _cmd_verify_backup(params: dict, _ctx: dict) -> dict:
    """Verify a backup file's integrity.

    Verification types:
      - ``checksum``: Compute SHA-256 of the file/archive.
      - ``restore_test``: If tar/gz, list contents and verify key files exist.
      - ``db_integrity``: If ``.db`` file, run ``PRAGMA integrity_check``.
    """
    import tarfile
    import sqlite3 as _sqlite3

    path = params.get("path", "")
    if not path:
        return {"status": "error", "error": "Parameter 'path' is required"}

    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    if not os.path.exists(path):
        return {"status": "error", "error": f"Path does not exist: {path}"}

    vtype = params.get("verification_type", "checksum")
    now = int(time.time())

    if vtype == "checksum":
        try:
            sha = hashlib.sha256()
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    sha.update(chunk)
            digest = sha.hexdigest()
            size = os.path.getsize(path)
            return {
                "status": "ok",
                "verification_type": "checksum",
                "path": path,
                "details": {"sha256": digest, "size": size},
                "verified_at": now,
            }
        except Exception as e:
            return {"status": "error", "verification_type": "checksum",
                    "path": path, "error": str(e), "verified_at": now}

    elif vtype == "restore_test":
        try:
            if not tarfile.is_tarfile(path):
                return {"status": "error", "verification_type": "restore_test",
                        "path": path, "error": "Not a valid tar archive",
                        "verified_at": now}
            with tarfile.open(path, "r:*") as tf:
                members = tf.getnames()
            file_count = len(members)
            # Show first 50 entries as a sample
            sample = members[:50]
            return {
                "status": "ok",
                "verification_type": "restore_test",
                "path": path,
                "details": {
                    "file_count": file_count,
                    "sample_files": sample,
                    "readable": True,
                },
                "verified_at": now,
            }
        except Exception as e:
            return {"status": "error", "verification_type": "restore_test",
                    "path": path, "error": str(e), "verified_at": now}

    elif vtype == "db_integrity":
        try:
            conn = _sqlite3.connect(path)
            result = conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()
            ok = result and result[0] == "ok"
            return {
                "status": "ok" if ok else "error",
                "verification_type": "db_integrity",
                "path": path,
                "details": {"integrity_check": result[0] if result else "unknown"},
                "verified_at": now,
            }
        except Exception as e:
            return {"status": "error", "verification_type": "db_integrity",
                    "path": path, "error": str(e), "verified_at": now}

    else:
        return {"status": "error", "error": f"Unknown verification_type: {vtype}"}


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
        "network_stats": _cmd_network_stats,
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
        # Endpoint monitoring
        "endpoint_check": _cmd_endpoint_check,
        # Live log streaming
        "follow_logs": _cmd_follow_logs,
        "stop_stream": _cmd_stop_stream,
        "get_stream": _cmd_get_stream,
        # Service discovery
        "discover_services": _cmd_discover_services,
        # Network discovery
        "network_discover": _cmd_network_discover,
        # Security posture scanning
        "security_scan": _cmd_security_scan,
        # Backup verification
        "verify_backup": _cmd_verify_backup,
    }
    for cmd in commands[:20]:  # Max 20 commands per cycle
        cmd_type = cmd.get("type", "")
        cmd_id = cmd.get("id", "")
        params = cmd.get("params", {})
        # Pass cmd_id into context for streaming commands
        ctx["_cmd_id"] = cmd_id
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


# ── Agent Heal Runtime ────────────────────────────────────────────────────────

import operator as _op
import re as _re

_HEAL_OPS = {
    ">": _op.gt, "<": _op.lt, ">=": _op.ge, "<=": _op.le,
    "==": _op.eq, "!=": _op.ne,
}

_HEAL_COND_RE = _re.compile(
    r"^\s*([a-zA-Z0-9_\[\]\.]+)\s*(>|<|>=|<=|==|!=)\s*([0-9\.-]+)\s*$"
)


def _heal_eval_single(cond: str, flat: dict) -> bool:
    """Evaluate a single metric comparison (e.g. 'cpu_percent > 90')."""
    m = _HEAL_COND_RE.match(cond)
    if not m:
        return False
    metric, op, val = m.groups()
    if metric not in flat:
        return False
    try:
        return _HEAL_OPS[op](float(flat[metric]), float(val))
    except (ValueError, TypeError):
        return False


def _heal_eval(cond: str, flat: dict) -> bool:
    """Evaluate a condition string, supporting AND/OR."""
    if " AND " in cond:
        return all(_heal_eval_single(p.strip(), flat) for p in cond.split(" AND "))
    if " OR " in cond:
        return any(_heal_eval_single(p.strip(), flat) for p in cond.split(" OR "))
    return _heal_eval_single(cond, flat)


def _heal_flatten(metrics: dict) -> dict:
    """Flatten metrics dict for condition evaluation."""
    flat: dict = {}
    for k, v in metrics.items():
        if isinstance(v, (int, float, str)):
            flat[k] = v
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    for sk, sv in item.items():
                        if isinstance(sv, (int, float)):
                            flat[f"{k}[{i}].{sk}"] = sv
    return flat


# Map heal action types to existing agent command handlers
if _PLATFORM == "windows":
    _HEAL_ACTION_MAP = {
        "restart_container": ("container_control", lambda p: {"name": p.get("container", ""), "action": "restart"}),
        "restart_service": ("restart_service", lambda p: {"service": p.get("service", p.get("target", ""))}),
        "clear_cache": ("exec", lambda p: {"command": p.get("command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue; Write-Output 'Cache cleared'")}),
        "flush_dns": ("exec", lambda p: {"command": p.get("command", "Clear-DnsClientCache; ipconfig /flushdns")}),
    }
else:
    _HEAL_ACTION_MAP = {
        "restart_container": ("container_control", lambda p: {"name": p.get("container", ""), "action": "restart"}),
        "restart_service": ("restart_service", lambda p: {"service": p.get("service", p.get("target", ""))}),
        "clear_cache": ("exec", lambda p: {"command": p.get("command", "sync && echo 3 > /proc/sys/vm/drop_caches")}),
        "flush_dns": ("exec", lambda p: {"command": p.get("command", "systemd-resolve --flush-caches 2>/dev/null || resolvectl flush-caches 2>/dev/null || true")}),
    }


class HealRuntime:
    """Agent-side heal runtime: evaluates server-provided rules locally."""

    def __init__(self) -> None:
        self._policy: dict = {}
        self._cooldowns: dict[str, float] = {}  # rule_id -> earliest_next_run
        self._reports: list[dict] = []
        self._lock = threading.Lock()

    def update_policy(self, policy: dict) -> None:
        """Update the heal policy from server heartbeat response."""
        with self._lock:
            self._policy = policy

    def evaluate(self, metrics: dict, ctx: dict) -> None:
        """Evaluate heal rules against current metrics and execute if needed."""
        with self._lock:
            rules = self._policy.get("rules", [])
            if not rules:
                return

        flat = _heal_flatten(metrics)
        now = time.time()

        for rule in rules:
            rule_id = rule.get("rule_id", "")
            condition = rule.get("condition", "")
            action_type = rule.get("action_type", "")
            trust = rule.get("trust_level", "notify")

            if not condition or not action_type:
                continue

            # Only execute actions the agent is trusted to run
            if trust != "execute":
                continue

            # Check cooldown
            with self._lock:
                if now < self._cooldowns.get(rule_id, 0):
                    continue

            # Evaluate condition
            if not _heal_eval(condition, flat):
                continue

            # Set cooldown immediately to prevent rapid re-firing
            cooldown_s = rule.get("cooldown_s", 300)
            with self._lock:
                self._cooldowns[rule_id] = now + cooldown_s

            # Execute via existing command handlers
            mapping = _HEAL_ACTION_MAP.get(action_type)
            if not mapping:
                continue

            cmd_type, param_builder = mapping
            params = param_builder(rule.get("action_params", {}))
            metrics_before = dict(flat)
            start = time.time()

            print(f"[agent-heal] Executing {action_type} for rule {rule_id}")

            # Reuse existing command handlers
            handlers = {
                "exec": _cmd_exec,
                "restart_service": _cmd_restart_service,
                "container_control": _cmd_container_control,
            }
            handler = handlers.get(cmd_type)
            if not handler:
                continue

            try:
                result = handler(params, ctx)
            except Exception as e:
                result = {"status": "error", "error": str(e)}

            success = result.get("status") == "ok"
            duration = round(time.time() - start, 2)

            # Verify: re-check condition after settle
            time.sleep(min(rule.get("verify_delay", 5), 15))
            fresh = _heal_flatten(collect_metrics())
            verified = not _heal_eval(condition, fresh)

            status_str = "verified" if verified else ("success" if success else "failed")
            print(f"[agent-heal] {action_type} for {rule_id}: {status_str} ({duration}s)")

            report_entry = {
                "rule_id": rule_id,
                "condition": condition,
                "action_type": action_type,
                "action_params": rule.get("action_params", {}),
                "success": success,
                "verified": verified,
                "duration_s": duration,
                "metrics_before": metrics_before,
                "metrics_after": dict(fresh),
                "trust_level": trust,
            }
            with self._lock:
                self._reports.append(report_entry)

    def drain_reports(self) -> list[dict]:
        """Return and clear buffered heal reports for the next heartbeat."""
        with self._lock:
            reports = self._reports[:]
            self._reports.clear()
            return reports


# ── Reporting ────────────────────────────────────────────────────────────────

def report(server: str, api_key: str, metrics: dict) -> tuple[bool, dict]:
    """Send metrics to NOBA server. Returns (success, response_body)."""
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
                return True, body
            return False, {}
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return False, {}


# ── PTY Session Manager ──────────────────────────────────────────────────────

_pty_sessions: dict[str, dict] = {}  # session_id -> {proc, master_fd, reader_thread}
_pty_lock = threading.Lock()


def _pty_open(session_id: str, ws_send, cols: int = 80, rows: int = 24) -> dict:
    """Open a PTY shell session."""
    with _pty_lock:
        if session_id in _pty_sessions:
            return {"type": "pty_error", "session": session_id, "error": "Session already exists"}

    if _PLATFORM == "windows":
        # Windows: use subprocess with CREATE_NEW_PROCESS_GROUP
        # ConPTY is handled transparently by Python 3.12+ on Windows
        shell = os.environ.get("COMSPEC", "powershell.exe")
        try:
            proc = subprocess.Popen(
                [shell],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP") else 0,
            )
        except Exception as e:
            return {"type": "pty_error", "session": session_id, "error": str(e)}

        def reader():
            try:
                while True:
                    data = proc.stdout.read(4096)
                    if not data:
                        break
                    try:
                        ws_send({"type": "pty_output", "session": session_id, "data": data.decode("utf-8", errors="replace")})
                    except Exception:
                        break
            except Exception:
                pass
            finally:
                ws_send({"type": "pty_exit", "session": session_id, "code": proc.poll() or 0})
                with _pty_lock:
                    _pty_sessions.pop(session_id, None)

        t = threading.Thread(target=reader, daemon=True, name=f"pty-{session_id}")
        t.start()

        with _pty_lock:
            _pty_sessions[session_id] = {"proc": proc, "master_fd": None, "reader": t, "platform": "windows"}

    else:
        # Linux/macOS: use pty.openpty()
        import pty as pty_mod
        import fcntl
        import struct
        import termios

        master_fd, slave_fd = pty_mod.openpty()

        # Set terminal size
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        shell = os.environ.get("SHELL", "/bin/bash")
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLUMNS"] = str(cols)
        env["LINES"] = str(rows)

        try:
            proc = subprocess.Popen(
                [shell],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=os.setsid,
                env=env,
                close_fds=True,
            )
        except Exception as e:
            os.close(master_fd)
            os.close(slave_fd)
            return {"type": "pty_error", "session": session_id, "error": str(e)}

        os.close(slave_fd)  # Parent doesn't need slave

        # Set master_fd to non-blocking
        import select as _select_mod

        def reader():
            try:
                while True:
                    r, _, _ = _select_mod.select([master_fd], [], [], 1.0)
                    if r:
                        try:
                            data = os.read(master_fd, 4096)
                        except OSError:
                            break
                        if not data:
                            break
                        try:
                            ws_send({"type": "pty_output", "session": session_id, "data": data.decode("utf-8", errors="replace")})
                        except Exception:
                            break
                    # Check if process is still alive
                    if proc.poll() is not None:
                        # Read remaining data
                        try:
                            while True:
                                r, _, _ = _select_mod.select([master_fd], [], [], 0.1)
                                if not r:
                                    break
                                data = os.read(master_fd, 4096)
                                if not data:
                                    break
                                ws_send({"type": "pty_output", "session": session_id, "data": data.decode("utf-8", errors="replace")})
                        except (OSError, Exception):
                            pass
                        break
            except Exception:
                pass
            finally:
                try:
                    os.close(master_fd)
                except OSError:
                    pass
                code = proc.poll()
                if code is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except Exception:
                        proc.kill()
                    code = proc.returncode or 0
                try:
                    ws_send({"type": "pty_exit", "session": session_id, "code": code})
                except Exception:
                    pass
                with _pty_lock:
                    _pty_sessions.pop(session_id, None)

        t = threading.Thread(target=reader, daemon=True, name=f"pty-{session_id}")
        t.start()

        with _pty_lock:
            _pty_sessions[session_id] = {"proc": proc, "master_fd": master_fd, "reader": t, "platform": "linux"}

    print(f"[agent-pty] Session {session_id} opened")
    return {"type": "pty_opened", "session": session_id}


def _pty_input(session_id: str, data: str) -> None:
    """Send input to a PTY session."""
    with _pty_lock:
        session = _pty_sessions.get(session_id)
    if not session:
        return

    raw = data.encode("utf-8")
    if session["platform"] == "windows":
        try:
            session["proc"].stdin.write(raw)
            session["proc"].stdin.flush()
        except Exception:
            pass
    else:
        try:
            os.write(session["master_fd"], raw)
        except OSError:
            pass


def _pty_resize(session_id: str, cols: int, rows: int) -> None:
    """Resize a PTY session."""
    with _pty_lock:
        session = _pty_sessions.get(session_id)
    if not session or session["platform"] == "windows":
        return
    try:
        import fcntl
        import struct
        import termios
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(session["master_fd"], termios.TIOCSWINSZ, winsize)
        # Signal the shell about the resize
        session["proc"].send_signal(signal.SIGWINCH)
    except Exception:
        pass


def _pty_close(session_id: str) -> None:
    """Close a PTY session."""
    with _pty_lock:
        session = _pty_sessions.pop(session_id, None)
    if not session:
        return
    try:
        session["proc"].terminate()
        session["proc"].wait(timeout=3)
    except Exception:
        try:
            session["proc"].kill()
        except Exception:
            pass
    if session.get("master_fd") is not None:
        try:
            os.close(session["master_fd"])
        except OSError:
            pass
    print(f"[agent-pty] Session {session_id} closed")


def _pty_close_all() -> None:
    """Close all PTY sessions (called on shutdown)."""
    with _pty_lock:
        ids = list(_pty_sessions.keys())
    for sid in ids:
        _pty_close(sid)


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
                        # Rename r["type"] to "cmd" to avoid overwriting
                        # the message type "result" with the command type
                        payload = {"type": "result", "cmd": r.get("type", "")}
                        payload.update({k: v for k, v in r.items() if k != "type"})
                        ws.send_json(payload)

                elif msg.get("type") == "pty_open":
                    sid = msg.get("session", "")
                    cols = msg.get("cols", 80)
                    rows = msg.get("rows", 24)
                    result = _pty_open(sid, lambda m: ws.send_json(m), cols, rows)
                    ws.send_json(result)

                elif msg.get("type") == "pty_input":
                    _pty_input(msg.get("session", ""), msg.get("data", ""))

                elif msg.get("type") == "pty_resize":
                    _pty_resize(msg.get("session", ""), msg.get("cols", 80), msg.get("rows", 24))

                elif msg.get("type") == "pty_close":
                    _pty_close(msg.get("session", ""))
                    ws.send_json({"type": "pty_exit", "session": msg.get("session", ""), "code": 0})

                elif msg.get("type") == "pong":
                    pass

        except Exception as exc:
            _pty_close_all()
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
    heal_runtime = HealRuntime()
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
            # Attach any buffered stream data
            stream_data = collect_stream_data()
            if stream_data:
                metrics["_stream_data"] = stream_data
            # Attach heal reports from previous cycle
            heal_reports = heal_runtime.drain_reports()
            if heal_reports:
                metrics["_heal_reports"] = heal_reports

            if args.dry_run:
                print(json.dumps(metrics, indent=2))
                break

            ok, resp_body = report(server, api_key, metrics)
            if ok:
                if consecutive_failures > 0:
                    print(f"[agent] Connection restored after {consecutive_failures} failures")
                consecutive_failures = 0
                # Execute any pending commands from server
                commands = resp_body.get("commands", [])
                if commands:
                    print(f"[agent] Received {len(commands)} command(s)")
                    cmd_results = execute_commands(commands, ctx)
                    # Check if interval was changed
                    if ctx.get("interval") != interval:
                        interval = ctx["interval"]
                        print(f"[agent] Interval changed to {interval}s")
                # Update heal policy from server
                heal_policy = resp_body.get("heal_policy", {})
                if heal_policy:
                    heal_runtime.update_policy(heal_policy)
                # Evaluate heal rules against current metrics
                heal_runtime.evaluate(metrics, ctx)
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
            elif has_active_streams():
                # When streaming logs, report every 2 seconds for near-real-time delivery
                time.sleep(2)
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
