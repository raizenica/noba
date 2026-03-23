"""Noba -- Integration instance management API."""
from __future__ import annotations

import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import _get_auth, _read_body, _require_operator, db

logger = logging.getLogger("noba")
router = APIRouter(tags=["integrations"])


# ── Instances CRUD ───────────────────────────────────────────────

@router.get("/api/integrations/instances")
def api_list_instances(
    category: str | None = None,
    site: str | None = None,
    auth=Depends(_get_auth),
):
    """List integration instances, optionally filtered by category or site."""
    return db.list_integration_instances(category=category, site=site)


@router.get("/api/integrations/instances/{instance_id}")
def api_get_instance(instance_id: str, auth=Depends(_get_auth)):
    """Get a single integration instance."""
    inst = db.get_integration_instance(instance_id)
    if not inst:
        raise HTTPException(404, f"Instance not found: {instance_id}")
    result = dict(inst)
    # Parse JSON fields
    for field in ("auth_config", "tags"):
        if field in result and isinstance(result[field], str):
            try:
                result[field] = json.loads(result[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return result


@router.post("/api/integrations/instances")
async def api_create_instance(request: Request, auth=Depends(_require_operator)):
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
    except Exception as exc:
        raise HTTPException(400, f"Failed to create instance: {exc}")

    return {"id": body["id"], "status": "created"}


@router.put("/api/integrations/instances/{instance_id}")
async def api_update_instance(
    instance_id: str, request: Request, auth=Depends(_require_operator),
):
    """Update an integration instance."""
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
        except Exception as exc:
            raise HTTPException(400, f"Update failed: {exc}")

    return {"id": instance_id, "status": "updated"}


@router.delete("/api/integrations/instances/{instance_id}")
def api_delete_instance(instance_id: str, auth=Depends(_require_operator)):
    """Delete an integration instance."""
    inst = db.get_integration_instance(instance_id)
    if not inst:
        raise HTTPException(404, f"Instance not found: {instance_id}")
    db.delete_integration_instance(instance_id)
    return {"id": instance_id, "status": "deleted"}


# ── Connection Test ──────────────────────────────────────────────

@router.post("/api/integrations/instances/test-connection")
async def api_test_connection(request: Request, auth=Depends(_require_operator)):
    """Test connectivity to an integration platform."""
    body = await _read_body(request)

    url = body.get("url", "")
    platform = body.get("platform", "")

    if not url:
        return {"success": False, "error": "No URL provided", "platform": platform}

    try:
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
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
    except Exception as exc:
        return {
            "success": False, "error": str(exc),
            "platform": platform, "url": url,
        }


# ── Catalog ──────────────────────────────────────────────────────

@router.get("/api/integrations/catalog/categories")
def api_catalog_categories(auth=Depends(_get_auth)):
    """List all available integration categories from the registry."""
    from ..healing.integration_registry import list_categories
    return list_categories()


@router.get("/api/integrations/catalog/categories/{category}/platforms")
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
def api_list_groups(auth=Depends(_get_auth)):
    """List all integration groups."""
    return db.list_integration_groups()


@router.get("/api/integrations/groups/{group_name}/members")
def api_list_group_members(group_name: str, auth=Depends(_get_auth)):
    """List members of an integration group."""
    return db.list_integration_group(group_name)


@router.post("/api/integrations/groups/{group_name}/members")
async def api_add_group_member(
    group_name: str, request: Request, auth=Depends(_require_operator),
):
    """Add an instance to a group."""
    body = await _read_body(request)
    instance_id = body.get("instance_id", "")
    if not instance_id:
        raise HTTPException(400, "Missing instance_id")
    db.add_to_integration_group(group_name, instance_id)
    return {"group": group_name, "instance_id": instance_id, "status": "added"}


@router.delete("/api/integrations/groups/{group_name}/members/{instance_id}")
def api_remove_group_member(
    group_name: str, instance_id: str, auth=Depends(_require_operator),
):
    """Remove an instance from a group."""
    db.remove_from_integration_group(group_name, instance_id)
    return {"group": group_name, "instance_id": instance_id, "status": "removed"}
