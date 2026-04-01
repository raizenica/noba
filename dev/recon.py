#!/usr/bin/env python3
"""Network reconnaissance tool for homelab infrastructure via Tailscale.

Discovers Tailscale nodes, scans ports, identifies services, and probes APIs
to produce a comprehensive map of the homelab.

Usage:
    python dev/recon.py                    # Full discovery
    python dev/recon.py --node my-server    # Scan specific node
    python dev/recon.py --deep             # Include k3s NodePort scan
    python dev/recon.py --json             # JSON output for programmatic use
    python dev/recon.py --timeout 1        # Custom timeout per port (seconds)
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required.  pip install httpx", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

class C:
    """ANSI colour codes — disabled when stdout is not a tty or --json."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    @classmethod
    def disable(cls) -> None:
        for attr in ("RESET", "BOLD", "DIM", "RED", "GREEN", "YELLOW",
                      "BLUE", "MAGENTA", "CYAN", "WHITE"):
            setattr(cls, attr, "")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class TailscaleNode:
    hostname: str
    ip: str
    os: str
    online: bool
    is_self: bool
    tags: list[str] = field(default_factory=list)


@dataclass
class ServiceInfo:
    port: int
    open: bool
    name: str = ""
    title: str = ""
    api_status: str = ""
    api_data: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Well-known ports and their expected service names
# ---------------------------------------------------------------------------

COMMON_PORTS: dict[int, str] = {
    22:    "SSH",
    53:    "DNS",
    80:    "HTTP",
    81:    "Caddy Admin",
    443:   "HTTPS",
    1883:  "MQTT",
    3000:  "Grafana",
    3001:  "Uptime Kuma",
    5000:  "Synology/Registry",
    5001:  "Synology HTTPS/Registry",
    5353:  "mDNS",
    6767:  "Bazarr",
    7878:  "Radarr",
    8080:  "HTTP Alt",
    8081:  "Nginx Proxy Manager",
    8086:  "InfluxDB",
    8096:  "Jellyfin/Emby",
    8123:  "Home Assistant",
    8443:  "HTTPS Alt",
    8686:  "Lidarr",
    8787:  "Readarr",
    8989:  "Sonarr",
    9000:  "Portainer",
    9001:  "MQTT WebSocket",
    9090:  "Prometheus",
    9443:  "Portainer HTTPS",
    9696:  "Prowlarr",
    32400: "Plex",
}

# HTTP(S) ports where we should attempt title / service identification
HTTP_PORTS: set[int] = {
    80, 81, 443, 3000, 3001, 5000, 5001, 6767, 7878, 8080, 8081, 8086,
    8096, 8123, 8443, 8686, 8787, 8989, 9000, 9090, 9443, 9696, 32400,
}

# ---------------------------------------------------------------------------
# Known API endpoints for service probing
# ---------------------------------------------------------------------------

API_PROBES: dict[str, list[dict[str, str]]] = {
    # label → list of {path, description}
    "Scrutiny":       [{"path": "/api/health", "desc": "health"},
                       {"path": "/api/summary", "desc": "summary"}],
    "Pi-hole":        [{"path": "/api/stats/summary", "desc": "stats"}],
    "TrueNAS":        [{"path": "/api/v2.0/system/version", "desc": "version"}],
    "Plex":           [{"path": "/identity", "desc": "identity"}],
    "Home Assistant":  [{"path": "/api/", "desc": "API root"}],
    "Sonarr":         [{"path": "/api/v3/system/status", "desc": "status"}],
    "Radarr":         [{"path": "/api/v3/system/status", "desc": "status"}],
    "Prowlarr":       [{"path": "/api/v3/system/status", "desc": "status"}],
    "Bazarr":         [{"path": "/api/system/status", "desc": "status"}],
    "Readarr":        [{"path": "/api/v1/system/status", "desc": "status"}],
    "Lidarr":         [{"path": "/api/v1/system/status", "desc": "status"}],
    "Uptime Kuma":    [{"path": "/api/status-page/heartbeat", "desc": "heartbeat"}],
    "Jellyfin":       [{"path": "/System/Info/Public", "desc": "public info"}],
    "Portainer":      [{"path": "/api/system/status", "desc": "status"}],
    "Prometheus":     [{"path": "/-/healthy", "desc": "health"}],
    "InfluxDB":       [{"path": "/health", "desc": "health"}],
    "Grafana":        [{"path": "/api/health", "desc": "health"}],
}

