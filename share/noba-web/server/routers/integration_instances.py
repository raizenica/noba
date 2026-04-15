# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Integration instance management API."""
from __future__ import annotations

import contextlib
import ipaddress
import json
import logging
import os
import socket
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import (
    _get_auth,
    _read_body,
    _require_admin,
    _require_operator,
    db,
    handle_errors,
)

logger = logging.getLogger("noba")
router = APIRouter(tags=["integrations"])

_UPDATABLE_FIELDS = frozenset({
    "name", "url", "api_key", "username", "password", "site", "tags",
    "enabled", "group_id", "verify_ssl", "ca_bundle", "extra",
})


def _is_safe_url(url: str) -> bool:
    """Block requests to private/internal networks."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        # Block common internal targets
        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False
        # Block metadata endpoints
        if hostname.startswith("169.254."):
            return False
        # Block private IP ranges
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        except ValueError:
            pass  # hostname is a domain name — resolve and check below
        # If it's a hostname (not an IP), resolve it and check the resolved IP
        try:
            resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            for _family, _, _, _, sockaddr in resolved:
                ip_str = sockaddr[0]
                try:
                    ip = ipaddress.ip_address(ip_str)
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                        return False
                except ValueError:
                    continue
        except socket.gaierror:
            return False  # can't resolve = not safe
        return True
    except HTTPException:
        raise
    except Exception:
        return False


# ── Instances CRUD ───────────────────────────────────────────────

@router.get("/api/integrations/instances")
@handle_errors
def api_list_instances(
    category: str | None = None,
    site: str | None = None,
    auth=Depends(_get_auth),
):
    """List integration instances, optionally filtered by category or site."""
    results = db.list_integration_instances(category=category, site=site)
    username, role = auth
    if role != "admin":
        for item in results:
            if isinstance(item, dict):
                item["auth_config"] = {"redacted": True}
    return results


@router.get("/api/integrations/instances/{instance_id}")
@handle_errors
def api_get_instance(instance_id: str, auth=Depends(_get_auth)):
    """Get a single integration instance."""
    inst = db.get_integration_instance(instance_id)
    if not inst:
        raise HTTPException(404, f"Instance not found: {instance_id}")
    result = dict(inst)
    # Parse JSON fields
    for field in ("auth_config", "tags"):
        if field in result and isinstance(result[field], str):
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                result[field] = json.loads(result[field])
    username, role = auth
    if role != "admin":
        result["auth_config"] = {"redacted": True}
    return result


@router.post("/api/integrations/instances")
@handle_errors
async def api_create_instance(request: Request, auth=Depends(_require_admin)):
    """Create a new integration instance."""
    body = await _read_body(request)

    required = ["id", "category", "platform"]
    for field in required:
        if not body.get(field):
            raise HTTPException(400, f"Missing required field: {field}")

    auth_config = body.get("auth_config", {})
    if isinstance(auth_config, dict):
        auth_config = json.dumps(auth_config)

    tags = body.get("tags", [])
    if isinstance(tags, list):
        tags = json.dumps(tags)

    try:
        db.insert_integration_instance(
            id=body["id"],
            category=body["category"],
            platform=body["platform"],
            url=body.get("url", ""),
            auth_config=auth_config,
            site=body.get("site"),
            tags=tags,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Failed to create instance: {exc}")

    return {"id": body["id"], "status": "created"}


@router.patch("/api/integrations/instances/{instance_id}")
@handle_errors
async def api_update_instance(
    instance_id: str, request: Request, auth=Depends(_require_admin),
):
    """Update an integration instance (partial)."""
    body = await _read_body(request)

    inst = db.get_integration_instance(instance_id)
    if not inst:
        raise HTTPException(404, f"Instance not found: {instance_id}")

    # Update fields that are provided
    update_fields: dict[str, str | None] = {}
    for field in ("url", "platform", "category", "site"):
        if field in body:
            update_fields[field] = body[field]

    if "auth_config" in body:
        ac = body["auth_config"]
        update_fields["auth_config"] = json.dumps(ac) if isinstance(ac, dict) else ac
    if "tags" in body:
        t = body["tags"]
        update_fields["tags"] = json.dumps(t) if isinstance(t, list) else t

    if update_fields:
        invalid = set(update_fields.keys()) - _UPDATABLE_FIELDS
        if invalid:
            raise HTTPException(400, f"Invalid fields: {', '.join(invalid)}")
        try:
            conn = db._get_conn()
            lock = db._lock
            sets = ", ".join(f"{k} = ?" for k in update_fields)
            vals = list(update_fields.values()) + [instance_id]
            with lock:
                conn.execute(
                    f"UPDATE integration_instances SET {sets} WHERE id = ?", vals,
                )
                conn.commit()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f"Update failed: {exc}")

    return {"id": instance_id, "status": "updated"}


@router.delete("/api/integrations/instances/{instance_id}")
@handle_errors
def api_delete_instance(instance_id: str, auth=Depends(_require_admin)):
    """Delete an integration instance."""
    inst = db.get_integration_instance(instance_id)
    if not inst:
        raise HTTPException(404, f"Instance not found: {instance_id}")
    db.delete_integration_instance(instance_id)
    return {"id": instance_id, "status": "deleted"}


# ── Per-instance actions ─────────────────────────────────────────

_ALLOWED_VM_ACTIONS = frozenset({"start", "stop", "poweroff"})


@router.post("/api/integrations/instances/{instance_id}/truenas/vm")
@handle_errors
async def api_instance_truenas_vm(
    instance_id: str, request: Request, auth=Depends(_require_operator),
):
    """Execute a VM action on a managed TrueNAS instance."""
    username, _ = auth
    body = await _read_body(request)
    vm_id  = body.get("id")
    action = body.get("action")
    try:
        vm_id = int(vm_id)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid VM ID")
    if vm_id < 0 or action not in _ALLOWED_VM_ACTIONS:
        raise HTTPException(400, "Invalid action")

    inst = db.get_integration_instance(instance_id)
    if not inst:
        raise HTTPException(404, f"Instance not found: {instance_id}")
    if dict(inst).get("platform") != "truenas":
        raise HTTPException(400, "Instance is not a TrueNAS platform")

    inst_d = dict(inst)
    url = inst_d.get("url", "")
    raw_ac = inst_d.get("auth_config", "{}")
    try:
        ac = json.loads(raw_ac) if isinstance(raw_ac, str) else (raw_ac or {})
    except Exception:
        ac = {}
    key = ac.get("api_key") or ac.get("token") or ac.get("apikey_env") or ac.get("apikey") or ""
    if not url or not key:
        raise HTTPException(400, "TrueNAS instance missing URL or API key")

    import urllib.request as _ur
    try:
        req = _ur.Request(
            f"{url.rstrip('/')}/api/v2.0/vm/id/{vm_id}/{action}",
            data=b"{}",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        with _ur.urlopen(req, timeout=5) as r:
            success = r.getcode() == 200
        db.audit_log("vm_action", username, f"Instance {instance_id} VM {vm_id} {action} {success}", "")
        return {"success": success}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("VM action failed for instance %s: %s", instance_id, exc)
        raise HTTPException(502, "VM action failed")


# ── Connection Test ──────────────────────────────────────────────

@router.post("/api/integrations/instances/test-connection")
@handle_errors
async def api_test_connection(request: Request, auth=Depends(_require_admin)):
    """Test connectivity to an integration platform (admin-only: makes outbound requests)."""
    body = await _read_body(request)

    url = body.get("url", "")
    platform = body.get("platform", "")

    if not url:
        return {"success": False, "error": "No URL provided", "platform": platform}

    verify = body.get("verify_ssl", True)
    if isinstance(verify, str) and os.path.isfile(verify):
        pass  # CA bundle path
    else:
        verify = bool(verify) if not isinstance(verify, str) else verify.lower() not in ("0", "false", "no")
    try:
        async with httpx.AsyncClient(timeout=10, verify=verify) as client:
            r = await client.get(url)
            return {
                "success": r.status_code < 500,
                "status_code": r.status_code,
                "platform": platform,
                "url": url,
            }
    except httpx.ConnectError:
        return {
            "success": False, "error": "Connection refused",
            "platform": platform, "url": url,
        }
    except httpx.ConnectTimeout:
        return {
            "success": False, "error": "Connection timed out",
            "platform": platform, "url": url,
        }
    except HTTPException:
        raise
    except Exception as exc:
        return {
            "success": False, "error": str(exc),
            "platform": platform, "url": url,
        }


# ── Catalog ──────────────────────────────────────────────────────

@router.get("/api/integrations/catalog/categories")
@handle_errors
def api_catalog_categories(auth=Depends(_get_auth)):
    """List all available integration categories from the registry."""
    from ..healing.integration_registry import list_categories
    return list_categories()


@router.get("/api/integrations/catalog/categories/{category}/platforms")
@handle_errors
def api_catalog_platforms(category: str, auth=Depends(_get_auth)):
    """List available platforms for a category."""
    from ..healing.integration_registry import list_operations, list_platforms
    ops = list_operations(category)
    if not ops:
        raise HTTPException(404, f"Unknown category: {category}")
    # Collect all platforms across all operations in this category
    platforms: set[str] = set()
    for op in ops:
        platforms.update(list_platforms(op))
    return sorted(platforms)


# ── Groups ───────────────────────────────────────────────────────

@router.get("/api/integrations/groups")
@handle_errors
def api_list_groups(auth=Depends(_get_auth)):
    """List all integration groups."""
    return db.list_integration_groups()


@router.get("/api/integrations/groups/{group_name}/members")
@handle_errors
def api_list_group_members(group_name: str, auth=Depends(_get_auth)):
    """List members of an integration group."""
    return db.list_integration_group(group_name)


@router.post("/api/integrations/groups/{group_name}/members")
@handle_errors
async def api_add_group_member(
    group_name: str, request: Request, auth=Depends(_require_admin),
):
    """Add an instance to a group."""
    body = await _read_body(request)
    instance_id = body.get("instance_id", "")
    if not instance_id:
        raise HTTPException(400, "Missing instance_id")
    db.add_to_integration_group(group_name, instance_id)
    return {"group": group_name, "instance_id": instance_id, "status": "added"}


@router.delete("/api/integrations/groups/{group_name}/members/{instance_id}")
@handle_errors
def api_remove_group_member(
    group_name: str, instance_id: str, auth=Depends(_require_admin),
):
    """Remove an instance from a group."""
    db.remove_from_integration_group(group_name, instance_id)
    return {"group": group_name, "instance_id": instance_id, "status": "removed"}
