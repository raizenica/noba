# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""TrueNAS integration via JSON-RPC 2.0 over WebSocket.

Replaces the deprecated REST API (removed in TrueNAS 26.04).
Uses a persistent WebSocket connection with API key authentication.
Falls back to the legacy REST API if WebSocket connection fails,
so existing setups continue working during the transition.

WebSocket endpoint: wss://<host>/api/current
Auth: auth.login_with_api_key(api_key)
Protocol: JSON-RPC 2.0 (no batch support)
"""
from __future__ import annotations

import json
import logging
import ssl
import threading
import time
from contextlib import contextmanager

logger = logging.getLogger("noba")

# Connection cache: reuse WebSocket connections across collection cycles
_ws_cache: dict[str, dict] = {}  # url -> {ws, last_used, lock}
_cache_lock = threading.Lock()
_CACHE_EXPIRY = 300  # 5 minutes idle before closing


def _get_ws_url(http_url: str) -> str:
    """Convert HTTP(S) URL to WebSocket URL."""
    url = http_url.rstrip("/")
    if url.startswith("https://"):
        return url.replace("https://", "wss://", 1) + "/api/current"
    return url.replace("http://", "ws://", 1) + "/api/current"


def _jsonrpc_call(ws, method: str, params: list | None = None, timeout: float = 10) -> dict:
    """Send a JSON-RPC 2.0 request and wait for the response."""

    msg_id = int(time.time() * 1000) % 1_000_000
    request = {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": method,
        "params": params or [],
    }
    ws.send(json.dumps(request))

    # Read responses until we get our ID back (skip subscription events)
    deadline = time.time() + timeout
    while time.time() < deadline:
        ws.settimeout(max(0.1, deadline - time.time()))
        try:
            raw = ws.recv()
        except Exception:
            break
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("id") == msg_id:
            if "error" in data:
                raise RuntimeError(f"JSON-RPC error: {data['error']}")
            return data.get("result", data)
    raise TimeoutError(f"JSON-RPC timeout for {method}")


@contextmanager
def _connect(url: str, api_key: str):
    """Get or create a WebSocket connection to TrueNAS."""
    import websocket as _websocket

    ws_url = _get_ws_url(url)

    # Check cache
    with _cache_lock:
        cached = _ws_cache.get(url)
        if cached and cached.get("ws"):
            try:
                cached["ws"].ping()
                cached["last_used"] = time.time()
                yield cached["ws"]
                return
            except Exception:
                # Stale connection
                try:
                    cached["ws"].close()
                except Exception:
                    pass
                del _ws_cache[url]

    # New connection
    ssl_opts = {"cert_reqs": ssl.CERT_NONE} if ws_url.startswith("wss://") else {}
    ws = _websocket.create_connection(
        ws_url,
        timeout=10,
        sslopt=ssl_opts,
        suppress_ragged_eofs=True,
    )
    try:
        # Authenticate
        _jsonrpc_call(ws, "auth.login_with_api_key", [api_key])

        # Cache it
        with _cache_lock:
            _ws_cache[url] = {"ws": ws, "last_used": time.time()}

        yield ws
    except Exception:
        ws.close()
        raise


def get_truenas(url: str, key: str) -> dict | None:
    """Fetch TrueNAS data via JSON-RPC 2.0 WebSocket.

    Same return format as the legacy REST version:
    {"apps": [...], "alerts": [...], "vms": [...], "status": "online"|"offline"}

    Falls back to legacy REST API if websocket-client is not installed
    or WebSocket connection fails.
    """
    if not url or not key:
        return None

    result = {"apps": [], "alerts": [], "vms": [], "status": "offline"}

    try:
        import websocket as _websocket  # noqa: F401
    except ImportError:
        logger.debug("websocket-client not installed, falling back to REST API")
        return _get_truenas_rest(url, key)

    try:
        with _connect(url, key) as ws:
            # Fetch apps
            try:
                apps = _jsonrpc_call(ws, "app.query")
                if isinstance(apps, list):
                    for app in apps:
                        result["apps"].append({
                            "name": app.get("name", "?"),
                            "state": app.get("state", "?"),
                        })
            except Exception as e:
                logger.debug("TrueNAS app.query: %s", e)

            # Fetch alerts
            try:
                alerts = _jsonrpc_call(ws, "alert.list")
                if isinstance(alerts, list):
                    for alert in alerts:
                        if alert.get("level") in ("WARNING", "CRITICAL") and not alert.get("dismissed"):
                            result["alerts"].append({
                                "level": alert.get("level"),
                                "text": alert.get("formatted", "Unknown Alert"),
                            })
            except Exception as e:
                logger.debug("TrueNAS alert.list: %s", e)

            # Fetch VMs
            try:
                vms = _jsonrpc_call(ws, "vm.query")
                if isinstance(vms, list):
                    for vm in vms:
                        result["vms"].append({
                            "id": vm.get("id"),
                            "name": vm.get("name", "?"),
                            "state": vm.get("status", {}).get("state", "UNKNOWN"),
                        })
            except Exception as e:
                logger.debug("TrueNAS vm.query: %s", e)

            # Fetch pools (new — useful for healing dashboard)
            try:
                pools = _jsonrpc_call(ws, "pool.query")
                if isinstance(pools, list):
                    result["pools"] = []
                    for pool in pools:
                        result["pools"].append({
                            "name": pool.get("name", "?"),
                            "status": pool.get("status", "UNKNOWN"),
                            "healthy": pool.get("healthy", False),
                        })
            except Exception as e:
                logger.debug("TrueNAS pool.query: %s", e)

            result["status"] = "online"

    except Exception as e:
        logger.warning("TrueNAS WebSocket failed, falling back to REST: %s", e)
        return _get_truenas_rest(url, key)

    return result


def _get_truenas_rest(url: str, key: str) -> dict | None:
    """Legacy REST API fallback (deprecated in TrueNAS 26.04)."""
    from .base import _http_get

    import httpx

    hdrs = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    base = url.rstrip("/")
    result = {"apps": [], "alerts": [], "vms": [], "status": "offline"}
    try:
        for app in _http_get(f"{base}/api/v2.0/app", hdrs):
            result["apps"].append({"name": app.get("name", "?"), "state": app.get("state", "?")})
        for alert in _http_get(f"{base}/api/v2.0/alert/list", hdrs):
            if alert.get("level") in ("WARNING", "CRITICAL") and not alert.get("dismissed"):
                result["alerts"].append({
                    "level": alert.get("level"),
                    "text": alert.get("formatted", "Unknown Alert"),
                })
        try:
            for vm in _http_get(f"{base}/api/v2.0/vm", hdrs):
                result["vms"].append({
                    "id": vm.get("id"),
                    "name": vm.get("name", "?"),
                    "state": vm.get("status", {}).get("state", "UNKNOWN"),
                })
        except (httpx.HTTPError, KeyError, ValueError) as e:
            logger.warning("TrueNAS VM fetch (REST fallback): %s", e)
        result["status"] = "online"
    except (httpx.HTTPError, KeyError, ValueError):
        pass
    return result


def cleanup_stale_connections() -> None:
    """Close WebSocket connections that haven't been used recently."""
    now = time.time()
    with _cache_lock:
        stale = [url for url, info in _ws_cache.items()
                 if now - info.get("last_used", 0) > _CACHE_EXPIRY]
        for url in stale:
            try:
                _ws_cache[url]["ws"].close()
            except Exception:
                pass
            del _ws_cache[url]
        if stale:
            logger.debug("Cleaned %d stale TrueNAS WebSocket connections", len(stale))
