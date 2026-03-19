"""Noba – External service integrations (Plex, Pi-hole, Kuma, TrueNAS, etc.)."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from .config import VERSION

logger = logging.getLogger("noba")


def _http_get(url: str, headers: dict | None = None, timeout: int = 4) -> dict | list:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ── Pi-hole ───────────────────────────────────────────────────────────────────
def get_pihole(url: str, token: str) -> dict | None:
    if not url:
        return None
    base = (url if url.startswith("http") else "http://" + url).rstrip("/").replace("/admin", "")
    hdrs = {"User-Agent": f"noba-web/{VERSION}", "Accept": "application/json"}
    if token:
        hdrs["sid"] = token

    # v6 API
    try:
        data = _http_get(f"{base}/api/stats/summary", hdrs)
        return {
            "queries": data.get("queries", {}).get("total", 0),
            "blocked": data.get("ads", {}).get("blocked", 0),
            "percent": round(data.get("ads", {}).get("percentage", 0.0), 1),
            "status":  data.get("gravity", {}).get("status", "unknown"),
            "domains": f"{data.get('gravity', {}).get('domains_being_blocked', 0):,}",
        }
    except Exception:
        pass

    # v5 legacy API
    try:
        auth_suffix = f"&auth={token}" if token else ""
        data = _http_get(f"{base}/admin/api.php?summaryRaw{auth_suffix}")
        return {
            "queries": data.get("dns_queries_today", 0),
            "blocked": data.get("ads_blocked_today", 0),
            "percent": round(data.get("ads_percentage_today", 0), 1),
            "status":  data.get("status", "enabled"),
            "domains": f"{data.get('domains_being_blocked', 0):,}",
        }
    except Exception:
        return None


# ── Plex ──────────────────────────────────────────────────────────────────────
def get_plex(url: str, token: str) -> dict | None:
    if not url or not token:
        return None
    base = url.rstrip("/")
    hdrs = {"Accept": "application/json", "X-Plex-Token": token}
    try:
        data1    = _http_get(f"{base}/status/sessions", hdrs, timeout=3)
        sessions = data1.get("MediaContainer", {}).get("size", 0)
        data2      = _http_get(f"{base}/activities", hdrs, timeout=3)
        activities = data2.get("MediaContainer", {}).get("size", 0)
        return {"sessions": sessions, "activities": activities, "status": "online"}
    except Exception:
        return {"sessions": 0, "activities": 0, "status": "offline"}


# ── Uptime Kuma ───────────────────────────────────────────────────────────────
def get_kuma(url: str) -> list:
    if not url:
        return []
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/metrics")
        with urllib.request.urlopen(req, timeout=3) as r:
            lines = r.read().decode().splitlines()
        monitors = []
        for line in lines:
            if line.startswith("monitor_status{"):
                m = re.search(r'monitor_name="([^"]+)"', line)
                if m:
                    val = int(float(line.split()[-1]))
                    monitors.append({
                        "name":   m.group(1),
                        "status": "Up" if val == 1 else ("Pending" if val == 2 else "Down"),
                    })
        return monitors
    except Exception:
        return []


# ── TrueNAS ───────────────────────────────────────────────────────────────────
def get_truenas(url: str, key: str) -> dict | None:
    if not url or not key:
        return None
    hdrs   = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    base   = url.rstrip("/")
    result = {"apps": [], "alerts": [], "vms": [], "status": "offline"}
    try:
        for app in _http_get(f"{base}/api/v2.0/app", hdrs):
            result["apps"].append({"name": app.get("name", "?"), "state": app.get("state", "?")})
        for alert in _http_get(f"{base}/api/v2.0/alert/list", hdrs):
            if alert.get("level") in ("WARNING", "CRITICAL") and not alert.get("dismissed"):
                result["alerts"].append({
                    "level": alert.get("level"),
                    "text":  alert.get("formatted", "Unknown Alert"),
                })
        try:
            for vm in _http_get(f"{base}/api/v2.0/vm", hdrs):
                result["vms"].append({
                    "id":    vm.get("id"),
                    "name":  vm.get("name", "?"),
                    "state": vm.get("status", {}).get("state", "UNKNOWN"),
                })
        except Exception as e:
            logger.warning("TrueNAS VM fetch: %s", e)
        result["status"] = "online"
    except Exception:
        pass
    return result


# ── Servarr (Radarr / Sonarr) ─────────────────────────────────────────────────
def get_servarr(url: str, key: str) -> dict | None:
    if not url or not key:
        return None
    hdrs = {"X-Api-Key": key, "Accept": "application/json"}
    try:
        data = _http_get(f"{url.rstrip('/')}/api/v3/queue", hdrs, timeout=3)
        return {"queue_count": data.get("totalRecords", 0), "status": "online"}
    except Exception:
        return {"queue_count": 0, "status": "offline"}


# ── qBittorrent ───────────────────────────────────────────────────────────────
def get_qbit(url: str, user: str, password: str) -> dict | None:
    if not url or not user:
        return None
    base   = url.rstrip("/")
    result = {"dl_speed": 0, "up_speed": 0, "active_torrents": 0, "status": "offline"}
    try:
        data   = urllib.parse.urlencode({"username": user, "password": password}).encode()
        req1   = urllib.request.Request(f"{base}/api/v2/auth/login", data=data)
        with urllib.request.urlopen(req1, timeout=4) as r1:
            cookie = r1.headers.get("Set-Cookie")
        if not cookie:
            return result
        req2 = urllib.request.Request(f"{base}/api/v2/sync/maindata")
        req2.add_header("Cookie", cookie)
        with urllib.request.urlopen(req2, timeout=4) as r2:
            d = json.loads(r2.read().decode())
        state = d.get("server_state", {})
        result.update({
            "dl_speed":       state.get("dl_info_speed", 0),
            "up_speed":       state.get("up_info_speed", 0),
            "active_torrents": sum(
                1 for t in d.get("torrents", {}).values()
                if t.get("state") in ("downloading", "stalledDL", "metaDL")
            ),
            "status": "online",
        })
    except Exception:
        pass
    return result


# ── Proxmox VE ────────────────────────────────────────────────────────────────
def get_proxmox(url: str, user: str, token_name: str, token_value: str) -> dict | None:
    if not url or not user or not token_name or not token_value:
        return None
    base      = url.rstrip("/")
    user_full = user if "@" in user else f"{user}@pam"
    auth_hdr  = f"PVEAPIToken={user_full}!{token_name}={token_value}"
    hdrs      = {"Authorization": auth_hdr, "Accept": "application/json"}
    result    = {"nodes": [], "vms": [], "status": "offline"}
    try:
        nodes_data = _http_get(f"{base}/api2/json/nodes", hdrs, timeout=5).get("data", [])
        for node in nodes_data:
            node_name = node.get("node", "unknown")
            maxmem    = node.get("maxmem", 1) or 1
            result["nodes"].append({
                "name":        node_name,
                "status":      node.get("status", "unknown"),
                "cpu":         round(node.get("cpu", 0) * 100, 1),
                "mem_percent": round(node.get("mem", 0) / maxmem * 100, 1),
            })
            for ep, vtype in (("qemu", "qemu"), ("lxc", "lxc")):
                try:
                    for vm in _http_get(
                        f"{base}/api2/json/nodes/{node_name}/{ep}", hdrs, timeout=4
                    ).get("data", [])[:30]:
                        mmem = vm.get("maxmem", 1) or 1
                        result["vms"].append({
                            "vmid":        vm.get("vmid"),
                            "name":        vm.get("name", f"{vtype}-{vm.get('vmid')}"),
                            "type":        vtype,
                            "node":        node_name,
                            "status":      vm.get("status", "unknown"),
                            "cpu":         round(vm.get("cpu", 0) * 100, 1),
                            "mem_percent": round(vm.get("mem", 0) / mmem * 100, 1),
                        })
                except Exception:
                    pass
        result["status"] = "online"
    except Exception:
        pass
    return result
