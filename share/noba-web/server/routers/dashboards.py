# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Custom dashboard endpoints."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import _client_ip, _get_auth, _read_body, _require_operator, db, handle_errors

logger = logging.getLogger("noba")

router = APIRouter(tags=["dashboards"])


@router.get("/api/dashboards")
@handle_errors
def api_list_dashboards(auth=Depends(_get_auth)):
    """List dashboards visible to the current user (own + shared)."""
    username, _ = auth
    return db.get_dashboards(owner=username)


@router.post("/api/dashboards")
@handle_errors
async def api_create_dashboard(request: Request, auth=Depends(_require_operator)):
    """Create a new custom dashboard."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    name = (body.get("name") or "").strip()
    config_json = body.get("config_json", "")
    if not name:
        raise HTTPException(400, "Dashboard name is required")
    if not config_json:
        raise HTTPException(400, "Dashboard config is required")
    # Validate that config_json is valid JSON
    try:
        json.loads(config_json) if isinstance(config_json, str) else None
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(400, "config_json must be valid JSON") from None
    if isinstance(config_json, (dict, list)):
        config_json = json.dumps(config_json)
    shared = bool(body.get("shared", False))
    dashboard_id = db.create_dashboard(name, username, config_json, shared=shared)
    if dashboard_id is None:
        raise HTTPException(500, "Failed to create dashboard")
    db.audit_log("dashboard_create", username, f"id={dashboard_id} name={name}", ip)
    return {"status": "ok", "id": dashboard_id}


@router.put("/api/dashboards/{dashboard_id}")
@handle_errors
async def api_update_dashboard(dashboard_id: int, request: Request, auth=Depends(_require_operator)):
    """Update a custom dashboard (owner or admin only)."""
    username, role = auth
    ip = _client_ip(request)
    existing = db.get_dashboard(dashboard_id)
    if not existing:
        raise HTTPException(404, "Dashboard not found")
    if existing["owner"] != username and role != "admin":
        raise HTTPException(403, "Only the owner or an admin can update this dashboard")
    body = await _read_body(request)
    kwargs = {}
    if "name" in body:
        n = str(body["name"]).strip()
        if n:
            kwargs["name"] = n
    if "config_json" in body:
        cj = body["config_json"]
        if isinstance(cj, (dict, list)):
            cj = json.dumps(cj)
        try:
            json.loads(cj)
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(400, "config_json must be valid JSON") from None
        kwargs["config_json"] = cj
    if "shared" in body:
        kwargs["shared"] = bool(body["shared"])
    ok = db.update_dashboard(dashboard_id, **kwargs)
    if not ok:
        raise HTTPException(404, "Dashboard not found or no changes")
    db.audit_log("dashboard_update", username, f"id={dashboard_id}", ip)
    return {"status": "ok"}


@router.delete("/api/dashboards/{dashboard_id}")
@handle_errors
async def api_delete_dashboard(dashboard_id: int, request: Request, auth=Depends(_require_operator)):
    """Delete a custom dashboard (owner or admin only)."""
    username, role = auth
    ip = _client_ip(request)
    existing = db.get_dashboard(dashboard_id)
    if not existing:
        raise HTTPException(404, "Dashboard not found")
    if existing["owner"] != username and role != "admin":
        raise HTTPException(403, "Only the owner or an admin can delete this dashboard")
    ok = db.delete_dashboard(dashboard_id)
    if not ok:
        raise HTTPException(404, "Dashboard not found")
    db.audit_log("dashboard_delete", username, f"id={dashboard_id}", ip)
    return {"status": "ok"}
