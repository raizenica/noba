# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Pi-hole integration with v6/v5 fallback and session caching."""
from __future__ import annotations

import threading
import time

import httpx

from ..config import VERSION
from .base import _http_get, get_category_client

# CF-9: dedicated per-category httpx pool so a slow Pi-hole doesn't starve
# other integrations. The legacy module-level `_client` name is preserved so
# that existing tests continue to patch `server.integrations.pihole._client`.
_CATEGORY = "dns"
_client = get_category_client(_CATEGORY)

# ── Pi-hole v6 session cache ────────────────────────────────────────────────
_pihole_sessions: dict[str, tuple[str, float]] = {}
_pihole_session_lock = threading.Lock()


def _pihole_v6_auth(base: str, password: str) -> str:
    """Authenticate to Pi-hole v6 and return session ID."""
    with _pihole_session_lock:
        cached = _pihole_sessions.get(base)
        if cached and time.time() < cached[1]:
            return cached[0]
    try:
        r = _client.post(f"{base}/api/auth", json={"password": password}, timeout=4)
        data = r.json()
        sid = data.get("session", {}).get("sid") or ""
        if sid:
            with _pihole_session_lock:
                _pihole_sessions[base] = (sid, time.time() + 280)  # ~5min TTL
        return sid
    except (httpx.HTTPError, ValueError):
        return ""


# ── Pi-hole ───────────────────────────────────────────────────────────────────
def get_pihole(url: str, token: str, password: str = "") -> dict | None:
    if not url:
        return None
    base = (url if url.startswith("http") else "http://" + url).rstrip("/").replace("/admin", "")
    hdrs = {"User-Agent": f"noba-web/{VERSION}", "Accept": "application/json"}

    # v6 API — authenticate with password or token
    sid = ""
    if password:
        sid = _pihole_v6_auth(base, password)
    if not sid and token:
        sid = token
    if sid:
        hdrs["sid"] = sid

    try:
        data = _http_get(f"{base}/api/stats/summary", hdrs)
        queries = data.get("queries", {})
        gravity = data.get("gravity", {})
        return {
            "queries": queries.get("total", 0),
            "blocked": queries.get("blocked", 0),
            "percent": round(queries.get("percent_blocked", 0.0), 1),
            "status":  "enabled" if gravity.get("domains_being_blocked", 0) > 0 else "disabled",
            "domains": f"{gravity.get('domains_being_blocked', 0):,}",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        # If auth error and password set, clear cache and retry once
        if password:
            with _pihole_session_lock:
                _pihole_sessions.pop(base, None)
            sid = _pihole_v6_auth(base, password)
            if sid:
                hdrs["sid"] = sid
                try:
                    data = _http_get(f"{base}/api/stats/summary", hdrs)
                    queries = data.get("queries", {})
                    gravity = data.get("gravity", {})
                    return {
                        "queries": queries.get("total", 0),
                        "blocked": queries.get("blocked", 0),
                        "percent": round(queries.get("percent_blocked", 0.0), 1),
                        "status":  "enabled" if gravity.get("domains_being_blocked", 0) > 0 else "disabled",
                        "domains": f"{gravity.get('domains_being_blocked', 0):,}",
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