# Map common <title> substrings or header hints to a canonical service name
SERVICE_SIGNATURES: list[tuple[str, str]] = [
    ("sonarr", "Sonarr"),
    ("radarr", "Radarr"),
    ("prowlarr", "Prowlarr"),
    ("bazarr", "Bazarr"),
    ("readarr", "Readarr"),
    ("lidarr", "Lidarr"),
    ("plex", "Plex"),
    ("jellyfin", "Jellyfin"),
    ("emby", "Emby"),
    ("home assistant", "Home Assistant"),
    ("homeassistant", "Home Assistant"),
    ("grafana", "Grafana"),
    ("uptime kuma", "Uptime Kuma"),
    ("portainer", "Portainer"),
    ("pi-hole", "Pi-hole"),
    ("pihole", "Pi-hole"),
    ("scrutiny", "Scrutiny"),
    ("truenas", "TrueNAS"),
    ("freenas", "TrueNAS"),
    ("proxmox", "Proxmox"),
    ("unifi", "UniFi"),
    ("adguard", "AdGuard Home"),
    ("nginx proxy manager", "Nginx Proxy Manager"),
    ("synology", "Synology DSM"),
    ("prometheus", "Prometheus"),
    ("influxdb", "InfluxDB"),
    ("cockpit", "Cockpit"),
    ("webmin", "Webmin"),
    ("authentik", "Authentik"),
    ("authelia", "Authelia"),
    ("nextcloud", "Nextcloud"),
    ("gitea", "Gitea"),
    ("forgejo", "Forgejo"),
    ("immich", "Immich"),
    ("paperless", "Paperless-ngx"),
    ("vaultwarden", "Vaultwarden"),
    ("homepage", "Homepage"),
    ("dashy", "Dashy"),
    ("homarr", "Homarr"),
    ("organizr", "Organizr"),
    ("tautulli", "Tautulli"),
    ("overseerr", "Overseerr"),
    ("calibre", "Calibre-Web"),
    ("komga", "Komga"),
    ("kavita", "Kavita"),
    ("actual", "Actual Budget"),
    ("mealie", "Mealie"),
]


# ---------------------------------------------------------------------------
# Tailscale discovery
# ---------------------------------------------------------------------------

