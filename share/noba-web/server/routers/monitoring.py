"""Noba – Endpoint monitoring, uptime, status page, and health score endpoints."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from .. import deps as _deps
from ..agent_store import _agent_data, _agent_data_lock
from ..deps import (
    _client_ip, _get_auth, _read_body,
    _require_admin, _require_operator, db,
)
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

_WEB_DIR = Path(__file__).resolve().parent.parent.parent  # share/noba-web/

router = APIRouter(tags=["monitoring"])


# ── Uptime SLA dashboard ────────────────────────────────────────────────────
@router.get("/api/uptime")
def api_uptime_dashboard(auth=Depends(_get_auth)):
    """Get uptime statistics for all monitored services and integrations."""
    stats = _deps.bg_collector.get() or {}

    items = []
    for svc in stats.get("services", []):
        items.append({
            "name": svc["name"],
            "type": "service",
            "status": "up" if svc.get("status") == "active" else "down",
        })
    integration_checks = [
        ("pihole", "Pi-hole"), ("plex", "Plex"), ("jellyfin", "Jellyfin"),
        ("truenas", "TrueNAS"), ("proxmox", "Proxmox"), ("adguard", "AdGuard"),
        ("hass", "Home Assistant"), ("unifi", "UniFi"), ("nextcloud", "Nextcloud"),
        ("tautulli", "Tautulli"), ("overseerr", "Overseerr"), ("gitea", "Gitea"),
        ("gitlab", "GitLab"), ("traefik", "Traefik"), ("k8s", "Kubernetes"),
    ]
    for key, label in integration_checks:
        data = stats.get(key)
        if data is None:
            continue
        if isinstance(data, dict):
            status = "up" if data.get("status") == "online" else "down"
        else:
            status = "up" if data else "down"
        items.append({"name": label, "type": "integration", "status": status})
    for r in stats.get("radar", []):
        items.append({
            "name": r.get("ip", ""),
            "type": "host",
            "status": "up" if r.get("status") == "Up" else "down",
            "ms": r.get("ms", 0),
        })
    return items


# ── /api/health-score — Infrastructure Health Score (Feature 7) ──────────────
@router.get("/api/health-score")
async def api_health_score(auth=Depends(_get_auth)):
    """Compute infrastructure-wide health score (0-100) with category breakdown."""
    from ..health_score import compute_health_score

    stats = _deps.bg_collector.get() if _deps.bg_collector else {}
    with _agent_data_lock:
        agent_snapshot = dict(_agent_data)
    return await compute_health_score(db, agent_snapshot, stats)


# ── Status page endpoints ────────────────────────────────────────────────────
@router.get("/status")
def public_status_page():
    """Public-facing status page -- no auth required."""
    return FileResponse(_WEB_DIR / "status.html")


@router.get("/api/status/public")
def api_public_status():
    """Public status data -- no auth required.

    Returns components with live status, active incidents, and 90-day uptime history.
    Falls back to legacy metric-driven services when no components are configured.
    """
    # Components from the DB
    components = db.list_status_components()
    collector_data = (_deps.bg_collector.get() if _deps.bg_collector else None) or {}

    # Enrich components with live status from collector
    enriched: list[dict] = []
    for comp in components:
        if not comp["enabled"]:
            continue
        status = "operational"
        if comp["service_key"]:
            val = collector_data.get(comp["service_key"])
            if val is None:
                status = "unknown"
            elif isinstance(val, dict) and val.get("status"):
                status = "operational" if val["status"] in ("online", "enabled", "ok") else "degraded"
            elif isinstance(val, list) and len(val) > 0:
                status = "operational"
            else:
                status = "operational" if val else "unknown"
        enriched.append({
            "id": comp["id"], "name": comp["name"],
            "group_name": comp["group_name"], "status": status,
        })

    # Legacy fallback: if no components configured, use statusPageServices from YAML
    if not enriched:
        cfg = read_yaml_settings()
        status_services = [s.strip() for s in cfg.get("statusPageServices", "").split(",") if s.strip()]
        for svc in status_services:
            val = collector_data.get(svc)
            if val is None:
                status = "unknown"
            elif isinstance(val, dict) and val.get("status"):
                status = "operational" if val["status"] in ("online", "enabled", "ok") else "degraded"
            elif isinstance(val, list) and len(val) > 0:
                status = "operational"
            else:
                status = "operational" if val else "unknown"
            enriched.append({"name": svc, "group_name": "Default", "status": status})

    # Active incidents
    active_incidents = db.list_status_incidents(limit=20, include_resolved=False)
    # Enrich with updates
    for inc in active_incidents:
        detail = db.get_status_incident(inc["id"])
        inc["updates"] = detail["updates"] if detail else []

    # Determine overall status
    overall = "operational"
    has_active = len(active_incidents) > 0
    any_critical = any(i["severity"] == "critical" for i in active_incidents)
    any_major = any(i["severity"] == "major" for i in active_incidents)
    if any_critical:
        overall = "major_outage"
    elif any_major or any(s["status"] == "degraded" for s in enriched):
        overall = "degraded"
    elif has_active:
        overall = "degraded"

    # 90-day uptime history
    uptime_history = db.get_status_uptime_history(days=90)

    return {
        "components": enriched,
        "services": enriched,  # backward compat
        "active_incidents": active_incidents,
        "uptime_history": uptime_history,
        "overall": overall,
        "timestamp": int(time.time()),
    }


@router.get("/api/status/incidents")
def api_public_status_incidents():
    """Public: list recent status incidents with their updates."""
    incidents = db.list_status_incidents(limit=50, include_resolved=True)
    for inc in incidents:
        detail = db.get_status_incident(inc["id"])
        inc["updates"] = detail["updates"] if detail else []
    return {"incidents": incidents}


# ── Status page admin endpoints ──────────────────────────────────────────────
@router.post("/api/status/components")
async def api_create_status_component(request: Request, auth=Depends(_require_admin)):
    """Admin: create a status page component."""
    username, _ = auth
    body = await _read_body(request)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    comp_id = db.create_status_component(
        name=name,
        group_name=body.get("group_name", "Default"),
        service_key=body.get("service_key"),
        display_order=int(body.get("display_order", 0)),
    )
    if not comp_id:
        raise HTTPException(500, "Failed to create component")
    db.audit_log("status_component_create", username, f"id={comp_id} name={name}", _client_ip(request))
    return {"id": comp_id, "status": "ok"}


@router.put("/api/status/components/{comp_id}")
async def api_update_status_component(comp_id: int, request: Request, auth=Depends(_require_admin)):
    """Admin: update a status page component."""
    username, _ = auth
    body = await _read_body(request)
    ok = db.update_status_component(comp_id, **{
        k: v for k, v in body.items()
        if k in ("name", "group_name", "service_key", "display_order", "enabled")
    })
    if not ok:
        raise HTTPException(404, "Component not found or no changes")
    db.audit_log("status_component_update", username, f"id={comp_id}", _client_ip(request))
    return {"status": "ok"}


@router.delete("/api/status/components/{comp_id}")
def api_delete_status_component(comp_id: int, request: Request, auth=Depends(_require_admin)):
    """Admin: delete a status page component."""
    username, _ = auth
    ok = db.delete_status_component(comp_id)
    if not ok:
        raise HTTPException(404, "Component not found")
    db.audit_log("status_component_delete", username, f"id={comp_id}", _client_ip(request))
    return {"status": "ok"}


@router.get("/api/status/components")
def api_list_status_components(auth=Depends(_get_auth)):
    """Authenticated: list all status components (for admin UI)."""
    return {"components": db.list_status_components()}


@router.post("/api/status/incidents/create")
async def api_create_status_incident(request: Request, auth=Depends(_require_admin)):
    """Admin: create a status page incident."""
    username, _ = auth
    body = await _read_body(request)
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title is required")
    severity = body.get("severity", "minor")
    if severity not in ("minor", "major", "critical"):
        raise HTTPException(400, "severity must be minor, major, or critical")
    message = (body.get("message") or "").strip()
    incident_id = db.create_status_incident(
        title=title, severity=severity, message=message, created_by=username,
    )
    if not incident_id:
        raise HTTPException(500, "Failed to create incident")
    db.audit_log("status_incident_create", username, f"id={incident_id} title={title}", _client_ip(request))
    return {"id": incident_id, "status": "ok"}


@router.post("/api/status/incidents/{incident_id}/update")
async def api_add_status_update(incident_id: int, request: Request, auth=Depends(_require_admin)):
    """Admin: add an update to a status incident."""
    username, _ = auth
    body = await _read_body(request)
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message is required")
    status = body.get("status", "investigating")
    if status not in ("investigating", "identified", "monitoring", "resolved"):
        raise HTTPException(400, "status must be investigating, identified, monitoring, or resolved")
    update_id = db.add_status_update(
        incident_id=incident_id, message=message, status=status, created_by=username,
    )
    if not update_id:
        raise HTTPException(404, "Incident not found or failed to add update")
    db.audit_log("status_incident_update", username, f"incident={incident_id} status={status}", _client_ip(request))
    return {"id": update_id, "status": "ok"}


@router.put("/api/status/incidents/{incident_id}/resolve")
def api_resolve_status_incident(incident_id: int, request: Request, auth=Depends(_require_admin)):
    """Admin: resolve a status incident."""
    username, _ = auth
    ok = db.resolve_status_incident(incident_id, created_by=username)
    if not ok:
        raise HTTPException(404, "Incident not found")
    db.audit_log("status_incident_resolve", username, f"id={incident_id}", _client_ip(request))
    return {"status": "ok"}


# ── Endpoint monitor endpoints ────────────────────────────────────────────────
@router.get("/api/endpoints")
def api_list_endpoints(auth=Depends(_get_auth)):
    """List all endpoint monitors with latest status."""
    return db.get_endpoint_monitors()


@router.post("/api/endpoints")
async def api_create_endpoint(request: Request, auth=Depends(_require_admin)):
    """Create a new endpoint monitor."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    if not name or not url:
        raise HTTPException(400, "Name and URL are required")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL must start with http:// or https://")
    kwargs = {}
    if "method" in body:
        m = str(body["method"]).upper()
        if m in ("GET", "HEAD"):
            kwargs["method"] = m
    for int_field in ("expected_status", "check_interval", "timeout", "notify_cert_days"):
        if int_field in body:
            try:
                kwargs[int_field] = int(body[int_field])
            except (TypeError, ValueError):
                pass
    if "agent_hostname" in body:
        kwargs["agent_hostname"] = body["agent_hostname"] or None
    if "enabled" in body:
        kwargs["enabled"] = bool(body["enabled"])
    monitor_id = db.create_endpoint_monitor(name, url, **kwargs)
    if monitor_id is None:
        raise HTTPException(500, "Failed to create monitor")
    db.audit_log("endpoint_create", username, f"id={monitor_id} name={name} url={url}", ip)
    return {"status": "ok", "id": monitor_id}


