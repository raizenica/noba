# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Infrastructure integrations.

This module is intentionally multi-category: TrueNAS/OMV (nas), Proxmox/XCP-ng
(hypervisor), Kubernetes (container_runtime), Gitea/GitLab/GitHub (git_devops),
Paperless (document_wiki), Vaultwarden (security). Each function routes
through the appropriate per-category httpx pool (CF-9) so that one slow
platform in one category can't starve callers in other categories.
"""
from __future__ import annotations

import logging

import httpx

from .base import ConfigError, TransientError, _http_get, get_category_client

# CF-9: per-category pools. Tests should patch the specific category client
# they're exercising (`_nas_client`, `_git_devops_client`, etc.) rather than
# the legacy `_client` alias.
_nas_client = get_category_client("nas")
_hypervisor_client = get_category_client("hypervisor")
_container_runtime_client = get_category_client("container_runtime")
_git_devops_client = get_category_client("git_devops")
_document_wiki_client = get_category_client("document_wiki")
_security_client = get_category_client("security")

# Legacy alias for code paths that have not yet been migrated — bound to the
# nas pool to match this file's historical dominant workload.
_client = _nas_client

logger = logging.getLogger("noba")



# ── TrueNAS ───────────────────────────────────────────────────────────────────
def get_truenas(url: str, key: str) -> dict | None:
    if not url or not key:
        return None
    hdrs   = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    base   = url.rstrip("/")
    result = {"apps": [], "alerts": [], "vms": [], "status": "offline"}
    try:
        for app in _http_get(f"{base}/api/v2.0/app", hdrs, category="nas"):
            result["apps"].append({"name": app.get("name", "?"), "state": app.get("state", "?")})
        for alert in _http_get(f"{base}/api/v2.0/alert/list", hdrs, category="nas"):
            if alert.get("level") in ("WARNING", "CRITICAL") and not alert.get("dismissed"):
                result["alerts"].append({
                    "level": alert.get("level"),
                    "text":  alert.get("formatted", "Unknown Alert"),
                })
        try:
            for vm in _http_get(f"{base}/api/v2.0/vm", hdrs, category="nas"):
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
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError):
        result["error"] = "Connection failed"
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
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError):
        return {"status": "offline", "error": "Connection failed"}





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
        r = _hypervisor_client.post(f"{base}/jsonrpc", json=login_payload, timeout=6)
        r.raise_for_status()
        session_id = r.json().get("result", "")

        # Get all VM records
        vm_payload = {
            "jsonrpc": "2.0", "method": "VM.get_all_records",
            "params": [session_id], "id": 2,
        }
        r2 = _hypervisor_client.post(f"{base}/jsonrpc", json=vm_payload, timeout=6)
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
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError):
        return {"status": "offline", "error": "Connection failed"}





# ── Kubernetes ───────────────────────────────────────────────────────────────
def get_k8s(url: str, token: str, *, verify_ssl=True) -> dict | None:
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Bearer {token}"}
        # CF-9: use per-category pool when verify=True; fall back to a
        # one-off client only when the caller opts out of verification (k8s
        # clusters with self-signed CAs are common in homelab setups, so
        # supporting verify=False without crashing is important).
        if verify_ssl is True or verify_ssl == "1" or verify_ssl == "true":
            r = _container_runtime_client.get(
                f"{base}/api/v1/pods", headers=hdrs, timeout=6,
            )
        else:
            with httpx.Client(timeout=6, verify=verify_ssl, follow_redirects=False) as c:
                r = c.get(f"{base}/api/v1/pods", headers=hdrs)
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
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError):
        return {"status": "offline", "error": "Connection failed"}





# ── Gitea ────────────────────────────────────────────────────────────────────
def get_gitea(url: str, token: str) -> dict | None:
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"token {token}"}
        # Use a raw request to get the x-total-count header
        r = _git_devops_client.get(
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
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError):
        return {"status": "offline", "error": "Connection failed"}





# ── GitLab ───────────────────────────────────────────────────────────────────
def get_gitlab(url: str, token: str) -> dict | None:
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"PRIVATE-TOKEN": token}
        r = _git_devops_client.get(
            f"{base}/api/v4/projects?per_page=1", headers=hdrs, timeout=4,
        )
        r.raise_for_status()
        total = int(r.headers.get("x-total", 0))
        return {"projects": total, "status": "online"}
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError):
        return {"status": "offline", "error": "Connection failed"}





# ── GitHub ───────────────────────────────────────────────────────────────────
def get_github(token: str) -> dict | None:
    if not token:
        return None
    try:
        hdrs = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        r = _git_devops_client.get(
            "https://api.github.com/user/repos?per_page=5&sort=updated",
            headers=hdrs, timeout=4,
        )
        r.raise_for_status()
        repos = r.json()
        total = len(repos) if isinstance(repos, list) else 0
        return {"repos": total, "status": "online"}
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError):
        return {"status": "offline", "error": "Connection failed"}





# ── Paperless-ngx ────────────────────────────────────────────────────────────
def get_paperless(url: str, token: str) -> dict | None:
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Token {token}"}
        data = _http_get(f"{base}/api/documents/?page_size=1", hdrs, category="document_wiki")
        return {
            "documents": data.get("count", 0),
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError):
        return {"status": "offline", "error": "Connection failed"}





# ── Vaultwarden ──────────────────────────────────────────────────────────────
def get_vaultwarden(url: str, admin_token: str) -> dict | None:
    if not url or not admin_token:
        return None
    try:
        base = url.rstrip("/")
        r = _security_client.get(
            f"{base}/admin/users/overview",
            headers={"Cookie": f"VAULTWARDEN_ADMIN={admin_token}"},
            timeout=4,
        )
        r.raise_for_status()
        return {"status": "online"}
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError):
        return {"status": "offline", "error": "Connection failed"}



