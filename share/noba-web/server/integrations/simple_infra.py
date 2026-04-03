# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Infrastructure integrations."""
from __future__ import annotations

import logging
import httpx

try:
    from . import simple
    _http_get = simple._http_get
    _client = simple._client
except ImportError:
    from .base import ConfigError, TransientError, _client, _http_get
    # If simple not available, use base directly (shouldn't happen in tests)
from .base import ConfigError, TransientError


logger = logging.getLogger("noba")



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
        except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
            logger.warning("TrueNAS VM fetch: %s", e)
        result["status"] = "online"
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        result["error"] = str(e)
    return result



# ── OpenMediaVault ───────────────────────────────────────────────────────────
def get_omv(url: str, user: str, password: str) -> dict | None:
    if not url or not user:
        return None
    try:
        base = url.rstrip("/")
        with httpx.Client(timeout=6, follow_redirects=False) as omv_client:
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
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





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
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





# ── Kubernetes ───────────────────────────────────────────────────────────────
def get_k8s(url: str, token: str, *, verify_ssl=True) -> dict | None:
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Bearer {token}"}
        r = httpx.get(f"{base}/api/v1/pods", headers=hdrs, timeout=6, verify=verify_ssl)
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
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





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
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





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
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





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
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





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
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





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
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}



