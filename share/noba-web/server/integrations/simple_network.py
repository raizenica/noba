# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Network integrations."""
from __future__ import annotations

import logging

import httpx

from .base import ConfigError, TransientError, _http_get

logger = logging.getLogger("noba")



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
        data = _http_get(f"{base}/control/stats", hdrs, category="dns")
        if not data:
            return None
        queries = data.get("num_dns_queries", 0)
        blocked = data.get("num_blocked_filtering", 0)
        pct = round(blocked / queries * 100, 1) if queries else 0
        return {"queries": queries, "blocked": blocked, "percent": pct, "status": "enabled"}
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, ZeroDivisionError, TypeError):
        return {"status": "offline", "error": "Connection failed"}





# ── Traefik ──────────────────────────────────────────────────────────────────
def get_traefik(url: str) -> dict | None:
    if not url:
        return None
    try:
        base = url.rstrip("/")
        routers = _http_get(f"{base}/api/http/routers", category="reverse_proxy")
        services = _http_get(f"{base}/api/http/services", category="reverse_proxy")
        router_list = routers if isinstance(routers, list) else []
        service_list = services if isinstance(services, list) else []
        errors = sum(
            1 for s in service_list
            if s.get("status") == "error"
            or any(v == "DOWN" for v in s.get("serverStatus", {}).values())
        )
        return {
            "routers": len(router_list),
            "services": len(service_list),
            "errors": errors,
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError):
        return {"status": "offline", "error": "Connection failed"}





# ── Nginx Proxy Manager ─────────────────────────────────────────────────────
def get_npm(url: str, token: str) -> dict | None:
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Bearer {token}"}
        data = _http_get(f"{base}/api/nginx/proxy-hosts", hdrs, category="reverse_proxy")
        return {
            "proxy_hosts": len(data) if isinstance(data, list) else 0,
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError):
        return {"status": "offline", "error": "Connection failed"}





# ── Cloudflare ───────────────────────────────────────────────────────────────
def get_cloudflare(token: str, zone_id: str) -> dict | None:
    if not token or not zone_id:
        return None
    try:
        hdrs = {"Authorization": f"Bearer {token}"}
        data = _http_get(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/analytics/dashboard?since=-1440",
            hdrs, timeout=6, category="cloud",
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
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError):
        return {"status": "offline", "error": "Connection failed"}



