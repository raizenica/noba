# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""All _cmd_* command handlers and execute_commands() dispatcher."""
from __future__ import annotations

import hashlib
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

from utils import (
    _PLATFORM,
    _HAS_SYSTEMD,
    _BACKUP_DIR,
    _CMD_MAX_OUTPUT,
    _detect_container_runtime,
    _safe_path,
    _safe_run,
    _read_proc,
)

# VERSION is read from __main__ at runtime via ctx or module reference
_CMD_TIMEOUT = 30


def _cmd_exec(params: dict, ctx: dict) -> dict:
    """Execute a shell command. Streams output line-by-line if WebSocket callback present."""
    cmd = params.get("command", "")
    if not cmd:
        return {"status": "error", "error": "No command provided"}
    timeout = min(params.get("timeout", _CMD_TIMEOUT), 60)
    cmd_id = ctx.get("_current_cmd_id", "")
    ws_send = ctx.get("_ws_send")

    import shlex
    if _PLATFORM == "windows":
        shell_cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
    else:
        try:
            shell_cmd = shlex.split(cmd)
        except ValueError:
            return {"status": "error", "error": "Invalid command syntax"}

    if ws_send and cmd_id:
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
    """Download updated agent.pyz from the server and restart."""
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
        # Validate it's a Python zipapp (starts with shebang) or Python source
        if not new_code.startswith(b"#!/") and b"def main" not in new_code:
            return {"status": "error", "error": "Invalid agent code"}
        # Use sys.argv[0] (resolves to agent.pyz on disk), NOT __file__ (inside zip)
        agent_path = os.path.abspath(sys.argv[0])
        tmp_path = agent_path + ".new"
        with open(tmp_path, "wb") as f:
            f.write(new_code)
        os.replace(tmp_path, agent_path)
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
    # Import VERSION from __main__ at call time
    import importlib
    try:
        mm = importlib.import_module("__main__")
        version = getattr(mm, "VERSION", "unknown")
    except Exception:
        version = "unknown"
    return {"status": "ok", "pong": int(time.time()), "version": version}


def _cmd_get_logs(params: dict, _ctx: dict) -> dict:
    """Fetch recent logs (journalctl on Linux, wevtutil on Windows)."""
    unit = params.get("unit", "")
    lines = min(params.get("lines", 50), 200)
    priority = params.get("priority", "")

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
    mode = params.get("mode", "ping")
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

_active_streams: dict[str, subprocess.Popen] = {}
_active_streams_lock = threading.Lock()
_stream_buffers: dict[str, list[str]] = {}
_stream_buffers_lock = threading.Lock()
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
                if len(buf) > _STREAM_BUFFER_MAX:
                    _stream_buffers[cmd_id] = buf[-_STREAM_BUFFER_MAX:]
    except (OSError, ValueError):
        pass
    finally:
        with _active_streams_lock:
            _active_streams.pop(cmd_id, None)


def _cmd_follow_logs(params: dict, ctx: dict) -> dict:
    """Start streaming journalctl -f output."""
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
    """Stop a running log stream."""
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
        _stream_buffers[stream_id] = []

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


# ── System commands ──────────────────────────────────────────────────────────

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


# ── Service commands ─────────────────────────────────────────────────────────

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
        cmd = ["sudo", "-n", "service", service, action]
    else:
        return {"status": "error", "error": f"Unsupported platform: {_PLATFORM}"}
    out = _safe_run(cmd, timeout=30)
    return {"status": "ok", "service": service, "action": action, "output": out}


# ── Network commands ─────────────────────────────────────────────────────────

_prev_net_readings: dict[str, dict] = {}
_prev_net_readings_lock = threading.Lock()