@router.put("/api/endpoints/{monitor_id}")
async def api_update_endpoint(monitor_id: int, request: Request, auth=Depends(_require_admin)):
    """Update an endpoint monitor."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    kwargs = {}
    if "name" in body:
        kwargs["name"] = str(body["name"]).strip()
    if "url" in body:
        u = str(body["url"]).strip()
        if not u.startswith(("http://", "https://")):
            raise HTTPException(400, "URL must start with http:// or https://")
        kwargs["url"] = u
    if "method" in body:
        m = str(body["method"]).upper()
        if m in ("GET", "HEAD"):
            kwargs["method"] = m
    for int_field in ("expected_status", "check_interval", "timeout", "notify_cert_days"):
        if int_field in body:
            try:
                kwargs[int_field] = int(body[int_field])
            except (TypeError, ValueError):
                pass
    if "agent_hostname" in body:
        kwargs["agent_hostname"] = body["agent_hostname"] or None
    if "enabled" in body:
        kwargs["enabled"] = bool(body["enabled"])
    ok = db.update_endpoint_monitor(monitor_id, **kwargs)
    if not ok:
        raise HTTPException(404, "Monitor not found or no changes")
    db.audit_log("endpoint_update", username, f"id={monitor_id}", ip)
    return {"status": "ok"}


@router.delete("/api/endpoints/{monitor_id}")
async def api_delete_endpoint(monitor_id: int, request: Request, auth=Depends(_require_admin)):
    """Delete an endpoint monitor."""
    username, _ = auth
    ip = _client_ip(request)
    ok = db.delete_endpoint_monitor(monitor_id)
    if not ok:
        raise HTTPException(404, "Monitor not found")
    db.audit_log("endpoint_delete", username, f"id={monitor_id}", ip)
    return {"status": "ok"}


@router.post("/api/endpoints/{monitor_id}/check")
async def api_check_endpoint_now(monitor_id: int, request: Request, auth=Depends(_require_operator)):
    """Trigger an immediate endpoint check."""
    username, _ = auth
    ip = _client_ip(request)
    monitor = db.get_endpoint_monitor(monitor_id)
    if not monitor:
        raise HTTPException(404, "Monitor not found")

    from ..scheduler import _run_endpoint_check
    result = _run_endpoint_check(monitor)
    db.audit_log("endpoint_check_now", username,
                 f"id={monitor_id} name={monitor['name']} result={result.get('last_status', '?')}", ip)
    return result
