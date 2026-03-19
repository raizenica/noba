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
import json
import os
import platform
import socket
import sys
import time
import urllib.request
import urllib.error

# ── Configuration ────────────────────────────────────────────────────────────
VERSION = "1.1.0"
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

# Commands the agent is allowed to execute. Anything not here is rejected.
ALLOWED_COMMANDS = {
    "exec":             "_cmd_exec",
    "restart_service":  "_cmd_restart_service",
    "update_agent":     "_cmd_update_agent",
    "set_interval":     "_cmd_set_interval",
    "ping":             "_cmd_ping",
}

# Safety: max output size, max execution time
_CMD_MAX_OUTPUT = 4096
_CMD_TIMEOUT = 30


def _cmd_exec(params: dict, ctx: dict) -> dict:
    """Execute a shell command (with safety limits)."""
    import subprocess
    cmd = params.get("command", "")
    if not cmd:
        return {"status": "error", "error": "No command provided"}
    timeout = min(params.get("timeout", _CMD_TIMEOUT), 60)
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
    import subprocess
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
    import subprocess
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
    import subprocess
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
    import subprocess
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
    import subprocess
    for cmd in [
        ["apt", "list", "--upgradable"],
        ["dnf", "check-update"],
        ["pkg", "version", "-vIL="],
    ]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            lines = [l for l in result.stdout.strip().split("\n") if l.strip() and "Listing" not in l]
            return {"status": "ok", "count": len(lines), "stdout": "\n".join(lines[:50])}
        except FileNotFoundError:
            continue
    return {"status": "error", "error": "No supported package manager found"}


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
    }
    for cmd in commands[:10]:  # Max 10 commands per cycle
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
