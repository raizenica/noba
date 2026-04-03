# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Network interfaces, connections, monitoring, VPN."""
from __future__ import annotations

import logging
import threading
import time

import psutil

from .util import _fmt_bytes, _run, validate_ip


logger = logging.getLogger("noba")

# ── Network I/O ───────────────────────────────────────────────────────────────
_net_prev: tuple | None = None
_net_prev_t: float | None = None
_net_lock = threading.Lock()

# ── Per-NIC tracking ──────────────────────────────────────────────────────────
_pernic_prev: dict = {}
_pernic_ts: float = 0.0
_pernic_lock = threading.Lock()

# ── Device presence ───────────────────────────────────────────────────────────
_device_presence: dict[str, dict] = {}
_device_presence_lock = threading.Lock()


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


def get_network_connections() -> list[dict]:
    """Get active network connections with process info."""
    connections = []
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status != "ESTABLISHED":
                continue
            try:
                proc_name = psutil.Process(conn.pid).name() if conn.pid else ""
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                proc_name = ""
            local = f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else ""
            remote = f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else ""
            connections.append({
                "pid": conn.pid,
                "process": proc_name[:20],
                "local": local,
                "remote": remote,
                "status": conn.status,
            })
    except (psutil.AccessDenied, Exception):
        pass
    return connections[:200]


def get_listening_ports() -> list[dict]:
    """Get all listening ports with process info."""
    ports = []
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status != "LISTEN":
                continue
            try:
                proc_name = psutil.Process(conn.pid).name() if conn.pid else ""
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                proc_name = ""
            ports.append({
                "port": conn.laddr.port if conn.laddr else 0,
                "address": conn.laddr.ip if conn.laddr else "",
                "pid": conn.pid,
                "process": proc_name[:20],
            })
    except (psutil.AccessDenied, Exception):
        pass
    # Deduplicate by port
    seen = set()
    unique = []
    for p in sorted(ports, key=lambda x: x["port"]):
        if p["port"] not in seen:
            seen.add(p["port"])
            unique.append(p)
    return unique


# ── Ping ──────────────────────────────────────────────────────────────────────
def ping_host(ip: str) -> tuple[str, bool, int]:
    import subprocess as _sp
    ip = ip.strip()
    if not validate_ip(ip):
        return ip, False, 0
    try:
        t0 = time.time()
        r  = _sp.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True, timeout=2.5)
        return ip, r.returncode == 0, round((time.time() - t0) * 1000)
    except Exception:
        return ip, False, 0


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


# ── Certificate expiry ────────────────────────────────────────────────────────
def check_cert_expiry(hosts: list[str]) -> list[dict]:
    import ssl
    import socket as _socket
    from datetime import datetime, timezone
    results = []
    for host in hosts:
        try:
            ctx = ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
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


# ── Tailscale ────────────────────────────────────────────────────────────────
def get_tailscale_status() -> dict | None:
    """Get Tailscale network status via CLI."""
    try:
        raw = _run(["tailscale", "status", "--json"], timeout=10,
                   cache_key="tailscale_status", cache_ttl=30)
        if not raw:
            return None
        import json as _json  # noqa: PLC0415
        data = _json.loads(raw)
        self_node = data.get("Self", {})
        peers_raw = data.get("Peer", {})
        peers = []
        for _key, p in peers_raw.items():
            ips = p.get("TailscaleIPs", [])
            host = p.get("HostName", "")
            if not host or host == "localhost":
                dns = p.get("DNSName", "")
                host = dns.split(".")[0] if dns else host or "unknown"
            peers.append({
                "hostname": host,
                "ip": ips[0] if ips else "",
                "os": p.get("OS", ""),
                "online": p.get("Online", False),
                "active": p.get("Active", False),
                "direct": "Direct" in str(p.get("CurAddr", "")),
                "curAddr": p.get("CurAddr", ""),
                "rxBytes": p.get("RxBytes", 0),
                "txBytes": p.get("TxBytes", 0),
                "lastSeen": p.get("LastSeen", ""),
                "exitNode": p.get("ExitNode", False),
                "subnets": [r for r in p.get("AllowedIPs", [])
                           if not r.endswith("/32") and not r.endswith("/128")],
                "tags": p.get("Tags", []),
            })
        self_ips = self_node.get("TailscaleIPs", [])
        online_count = sum(1 for p in peers if p["online"])
        return {
            "self": {
                "hostname": self_node.get("HostName", ""),
                "ip": self_ips[0] if self_ips else "",
                "os": self_node.get("OS", ""),
                "relay": self_node.get("Relay", ""),
            },
            "peers": peers,
            "onlineCount": online_count,
            "totalCount": len(peers),
            "tailnet": data.get("MagicDNSSuffix", ""),
        }
    except (OSError, ValueError):
        return None
