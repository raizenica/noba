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
import queue as _queue
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
VERSION = "2.4.28"
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
    
    # Normalize and resolve the path to prevent traversal attacks
    try:
        # realpath() resolves symlinks AND normalizes (removes .., ., etc.)
        real = os.path.realpath(path)
    except (OSError, ValueError) as e:
        return f"Invalid path: {e}"
    
    # Additional check: ensure no path traversal components in original
    # This catches attempts before resolution (defense in depth)
    normalized = os.path.normpath(path)
    if normalized.startswith("..") or "/../" in path:
        return "Path traversal not allowed"
    
    if write:
        # Strict allowlist for write operations
        # Check both the resolved path and the normalized original
        allowed = False
        for safe_dir in _SAFE_WRITE_DIRS:
            safe_real = os.path.realpath(safe_dir)
            if real.startswith(safe_real) or normalized.startswith(safe_dir):
                allowed = True
                break
        if not allowed:
            return f"Write denied: path must be under {', '.join(_SAFE_WRITE_DIRS)}"
    else:
        # Denylist for read operations (less restrictive)
        for denied in _SAFE_READ_DENYLIST:
            if real == denied or real.startswith(denied + "/"):
                return f"Denied path: {real}"
        for pat in _SAFE_READ_DENY_PATTERNS:
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

    # Use list-based execution to prevent shell injection
    import shlex
    if _PLATFORM == "windows":
        shell_cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
    else:
        try:
            shell_cmd = shlex.split(cmd)
        except ValueError:
            return {"status": "error", "error": "Invalid command syntax"}

    if ws_send and cmd_id:
        # Streaming mode: read output line-by-line and send via WebSocket
        try:
            proc = subprocess.Popen(
                shell_cmd, shell=False,
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
            shell_cmd, shell=False,
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
    if not service or not re.match(r'^[a-zA-Z0-9@._\-]+$', service) or len(service) > 128:
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
    err = _safe_path(path, write=True)
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
    err = _safe_path(path, write=True)
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
    err = _safe_path(dest_path, write=True)
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


def _cmd_refresh_capabilities(_params: dict, _ctx: dict) -> dict:
    """Force a capability re-probe on the next report cycle."""
    global _last_capability_probe
    _last_capability_probe = 0
    return {"status": "ok", "message": "Capabilities will be re-probed on next report"}


# ── Remote Desktop (RDP) ──────────────────────────────────────────────────────
#
# Zero external dependencies: ctypes calls system libraries that ship with every
# supported OS.  Compression uses Python's built-in zlib.
#
# Capture chain (per platform):
#   Linux X11       → libX11 XGetImage   → BGRX pixels → RGB → PNG
#   Linux Wayland   → XWayland ($DISPLAY) → same X11 path
#   Linux headless  → DISPLAY not set    → capture returns None (view-only msg)
#   Windows         → gdi32 BitBlt       → BGR pixels  → RGB → PNG
#   macOS           → CoreGraphics       → BGRA pixels → RGB → PNG
#
# Input injection (operator/admin only):
#   Linux           → libXtst XTestFake* events
#   Windows         → user32 SendInput
#   macOS           → CGEventPost
#
# Frame transport: agent puts frames in _rdp_frame_queue (maxsize=2 → fresh-only),
# the main WS loop drains the queue with a 0.2 s recv timeout when RDP is active.


_rdp_frame_queue: _queue.Queue = _queue.Queue(maxsize=2)
_rdp_active = threading.Event()
_rdp_lock = threading.Lock()
_rdp_thread: threading.Thread | None = None
_mutter_proc: "subprocess.Popen | None" = None
_mutter_proc_lock = threading.Lock()
# Serialises all writes to the subprocess stdin (and CAPTURE read cycles).
# Without this, concurrent inject + capture writes corrupt the command stream.
_mutter_io_lock = threading.Lock()

# Cached ctypes state (loaded once per process)
_rdp_x11_lib = None
_rdp_xtst_lib = None
_rdp_x11_dpy = None  # persistent X11 Display* for input injection


def _rdp_load_x11():
    global _rdp_x11_lib
    if _rdp_x11_lib is None:
        try:
            import ctypes
            import ctypes.util
            name = ctypes.util.find_library("X11") or "libX11.so.6"
            lib = ctypes.CDLL(name)
            lib.XOpenDisplay.restype = ctypes.c_void_p
            lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            lib.XDefaultScreen.restype = ctypes.c_int
            lib.XDefaultScreen.argtypes = [ctypes.c_void_p]
            lib.XDefaultRootWindow.restype = ctypes.c_ulong
            lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            lib.XDisplayWidth.restype = ctypes.c_int
            lib.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
            lib.XDisplayHeight.restype = ctypes.c_int
            lib.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
            lib.XGetImage.restype = ctypes.c_void_p
            lib.XGetImage.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong,
                ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                ctypes.c_ulong, ctypes.c_int,
            ]
            lib.XDestroyImage.restype = ctypes.c_int
            lib.XDestroyImage.argtypes = [ctypes.c_void_p]
            lib.XCloseDisplay.restype = ctypes.c_int
            lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
            lib.XFlush.restype = ctypes.c_int
            lib.XFlush.argtypes = [ctypes.c_void_p]
            _rdp_x11_lib = lib
        except Exception:
            _rdp_x11_lib = False  # mark as unavailable
    return _rdp_x11_lib if _rdp_x11_lib else None


