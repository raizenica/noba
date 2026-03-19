"""Noba – External service integrations (Plex, Pi-hole, Kuma, TrueNAS, etc.)."""
from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta

import httpx

from .config import VERSION

_POOL_CONNECTIONS = int(os.environ.get("NOBA_POOL_CONNECTIONS", 20))
_POOL_KEEPALIVE = int(os.environ.get("NOBA_POOL_KEEPALIVE", 10))

logger = logging.getLogger("noba")

# Shared client with connection pooling and sensible defaults.
_client = httpx.Client(
    timeout=4,
    follow_redirects=True,
    limits=httpx.Limits(
        max_connections=_POOL_CONNECTIONS,
        max_keepalive_connections=_POOL_KEEPALIVE,
        keepalive_expiry=30,
    ),
)


def _http_get(url: str, headers: dict | None = None, timeout: int = 4) -> dict | list:
    r = _client.get(url, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


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
    except (httpx.HTTPError, KeyError, ValueError):
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
    except (httpx.HTTPError, KeyError, ValueError):
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
    except (httpx.HTTPError, KeyError, ValueError):
        return {"sessions": 0, "activities": 0, "status": "offline"}


# ── Uptime Kuma ───────────────────────────────────────────────────────────────
def get_kuma(url: str) -> list:
    if not url:
        return []
    try:
        r = _client.get(f"{url.rstrip('/')}/metrics", timeout=3)
        r.raise_for_status()
        lines = r.text.splitlines()
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
    except (httpx.HTTPError, ValueError):
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
        except (httpx.HTTPError, KeyError, ValueError) as e:
            logger.warning("TrueNAS VM fetch: %s", e)
        result["status"] = "online"
    except (httpx.HTTPError, KeyError, ValueError):
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
    except (httpx.HTTPError, KeyError, ValueError):
        return {"queue_count": 0, "status": "offline"}


# ── qBittorrent ───────────────────────────────────────────────────────────────
def get_qbit(url: str, user: str, password: str) -> dict | None:
    if not url or not user:
        return None
    base   = url.rstrip("/")
    result = {"dl_speed": 0, "up_speed": 0, "active_torrents": 0, "status": "offline"}
    try:
        # Use a separate client to avoid cookie jar contamination on the shared _client
        with httpx.Client(timeout=4) as qclient:
            r1 = qclient.post(
                f"{base}/api/v2/auth/login",
                data={"username": user, "password": password},
            )
        cookie = r1.headers.get("set-cookie")
        if not cookie:
            return result
        r2 = _client.get(
            f"{base}/api/v2/sync/maindata",
            headers={"Cookie": cookie},
            timeout=4,
        )
        d = r2.json()
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
    except (httpx.HTTPError, KeyError, ValueError):
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
                except (httpx.HTTPError, KeyError, ValueError):
                    pass
        result["status"] = "online"
    except (httpx.HTTPError, KeyError, ValueError):
        pass
    return result


# ── AdGuard Home ─────────────────────────────────────────────────────────────
def get_adguard(url: str, user: str, password: str):
    if not url:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {}
        if user:
            import base64
            cred = base64.b64encode(f"{user}:{password}".encode()).decode()
            hdrs["Authorization"] = f"Basic {cred}"
        data = _http_get(f"{base}/control/stats", hdrs)
        if not data:
            return None
        queries = data.get("num_dns_queries", 0)
        blocked = data.get("num_blocked_filtering", 0)
        pct = round(blocked / queries * 100, 1) if queries else 0
        return {"queries": queries, "blocked": blocked, "percent": pct, "status": "enabled"}
    except (httpx.HTTPError, KeyError, ValueError, ZeroDivisionError):
        return None


# ── Jellyfin ─────────────────────────────────────────────────────────────────
def get_jellyfin(url: str, key: str):
    if not url or not key:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"X-Emby-Token": key}
        sessions = _http_get(f"{base}/Sessions", hdrs)
        counts = _http_get(f"{base}/Items/Counts", hdrs)
        playing = sum(1 for s in (sessions or []) if s.get("NowPlayingItem"))
        return {
            "streams": playing,
            "movies": (counts or {}).get("MovieCount", 0),
            "series": (counts or {}).get("SeriesCount", 0),
            "episodes": (counts or {}).get("EpisodeCount", 0),
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return {"streams": 0, "status": "offline"}


# ── Home Assistant ───────────────────────────────────────────────────────────
def get_hass(url: str, token: str):
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Bearer {token}"}
        states = _http_get(f"{base}/api/states", hdrs)
        if not isinstance(states, list):
            return None
        domains = {}
        for e in states:
            d = e.get("entity_id", "").split(".")[0]
            domains[d] = domains.get(d, 0) + 1
        lights_on = sum(1 for e in states if e.get("entity_id", "").startswith("light.") and e.get("state") == "on")
        switches_on = sum(1 for e in states if e.get("entity_id", "").startswith("switch.") and e.get("state") == "on")
        automations = domains.get("automation", 0)
        return {
            "entities": len(states), "automations": automations,
            "lights_on": lights_on, "switches_on": switches_on,
            "domains": domains, "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def get_hass_entities(url: str, token: str, entity_filter: str = "") -> dict | None:
    """Fetch detailed Home Assistant entity states with optional domain filter."""
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Bearer {token}"}
        states = _http_get(f"{base}/api/states", hdrs)
        if not isinstance(states, list):
            return None
        entities = []
        for e in states:
            eid = e.get("entity_id", "")
            domain = eid.split(".")[0] if "." in eid else ""
            if entity_filter and domain != entity_filter:
                continue
            state = e.get("state", "unknown")
            attrs = e.get("attributes", {})
            entity = {
                "entity_id": eid,
                "domain": domain,
                "state": state,
                "name": attrs.get("friendly_name", eid),
                "icon": attrs.get("icon", ""),
            }
            # Add domain-specific attributes
            if domain == "sensor":
                entity["unit"] = attrs.get("unit_of_measurement", "")
                entity["device_class"] = attrs.get("device_class", "")
            elif domain == "light":
                entity["brightness"] = attrs.get("brightness")
                entity["color_temp"] = attrs.get("color_temp")
                entity["rgb_color"] = attrs.get("rgb_color")
            elif domain == "climate":
                entity["temperature"] = attrs.get("temperature")
                entity["current_temperature"] = attrs.get("current_temperature")
                entity["hvac_action"] = attrs.get("hvac_action", "")
            elif domain == "media_player":
                entity["media_title"] = attrs.get("media_title", "")
                entity["source"] = attrs.get("source", "")
            elif domain in ("binary_sensor", "switch", "input_boolean"):
                entity["device_class"] = attrs.get("device_class", "")
            elif domain == "cover":
                entity["current_position"] = attrs.get("current_position")
            if "battery_level" in attrs:
                entity["battery"] = attrs.get("battery_level")
            entities.append(entity)
        return {"entities": entities[:500], "total": len(states)}
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def get_hass_services(url: str, token: str) -> list | None:
    """Fetch available Home Assistant services."""
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Bearer {token}"}
        services = _http_get(f"{base}/api/services", hdrs)
        if not isinstance(services, list):
            return None
        result = []
        for svc in services:
            domain = svc.get("domain", "")
            for name, info in svc.get("services", {}).items():
                result.append({
                    "domain": domain,
                    "service": name,
                    "name": info.get("name", name),
                    "description": info.get("description", "")[:100],
                })
        return result
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── UniFi Controller ─────────────────────────────────────────────────────────
def get_unifi(url: str, user: str, password: str, site: str = "default"):
    if not url or not user:
        return None
    try:
        base = url.rstrip("/")
        site = site or "default"
        # Login — use a separate client to avoid cookie jar contamination
        with httpx.Client(timeout=4, verify=False) as uclient:
            login_r = uclient.post(f"{base}/api/login", json={"username": user, "password": password}, headers={"Referer": base})
            if login_r.status_code != 200:
                return None
            cookies = login_r.cookies
            # Devices
            dev_r = uclient.get(f"{base}/api/s/{site}/stat/device", cookies=cookies)
            devices = dev_r.json().get("data", []) if dev_r.status_code == 200 else []
            # Clients
            sta_r = uclient.get(f"{base}/api/s/{site}/stat/sta", cookies=cookies)
            clients = sta_r.json().get("data", []) if sta_r.status_code == 200 else []
            adopted = sum(1 for d in devices if d.get("adopted"))
            # Logout — release the session on the controller
            try:
                uclient.post(f"{base}/api/logout", cookies=cookies)
            except Exception:
                pass
        return {
            "devices": len(devices), "adopted": adopted,
            "clients": len(clients), "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Speedtest Tracker ────────────────────────────────────────────────────────
def get_speedtest(url: str):
    if not url:
        return None
    try:
        base = url.rstrip("/")
        data = _http_get(f"{base}/api/speedtest/latest")
        if not data or not data.get("data"):
            return None
        r = data["data"]
        return {
            "download": round(r.get("download", 0) / 1_000_000, 1),
            "upload": round(r.get("upload", 0) / 1_000_000, 1),
            "ping": round(r.get("ping", 0), 1),
            "server": r.get("server_name", ""),
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None


# ── Tautulli ─────────────────────────────────────────────────────────────────
def get_tautulli(url: str, key: str) -> dict | None:
    if not url or not key:
        return None
    try:
        base = url.rstrip("/")
        activity = _http_get(
            f"{base}/api/v2?apikey={key}&cmd=get_activity", timeout=4,
        )
        resp = activity.get("response", {}).get("data", {})
        streams = resp.get("stream_count", 0)
        direct_play = resp.get("stream_count_direct_play", 0)
        transcode = resp.get("stream_count_transcode", 0)

        top_users_data = _http_get(
            f"{base}/api/v2?apikey={key}&cmd=get_home_stats&stat_id=top_users&stats_count=5",
            timeout=4,
        )
        top_resp = top_users_data.get("response", {}).get("data", [])
        top_users = []
        # top_resp may be a list of stat groups or a flat list
        rows = top_resp if isinstance(top_resp, list) else []
        for item in rows:
            if isinstance(item, dict) and "rows" in item:
                # stat group format
                for row in item["rows"]:
                    top_users.append({
                        "user": row.get("friendly_name", row.get("user", "?")),
                        "total_plays": int(row.get("total_plays", 0)),
                    })
                break
            elif isinstance(item, dict) and "friendly_name" in item:
                top_users.append({
                    "user": item.get("friendly_name", "?"),
                    "total_plays": int(item.get("total_plays", 0)),
                })

        return {
            "streams": int(streams),
            "stream_count_direct_play": int(direct_play),
            "stream_count_transcode": int(transcode),
            "top_users": top_users,
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Overseerr ────────────────────────────────────────────────────────────────
def get_overseerr(url: str, key: str) -> dict | None:
    if not url or not key:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"X-Api-Key": key}
        data = _http_get(f"{base}/api/v1/request/count", hdrs)
        return {
            "pending": data.get("pending", 0),
            "approved": data.get("approved", 0),
            "available": data.get("available", 0),
            "total": data.get("total", 0),
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Prowlarr ─────────────────────────────────────────────────────────────────
def get_prowlarr(url: str, key: str) -> dict | None:
    if not url or not key:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"X-Api-Key": key}
        data = _http_get(f"{base}/api/v1/indexer", hdrs)
        return {
            "indexer_count": len(data) if isinstance(data, list) else 0,
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Servarr Extended (Radarr / Sonarr — missing + disk) ──────────────────────
def get_servarr_extended(url: str, key: str, service: str = "radarr") -> dict | None:
    if not url or not key:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"X-Api-Key": key, "Accept": "application/json"}

        queue = _http_get(f"{base}/api/v3/queue", hdrs, timeout=3)
        queue_count = queue.get("totalRecords", 0)

        missing_data = _http_get(
            f"{base}/api/v3/wanted/missing?pageSize=1", hdrs, timeout=3,
        )
        missing = missing_data.get("totalRecords", 0)

        rootfolders = _http_get(f"{base}/api/v3/rootfolder", hdrs, timeout=3)
        total_space = 0.0
        free_space = 0.0
        for rf in (rootfolders if isinstance(rootfolders, list) else []):
            total_space += rf.get("totalSpace", 0)
            free_space += rf.get("freeSpace", 0)

        return {
            "queue_count": queue_count,
            "missing": missing,
            "total_space_gb": round(total_space / (1024 ** 3), 1),
            "free_space_gb": round(free_space / (1024 ** 3), 1),
            "status": "online",
            "service": service,
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Servarr Calendar (Radarr / Sonarr) ───────────────────────────────────────
def get_servarr_calendar(url: str, key: str, days: int = 7) -> list | None:
    if not url or not key:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"X-Api-Key": key, "Accept": "application/json"}
        today = date.today().isoformat()
        end = (date.today() + timedelta(days=days)).isoformat()
        data = _http_get(f"{base}/api/v3/calendar?start={today}&end={end}", hdrs, timeout=4)
        items = []
        for entry in (data if isinstance(data, list) else []):
            title = entry.get("title", "")
            # Sonarr entries have 'series' and 'episodeFile'; Radarr have 'title'
            if "series" in entry:
                title = entry.get("series", {}).get("title", title)
                item_type = "episode"
                air_date = entry.get("airDateUtc", entry.get("airDate", ""))
            else:
                item_type = "movie"
                air_date = entry.get("inCinemas", entry.get("digitalRelease", entry.get("physicalRelease", "")))
            items.append({"title": title, "date": air_date, "type": item_type})
        return items
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Nextcloud ────────────────────────────────────────────────────────────────
def get_nextcloud(url: str, user: str, password: str) -> dict | None:
    if not url or not user:
        return None
    try:
        import base64
        base = url.rstrip("/")
        cred = base64.b64encode(f"{user}:{password}".encode()).decode()
        hdrs = {
            "Authorization": f"Basic {cred}",
            "OCS-APIREQUEST": "true",
        }
        data = _http_get(
            f"{base}/ocs/v2.php/apps/serverinfo/api/v1/info?format=json", hdrs,
        )
        ocs = data.get("ocs", {}).get("data", {})
        nc = ocs.get("nextcloud", {})
        storage = nc.get("storage", {})
        system = nc.get("system", {})
        active = ocs.get("activeUsers", {})
        return {
            "active_users": active.get("last5minutes", 0),
            "storage_total_gb": round(system.get("freespacealiased", system.get("mem_total", 0)) / (1024 ** 3), 1) if system.get("freespacealiased") else 0.0,
            "storage_free_gb": round(system.get("freespace", 0) / (1024 ** 3), 1),
            "num_files": storage.get("num_files", 0),
            "version": system.get("version", ""),
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Traefik ──────────────────────────────────────────────────────────────────
def get_traefik(url: str) -> dict | None:
    if not url:
        return None
    try:
        base = url.rstrip("/")
        routers = _http_get(f"{base}/api/http/routers")
        services = _http_get(f"{base}/api/http/services")
        router_list = routers if isinstance(routers, list) else []
        service_list = services if isinstance(services, list) else []
        errors = sum(
            1 for s in service_list
            if s.get("status") == "error" or s.get("serverStatus", {}) != {}
            and any(v == "DOWN" for v in s.get("serverStatus", {}).values())
        )
        return {
            "routers": len(router_list),
            "services": len(service_list),
            "errors": errors,
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Nginx Proxy Manager ─────────────────────────────────────────────────────
def get_npm(url: str, token: str) -> dict | None:
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Bearer {token}"}
        data = _http_get(f"{base}/api/nginx/proxy-hosts", hdrs)
        return {
            "proxy_hosts": len(data) if isinstance(data, list) else 0,
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Authentik ────────────────────────────────────────────────────────────────
def get_authentik(url: str, token: str) -> dict | None:
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Bearer {token}"}
        users_data = _http_get(f"{base}/api/v3/core/users/?page_size=1", hdrs)
        user_count = users_data.get("pagination", {}).get("count", 0)
        events_data = _http_get(
            f"{base}/api/v3/events/events/?action=login_failed&ordering=-created&page_size=10",
            hdrs,
        )
        failed_logins = events_data.get("pagination", {}).get("count", 0)
        return {
            "users": user_count,
            "failed_logins": failed_logins,
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Cloudflare ───────────────────────────────────────────────────────────────
def get_cloudflare(token: str, zone_id: str) -> dict | None:
    if not token or not zone_id:
        return None
    try:
        hdrs = {"Authorization": f"Bearer {token}"}
        data = _http_get(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/analytics/dashboard?since=-1440",
            hdrs, timeout=6,
        )
        totals = data.get("result", {}).get("totals", {})
        requests = totals.get("requests", {}).get("all", 0)
        threats = totals.get("threats", {}).get("all", 0)
        bandwidth = totals.get("bandwidth", {}).get("all", 0)
        cached = totals.get("bandwidth", {}).get("cached", 0)
        cache_ratio = round(cached / bandwidth * 100, 1) if bandwidth else 0.0
        return {
            "requests": requests,
            "threats": threats,
            "bandwidth_gb": round(bandwidth / (1024 ** 3), 2),
            "cache_hit_ratio": cache_ratio,
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── OpenMediaVault ───────────────────────────────────────────────────────────
def get_omv(url: str, user: str, password: str) -> dict | None:
    if not url or not user:
        return None
    try:
        base = url.rstrip("/")
        with httpx.Client(timeout=6, follow_redirects=True) as omv_client:
            # Authenticate via JSON-RPC
            login_resp = omv_client.post(
                f"{base}/rpc.php",
                json={
                    "service": "Session",
                    "method": "login",
                    "params": {"username": user, "password": password},
                },
            )
            login_resp.raise_for_status()

            # Fetch filesystems
            fs_resp = omv_client.post(
                f"{base}/rpc.php",
                json={
                    "service": "FileSystemMgmt",
                    "method": "enumerateFileSystems",
                    "params": {},
                },
            )
            fs_resp.raise_for_status()
            fs_data = fs_resp.json()

        filesystems = []
        items = fs_data.get("response", fs_data) if isinstance(fs_data, dict) else fs_data
        if isinstance(items, list):
            for fs in items:
                filesystems.append({
                    "device": fs.get("devicefile", ""),
                    "label": fs.get("label", fs.get("devicefile", "")),
                    "percent": float(fs.get("percentage", 0)),
                })
        return {"filesystems": filesystems, "status": "online"}
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── XCP-ng ───────────────────────────────────────────────────────────────────
def get_xcpng(url: str, user: str, password: str) -> dict | None:
    if not url or not user:
        return None
    try:
        base = url.rstrip("/")
        # Login
        login_payload = {
            "jsonrpc": "2.0", "method": "session.login_with_password",
            "params": [user, password], "id": 1,
        }
        r = _client.post(f"{base}/jsonrpc", json=login_payload, timeout=6)
        r.raise_for_status()
        session_id = r.json().get("result", "")

        # Get all VM records
        vm_payload = {
            "jsonrpc": "2.0", "method": "VM.get_all_records",
            "params": [session_id], "id": 2,
        }
        r2 = _client.post(f"{base}/jsonrpc", json=vm_payload, timeout=6)
        r2.raise_for_status()
        vms = r2.json().get("result", {})

        # Filter out control domains and templates
        real_vms = {
            k: v for k, v in vms.items()
            if not v.get("is_control_domain", False) and not v.get("is_a_template", False)
        }
        running = sum(
            1 for v in real_vms.values()
            if v.get("power_state") == "Running"
        )
        return {"vms": len(real_vms), "running_vms": running, "status": "online"}
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Homebridge ───────────────────────────────────────────────────────────────
def get_homebridge(url: str, user: str, password: str) -> dict | None:
    if not url or not user:
        return None
    try:
        base = url.rstrip("/")
        with httpx.Client(timeout=4, follow_redirects=True) as hb_client:
            login_r = hb_client.post(
                f"{base}/api/auth/login",
                json={"username": user, "password": password},
            )
            login_r.raise_for_status()
            token = login_r.json().get("access_token", "")
            hdrs = {"Authorization": f"Bearer {token}"}
            acc_r = hb_client.get(f"{base}/api/accessories", headers=hdrs)
            acc_r.raise_for_status()
            accessories = acc_r.json()

        acc_list = accessories if isinstance(accessories, list) else []
        battery_devices = []
        for acc in acc_list:
            svc_chars = acc.get("serviceCharacteristics", acc.get("values", {}))
            # Look for battery level in characteristics
            if isinstance(svc_chars, list):
                for ch in svc_chars:
                    if ch.get("type") == "BatteryLevel" or ch.get("description") == "Battery Level":
                        battery_devices.append({
                            "name": acc.get("serviceName", acc.get("name", "?")),
                            "battery": int(ch.get("value", 0)),
                        })
                        break
        return {
            "accessories": len(acc_list),
            "battery_devices": battery_devices,
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Zigbee2MQTT ──────────────────────────────────────────────────────────────
def get_z2m(url: str) -> dict | None:
    if not url:
        return None
    try:
        base = url.rstrip("/")
        devices = _http_get(f"{base}/api/devices")
        dev_list = devices if isinstance(devices, list) else []
        offline = sum(
            1 for d in dev_list
            if d.get("availability", {}).get("state") == "offline"
            or d.get("interview_completed") is False
        )
        low_battery = []
        for d in dev_list:
            battery = d.get("battery")
            if battery is not None and int(battery) < 20:
                low_battery.append({
                    "name": d.get("friendly_name", d.get("ieee_address", "?")),
                    "battery": int(battery),
                })
        return {
            "devices": len(dev_list),
            "offline": offline,
            "low_battery": low_battery,
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── ESPHome ──────────────────────────────────────────────────────────────────
def get_esphome(url: str) -> dict | None:
    if not url:
        return None
    try:
        base = url.rstrip("/")
        data = _http_get(f"{base}/devices")
        dev_list = data if isinstance(data, list) else []
        online = sum(
            1 for d in dev_list
            if d.get("status") == "ONLINE" or d.get("connected") is True
        )
        return {
            "nodes": len(dev_list),
            "online": online,
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── UniFi Protect ────────────────────────────────────────────────────────────
def get_unifi_protect(url: str, user: str, password: str) -> dict | None:
    if not url or not user:
        return None
    try:
        base = url.rstrip("/")
        with httpx.Client(timeout=6, verify=False, follow_redirects=True) as up_client:
            login_r = up_client.post(
                f"{base}/api/auth/login",
                json={"username": user, "password": password},
            )
            login_r.raise_for_status()
            cam_r = up_client.get(f"{base}/proxy/protect/api/cameras")
            cam_r.raise_for_status()
            cameras = cam_r.json()

        cam_list = cameras if isinstance(cameras, list) else []
        recording = sum(
            1 for c in cam_list
            if c.get("isRecording") or c.get("recordingSettings", {}).get("mode") != "never"
        )
        return {
            "cameras": len(cam_list),
            "recording": recording,
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── PiKVM ────────────────────────────────────────────────────────────────────
def get_pikvm(url: str, user: str, password: str) -> dict | None:
    if not url:
        return None
    try:
        import base64
        base = url.rstrip("/")
        cred = base64.b64encode(f"{user}:{password}".encode()).decode()
        hdrs = {"Authorization": f"Basic {cred}"}
        _http_get(f"{base}/api/info", hdrs)
        return {"online": True, "status": "online"}
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Kubernetes ───────────────────────────────────────────────────────────────
def get_k8s(url: str, token: str) -> dict | None:
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Bearer {token}"}
        r = httpx.get(f"{base}/api/v1/pods", headers=hdrs, timeout=6, verify=False)
        r.raise_for_status()
        data = r.json()
        pods = data.get("items", [])
        running = sum(
            1 for p in pods
            if p.get("status", {}).get("phase") == "Running"
        )
        namespaces = len({
            p.get("metadata", {}).get("namespace", "default") for p in pods
        })
        return {
            "pods": len(pods),
            "running": running,
            "namespaces": namespaces,
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Gitea ────────────────────────────────────────────────────────────────────
def get_gitea(url: str, token: str) -> dict | None:
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"token {token}"}
        # Use a raw request to get the x-total-count header
        r = _client.get(
            f"{base}/api/v1/repos/search?limit=1", headers=hdrs, timeout=4,
        )
        r.raise_for_status()
        total = int(r.headers.get("x-total-count", 0))
        if not total:
            body = r.json()
            if isinstance(body, dict):
                total = len(body.get("data", []))
            elif isinstance(body, list):
                total = len(body)

        return {"repos": total, "status": "online"}
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── GitLab ───────────────────────────────────────────────────────────────────
def get_gitlab(url: str, token: str) -> dict | None:
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"PRIVATE-TOKEN": token}
        r = _client.get(
            f"{base}/api/v4/projects?per_page=1", headers=hdrs, timeout=4,
        )
        r.raise_for_status()
        total = int(r.headers.get("x-total", 0))
        return {"projects": total, "status": "online"}
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── GitHub ───────────────────────────────────────────────────────────────────
def get_github(token: str) -> dict | None:
    if not token:
        return None
    try:
        hdrs = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        r = _client.get(
            "https://api.github.com/user/repos?per_page=5&sort=updated",
            headers=hdrs, timeout=4,
        )
        r.raise_for_status()
        repos = r.json()
        total = len(repos) if isinstance(repos, list) else 0
        return {"repos": total, "status": "online"}
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Paperless-ngx ────────────────────────────────────────────────────────────
def get_paperless(url: str, token: str) -> dict | None:
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Token {token}"}
        data = _http_get(f"{base}/api/documents/?page_size=1", hdrs)
        return {
            "documents": data.get("count", 0),
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Vaultwarden ──────────────────────────────────────────────────────────────
def get_vaultwarden(url: str, admin_token: str) -> dict | None:
    if not url or not admin_token:
        return None
    try:
        base = url.rstrip("/")
        r = _client.get(
            f"{base}/admin/users/overview",
            headers={"Cookie": f"VAULTWARDEN_ADMIN={admin_token}"},
            timeout=4,
        )
        r.raise_for_status()
        return {"status": "online"}
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── Energy Monitoring (Shelly) ───────────────────────────────────────────
def get_energy_shelly(urls: list[str]) -> list[dict]:
    """Query Shelly smart plugs/meters for power data."""
    results = []
    for entry in urls:
        parts = entry.split("|")
        url = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else url
        if not url:
            continue
        base = (url if url.startswith("http") else "http://" + url).rstrip("/")
        try:
            # Shelly Gen2 API
            data = _http_get(f"{base}/rpc/Switch.GetStatus?id=0", timeout=3)
            results.append({
                "name": name,
                "power_w": round(data.get("apower", 0), 1),
                "voltage_v": round(data.get("voltage", 0), 1),
                "current_a": round(data.get("current", 0), 3),
                "energy_wh": round(data.get("aenergy", {}).get("total", 0), 1),
                "on": data.get("output", False),
                "status": "online",
            })
        except (httpx.HTTPError, KeyError, ValueError):
            try:
                # Shelly Gen1 API fallback
                data = _http_get(f"{base}/status", timeout=3)
                meter = data.get("meters", [{}])[0] if data.get("meters") else {}
                relay = data.get("relays", [{}])[0] if data.get("relays") else {}
                results.append({
                    "name": name,
                    "power_w": round(meter.get("power", 0), 1),
                    "voltage_v": 0,
                    "current_a": 0,
                    "energy_wh": round(meter.get("total", 0) / 60, 1),  # Watt-minutes to Wh
                    "on": relay.get("ison", False),
                    "status": "online",
                })
            except (httpx.HTTPError, KeyError, ValueError):
                results.append({"name": name, "status": "offline"})
    return results


# ── Weather (OpenWeatherMap) ─────────────────────────────────────────────────
def get_weather(api_key: str, city: str) -> dict | None:
    if not api_key or not city:
        return None
    try:
        data = _http_get(
            f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric",
            timeout=4,
        )
        weather = data.get("weather", [{}])[0] if data.get("weather") else {}
        main = data.get("main", {})
        return {
            "temp": float(main.get("temp", 0)),
            "feels_like": float(main.get("feels_like", 0)),
            "humidity": int(main.get("humidity", 0)),
            "description": weather.get("description", ""),
            "icon": weather.get("icon", ""),
            "city": data.get("name", city),
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None