def _cmd_network_stats(_params: dict, _ctx: dict) -> dict:
    """Return per-interface traffic stats and per-process TCP connections."""
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

    connections: list[dict] = []
    top_talkers_map: dict[str, int] = {}
    try:
        result = subprocess.run(
            ["ss", "-tnp"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 6:
                continue
            state = parts[0]
            local = parts[3]
            remote = parts[4]
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

    top_talkers = sorted(
        [{"process": p, "connections": c} for p, c in top_talkers_map.items()],
        key=lambda x: x["connections"],
        reverse=True,
    )[:20]

    return {
        "status": "ok",
        "interfaces": interfaces,
        "connections": connections[:200],
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
    if rtype in ("A", "AAAA"):
        family = socket.AF_INET if rtype == "A" else socket.AF_INET6
        try:
            results = socket.getaddrinfo(host, None, family)
            addrs = list({r[4][0] for r in results})
            return {"status": "ok", "host": host, "type": rtype, "addresses": addrs}
        except socket.gaierror as e:
            return {"status": "error", "error": str(e)}
    out = _safe_run(["nslookup", f"-type={rtype}", host], timeout=10)
    return {"status": "ok", "host": host, "type": rtype, "output": out}


# ── File commands ────────────────────────────────────────────────────────────

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
    if os.path.exists(path):
        try:
            os.makedirs(_BACKUP_DIR, exist_ok=True)
            bname = os.path.basename(path) + f".{int(time.time())}.bak"
            bpath = os.path.join(_BACKUP_DIR, bname)
            import shutil
            shutil.copy2(path, bpath)
        except Exception:
            pass
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


# ── User commands ────────────────────────────────────────────────────────────

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


# ── Container commands ───────────────────────────────────────────────────────

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


# ── Agent management ─────────────────────────────────────────────────────────

def _cmd_uninstall_agent(params: dict, _ctx: dict) -> dict:
    """Uninstall the NOBA agent: stop service, remove files."""
    if not params.get("confirm"):
        return {"status": "error", "error": "Set confirm=true to uninstall"}
    steps = []
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
    # Use sys.argv[0] (resolves to agent.pyz on disk), NOT __file__ (inside zip)
    agent_path = os.path.abspath(sys.argv[0])
    try:
        os.remove(agent_path)
        steps.append(f"Removed {agent_path}")
    except OSError:
        steps.append(f"Could not remove {agent_path}")
    # Import DEFAULT_CONFIG from __main__
    import importlib
    try:
        mm = importlib.import_module("__main__")
        config_path = getattr(mm, "DEFAULT_CONFIG", "/etc/noba-agent.yaml")
    except Exception:
        config_path = "/etc/noba-agent.yaml"
    if os.path.exists(config_path):
        try:
            os.remove(config_path)
            steps.append(f"Removed {config_path}")
        except OSError:
            pass
    return {"status": "ok", "steps": steps}


# ── File transfer commands ───────────────────────────────────────────────────

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
    max_size = 50 * 1024 * 1024
    if file_size > max_size:
        return {"status": "error", "error": f"File too large: {file_size} > {max_size}"}

    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(65536)
            if not block:
                break
            h.update(block)
    checksum = f"sha256:{h.hexdigest()}"

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

            if expected_checksum.startswith("sha256:"):
                actual = hashlib.sha256(data).hexdigest()
                expected = expected_checksum.split(":", 1)[1]
                if actual != expected:
                    return {"status": "error", "error": f"Checksum mismatch: {actual} != {expected}"}

            if os.path.exists(dest_path):
                try:
                    os.makedirs(_BACKUP_DIR, exist_ok=True)
                    bname = os.path.basename(dest_path) + f".{int(time.time())}.bak"
                    shutil.copy2(dest_path, os.path.join(_BACKUP_DIR, bname))
                except Exception:
                    pass

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
    import urllib.parse as _up

    url = params.get("url", "")
    if not url:
        return {"status": "error", "error": "No URL provided"}
    method = params.get("method", "GET").upper()
    if method not in ("GET", "HEAD"):
        method = "GET"
    timeout = min(params.get("timeout", 10), 30)

    import importlib
    try:
        mm = importlib.import_module("__main__")
        version = getattr(mm, "VERSION", "unknown")
    except Exception:
        version = "unknown"

    result: dict = {"status": "ok"}
    start = time.time()

    try:
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", f"NOBA-Agent/{version}")
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

    parsed = _up.urlparse(url)
    if parsed.scheme == "https":
        try:
            hostname = parsed.hostname or ""
            port = parsed.port or 443
            ctx_ssl = ssl.create_default_context()
            ctx_ssl.minimum_version = ssl.TLSVersion.TLSv1_2
            with ctx_ssl.wrap_socket(
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
                    expiry_dt = datetime.datetime.strptime(
                        not_after, "%b %d %H:%M:%S %Y %Z"
                    )
                    days_left = (expiry_dt - datetime.datetime.utcnow()).days
                    result["cert_expiry_days"] = days_left
                issuer = dict(x[0] for x in cert.get("issuer", ()))
                result["cert_issuer"] = issuer.get("organizationName", "")
        except Exception:
            pass

    return result


def _cmd_discover_services(_params: dict, _ctx: dict) -> dict:
    """Discover running services, listening ports, and established connections."""
    services: list[dict] = []

    try:
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) < 6:
                    continue
                local_addr = parts[3]
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
                proc_name = ""
                for p in parts:
                    if "users:" in p:
                        start = p.find('(("')
                        if start >= 0:
                            end = p.find('"', start + 3)
                            if end >= 0:
                                proc_name = p[start + 3:end]
                        break
                svc_name = proc_name or f"port-{port}"
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
        pass

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
                local_port_str = local_addr.rsplit(":", 1)[-1] if ":" in local_addr else ""
                try:
                    local_port = int(local_port_str)
                except (ValueError, TypeError):
                    continue
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


def _cmd_network_discover(_params: dict, _ctx: dict) -> dict:
    """Discover devices on the local network via ARP + mDNS + port probing."""
    devices: dict[str, dict] = {}

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

    try:
        result = subprocess.run(
            ["avahi-browse", "-apt", "--no-db-lookup", "-t"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
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
        pass
    except Exception:
        pass

    for dev in devices.values():
        if not dev["hostname"]:
            try:
                host, _, _ = socket.gethostbyaddr(dev["ip"])
                dev["hostname"] = host
            except (socket.herror, socket.gaierror, OSError):
                pass

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


def _cmd_security_scan(_params: dict, _ctx: dict) -> dict:
    """Scan the host for common security misconfigurations."""
    findings: list[dict] = []
    _check_ssh_config(findings)
    _check_firewall(findings)
    _check_auto_updates(findings)
    _check_sensitive_files(findings)
    _check_insecure_ports(findings)
    score = _calculate_security_score(findings)
    return {"status": "ok", "score": score, "findings": findings}


def _check_ssh_config(findings: list[dict]) -> None:
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
    active: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        if len(parts) == 2:
            active[parts[0]] = parts[1]

    root_login = active.get("permitrootlogin", "")
    if root_login in ("yes", ""):
        findings.append({
            "severity": "high",
            "category": "ssh",
            "description": "SSH PermitRootLogin is enabled (or defaults to yes)",
            "remediation": "Set 'PermitRootLogin no' or 'PermitRootLogin prohibit-password' in /etc/ssh/sshd_config.",
        })

    pass_auth = active.get("passwordauthentication", "")
    if pass_auth == "yes":
        findings.append({
            "severity": "medium",
            "category": "ssh",
            "description": "SSH PasswordAuthentication is enabled — prefer key-based auth",
            "remediation": "Set 'PasswordAuthentication no' in /etc/ssh/sshd_config and use SSH keys.",
        })
    elif pass_auth == "":
        findings.append({
            "severity": "low",
            "category": "ssh",
            "description": "SSH PasswordAuthentication not explicitly set — default may allow passwords",
            "remediation": "Explicitly set 'PasswordAuthentication no' in /etc/ssh/sshd_config.",
        })


def _check_firewall(findings: list[dict]) -> None:
    fw_active = False

    try:
        r = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and "active" in r.stdout.lower():
            fw_active = True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if not fw_active:
        try:
            r = subprocess.run(["nft", "list", "tables"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                fw_active = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    if not fw_active:
        try:
            r = subprocess.run(["iptables", "-L", "-n"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
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
    auto_update = False

    if os.path.isfile("/etc/apt/apt.conf.d/20auto-upgrades"):
        try:
            with open("/etc/apt/apt.conf.d/20auto-upgrades") as f:
                content = f.read().lower()
            if 'unattended-upgrade "1"' in content or "unattended-upgrade \"1\"" in content:
                auto_update = True
        except (PermissionError, OSError):
            pass

    if not auto_update and os.path.isfile("/etc/dnf/automatic.conf"):
        try:
            with open("/etc/dnf/automatic.conf") as f:
                content = f.read().lower()
            if "apply_updates = yes" in content or "apply_updates=yes" in content:
                auto_update = True
        except (PermissionError, OSError):
            pass

    if not auto_update and os.path.isfile("/etc/yum/yum-cron.conf"):
        try:
            with open("/etc/yum/yum-cron.conf") as f:
                content = f.read().lower()
            if "apply_updates = yes" in content or "apply_updates=yes" in content:
                auto_update = True
        except (PermissionError, OSError):
            pass

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
    insecure_ports = {
        21: ("FTP", "high"),
        23: ("Telnet", "high"),
        69: ("TFTP", "medium"),
        161: ("SNMP", "medium"),
        445: ("SMB", "medium"),
    }
    listening: set[int] = set()

    for proto_file in ("/proc/net/tcp", "/proc/net/tcp6"):
        if not os.path.isfile(proto_file):
            continue
        try:
            with open(proto_file) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    if parts[3] != "0A":
                        continue
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
    deductions = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = f.get("severity", "low")
        if sev == "high":
            deductions["high"] += 20
        elif sev == "medium":
            deductions["medium"] += 10
        else:
            deductions["low"] += 5

    total = min(deductions["high"], 60) + min(deductions["medium"], 30) + min(deductions["low"], 15)
    return max(0, 100 - total)


def _cmd_verify_backup(params: dict, _ctx: dict) -> dict:
    """Verify a backup file's integrity."""
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


# ── Capability probing ───────────────────────────────────────────────────────

_last_capability_probe: float = 0
_CAPABILITY_PROBE_INTERVAL = 21600  # 6 hours


def probe_capabilities() -> dict:
    """Probe the host for OS info and available tools."""
    import shutil

    os_name = platform.system().lower()

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

    is_wsl = False
    if os_name == "linux":
        try:
            with open("/proc/version") as f:
                pv = f.read().lower()
                is_wsl = "microsoft" in pv or "wsl" in pv
        except OSError:
            pass

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


def _cmd_refresh_capabilities(_params: dict, _ctx: dict) -> dict:
    """Force a capability re-probe on the next report cycle."""
    global _last_capability_probe
    _last_capability_probe = 0
    return {"status": "ok", "message": "Capabilities will be re-probed on next report"}


# ── HTTP report ──────────────────────────────────────────────────────────────

def report(server: str, api_key: str, metrics: dict) -> tuple[bool, dict]:
    """Send metrics to NOBA server. Returns (success, response_body)."""
    import json
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


# ── Command dispatcher ───────────────────────────────────────────────────────

def execute_commands(commands: list, ctx: dict) -> list:
    """Execute a list of commands and return results."""
    results = []
    handlers = {
        "exec": _cmd_exec,
        "restart_service": _cmd_restart_service,
        "update_agent": _cmd_update_agent,
        "set_interval": _cmd_set_interval,
        "ping": _cmd_ping,
        "get_logs": _cmd_get_logs,
        "check_service": _cmd_check_service,
        "network_test": _cmd_network_test,
        "package_updates": _cmd_package_updates,
        "system_info": _cmd_system_info,
        "disk_usage": _cmd_disk_usage,
        "reboot": _cmd_reboot,
        "process_kill": _cmd_process_kill,
        "list_services": _cmd_list_services,
        "service_control": _cmd_service_control,
        "network_stats": _cmd_network_stats,
        "network_config": _cmd_network_config,
        "dns_lookup": _cmd_dns_lookup,
        "file_read": _cmd_file_read,
        "file_write": _cmd_file_write,
        "file_delete": _cmd_file_delete,
        "file_list": _cmd_file_list,
        "file_checksum": _cmd_file_checksum,
        "file_stat": _cmd_file_stat,
        "list_users": _cmd_list_users,
        "user_manage": _cmd_user_manage,
        "container_list": _cmd_container_list,
        "container_control": _cmd_container_control,
        "container_logs": _cmd_container_logs,
        "file_transfer": _cmd_file_transfer,
        "file_push": _cmd_file_push,
        "uninstall_agent": _cmd_uninstall_agent,
        "endpoint_check": _cmd_endpoint_check,
        "follow_logs": _cmd_follow_logs,
        "stop_stream": _cmd_stop_stream,
        "get_stream": _cmd_get_stream,
        "discover_services": _cmd_discover_services,
        "network_discover": _cmd_network_discover,
        "security_scan": _cmd_security_scan,
        "verify_backup": _cmd_verify_backup,
        "refresh_capabilities": _cmd_refresh_capabilities,
    }
    for cmd in commands[:20]:
        cmd_type = cmd.get("type", "")
        cmd_id = cmd.get("id", "")
        params = cmd.get("params", {})
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