def _rdp_load_xtst():
    global _rdp_xtst_lib
    if _rdp_xtst_lib is None:
        try:
            import ctypes
            import ctypes.util
            name = ctypes.util.find_library("Xtst") or "libXtst.so.6"
            lib = ctypes.CDLL(name)
            lib.XTestFakeMotionEvent.argtypes = [
                ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
            lib.XTestFakeButtonEvent.argtypes = [
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
            lib.XTestFakeKeyEvent.argtypes = [
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
            _rdp_xtst_lib = lib
        except Exception:
            _rdp_xtst_lib = False
    return _rdp_xtst_lib if _rdp_xtst_lib else None


def _rdp_get_x11_display():
    """Return a persistent X11 Display* for input injection (open once, reuse)."""
    global _rdp_x11_dpy
    if _rdp_x11_dpy:
        return _rdp_x11_dpy
    _rdp_set_xauthority()
    lib = _rdp_load_x11()
    if not lib:
        return None
    try:
        display_name = _rdp_find_display()
        dpy = lib.XOpenDisplay(display_name)
        if dpy:
            _rdp_x11_dpy = dpy
        return _rdp_x11_dpy
    except Exception:
        return None


def _rdp_find_display() -> bytes:
    """Return the best X11 display string, probing sockets when $DISPLAY is absent."""
    d = os.environ.get("DISPLAY", "")
    if d:
        return d.encode()
    # Probe /tmp/.X11-unix/ for running display sockets
    try:
        for name in sorted(os.listdir("/tmp/.X11-unix/")):
            if name.startswith("X"):
                return f":{name[1:]}".encode()
    except OSError:
        pass
    return b":0"


def _rdp_set_xauthority() -> None:
    """Ensure XAUTHORITY points to the user's Xauthority cookie file.

    When the agent runs as root (uid=0) the X display belongs to the logged-in
    user. We find the socket owner via stat() and resolve their home directory.
    Falls back to common session-specific temp paths on Wayland compositors.
    """
    if os.environ.get("XAUTHORITY"):
        return
    import glob as _glob

    uid = os.getuid()
    home = os.path.expanduser("~")

    # When running as root, the X11 socket is owned by the actual desktop user.
    # Use their home directory to find the cookie file instead of /root/.
    if uid == 0:
        try:
            import pwd as _pwd
            for sock_name in ["X0", "X1", "X2"]:
                sock = f"/tmp/.X11-unix/{sock_name}"
                if os.path.exists(sock):
                    owner_uid = os.stat(sock).st_uid
                    if owner_uid != 0:
                        entry = _pwd.getpwuid(owner_uid)
                        home = entry.pw_dir
                        uid = owner_uid
                        break
        except Exception:
            pass

    patterns = [
        f"{home}/.Xauthority",
        f"/run/user/{uid}/.mutter-Xwaylandauth.*",
        f"/run/user/{uid}/Xwaylandauth.*",
        f"/run/user/{uid}/xauth*",
        f"/run/user/{uid}/.xauth*",
        f"/tmp/xauth_{uid}*",
        f"/tmp/.xauth*-{uid}",
        "/tmp/xauth_*",
        "/tmp/.xauth*",
        f"/var/run/user/{uid}/xauth*",
    ]
    for pattern in patterns:
        if "*" in pattern or "?" in pattern:
            for m in sorted(_glob.glob(pattern)):
                if os.path.isfile(m) and os.access(m, os.R_OK):
                    os.environ["XAUTHORITY"] = m
                    return
        elif os.path.isfile(pattern) and os.access(pattern, os.R_OK):
            os.environ["XAUTHORITY"] = pattern
            return


def _capture_screen_x11():
    """Capture the X11 root window, trying each available socket.
    Returns (w, h, rgb_bytes) or None. Raises RuntimeError on hard failures."""
    import ctypes
    _rdp_set_xauthority()
    lib = _rdp_load_x11()
    if not lib:
        raise RuntimeError("libX11 not found — install libX11.so.6")

    # Build list of displays to try: env var first, then all probed sockets
    candidates: list[bytes] = []
    env_d = os.environ.get("DISPLAY", "")
    if env_d:
        candidates.append(env_d.encode())
    try:
        for name in sorted(os.listdir("/tmp/.X11-unix/")):
            if name.startswith("X"):
                cand = f":{name[1:]}".encode()
                if cand not in candidates:
                    candidates.append(cand)
    except OSError:
        pass
    if not candidates:
        candidates = [b":0"]

    last_err = "no displays found"
    for display_name in candidates:
        try:
            dpy = lib.XOpenDisplay(display_name)
            if not dpy:
                last_err = f"XOpenDisplay({display_name.decode()!r}) failed"
                continue
            screen = lib.XDefaultScreen(dpy)
            root = lib.XDefaultRootWindow(dpy)
            # Use XGetWindowAttributes for real dimensions — XDisplayWidth/Height
            # returns stale/zero values on XWayland when accessed cross-user.
            class _XWindowAttr(ctypes.Structure):
                _fields_ = [
                    ("_pad", ctypes.c_int * 5),   # skip: visual, root, x, y, border_width? no...
                ]
            # XWindowAttributes struct layout: x(4), y(4), width(4), height(4), ...
            # Simplest: allocate a large buffer and read w/h at offsets 8,12
            attr_buf = (ctypes.c_int * 32)()
            lib.XGetWindowAttributes.restype = ctypes.c_int
            lib.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
            lib.XGetWindowAttributes(dpy, root, attr_buf)
            # XWindowAttributes: x@0, y@4, width@8, height@12 (all c_int)
            w = attr_buf[2]  # width
            h = attr_buf[3]  # height
            if w <= 0 or h <= 0:
                # Fallback to cached values
                w = lib.XDisplayWidth(dpy, screen)
                h = lib.XDisplayHeight(dpy, screen)
            if w <= 0 or h <= 0:
                lib.XCloseDisplay(dpy)
                last_err = f"{display_name.decode()!r} has {w}x{h} dimensions (virtual/headless)"
                continue
            # XGetImage can hang on Wayland compositors that block X11 capture.
            # Run it in a thread with a 4s timeout to detect hangs.
            import threading as _threading
            _img_result: list = [None]
            def _do_xgetimage() -> None:
                ptr = lib.XGetImage(dpy, root, 0, 0, w, h, 0xFFFFFFFF, 2)
                if not ptr:
                    ptr = lib.XGetImage(dpy, root, 0, 0, w, h, 1, 2)
                _img_result[0] = ptr
            _t = _threading.Thread(target=_do_xgetimage, daemon=True)
            _t.start()
            _t.join(timeout=4.0)
            if _t.is_alive():
                lib.XCloseDisplay(dpy)
                last_err = f"XGetImage timed out on {display_name.decode()!r} — compositor blocking X11 capture"
                continue
            img_ptr = _img_result[0]
            if not img_ptr:
                lib.XCloseDisplay(dpy)
                last_err = f"XGetImage returned NULL on {display_name.decode()!r} ({w}x{h})"
                continue

            # Parse XImage header
            class _XImageHead(ctypes.Structure):
                _fields_ = [
                    ("width", ctypes.c_int),
                    ("height", ctypes.c_int),
                    ("xoffset", ctypes.c_int),
                    ("format", ctypes.c_int),
                    ("data", ctypes.POINTER(ctypes.c_ubyte)),
                    ("byte_order", ctypes.c_int),
                    ("bitmap_unit", ctypes.c_int),
                    ("bitmap_bit_order", ctypes.c_int),
                    ("bitmap_pad", ctypes.c_int),
                    ("depth", ctypes.c_int),
                    ("bytes_per_line", ctypes.c_int),
                    ("bits_per_pixel", ctypes.c_int),
                ]

            img = ctypes.cast(img_ptr, ctypes.POINTER(_XImageHead)).contents
            bpl = img.bytes_per_line
            bpp = img.bits_per_pixel // 8
            raw = bytes(img.data[:bpl * h])
            lib.XDestroyImage(img_ptr)
            lib.XCloseDisplay(dpy)

            if bpl != w * bpp:
                stripped = bytearray(w * bpp * h)
                for y in range(h):
                    stripped[y * w * bpp:(y + 1) * w * bpp] = raw[y * bpl:y * bpl + w * bpp]
                raw = bytes(stripped)

            # Convert BGRX → RGB
            rgb = bytearray(w * h * 3)
            rgb[0::3] = raw[2::bpp]  # R
            rgb[1::3] = raw[1::bpp]  # G
            rgb[2::3] = raw[0::bpp]  # B
            return w, h, bytes(rgb)

        except Exception as e:
            last_err = f"{display_name.decode()!r}: {e}"
            print(f"[agent-rdp] X11 capture error on {display_name.decode()!r}: {e}", file=sys.stderr)

    raise RuntimeError(f"X11 capture failed on all displays — {last_err}")


def _capture_screen_windows():
    """Capture the primary monitor using Windows GDI BitBlt. Returns (w, h, rgb_bytes) or None."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32")
        gdi32 = ctypes.WinDLL("gdi32")

        w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
        h = user32.GetSystemMetrics(1)  # SM_CYSCREEN

        hwnd = user32.GetDesktopWindow()
        hdc = user32.GetDC(hwnd)
        memdc = gdi32.CreateCompatibleDC(hdc)
        hbmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
        gdi32.SelectObject(memdc, hbmp)
        gdi32.BitBlt(memdc, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)  # SRCCOPY

        class _BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # negative = top-down scan order
        bmi.biPlanes = 1
        bmi.biBitCount = 24   # 24-bit BGR, no alpha
        bmi.biCompression = 0  # BI_RGB

        buf = (ctypes.c_byte * (w * h * 3))()
        gdi32.GetDIBits(memdc, hbmp, 0, h, buf, ctypes.byref(bmi), 0)

        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(hwnd, hdc)

        raw = bytes(buf)
        # GetDIBits 24-bit BI_RGB returns BGR; swap to RGB
        rgb = bytearray(w * h * 3)
        rgb[0::3] = raw[2::3]  # R
        rgb[1::3] = raw[1::3]  # G
        rgb[2::3] = raw[0::3]  # B
        return w, h, bytes(rgb)
    except Exception as e:
        print(f"[agent-rdp] Windows GDI capture error: {e}", file=sys.stderr)
        return None


def _capture_screen_macos():
    """Capture the main display using CoreGraphics. Returns (w, h, rgb_bytes) or None."""
    try:
        import ctypes
        cg = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        cg.CGDisplayCreateImage.restype = ctypes.c_void_p
        cg.CGDisplayCreateImage.argtypes = [ctypes.c_uint32]
        cg.CGImageGetWidth.restype = ctypes.c_size_t
        cg.CGImageGetWidth.argtypes = [ctypes.c_void_p]
        cg.CGImageGetHeight.restype = ctypes.c_size_t
        cg.CGImageGetHeight.argtypes = [ctypes.c_void_p]
        cg.CGImageGetDataProvider.restype = ctypes.c_void_p
        cg.CGImageGetDataProvider.argtypes = [ctypes.c_void_p]
        cg.CGDataProviderCopyData.restype = ctypes.c_void_p
        cg.CGDataProviderCopyData.argtypes = [ctypes.c_void_p]
        cg.CFDataGetLength.restype = ctypes.c_long
        cg.CFDataGetLength.argtypes = [ctypes.c_void_p]
        cg.CFDataGetBytePtr.restype = ctypes.POINTER(ctypes.c_uint8)
        cg.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        cg.CFRelease.restype = None
        cg.CFRelease.argtypes = [ctypes.c_void_p]
        cg.CGImageRelease.restype = None
        cg.CGImageRelease.argtypes = [ctypes.c_void_p]

        display_id = cg.CGMainDisplayID()
        img = cg.CGDisplayCreateImage(display_id)
        if not img:
            return None

        w = cg.CGImageGetWidth(img)
        h = cg.CGImageGetHeight(img)
        provider = cg.CGImageGetDataProvider(img)
        data = cg.CGDataProviderCopyData(provider)
        length = cg.CFDataGetLength(data)
        ptr = cg.CFDataGetBytePtr(data)
        raw = bytes(ptr[:length])
        cg.CFRelease(data)
        cg.CGImageRelease(img)

        # CoreGraphics returns BGRA; convert to RGB
        rgb = bytearray(w * h * 3)
        rgb[0::3] = raw[2::4]  # R
        rgb[1::3] = raw[1::4]  # G
        rgb[2::3] = raw[0::4]  # B
        return w, h, bytes(rgb)
    except Exception as e:
        print(f"[agent-rdp] macOS CoreGraphics capture error: {e}", file=sys.stderr)
        return None


def _capture_screen_grim() -> tuple | None:
    """Capture via grim (Wayland wlr-screencopy). Returns (w, h, rgb) or None."""
    import subprocess
    import tempfile

    # Locate grim; also need WAYLAND_DISPLAY for the compositor socket
    grim = _which("grim")
    if not grim:
        print("[agent-rdp] grim not found — install grim for Wayland capture", file=sys.stderr)
        return None
    # Set WAYLAND_DISPLAY if absent — try common socket names
    env = os.environ.copy()
    if not env.get("WAYLAND_DISPLAY"):
        for wl in ("wayland-0", "wayland-1"):
            sock = f"/run/user/{os.getuid()}/wayland-0"
            try:
                # Find actual socket owner if running as root
                for sock_name in ["X0", "X1"]:
                    sp = f"/tmp/.X11-unix/{sock_name}"
                    if os.path.exists(sp):
                        owner_uid = os.stat(sp).st_uid
                        if owner_uid != 0:
                            sock = f"/run/user/{owner_uid}/{wl}"
                            break
            except Exception:
                pass
            if os.path.exists(sock):
                env["WAYLAND_DISPLAY"] = wl
                env["XDG_RUNTIME_DIR"] = os.path.dirname(sock)
                break
    if not env.get("WAYLAND_DISPLAY"):
        print("[agent-rdp] WAYLAND_DISPLAY not set and could not find wayland socket", file=sys.stderr)
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        result = subprocess.run(
            [grim, "-t", "png", tmp_path],
            env=env, timeout=5, capture_output=True,
        )
        if result.returncode != 0:
            return None
        with open(tmp_path, "rb") as f:
            png_data = f.read()
        os.unlink(tmp_path)
        return _rdp_decode_png(png_data)
    except Exception as e:
        print(f"[agent-rdp] grim capture error: {e}", file=sys.stderr)
        return None


def _rdp_display_owner() -> tuple:
    """Return (uid, gid, home, display_str, xauth_path) for the X11/Wayland display owner.
    When the agent runs as root, find the user who owns the X socket."""
    import pwd as _pwd
    import glob as _g
    uid = os.getuid()
    try:
        entry = _pwd.getpwuid(uid)
        home, gid = entry.pw_dir, entry.pw_gid
    except Exception:
        home, gid = os.path.expanduser("~"), os.getgid()

    display_str = os.environ.get("DISPLAY", "")
    # If root or no DISPLAY: find display owner from X socket
    if uid == 0 or not display_str:
        try:
            for sock in sorted(os.listdir("/tmp/.X11-unix/")) if os.path.isdir("/tmp/.X11-unix/") else []:
                if not sock.startswith("X"):
                    continue
                owner_uid = os.stat(f"/tmp/.X11-unix/{sock}").st_uid
                if owner_uid != 0:
                    e2 = _pwd.getpwuid(owner_uid)
                    uid, gid, home = owner_uid, e2.pw_gid, e2.pw_dir
                    display_str = f":{sock[1:]}"
                    break
                elif not display_str:
                    display_str = f":{sock[1:]}"
        except Exception:
            pass
    if not display_str:
        display_str = ":0"

    xauth = ""
    for pattern in [f"{home}/.Xauthority", f"/tmp/xauth_{uid}*", f"/run/user/{uid}/xauth*",
                    f"/run/user/{uid}/.mutter-Xwaylandauth.*"]:
        if "*" in pattern:
            matches = sorted(_g.glob(pattern))
            if matches:
                xauth = matches[-1]
                break
        elif os.path.exists(pattern):
            xauth = pattern
            break
    return uid, gid, home, display_str, xauth


def _capture_screen_gnome() -> tuple | None:
    """Capture via GNOME Shell's D-Bus Screenshot API.
    GNOME (Mutter) does not support wlr-screencopy, so grim/wayshot won't work.
    Uses gdbus or gnome-screenshot as the session user via D-Bus session bus."""
    import subprocess
    uid, gid, home, _, _ = _rdp_display_owner()
    # Only attempt if GNOME Shell is running for this user
    if not os.path.exists(f"/run/user/{uid}/gnome-shell"):
        return None
    bus_path = f"/run/user/{uid}/bus"
    if not os.path.exists(bus_path):
        print("[agent-rdp] GNOME session bus not found", file=sys.stderr)
        return None
    env = os.environ.copy()
    env["HOME"] = home
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"
    env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    preexec = None
    if os.getuid() == 0 and uid != 0:
        _uid, _gid = uid, gid
        def preexec():
            os.setgid(_gid)
            os.setuid(_uid)
    tmp_path = f"/tmp/noba_rdp_{uid}.png"
    # Try gdbus call to org.gnome.Shell.Screenshot interface
    gdbus = _which("gdbus")
    if gdbus:
        try:
            r = subprocess.run(
                [gdbus, "call", "--session",
                 "--dest", "org.gnome.Shell.Screenshot",
                 "--object-path", "/org/gnome/Shell/Screenshot",
                 "--method", "org.gnome.Shell.Screenshot.Screenshot",
                 "false", "false", tmp_path],
                env=env, preexec_fn=preexec, capture_output=True, timeout=5,
            )
            if r.returncode == 0 and os.path.exists(tmp_path):
                with open(tmp_path, "rb") as f:
                    png_data = f.read()
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                result = _rdp_decode_png(png_data)
                if result:
                    print(f"[agent-rdp] captured via gdbus/gnome-shell {result[0]}x{result[1]}", file=sys.stderr)
                    return result
            print(f"[agent-rdp] gdbus rc={r.returncode} stderr={r.stderr[:100]!r}", file=sys.stderr)
        except Exception as e:
            print(f"[agent-rdp] gdbus error: {e}", file=sys.stderr)
    # Fallback: gnome-screenshot CLI
    gnome_ss = _which("gnome-screenshot")
    if gnome_ss:
        try:
            r = subprocess.run(
                [gnome_ss, "-f", tmp_path],
                env=env, preexec_fn=preexec, capture_output=True, timeout=5,
            )
            if r.returncode == 0 and os.path.exists(tmp_path):
                with open(tmp_path, "rb") as f:
                    png_data = f.read()
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                result = _rdp_decode_png(png_data)
                if result:
                    print(f"[agent-rdp] captured via gnome-screenshot {result[0]}x{result[1]}", file=sys.stderr)
                    return result
            print(f"[agent-rdp] gnome-screenshot rc={r.returncode} stderr={r.stderr[:100]!r}", file=sys.stderr)
        except Exception as e:
            print(f"[agent-rdp] gnome-screenshot error: {e}", file=sys.stderr)
    return None


_MUTTER_SESSION_SCRIPT = r'''
import sys, os, json, threading, struct, gi
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gio, GLib, Gst
Gst.init(None)
main_loop = GLib.MainLoop()
state = {"rgb": None, "rd_path": None, "sc_stream": None, "ready": False, "width": 1920, "height": 1080}
state_lock = threading.Lock()
bus_addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
try:
    dbus_conn = Gio.DBusConnection.new_for_address_sync(
        bus_addr,
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None, None)
    rd = dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", "/org/gnome/Mutter/RemoteDesktop",
        "org.gnome.Mutter.RemoteDesktop", "CreateSession",
        None, GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None)
    rd_path = rd.get_child_value(0).get_string()
    state["rd_path"] = rd_path
    props = dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", rd_path,
        "org.freedesktop.DBus.Properties", "GetAll",
        GLib.Variant("(s)", ("org.gnome.Mutter.RemoteDesktop.Session",)),
        GLib.VariantType("(a{sv})"), Gio.DBusCallFlags.NONE, -1, None)
    sid = props.get_child_value(0).lookup_value("SessionId", None).get_string()
    sc = dbus_conn.call_sync("org.gnome.Mutter.ScreenCast", "/org/gnome/Mutter/ScreenCast",
        "org.gnome.Mutter.ScreenCast", "CreateSession",
        GLib.Variant("(a{sv})", ({"remote-desktop-session-id": GLib.Variant("s", sid)},)),
        GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None)
    sc_path = sc.get_child_value(0).get_string()
    stream_path = None
    try:
        dcfg = dbus_conn.call_sync("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
            "org.gnome.Mutter.DisplayConfig", "GetCurrentState",
            None, GLib.VariantType("(ua((ssss)a(siiddada{sv})a{sv})a(iiduba(ssss)a{sv})a{sv})"),
            Gio.DBusCallFlags.NONE, -1, None)
        monitors = dcfg.get_child_value(1)
        for i in range(monitors.n_children()):
            connector = monitors.get_child_value(i).get_child_value(0).get_child_value(0).get_string()
            try:
                s = dbus_conn.call_sync("org.gnome.Mutter.ScreenCast", sc_path,
                    "org.gnome.Mutter.ScreenCast.Session", "RecordMonitor",
                    GLib.Variant("(sa{sv})", (connector, {"cursor-mode": GLib.Variant("u", 1)})),
                    GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None)
                stream_path = s.get_child_value(0).get_string()
                break
            except Exception:
                pass
    except Exception:
        pass
    if not stream_path:
        s = dbus_conn.call_sync("org.gnome.Mutter.ScreenCast", sc_path,
            "org.gnome.Mutter.ScreenCast.Session", "RecordVirtual",
            GLib.Variant("(a{sv})", ({"cursor-mode": GLib.Variant("u", 0), "is-recording": GLib.Variant("b", True)},)),
            GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None)
        stream_path = s.get_child_value(0).get_string()
    state["sc_stream"] = stream_path
except Exception as e:
    print("MUTTER_ERROR:" + str(e), file=sys.stderr, flush=True)
    sys.exit(1)

def _on_sample(sink):
    sample = sink.emit("pull-sample")
    buf = sample.get_buffer()
    caps = sample.get_caps()
    s = caps.get_structure(0)
    w = s.get_int("width")[1]; h = s.get_int("height")[1]
    data = buf.extract_dup(0, buf.get_size())
    with state_lock:
        state["rgb"] = bytes(data[:w * h * 3])
        state["width"] = w
        state["height"] = h
        if not state["ready"]:
            state["ready"] = True
            print("READY", file=sys.stderr, flush=True)
    return Gst.FlowReturn.OK

def _on_gst_bus(bus, msg):
    if msg.type == Gst.MessageType.ERROR:
        err, _ = msg.parse_error()
        print("GST_ERROR:" + str(err), file=sys.stderr, flush=True)

def _start_pipeline(nid):
    pipeline = Gst.Pipeline.new("rdp")
    src = Gst.ElementFactory.make("pipewiresrc", "src")
    conv = Gst.ElementFactory.make("videoconvert", "conv")
    sink = Gst.ElementFactory.make("appsink", "sink")
    sp, _ = Gst.Structure.from_string(
        "props,node.target=(string)" + str(nid) +
        ",media.class=(string)Stream/Input/Video"
        ",media.type=(string)Video,media.category=(string)Capture")
    src.set_property("stream-properties", sp)
    src.set_property("client-name", "noba-agent")
    sink.set_property("sync", False)
    sink.set_property("emit-signals", True)
    sink.set_property("max-buffers", 1)
    sink.set_property("drop", True)
    sink.connect("new-sample", _on_sample)
    pipeline.add(src); pipeline.add(conv); pipeline.add(sink)
    src.link(conv)
    conv.link_filtered(sink, Gst.Caps.from_string("video/x-raw,format=RGB"))
    gbus = pipeline.get_bus()
    gbus.add_signal_watch()
    gbus.connect("message", _on_gst_bus)
    pipeline.set_state(Gst.State.PLAYING)
    state["pipeline"] = pipeline

def _on_dbus_signal(conn, sender, obj_path, iface, sig, params, ud):
    if sig == "PipeWireStreamAdded":
        nid = params.get_child_value(0).get_uint32()
        GLib.idle_add(lambda: _start_pipeline(nid) or False)

dbus_conn.signal_subscribe(None, None, "PipeWireStreamAdded", stream_path,
    None, Gio.DBusSignalFlags.NONE, _on_dbus_signal, None)
dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", rd_path,
    "org.gnome.Mutter.RemoteDesktop.Session", "Start",
    None, None, Gio.DBusCallFlags.NONE, -1, None)

def _inject(ev):
    rd = state.get("rd_path")
    sc = state.get("sc_stream")
    if not rd:
        return
    evt = ev.get("event", "")
    try:
        if evt == "mousemove" and sc:
            with state_lock:
                sw, sh = state["width"], state["height"]
            x = float(ev.get("x", 0)) * sw
            y = float(ev.get("y", 0)) * sh
            dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", rd,
                "org.gnome.Mutter.RemoteDesktop.Session", "NotifyPointerMotionAbsolute",
                GLib.Variant("(sdd)", (sc, x, y)),
                None, Gio.DBusCallFlags.NONE, 100, None)
        elif evt in ("mousedown", "mouseup"):
            # Mutter uses Linux kernel button codes, not X11 button numbers
            _btn_map = {1: 272, 2: 274, 3: 273}  # left, middle, right
            btn = _btn_map.get(int(ev.get("button", 1)), 272)
            dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", rd,
                "org.gnome.Mutter.RemoteDesktop.Session", "NotifyPointerButton",
                GLib.Variant("(ib)", (btn, evt == "mousedown")),
                None, Gio.DBusCallFlags.NONE, 100, None)
        elif evt == "wheel":
            steps = -1 if float(ev.get("delta_y", 0)) > 0 else 1
            dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", rd,
                "org.gnome.Mutter.RemoteDesktop.Session", "NotifyPointerAxisDiscrete",
                GLib.Variant("(ui)", (0, steps)),
                None, Gio.DBusCallFlags.NONE, 100, None)
        elif evt in ("keydown", "keyup"):
            kc = int(ev.get("keycode", 0))
            dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", rd,
                "org.gnome.Mutter.RemoteDesktop.Session", "NotifyKeyboardKeycode",
                GLib.Variant("(ub)", (kc, evt == "keydown")),
                None, Gio.DBusCallFlags.NONE, 100, None)
    except Exception as e:
        print("INJECT_ERR:" + str(e), file=sys.stderr, flush=True)

def _cmd_loop():
    import select as _sel2
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "CAPTURE":
            with state_lock:
                rgb = state.get("rgb")
                w, h = state["width"], state["height"]
            if rgb:
                # NOBR = NOBA Raw: 4-byte magic + 4-byte w + 4-byte h + raw RGB bytes
                sys.stdout.buffer.write(b"NOBR" + struct.pack(">II", w, h) + rgb)
            else:
                sys.stdout.buffer.write(b"NONE")
            sys.stdout.buffer.flush()
        elif cmd == "STOP":
            GLib.idle_add(main_loop.quit)
            break
        elif cmd:
            try:
                ev = json.loads(cmd)
                # Coalesce stale mousemove events: drain all pending lines from
                # stdin and keep only the last mousemove, then process it.
                if ev.get("event") == "mousemove":
                    while _sel2.select([sys.stdin], [], [], 0)[0]:
                        peek = sys.stdin.readline().strip()
                        if not peek:
                            break
                        try:
                            pev = json.loads(peek)
                            if pev.get("event") == "mousemove":
                                ev = pev  # discard stale, keep newer
                            else:
                                _inject(ev)  # flush pending move first
                                ev = pev
                        except Exception:
                            break
                _inject(ev)
            except Exception:
                pass

threading.Thread(target=_cmd_loop, daemon=True).start()
main_loop.run()
'''


def _mutter_subprocess_start(uid: int, gid: int, home: str) -> "subprocess.Popen | None":
    """Launch the persistent Mutter session subprocess. Returns proc if READY, else None."""
    import select as _sel
    env = os.environ.copy()
    env["HOME"] = home
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
    env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    env["PIPEWIRE_RUNTIME_DIR"] = f"/run/user/{uid}"
    preexec_fn = None
    if os.getuid() == 0 and uid != 0:
        _uid, _gid = uid, gid
        def preexec_fn():
            os.setgid(_gid)
            os.setuid(_uid)
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", _MUTTER_SESSION_SCRIPT],
            env=env, preexec_fn=preexec_fn,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            rlist = _sel.select([proc.stderr], [], [], min(remaining, 0.5))[0]
            if rlist:
                line = proc.stderr.readline()
                if line:
                    msg = line.decode("utf-8", errors="replace").strip()
                    print(f"[agent-rdp] mutter: {msg}", file=sys.stderr)
                    if msg == "READY":
                        # Start a daemon thread to drain stderr so the buffer
                        # never blocks and subprocess messages stay visible.
                        def _drain(p: "subprocess.Popen") -> None:
                            try:
                                for ln in p.stderr:
                                    print(f"[agent-rdp] mutter: {ln.decode('utf-8', errors='replace').rstrip()}", file=sys.stderr)
                            except Exception:
                                pass
                        threading.Thread(target=_drain, args=(proc,), daemon=True).start()
                        return proc
                    if "ERROR" in msg:
                        proc.kill()
                        return None
            if proc.poll() is not None:
                return None
        proc.kill()
        return None
    except Exception as e:
        print(f"[agent-rdp] mutter start error: {e}", file=sys.stderr)
        return None


def _mutter_ensure(uid: int, gid: int, home: str) -> bool:
    """Ensure the Mutter session subprocess is running. Returns True if ready."""
    global _mutter_proc
    with _mutter_proc_lock:
        if _mutter_proc is not None and _mutter_proc.poll() is None:
            return True
    proc = _mutter_subprocess_start(uid, gid, home)
    if proc is None:
        return False
    with _mutter_proc_lock:
        if _mutter_proc is not None and _mutter_proc.poll() is None:
            proc.kill()  # lost the race
        else:
            _mutter_proc = proc
    return True


def _mutter_stop() -> None:
    """Stop the persistent Mutter session subprocess."""
    global _mutter_proc
    with _mutter_proc_lock:
        proc = _mutter_proc
        _mutter_proc = None
    if proc is not None:
        try:
            proc.stdin.write(b"STOP\n")
            proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass


def _capture_screen_pipewire() -> tuple | None:
    """Capture via persistent Mutter ScreenCast D-Bus + PipeWire + GStreamer session.

    Works on GNOME Wayland (headless or physical display). A long-lived subprocess
    holds the RemoteDesktop+ScreenCast session for both capture and input injection.
    """
    import select as _sel
    import struct
    uid, gid, home, _, _ = _rdp_display_owner()
    bus_path = f"/run/user/{uid}/bus"
    pipewire_sock = f"/run/user/{uid}/pipewire-0"
    if not os.path.exists(bus_path) or not os.path.exists(pipewire_sock):
        return None
    if not _mutter_ensure(uid, gid, home):
        return None
    with _mutter_proc_lock:
        proc = _mutter_proc
    if proc is None or proc.poll() is not None:
        return None
    try:
        # Hold the lock only for the write — pipe writes ≤ PIPE_BUF are atomic,
        # but we still serialise to prevent inject JSON landing before CAPTURE.
        # The read happens outside the lock so inject writes aren't blocked while
        # we wait for the PNG (up to 2 s).
        with _mutter_io_lock:
            proc.stdin.write(b"CAPTURE\n")
            proc.stdin.flush()
        ready = _sel.select([proc.stdout], [], [], 2.0)[0]
        if not ready:
            return None
        magic = proc.stdout.read(4)
        if magic == b"NONE":
            return None
        if magic == b"NOBR":
            # Raw RGB: 4-byte w + 4-byte h + w*h*3 raw bytes
            dims = proc.stdout.read(8)
            if len(dims) < 8:
                return None
            w, h = struct.unpack(">II", dims)
            size = w * h * 3
            if size > 15_000_000:
                return None
            rgb = proc.stdout.read(size)
            if len(rgb) < size:
                return None
            return (w, h, rgb)
        if magic != b"NOBA":  # legacy PNG path (backward compat)
            return None
        size = struct.unpack(">I", proc.stdout.read(4))[0]
        if size > 15_000_000:
            return None
        png = proc.stdout.read(size)
        if len(png) < size:
            return None
        return _rdp_decode_png(png)
    except Exception as e:
        print(f"[agent-rdp] pipewire error: {e}", file=sys.stderr)
        _mutter_stop()
        return None


def _capture_screen_cmd() -> tuple | None:
    """Capture via grim, wayshot, scrot, or ImageMagick import.
    Runs as the display owner when agent is root for proper X11/Wayland auth."""
    import subprocess
    uid, gid, home, display_str, xauth = _rdp_display_owner()
    env = os.environ.copy()
    env["DISPLAY"] = display_str
    env["HOME"] = home
    if xauth:
        env["XAUTHORITY"] = xauth
    for wl in ("wayland-0", "wayland-1"):
        if os.path.exists(f"/run/user/{uid}/{wl}"):
            env.setdefault("WAYLAND_DISPLAY", wl)
            env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
            break

    preexec = None
    if os.getuid() == 0 and uid != 0:
        _uid, _gid = uid, gid
        def preexec():
            os.setgid(_gid)
            os.setuid(_uid)

    for tool, args in [
        ("grim", ["-t", "png", "-"]),
        ("wayshot", ["--stdout"]),
        ("scrot", ["-"]),
        ("import", ["-window", "root", "-depth", "8", "png:-"]),
    ]:
        exe = _which(tool)
        if not exe:
            continue
        try:
            r = subprocess.run(
                [exe] + args,
                capture_output=True, timeout=8, env=env, preexec_fn=preexec,
            )
            if r.returncode == 0 and r.stdout:
                result = _rdp_decode_png(r.stdout)
                if result:
                    print(f"[agent-rdp] captured via {tool} {result[0]}x{result[1]}", file=sys.stderr)
                    return result
            print(f"[agent-rdp] {tool} rc={r.returncode} stderr={r.stderr[:100]!r}", file=sys.stderr)
        except Exception as e:
            print(f"[agent-rdp] {tool} error: {e}", file=sys.stderr)
    return None


def _rdp_decode_png(data: bytes) -> tuple | None:
    """Decode a PNG byte string to (w, h, rgb_bytes). Pure stdlib."""
    import zlib as _zlib
    import struct as _struct
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    chunks: dict = {}
    while pos < len(data) - 12:
        length = _struct.unpack_from(">I", data, pos)[0]
        tag = data[pos + 4:pos + 8]
        chunks.setdefault(tag, []).append(data[pos + 8:pos + 8 + length])
        pos += 12 + length
    if b"IHDR" not in chunks:
        return None
    ihdr = chunks[b"IHDR"][0]
    w, h = _struct.unpack_from(">II", ihdr)
    bit_depth, color_type = ihdr[8], ihdr[9]
    if bit_depth != 8 or color_type not in (2, 6):  # RGB or RGBA only
        return None
    raw = _zlib.decompress(b"".join(chunks.get(b"IDAT", [])))
    bpp = 3 if color_type == 2 else 4
    stride = w * bpp + 1
    rgb = bytearray(w * h * 3)
    prev = bytes(w * bpp)
    for y in range(h):
        row = raw[y * stride:y * stride + stride]
        filt = row[0]
        cur = bytearray(row[1:])
        if filt == 1:  # Sub
            for i in range(bpp, len(cur)):
                cur[i] = (cur[i] + cur[i - bpp]) & 0xFF
        elif filt == 2:  # Up
            for i in range(len(cur)):
                cur[i] = (cur[i] + prev[i]) & 0xFF
        elif filt == 3:  # Average
            for i in range(len(cur)):
                a = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + (a + prev[i]) // 2) & 0xFF
        elif filt == 4:  # Paeth
            for i in range(len(cur)):
                a = cur[i - bpp] if i >= bpp else 0
                b_val = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b_val - c
                pa, pb, pc = abs(p - a), abs(p - b_val), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b_val if pb <= pc else c)
                cur[i] = (cur[i] + pr) & 0xFF
        if bpp == 3:
            rgb[y * w * 3:(y + 1) * w * 3] = cur
        else:
            for x in range(w):
                rgb[(y * w + x) * 3:(y * w + x) * 3 + 3] = cur[x * 4:x * 4 + 3]
        prev = bytes(cur)
    return w, h, bytes(rgb)


def _which(cmd: str) -> str | None:
    """Locate an executable in PATH. Returns path string or None."""
    import shutil
    return shutil.which(cmd)


def _capture_screen() -> tuple | None:
    """Dispatch to the platform-appropriate screen capture. Returns (w, h, rgb) or None.
    Raises RuntimeError with a full diagnostic reason when everything fails."""
    if _PLATFORM == "windows":
        return _capture_screen_windows()
    if _PLATFORM == "darwin":
        return _capture_screen_macos()
    # Linux: detect Wayland early to avoid XOpenDisplay hanging (it has no timeout,
    # unlike XGetImage which is wrapped in a 4s thread). If a wayland socket exists
    # for any user in /run/user, skip X11 entirely and go straight to grim.
    _wayland_present = False
    try:
        if os.path.isdir("/run/user"):
            for _uid_dir in os.listdir("/run/user"):
                for _wl in ("wayland-0", "wayland-1"):
                    if os.path.exists(f"/run/user/{_uid_dir}/{_wl}"):
                        _wayland_present = True
                        break
                if _wayland_present:
                    break
    except OSError:
        pass
    x11_err = ""
    if not _wayland_present:
        try:
            result = _capture_screen_x11()
            if result:
                return result
        except RuntimeError as e:
            x11_err = str(e)
    result = _capture_screen_grim()
    if result:
        return result
    result = _capture_screen_pipewire()
    if result:
        return result
    result = _capture_screen_gnome()
    if result:
        return result
    result = _capture_screen_cmd()
    if result:
        return result
    x11_note = "skipped (Wayland detected)" if _wayland_present else (x11_err or "returned None")
    raise RuntimeError(
        f"All capture methods failed. X11: {x11_note}. "
        f"grim/gnome-screenshot/gdbus/scrot: not found or compositor rejected capture."
    )


def _rdp_scale_half(width: int, height: int, rgb_bytes: bytes) -> tuple:
    """Downsample by 2× using every other pixel/row. Fast O(h) slice operations."""
    new_w = max(1, width // 2)
    new_h = max(1, height // 2)
    rows = []
    for y in range(new_h):
        row_start = (y * 2) * width * 3
        row = rgb_bytes[row_start:row_start + width * 3]
        scaled = bytearray(new_w * 3)
        scaled[0::3] = row[0::6]   # R of even pixels
        scaled[1::3] = row[1::6]   # G
        scaled[2::3] = row[2::6]   # B
        rows.append(bytes(scaled))
    return new_w, new_h, b"".join(rows)


_HAS_PILLOW: bool | None = None


def _rdp_encode_frame(width: int, height: int, rgb_bytes: bytes, quality: int = 70) -> str:
    """Encode RGB bytes as JPEG (Pillow) or PNG fallback. Returns base64 string."""
    global _HAS_PILLOW
    import base64 as _b64
    if _HAS_PILLOW is None:
        try:
            from PIL import Image as _Img  # noqa: F401
            _HAS_PILLOW = True
        except ImportError:
            _HAS_PILLOW = False
    if _HAS_PILLOW:
        try:
            from PIL import Image as _Img
            import io as _io
            img = _Img.frombytes("RGB", (width, height), rgb_bytes)
            buf = _io.BytesIO()
            img.save(buf, "JPEG", quality=quality, optimize=False)
            return _b64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            pass  # fall through to PNG
    # Pure-Python PNG fallback (no external deps)
    import struct
    import zlib

    def _chunk(name: bytes, data: bytes) -> bytes:
        body = name + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    bpr = width * 3
    raw = bytearray(height * (1 + bpr))
    for y in range(height):
        raw[y * (1 + bpr)] = 0
        raw[y * (1 + bpr) + 1:(y + 1) * (1 + bpr)] = rgb_bytes[y * bpr:(y + 1) * bpr]
    idat = zlib.compress(bytes(raw), 1)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
    return _b64.b64encode(png).decode("ascii")


def _rdp_inject_input(event: dict) -> None:
    """Inject a mouse or keyboard event on the current platform."""
    if _PLATFORM == "linux":
        _rdp_inject_x11(event)
    elif _PLATFORM == "windows":
        _rdp_inject_windows(event)
    elif _PLATFORM == "darwin":
        _rdp_inject_macos(event)


def _rdp_inject_mutter(event: dict) -> None:
    """Send an input event to the persistent Mutter session subprocess via stdin."""
    with _mutter_proc_lock:
        proc = _mutter_proc
    if proc is None or proc.poll() is not None:
        return
    try:
        import json as _json
        line = (_json.dumps(event) + "\n").encode()
        print(f"[agent-rdp] inject→mutter: {event.get('event')} ({event.get('x','')},{event.get('y','')})", file=sys.stderr)
        with _mutter_io_lock:
            proc.stdin.write(line)
            proc.stdin.flush()
    except Exception as e:
        print(f"[agent-rdp] mutter input error: {e}", file=sys.stderr)


def _rdp_inject_x11(event: dict) -> None:
    """Inject input via XTest (libXtst) or Mutter D-Bus on Wayland. Coordinates are normalized 0–1."""
    # On Wayland, route to the persistent Mutter session subprocess
    with _mutter_proc_lock:
        proc = _mutter_proc
    if proc is not None and proc.poll() is None:
        _rdp_inject_mutter(event)
        return
    lib = _rdp_load_x11()
    xtst = _rdp_load_xtst()
    dpy = _rdp_get_x11_display()
    if not (lib and xtst and dpy):
        return
    try:
        evt = event.get("event", "")
        nx = float(event.get("x", 0))
        ny = float(event.get("y", 0))

        # Get current screen size for coordinate denormalization
        screen = lib.XDefaultScreen(dpy)
        sw = lib.XDisplayWidth(dpy, screen)
        sh = lib.XDisplayHeight(dpy, screen)
        px = max(0, min(sw - 1, int(nx * sw)))
        py = max(0, min(sh - 1, int(ny * sh)))

        if evt == "mousemove":
            xtst.XTestFakeMotionEvent(dpy, -1, px, py, 0)
        elif evt == "mousedown":
            xtst.XTestFakeButtonEvent(dpy, int(event.get("button", 1)), 1, 0)
        elif evt == "mouseup":
            xtst.XTestFakeButtonEvent(dpy, int(event.get("button", 1)), 0, 0)
        elif evt == "wheel":
            # Button 4 = scroll up, button 5 = scroll down
            btn = 4 if float(event.get("delta_y", 0)) < 0 else 5
            xtst.XTestFakeButtonEvent(dpy, btn, 1, 0)
            xtst.XTestFakeButtonEvent(dpy, btn, 0, 0)
        elif evt == "keydown":
            xtst.XTestFakeKeyEvent(dpy, int(event.get("keycode", 0)), 1, 0)
        elif evt == "keyup":
            xtst.XTestFakeKeyEvent(dpy, int(event.get("keycode", 0)), 0, 0)
        lib.XFlush(dpy)
    except Exception as e:
        print(f"[agent-rdp] X11 input error: {e}", file=sys.stderr)


def _rdp_inject_windows(event: dict) -> None:
    """Inject input via user32 SendInput."""
    try:
        import ctypes
        from ctypes import wintypes

        class _MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]

        class _KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]

        class _INPUT_UNION(ctypes.Union):
            _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

        class _INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]

        user32 = ctypes.WinDLL("user32")
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        evt = event.get("event", "")
        nx = float(event.get("x", 0))
        ny = float(event.get("y", 0))

        # MOUSEEVENTF_ABSOLUTE uses 0-65535 coordinate space
        abs_x = int(nx * 65535)
        abs_y = int(ny * 65535)

        inp = _INPUT()
        if evt == "mousemove":
            inp.type = 0  # INPUT_MOUSE
            inp.u.mi.dx = abs_x
            inp.u.mi.dy = abs_y
            inp.u.mi.dwFlags = 0x8001  # MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
        elif evt in ("mousedown", "mouseup"):
            btn = int(event.get("button", 1))
            down_flags = {1: 0x0002, 2: 0x0008, 3: 0x0020}
            up_flags   = {1: 0x0004, 2: 0x0010, 3: 0x0040}
            flags = down_flags.get(btn, 0x0002) if evt == "mousedown" else up_flags.get(btn, 0x0004)
            inp.type = 0
            inp.u.mi.dwFlags = flags | 0x8000  # MOUSEEVENTF_ABSOLUTE
            inp.u.mi.dx = abs_x
            inp.u.mi.dy = abs_y
        elif evt == "wheel":
            inp.type = 0
            inp.u.mi.dwFlags = 0x0800  # MOUSEEVENTF_WHEEL
            delta = int(event.get("delta_y", 0))
            inp.u.mi.mouseData = ctypes.c_ulong(-delta * 120 & 0xFFFFFFFF).value
        elif evt in ("keydown", "keyup"):
            inp.type = 1  # INPUT_KEYBOARD
            inp.u.ki.wVk = int(event.get("keycode", 0))
            inp.u.ki.dwFlags = 0x0002 if evt == "keyup" else 0  # KEYEVENTF_KEYUP
        else:
            return

        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
    except Exception as e:
        print(f"[agent-rdp] Windows input error: {e}", file=sys.stderr)


def _rdp_inject_macos(event: dict) -> None:
    """Inject input via CoreGraphics CGEventPost."""
    try:
        import ctypes
        cg = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        cg.CGEventCreateMouseEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32,
            ctypes.c_double, ctypes.c_double, ctypes.c_uint32]  # CGPoint via two doubles
        cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        cg.CGEventCreateKeyboardEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
        cg.CGEventPost.restype = None
        cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        cg.CFRelease.restype = None
        cg.CFRelease.argtypes = [ctypes.c_void_p]

        # Get screen size
        cg.CGDisplayPixelsWide.restype = ctypes.c_size_t
        cg.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
        cg.CGDisplayPixelsHigh.restype = ctypes.c_size_t
        cg.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        did = cg.CGMainDisplayID()
        sw = cg.CGDisplayPixelsWide(did)
        sh = cg.CGDisplayPixelsHigh(did)

        evt = event.get("event", "")
        nx = float(event.get("x", 0))
        ny = float(event.get("y", 0))
        px = nx * sw
        py = ny * sh

        # kCGEventMouseMoved=5, kCGEventLeftMouseDown=1, kCGEventLeftMouseUp=2
        # kCGEventRightMouseDown=3, kCGEventRightMouseUp=4
        # kCGEventScrollWheel=22, kCGEventKeyDown=10, kCGEventKeyUp=11
        # kCGHIDEventTap=0
        ev_map = {
            ("mousemove", 0): (5, 0), ("mousemove", 1): (5, 0),
            ("mousedown", 1): (1, 1), ("mouseup", 1): (2, 1),
            ("mousedown", 3): (3, 3), ("mouseup", 3): (4, 3),
        }
        if evt in ("mousemove", "mousedown", "mouseup"):
            btn = int(event.get("button", 1))
            etype, ebtn = ev_map.get((evt, btn), (5, 0))
            ref = cg.CGEventCreateMouseEvent(None, etype, px, py, ebtn)
            if ref:
                cg.CGEventPost(0, ref)
                cg.CFRelease(ref)
        elif evt == "wheel":
            # CGEventCreateScrollWheelEvent is variadic — use CGEventPost with scroll type
            pass  # skip for now; macOS scroll injection requires variadic ctypes call
        elif evt in ("keydown", "keyup"):
            down = evt == "keydown"
            ref = cg.CGEventCreateKeyboardEvent(None, int(event.get("keycode", 0)), down)
            if ref:
                cg.CGEventPost(0, ref)
                cg.CFRelease(ref)
    except Exception as e:
        print(f"[agent-rdp] macOS input error: {e}", file=sys.stderr)


def _rdp_capture_loop(quality: int, fps: int) -> None:
    """Background thread: capture screen, encode, push to frame queue."""
    interval = 1.0 / max(1, fps)
    scale = max(0.25, min(1.0, quality / 100.0))  # quality 10-100 → scale 0.1-1.0
    # Clamp scale to reasonable values: 50% (quality≤50) or 100% (quality>75)
    if quality <= 50:
        do_scale = True
    elif quality <= 75:
        do_scale = True   # still scale, just less aggressively (use scale directly)
    else:
        do_scale = False  # native resolution

    print(f"[agent-rdp] Capture started at {fps}fps quality={quality} scale={scale:.2f}")

    _consecutive_failures = 0
    _MAX_FAILURES = 8  # tolerate ~8 cycles of subprocess restart before giving up

    while _rdp_active.is_set():
        t0 = time.monotonic()
        try:
            result = _capture_screen()
            if result:
                _consecutive_failures = 0
                w, h, rgb = result
                if do_scale:
                    w, h, rgb = _rdp_scale_half(w, h, rgb)
                frame_data = _rdp_encode_frame(w, h, rgb, quality)
                frame = {"type": "rdp_frame", "w": w, "h": h, "data": frame_data}
                try:
                    _rdp_frame_queue.put_nowait(frame)
                except _queue.Full:
                    # Main loop hasn't drained yet; replace with fresher frame
                    try:
                        _rdp_frame_queue.get_nowait()
                    except _queue.Empty:
                        pass
                    try:
                        _rdp_frame_queue.put_nowait(frame)
                    except _queue.Full:
                        pass
            else:
                # No display available — notify browser once then pause
                _rdp_frame_queue.put_nowait({"type": "rdp_unavailable",
                                             "reason": "No display available on this agent"})
                _rdp_active.clear()
                break
        except RuntimeError as e:
            # Transient failures (subprocess restarting, Mutter session closing) are
            # normal — tolerate a burst before notifying the browser.
            _consecutive_failures += 1
            print(f"[agent-rdp] Display error ({_consecutive_failures}/{_MAX_FAILURES}): {e}", file=sys.stderr)
            if _consecutive_failures >= _MAX_FAILURES:
                try:
                    _rdp_frame_queue.put_nowait({"type": "rdp_unavailable", "reason": str(e)})
                except _queue.Full:
                    pass
                _rdp_active.clear()
                break
            # Brief pause to let Mutter subprocess restart
            _rdp_active.wait(timeout=0.5)
            continue
        except Exception as e:
            print(f"[agent-rdp] Frame error: {e}", file=sys.stderr)

        elapsed = time.monotonic() - t0
        sleep_time = max(0.0, interval - elapsed)
        if sleep_time > 0:
            _rdp_active.wait(timeout=sleep_time)

    print("[agent-rdp] Capture stopped")


def _rdp_start(quality: int = 70, fps: int = 5) -> None:
    """Start or restart the RDP capture thread."""
    global _rdp_thread
    with _rdp_lock:
        if _rdp_active.is_set():
            # Already running — just update parameters by restarting thread
            _rdp_active.clear()
            if _rdp_thread and _rdp_thread.is_alive():
                _rdp_thread.join(timeout=2)
        _rdp_active.set()
        _rdp_thread = threading.Thread(
            target=_rdp_capture_loop, args=(quality, fps),
            daemon=True, name="noba-rdp",
        )
        _rdp_thread.start()


def _rdp_stop() -> None:
    """Stop the RDP capture thread and Mutter session subprocess."""
    global _rdp_thread
    _rdp_active.clear()
    _mutter_stop()
    # Drain leftover frames
    while not _rdp_frame_queue.empty():
        try:
            _rdp_frame_queue.get_nowait()
        except _queue.Empty:
            break


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
        # Capability refresh
        "refresh_capabilities": _cmd_refresh_capabilities,
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

import operator as _op  # noqa: E402 (intentional late import for eval sandbox)
import re as _re  # noqa: E402 (intentional late import for eval sandbox)

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


# ── Capability Probing ────────────────────────────────────────────────────────

_last_capability_probe: float = 0
_CAPABILITY_PROBE_INTERVAL = 21600  # 6 hours


def probe_capabilities() -> dict:
    """Probe the host for OS info and available tools.

    Returns a dict matching the CapabilityManifest shape:
      os, distro, distro_version, kernel, init_system,
      is_wsl, is_container, capabilities (dict of tool -> {available, version?})
    """
    import shutil

    os_name = platform.system().lower()

    # ── Distro / version ──────────────────────────────────────────────────
    distro = os_name
    distro_version = platform.version()
    if os_name == "linux":
        try:
            with open("/etc/os-release") as f:
                osr = {}
                for line in f:
                    if "=" in line:
                        k, _, v = line.strip().partition("=")
                        osr[k] = v.strip('"')
                distro = osr.get("ID", "linux")
                distro_version = osr.get("VERSION_ID", distro_version)
        except OSError:
            pass
    elif os_name == "darwin":
        distro = "macos"
    elif os_name == "windows":
        distro = "windows"

    kernel = platform.release()

    # ── Init system ───────────────────────────────────────────────────────
    init_system = "unknown"
    if os_name == "linux":
        if os.path.isdir("/run/systemd/system"):
            init_system = "systemd"
        elif os.path.isfile("/sbin/openrc"):
            init_system = "openrc"
    elif os_name == "darwin":
        init_system = "launchd"
    elif os_name == "windows":
        init_system = "windows_scm"

    # ── WSL detection ─────────────────────────────────────────────────────
    is_wsl = False
    if os_name == "linux":
        try:
            with open("/proc/version") as f:
                pv = f.read().lower()
                is_wsl = "microsoft" in pv or "wsl" in pv
        except OSError:
            pass

    # ── Container detection ───────────────────────────────────────────────
    is_container = False
    if os_name == "linux":
        if os.path.exists("/.dockerenv"):
            is_container = True
        else:
            try:
                with open("/proc/1/cgroup") as f:
                    if "docker" in f.read():
                        is_container = True
            except OSError:
                pass

    # ── Tool probing ──────────────────────────────────────────────────────
    capabilities: dict[str, dict] = {}

    if os_name == "windows":
        win_tools = [
            "powershell", "wevtutil", "sfc", "chkdsk", "sc",
            "docker", "podman", "tailscale",
        ]
        for tool in win_tools:
            try:
                r = subprocess.run(
                    ["where", tool],
                    capture_output=True, timeout=5,
                )
                capabilities[tool] = {"available": r.returncode == 0}
            except Exception:
                capabilities[tool] = {"available": False}
    else:
        unix_tools = [
            "docker", "podman", "systemctl", "rc-service",
            "apt", "dnf", "apk", "pacman",
            "certbot", "zfs", "btrfs", "tailscale",
            "iptables", "nftables", "logrotate", "fstrim",
            "ip", "ifconfig", "kill", "shutdown",
            "journalctl", "mdadm",
        ]
        for tool in unix_tools:
            capabilities[tool] = {"available": shutil.which(tool) is not None}

    # Get versions for key tools
    _version_cmds = {
        "docker": ["docker", "--version"],
        "tailscale": ["tailscale", "version"],
    }
    for tool, cmd in _version_cmds.items():
        if capabilities.get(tool, {}).get("available"):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    capabilities[tool]["version"] = r.stdout.strip().split("\n")[0]
            except Exception:
                pass

    return {
        "os": os_name,
        "distro": distro,
        "distro_version": distro_version,
        "kernel": kernel,
        "init_system": init_system,
        "is_wsl": is_wsl,
        "is_container": is_container,
        "capabilities": capabilities,
    }


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


def _pty_find_restricted_user() -> str | None:
    """Find a non-root user to drop to for operator sessions (Linux)."""
    import pwd
    for name in ("noba-agent", "noba", "nobody"):
        try:
            pwd.getpwnam(name)
            return name
        except KeyError:
            continue
    return None


def _pty_open(session_id: str, ws_send, cols: int = 80, rows: int = 24,
              role: str = "admin") -> dict:
    """Open a PTY shell session. Operators get a restricted shell."""
    with _pty_lock:
        if session_id in _pty_sessions:
            return {"type": "pty_error", "session": session_id, "error": "Session already exists"}

    is_restricted = role != "admin"

    if _PLATFORM == "windows":
        # Windows: PowerShell with Constrained Language Mode for operators
        shell_cmd = ["powershell.exe", "-NoProfile"]
        if is_restricted:
            # Constrained Language Mode blocks .NET, COM, unsafe operations
            shell_cmd = [
                "powershell.exe", "-NoProfile", "-Command",
                "$ExecutionContext.SessionState.LanguageMode = 'ConstrainedLanguage'; "
                "Write-Host '[ Restricted session — ConstrainedLanguage mode ]' -ForegroundColor Yellow; "
                "Set-Location $env:USERPROFILE; "
                "powershell.exe -NoProfile",
            ]
        try:
            proc = subprocess.Popen(
                shell_cmd,
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

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLUMNS"] = str(cols)
        env["LINES"] = str(rows)

        if is_restricted:
            restricted_user = _pty_find_restricted_user()
            if restricted_user:
                # Drop to restricted user via su
                shell_cmd = ["su", "-", restricted_user, "-s", "/bin/bash"]
                env["HOME"] = f"/home/{restricted_user}" if restricted_user != "nobody" else "/tmp"
            else:
                # No restricted user available — use bash with rbash
                shell_cmd = ["/bin/bash", "--restricted"]
                env["PS1"] = "[restricted]\\u@\\h:\\w\\$ "
        else:
            shell = os.environ.get("SHELL", "/bin/bash")
            shell_cmd = [shell]

        try:
            proc = subprocess.Popen(
                shell_cmd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
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
                # ── Drain RDP frame queue before blocking on recv ──────────────
                # The capture thread (if active) enqueues frames here so that only
                # the main loop touches the socket, avoiding concurrent send races.
                while True:
                    try:
                        frame = _rdp_frame_queue.get_nowait()
                        ws.send_json(frame)
                    except _queue.Empty:
                        break

                # Use a short timeout when RDP is active so frames are sent promptly
                recv_timeout = 0.2 if _rdp_active.is_set() else 30
                msg = ws.recv_json(timeout=recv_timeout)
                if msg is None:
                    if not _rdp_active.is_set():
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
                    pty_role = msg.get("role", "operator")
                    result = _pty_open(sid, lambda m: ws.send_json(m), cols, rows, role=pty_role)
                    ws.send_json(result)

                elif msg.get("type") == "pty_input":
                    _pty_input(msg.get("session", ""), msg.get("data", ""))

                elif msg.get("type") == "pty_resize":
                    _pty_resize(msg.get("session", ""), msg.get("cols", 80), msg.get("rows", 24))

                elif msg.get("type") == "pty_close":
                    _pty_close(msg.get("session", ""))
                    ws.send_json({"type": "pty_exit", "session": msg.get("session", ""), "code": 0})

                elif msg.get("type") == "rdp_start":
                    _rdp_start(
                        quality=int(msg.get("quality", 70)),
                        fps=int(msg.get("fps", 5)),
                    )

                elif msg.get("type") == "rdp_stop":
                    _rdp_stop()

                elif msg.get("type") == "rdp_input":
                    _rdp_inject_input(msg)

                elif msg.get("type") == "pong":
                    pass

        except Exception as exc:
            _rdp_stop()
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

            # Attach capability manifest periodically (every 6h or on first report)
            global _last_capability_probe
            now_ts = time.time()
            if now_ts - _last_capability_probe > _CAPABILITY_PROBE_INTERVAL:
                try:
                    metrics["_capabilities"] = probe_capabilities()
                    _last_capability_probe = now_ts
                except Exception as e:
                    print(f"[agent] Capability probe failed: {e}", file=sys.stderr)

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