def discover_tailscale_nodes() -> list[TailscaleNode]:
    """Parse `tailscale status` to discover all nodes on the tailnet."""
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        print(f"{C.RED}ERROR: tailscale CLI not found in PATH{C.RESET}",
              file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print(f"{C.RED}ERROR: tailscale status timed out{C.RESET}",
              file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        # Fall back to text parsing
        return _parse_tailscale_text()

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return _parse_tailscale_text()

    nodes: list[TailscaleNode] = []
    self_ip = data.get("Self", {}).get("TailscaleIPs", [""])[0]
    self_host = data.get("Self", {}).get("HostName", "self")
    self_os = data.get("Self", {}).get("OS", "")

    nodes.append(TailscaleNode(
        hostname=self_host,
        ip=self_ip,
        os=self_os,
        online=True,
        is_self=True,
    ))

    for _peer_id, peer in data.get("Peer", {}).items():
        ts_ips = peer.get("TailscaleIPs", [])
        ip = ts_ips[0] if ts_ips else ""
        hostname = peer.get("HostName", peer.get("DNSName", "unknown"))
        # Strip trailing dot from DNS name
        hostname = hostname.rstrip(".")
        os_name = peer.get("OS", "")
        online = peer.get("Online", False)
        tags = peer.get("Tags", []) or []

        nodes.append(TailscaleNode(
            hostname=hostname,
            ip=ip,
            os=os_name,
            online=online,
            is_self=False,
            tags=tags,
        ))

    return nodes


def _parse_tailscale_text() -> list[TailscaleNode]:
    """Fallback: parse plain `tailscale status` text output."""
    try:
        result = subprocess.run(
            ["tailscale", "status"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    nodes: list[TailscaleNode] = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        ip = parts[0]
        hostname = parts[1]
        # The status field is typically the 4th or later column
        # Format: IP  HOSTNAME  OS  STATUS  ...
        os_name = parts[2] if len(parts) > 2 else ""
        online = any(tok in line for tok in ("-", "active;"))
        nodes.append(TailscaleNode(
            hostname=hostname, ip=ip, os=os_name,
            online=online, is_self=False,
        ))

    return nodes


# ---------------------------------------------------------------------------
# Port scanning
# ---------------------------------------------------------------------------

def scan_port(ip: str, port: int, timeout: float = 2.0) -> bool:
    """Check whether a single TCP port is open."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((ip, port)) == 0
    except (OSError, socket.error):
        return False


def scan_node(ip: str, ports: list[int], timeout: float = 2.0,
              max_workers: int = 40) -> list[int]:
    """Scan a list of ports on a given IP, return list of open ports."""
    open_ports: list[int] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(scan_port, ip, port, timeout): port
                   for port in ports}
        for future in as_completed(futures):
            port = futures[future]
            try:
                if future.result():
                    open_ports.append(port)
            except Exception:
                pass
    return sorted(open_ports)


# ---------------------------------------------------------------------------
# Service identification via HTTP
# ---------------------------------------------------------------------------

def identify_http_service(ip: str, port: int,
                          timeout: float = 5.0) -> tuple[str, str]:
    """Try to identify an HTTP service by its title and response.

    Returns (service_name, page_title).
    """
    schemes = ["https"] if port in (443, 8443, 9443, 5001) else ["http"]
    if port in (8080, 80, 3000, 3001):
        schemes = ["http", "https"]
    elif port not in (443, 8443, 9443, 5001):
        schemes = ["http", "https"]

    for scheme in schemes:
        url = f"{scheme}://{ip}:{port}/"
        try:
            with httpx.Client(verify=False, timeout=timeout,
                              follow_redirects=True,
                              limits=httpx.Limits(
                                  max_connections=5,
                                  max_keepalive_connections=2)) as client:
                resp = client.get(url)
                body = resp.text[:8000]  # only need the head
                title = _extract_title(body)

                # Try to identify service from title, headers, body
                service = _match_service(title, body, resp.headers)
                return service, title
        except Exception:
            continue

    return "", ""


def _extract_title(html: str) -> str:
    """Pull <title>...</title> from HTML."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html,
                  re.IGNORECASE | re.DOTALL)
    if m:
        title = m.group(1).strip()
        # Collapse whitespace
        return re.sub(r"\s+", " ", title)[:120]
    return ""


def _match_service(title: str, body: str, headers: httpx.Headers) -> str:
    """Try to match a service name from response data."""
    combined = (title + " " + body[:2000]).lower()

    # Check server header
    server = headers.get("server", "").lower()
    if "plex" in server:
        return "Plex"

    # Check known signatures
    for pattern, name in SERVICE_SIGNATURES:
        if pattern in combined:
            return name

    # Check X-Application-Name or similar
    app_name = headers.get("x-application-name", "")
    if app_name:
        return app_name

    return ""


# ---------------------------------------------------------------------------
# API probing
# ---------------------------------------------------------------------------

def probe_apis(ip: str, port: int, service: str,
               timeout: float = 5.0) -> list[dict[str, Any]]:
    """For a known service, try its known API endpoints.

    Returns a list of {endpoint, status_code, ok, snippet}.
    """
    probes = API_PROBES.get(service, [])
    if not probes:
        return []

    scheme = "https" if port in (443, 8443, 9443, 5001) else "http"
    results: list[dict[str, Any]] = []

    for probe in probes:
        url = f"{scheme}://{ip}:{port}{probe['path']}"
        entry: dict[str, Any] = {
            "endpoint": probe["path"],
            "description": probe["desc"],
            "ok": False,
            "status_code": None,
            "snippet": "",
        }
        try:
            with httpx.Client(verify=False, timeout=timeout,
                              follow_redirects=True,
                              limits=httpx.Limits(
                                  max_connections=5,
                                  max_keepalive_connections=2)) as client:
                resp = client.get(url)
                entry["status_code"] = resp.status_code
                entry["ok"] = 200 <= resp.status_code < 400
                # Capture a snippet of the response
                text = resp.text[:500]
                try:
                    parsed = json.loads(resp.text[:2000])
                    entry["snippet"] = _summarise_json(parsed)
                except (json.JSONDecodeError, ValueError):
                    entry["snippet"] = text[:200]
        except Exception as exc:
            entry["snippet"] = f"error: {type(exc).__name__}"

        results.append(entry)

    return results


def _summarise_json(data: Any, max_keys: int = 8) -> str:
    """Create a compact summary of a JSON response."""
    if isinstance(data, dict):
        keys = list(data.keys())[:max_keys]
        parts = []
        for k in keys:
            v = data[k]
            if isinstance(v, (dict, list)):
                parts.append(f"{k}: ({type(v).__name__})")
            else:
                sv = str(v)[:60]
                parts.append(f"{k}: {sv}")
        suffix = f" +{len(data) - max_keys} more" if len(data) > max_keys else ""
        return "{" + ", ".join(parts) + suffix + "}"
    elif isinstance(data, list):
        return f"[{len(data)} items]"
    return str(data)[:200]


# ---------------------------------------------------------------------------
# NodePort scanning for k3s
# ---------------------------------------------------------------------------

def scan_nodeports(ip: str, start: int = 30000, end: int = 30200,
                   timeout: float = 2.0) -> list[ServiceInfo]:
    """Scan the k3s NodePort range and try to identify services."""
    ports = list(range(start, end + 1))
    open_ports = scan_node(ip, ports, timeout=timeout, max_workers=60)

    services: list[ServiceInfo] = []
    for port in open_ports:
        svc_name, title = identify_http_service(ip, port, timeout=4.0)
        services.append(ServiceInfo(
            port=port, open=True,
            name=svc_name or "unknown",
            title=title,
        ))

    return services


# ---------------------------------------------------------------------------
# Full scan orchestration
# ---------------------------------------------------------------------------

def scan_full(nodes: list[TailscaleNode],
              target_hostname: str | None = None,
              deep: bool = False,
              timeout: float = 2.0) -> dict[str, Any]:
    """Run the full reconnaissance pipeline."""
    report: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "nodes": [],
    }

    targets = nodes
    if target_hostname:
        targets = [n for n in nodes
                   if target_hostname.lower() in n.hostname.lower()]
        if not targets:
            print(f"{C.RED}No node matching '{target_hostname}' found.{C.RESET}",
                  file=sys.stderr)
            print(f"{C.DIM}Available nodes: "
                  f"{', '.join(n.hostname for n in nodes)}{C.RESET}",
                  file=sys.stderr)
            sys.exit(1)

    total_nodes = len(targets)
    for idx, node in enumerate(targets, 1):
        node_report: dict[str, Any] = {
            "hostname": node.hostname,
            "ip": node.ip,
            "os": node.os,
            "online": node.online,
            "is_self": node.is_self,
            "tags": node.tags,
            "services": [],
            "nodeports": [],
        }

        if not node.online:
            _print_node_header(node, idx, total_nodes)
            print(f"  {C.DIM}(offline — skipping){C.RESET}")
            report["nodes"].append(node_report)
            continue

        if not node.ip:
            _print_node_header(node, idx, total_nodes)
            print(f"  {C.DIM}(no IP — skipping){C.RESET}")
            report["nodes"].append(node_report)
            continue

        _print_node_header(node, idx, total_nodes)

        # Port scan
        ports = sorted(COMMON_PORTS.keys())
        print(f"  {C.DIM}Scanning {len(ports)} common ports...{C.RESET}",
              end="", flush=True)
        open_ports = scan_node(node.ip, ports, timeout=timeout)
        print(f" {C.GREEN}{len(open_ports)} open{C.RESET}")

        # Service identification and API probing
        for port in open_ports:
            svc = ServiceInfo(port=port, open=True,
                              name=COMMON_PORTS.get(port, ""))

            if port in HTTP_PORTS:
                identified, title = identify_http_service(
                    node.ip, port, timeout=5.0)
                if identified:
                    svc.name = identified
                svc.title = title

            # API probing
            if svc.name and svc.name in API_PROBES:
                api_results = probe_apis(node.ip, port, svc.name, timeout=5.0)
                healthy = [r for r in api_results if r["ok"]]
                svc.api_status = (f"{len(healthy)}/{len(api_results)} OK"
                                  if api_results else "")
                svc.api_data = api_results if api_results else None

            _print_service(svc)
            node_report["services"].append({
                "port": svc.port,
                "name": svc.name,
                "title": svc.title,
                "api_status": svc.api_status,
                "api_data": svc.api_data,
            })

        # NodePort scan
        if deep:
            print(f"  {C.DIM}Scanning k3s NodePorts 30000-30200...{C.RESET}",
                  end="", flush=True)
            np_services = scan_nodeports(node.ip, timeout=timeout)
            print(f" {C.GREEN}{len(np_services)} open{C.RESET}")
            for svc in np_services:
                _print_service(svc)
                node_report["nodeports"].append({
                    "port": svc.port,
                    "name": svc.name,
                    "title": svc.title,
                })

        report["nodes"].append(node_report)

    return report


# ---------------------------------------------------------------------------
# Terminal output helpers
# ---------------------------------------------------------------------------

def _print_node_header(node: TailscaleNode, idx: int, total: int) -> None:
    status_icon = f"{C.GREEN}ONLINE{C.RESET}" if node.online else f"{C.RED}OFFLINE{C.RESET}"
    self_tag = f" {C.CYAN}(self){C.RESET}" if node.is_self else ""
    os_tag = f" {C.DIM}[{node.os}]{C.RESET}" if node.os else ""
    print(f"\n{C.BOLD}{C.BLUE}[{idx}/{total}] {node.hostname}{C.RESET}"
          f"  {node.ip}  {status_icon}{self_tag}{os_tag}")


def _print_service(svc: ServiceInfo) -> None:
    port_str = f"{C.YELLOW}{svc.port:>5}{C.RESET}"
    name_str = svc.name or "unknown"
    title_str = f"  {C.DIM}\"{svc.title}\"{C.RESET}" if svc.title else ""
    api_str = ""
    if svc.api_status:
        colour = C.GREEN if svc.api_status.startswith(
            svc.api_status.split("/")[1].split()[0]) else C.YELLOW
        # Simpler: green if all OK
        parts = svc.api_status.split("/")
        ok_count = int(parts[0])
        total = int(parts[1].split()[0])
        colour = C.GREEN if ok_count == total else C.YELLOW
        if ok_count == 0:
            colour = C.RED
        api_str = f"  API: {colour}{svc.api_status}{C.RESET}"
    print(f"  {port_str}  {C.WHITE}{name_str:<22}{C.RESET}{title_str}{api_str}")


def print_summary(report: dict[str, Any]) -> None:
    """Print a summary block at the end."""
    print(f"\n{C.BOLD}{'=' * 60}{C.RESET}")
    print(f"{C.BOLD}RECON SUMMARY{C.RESET}")
    print(f"{'=' * 60}")

    total_nodes = len(report["nodes"])
    online_nodes = sum(1 for n in report["nodes"] if n["online"])
    total_services = sum(len(n["services"]) for n in report["nodes"])
    total_nodeports = sum(len(n.get("nodeports", [])) for n in report["nodes"])

    print(f"  Nodes discovered:  {C.CYAN}{total_nodes}{C.RESET}"
          f"  ({C.GREEN}{online_nodes} online{C.RESET},"
          f" {C.RED}{total_nodes - online_nodes} offline{C.RESET})")
    print(f"  Open ports found:  {C.CYAN}{total_services}{C.RESET}")
    if total_nodeports:
        print(f"  k3s NodePorts:     {C.CYAN}{total_nodeports}{C.RESET}")

    # Services with successful API probes
    api_ok = 0
    api_total = 0
    for node in report["nodes"]:
        for svc in node["services"]:
            if svc.get("api_data"):
                api_total += 1
                ok = sum(1 for r in svc["api_data"] if r["ok"])
                if ok > 0:
                    api_ok += 1

    if api_total:
        print(f"  APIs responding:   {C.GREEN}{api_ok}{C.RESET}"
              f"/{api_total} services")

    # List identified services per node
    print(f"\n{C.BOLD}Service Map:{C.RESET}")
    for node in report["nodes"]:
        if not node["services"] and not node.get("nodeports"):
            continue
        print(f"  {C.BLUE}{node['hostname']}{C.RESET} ({node['ip']})")
        for svc in node["services"]:
            name = svc["name"] or f"port {svc['port']}"
            detail = ""
            if svc["title"]:
                detail = f' - "{svc["title"]}"'
            if svc["api_status"]:
                detail += f" [API: {svc['api_status']}]"
            print(f"    {C.YELLOW}{svc['port']:>5}{C.RESET}  {name}{detail}")
        for svc in node.get("nodeports", []):
            name = svc["name"] or f"NodePort {svc['port']}"
            detail = f' - "{svc["title"]}"' if svc.get("title") else ""
            print(f"    {C.MAGENTA}{svc['port']:>5}{C.RESET}  {name}{detail}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Homelab network reconnaissance via Tailscale",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s                    Full discovery of all Tailscale nodes
  %(prog)s --node my-server   Scan only nodes matching 'my-server'
  %(prog)s --deep             Include k3s NodePort range (30000-30200)
  %(prog)s --json             Output as JSON for programmatic use
  %(prog)s --timeout 1        Faster scan with 1s timeout per port
""",
    )
    parser.add_argument("--node", "-n", type=str, default=None,
                        help="Scan only nodes matching this hostname (substring match)")
    parser.add_argument("--deep", "-d", action="store_true",
                        help="Include k3s NodePort scan (30000-30200)")
    parser.add_argument("--json", "-j", action="store_true",
                        help="Output as JSON instead of coloured text")
    parser.add_argument("--timeout", "-t", type=float, default=2.0,
                        help="TCP connect timeout per port in seconds (default: 2)")
    args = parser.parse_args()

    # Disable colours for JSON output or non-tty
    if args.json or not sys.stdout.isatty():
        C.disable()

    if not args.json:
        print(f"{C.BOLD}{C.CYAN}NOBA Homelab Recon{C.RESET}")
        print(f"{C.DIM}Discovering Tailscale nodes...{C.RESET}", flush=True)

    # Step 1: discover nodes
    nodes = discover_tailscale_nodes()
    if not nodes:
        print(f"{C.RED}No Tailscale nodes found. Is Tailscale running?{C.RESET}",
              file=sys.stderr)
        sys.exit(1)

    if not args.json:
        online = sum(1 for n in nodes if n.online)
        print(f"{C.GREEN}Found {len(nodes)} nodes "
              f"({online} online){C.RESET}")

    # Step 2: scan
    report = scan_full(nodes, target_hostname=args.node,
                       deep=args.deep, timeout=args.timeout)

    # Step 3: output
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_summary(report)


if __name__ == "__main__":
    main()
