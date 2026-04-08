# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Service-specific proxy and control endpoints (cameras, HA, Pi-hole, etc.)."""
from __future__ import annotations

import asyncio
import logging
import re
import subprocess

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..deps import (
    _client_ip,
    _get_auth,
    _read_body,
    _require_admin,
    _require_operator,
    db,
    handle_errors,
)
from ..metrics import get_rclone_remotes
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

router = APIRouter()


# ── /api/cameras/snapshot ────────────────────────────────────────────────────
@router.get("/api/cameras/snapshot/{cam}")
@handle_errors
def api_camera_snapshot(cam: str, auth=Depends(_get_auth)):
    cfg = read_yaml_settings()
    frigate_url = cfg.get("frigateUrl", "")
    if not frigate_url:
        raise HTTPException(404, "Frigate not configured")
    if not re.match(r'^[a-zA-Z0-9_-]+$', cam):
        raise HTTPException(400, "Invalid camera name")
    import httpx as _httpx  # noqa: PLC0415
    try:
        r = _httpx.get(f"{frigate_url.rstrip('/')}/api/{cam}/latest.jpg", timeout=8)
        r.raise_for_status()
        return Response(content=r.content, media_type="image/jpeg",
                       headers={"Cache-Control": "no-cache, max-age=5"})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, "Failed to fetch snapshot") from None


# ── /api/cameras ──────────────────────────────────────────────────────────
@router.get("/api/cameras")
@handle_errors
def api_cameras(auth=Depends(_get_auth)):
    """Return configured camera feed URLs."""
    cfg = read_yaml_settings()
    feeds = cfg.get("cameraFeeds", [])
    return [{"name": f.get("name", f"Camera {i+1}"),
             "url": f.get("url", ""),
             "type": f.get("type", "snapshot")}
            for i, f in enumerate(feeds) if f.get("url")]


# ── /api/tailscale/status ────────────────────────────────────────────────────
@router.get("/api/tailscale/status")
@handle_errors
def api_tailscale_status(auth=Depends(_get_auth)):
    from ..metrics import get_tailscale_status  # noqa: PLC0415
    return get_tailscale_status() or {"error": "Tailscale not available"}


# ── /api/disks/intelligence ──────────────────────────────────────────────────
_scrutiny_cache: dict = {"data": None, "ts": 0.0}
_SCRUTINY_TTL = 300  # 5 min — SMART data doesn't change often


@router.get("/api/disks/intelligence")
@handle_errors
def api_disk_intelligence(auth=Depends(_get_auth)):
    import time as _time

    cfg = read_yaml_settings()
    url = cfg.get("scrutinyUrl", "")
    if not url:
        raise HTTPException(404, "Scrutiny not configured")
    now = _time.time()
    if _scrutiny_cache["data"] is not None and now - _scrutiny_cache["ts"] < _SCRUTINY_TTL:
        return _scrutiny_cache["data"]
    from ..integrations import get_scrutiny_intelligence  # noqa: PLC0415

    result = get_scrutiny_intelligence(url) or []
    _scrutiny_cache["data"] = result
    _scrutiny_cache["ts"] = now
    return result


# ── /api/services/dependencies/blast-radius ──────────────────────────────────
@router.get("/api/services/dependencies/blast-radius")
@handle_errors
def api_blast_radius(node: str, auth=Depends(_get_auth)):
    cfg = read_yaml_settings()
    deps_str = cfg.get("serviceDependencies", "")
    if not deps_str:
        return {"node": node, "dependents": [], "dependencies": []}
    edges = []
    for edge in deps_str.split(","):
        edge = edge.strip()
        if ">" in edge:
            src, dst = edge.split(">", 1)
            edges.append((src.strip(), dst.strip()))
    dependents: set[str] = set()
    def walk_dependents(n: str) -> None:
        for src, dst in edges:
            if dst == n and src not in dependents:
                dependents.add(src)
                walk_dependents(src)
    walk_dependents(node)
    dependencies: set[str] = set()
    def walk_dependencies(n: str) -> None:
        for src, dst in edges:
            if src == n and dst not in dependencies:
                dependencies.add(dst)
                walk_dependencies(dst)
    walk_dependencies(node)
    return {
        "node": node,
        "dependents": sorted(dependents),
        "dependencies": sorted(dependencies),
    }


# ── /api/hass (Home Assistant) ────────────────────────────────────────────────
@router.post("/api/hass/services/{domain}/{service}")
@handle_errors
async def api_hass_proxy(domain: str, service: str, request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    cfg = read_yaml_settings()
    hass_url = cfg.get("hassUrl", "")
    hass_token = cfg.get("hassToken", "")
    if not hass_url or not hass_token:
        raise HTTPException(400, "Home Assistant not configured")
    if not re.match(r'^[a-z_]+$', domain) or not re.match(r'^[a-z_]+$', service):
        raise HTTPException(400, "Invalid domain or service name")
    body = await _read_body(request)
    import httpx as _httpx
    try:
        r = _httpx.post(f"{hass_url.rstrip('/')}/api/services/{domain}/{service}",
                       json=body, headers={"Authorization": f"Bearer {hass_token}"}, timeout=10)
        db.audit_log("hass_service", username, f"{domain}.{service}", _client_ip(request))
        return {"status": "ok", "http_status": r.status_code}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("HA service call failed: %s", e)
        raise HTTPException(502, "HA service call failed") from None


@router.get("/api/hass/entities")
@handle_errors
def api_hass_entities(request: Request, auth=Depends(_get_auth)):
    """List HA entities with full state details."""
    from ..integrations import get_hass_entities
    cfg = read_yaml_settings()
    hass_url = cfg.get("hassUrl", "")
    hass_token = cfg.get("hassToken", "")
    if not hass_url or not hass_token:
        raise HTTPException(400, "Home Assistant not configured")
    domain = request.query_params.get("domain", "")
    result = get_hass_entities(hass_url, hass_token, domain)
    if result is None:
        raise HTTPException(502, "Failed to fetch HA entities")
    return result


@router.get("/api/hass/services")
@handle_errors
def api_hass_services(auth=Depends(_get_auth)):
    """List available HA services."""
    from ..integrations import get_hass_services
    cfg = read_yaml_settings()
    hass_url = cfg.get("hassUrl", "")
    hass_token = cfg.get("hassToken", "")
    if not hass_url or not hass_token:
        raise HTTPException(400, "Home Assistant not configured")
    result = get_hass_services(hass_url, hass_token)
    if result is None:
        raise HTTPException(502, "Failed to fetch HA services")
    return result


@router.post("/api/hass/toggle/{entity_id:path}")
@handle_errors
async def api_hass_toggle(entity_id: str, request: Request, auth=Depends(_require_operator)):
    """Toggle a Home Assistant entity."""
    username, _ = auth
    cfg = read_yaml_settings()
    hass_url = cfg.get("hassUrl", "")
    hass_token = cfg.get("hassToken", "")
    if not hass_url or not hass_token:
        raise HTTPException(400, "Home Assistant not configured")
    domain = entity_id.split(".")[0] if "." in entity_id else ""
    if domain not in ("light", "switch", "input_boolean", "fan", "cover", "scene", "automation", "script"):
        raise HTTPException(400, f"Cannot toggle domain: {domain}")
    service = "toggle" if domain != "scene" else "turn_on"
    import httpx as _httpx
    try:
        r = _httpx.post(f"{hass_url.rstrip('/')}/api/services/{domain}/{service}",
                       json={"entity_id": entity_id},
                       headers={"Authorization": f"Bearer {hass_token}"}, timeout=10)
        db.audit_log("hass_toggle", username, f"Toggled {entity_id}", _client_ip(request))
        return {"success": r.status_code == 200, "entity_id": entity_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("HA toggle failed: %s", e)
        raise HTTPException(502, "HA toggle failed") from None


@router.post("/api/hass/scene/{entity_id:path}")
@handle_errors
async def api_hass_scene(entity_id: str, request: Request, auth=Depends(_require_operator)):
    """Activate a Home Assistant scene."""
    username, _ = auth
    cfg = read_yaml_settings()
    hass_url = cfg.get("hassUrl", "")
    hass_token = cfg.get("hassToken", "")
    if not hass_url or not hass_token:
        raise HTTPException(400, "Home Assistant not configured")
    import httpx as _httpx
    try:
        r = _httpx.post(f"{hass_url.rstrip('/')}/api/services/scene/turn_on",
                       json={"entity_id": entity_id},
                       headers={"Authorization": f"Bearer {hass_token}"}, timeout=10)
        db.audit_log("hass_scene", username, f"Activated {entity_id}", _client_ip(request))
        return {"success": r.status_code == 200}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Scene activation failed: %s", e)
        raise HTTPException(502, "Scene activation failed") from None


def _pihole_get_sid(base: str, password: str) -> str:
    """Authenticate with Pi-hole v6 and return a fresh session ID.

    Pi-hole v6 issues short-lived SIDs via POST /api/auth {"password": ...}.
    The CE collector side already handles this via `integrations/pihole.py`,
    but the `/api/pihole/toggle` router path was still reusing the static
    `piholeToken` config field as the SID, which v6 rejects. This helper
    forces a fresh session per toggle.
    """
    import httpx as _httpx
    r = _httpx.post(f"{base}/api/auth", json={"password": password}, timeout=5)
    data = r.json()
    session = data.get("session", {})
    if not session.get("valid"):
        raise HTTPException(
            502,
            f"Pi-hole auth failed: {session.get('message', 'invalid credentials')}",
        )
    return session["sid"]


# ── /api/pihole/toggle ───────────────────────────────────────────────────────
@router.post("/api/pihole/toggle")
@handle_errors
async def api_pihole_toggle(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    body = await _read_body(request)
    action = body.get("action", "disable")
    duration = int(body.get("duration", 0))
    cfg = read_yaml_settings()
    ph_url = cfg.get("piholeUrl", "")
    # v6 requires a password; fall back to the legacy `piholeToken` field
    # for users who haven't migrated their config yet.
    ph_password = cfg.get("piholePassword", "") or cfg.get("piholeToken", "")
    if not ph_url:
        raise HTTPException(400, "Pi-hole not configured")
    base = (ph_url if ph_url.startswith("http") else "http://" + ph_url).rstrip("/").replace("/admin", "")
    import httpx as _httpx
    try:
        # Pi-hole v6: authenticate per call to get a fresh SID. v5 fallback
        # uses the legacy /admin/api.php query-string path with no SID.
        sid = _pihole_get_sid(base, ph_password) if ph_password else ""
        if action == "disable":
            if sid:
                _httpx.post(
                    f"{base}/api/dns/blocking",
                    json={"blocking": False, "timer": duration or None},
                    headers={"sid": sid}, timeout=5,
                )
            else:
                _httpx.post(
                    f"{base}/admin/api.php?disable={duration or 300}",
                    timeout=5,
                )
        else:  # enable
            if sid:
                _httpx.post(
                    f"{base}/api/dns/blocking",
                    json={"blocking": True},
                    headers={"sid": sid}, timeout=5,
                )
            else:
                _httpx.post(f"{base}/admin/api.php?enable", timeout=5)
        db.audit_log("pihole_toggle", username, f"{action} (duration={duration}s)", _client_ip(request))
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Pi-hole toggle failed: %s", e)
        raise HTTPException(502, "Pi-hole toggle failed") from None


# ── /api/game-servers ─────────────────────────────────────────────────────────
@router.get("/api/game-servers")
@handle_errors
def api_game_servers(auth=Depends(_get_auth)):
    from ..metrics import probe_game_server, query_source_server
    cfg = read_yaml_settings()
    servers = cfg.get("gameServers", [])
    results = []
    for s in servers:
        host = s.get("host", "")
        port = int(s.get("port", 0))
        name = s.get("name", f"{host}:{port}")
        protocol = s.get("protocol", "tcp")
        if host and port:
            if protocol == "source":
                result = query_source_server(host, port)
            else:
                result = probe_game_server(host, port)
            result["name"] = name
            results.append(result)
    return results


# ── /api/wol ──────────────────────────────────────────────────────────────────
@router.post("/api/wol")
@handle_errors
async def api_wol(request: Request, auth=Depends(_require_operator)):
    from ..metrics import send_wol
    username, _ = auth
    body = await _read_body(request)
    mac = body.get("mac", "").strip()
    if not mac:
        raise HTTPException(400, "MAC address required")
    ok = send_wol(mac)
    db.audit_log("wol", username, f"WOL {mac} -> {ok}", _client_ip(request))
    return {"success": ok}


# ── /api/cloud-remotes ────────────────────────────────────────────────────────
@router.get("/api/cloud-remotes")
@handle_errors
def api_cloud_remotes(auth=Depends(_get_auth)):
    return get_rclone_remotes()


@router.post("/api/cloud-remotes/create")
@handle_errors
async def api_cloud_remote_create(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    body = await _read_body(request)
    name = body.get("name", "").strip()
    remote_type = body.get("type", "").strip()
    params = body.get("params", {})
    if not name or not remote_type:
        raise HTTPException(400, "Name and type are required")
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$', name):
        raise HTTPException(400, "Invalid remote name")
    cmd = ["rclone", "config", "create", name, remote_type]
    for k, v in params.items():
        if not re.match(r'^[a-zA-Z0-9_-]+$', str(k)):
            raise HTTPException(400, f"Invalid parameter key: {k}")
        sv = str(v)
        if not re.match(r'^[a-zA-Z0-9_./:@=, -]+$', sv):
            raise HTTPException(400, f"Invalid parameter value for {k}")
        cmd.append(f"{k}={sv}")
    try:
        r = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            raise HTTPException(422, r.stderr.strip()[:200] or "Failed to create remote")
        db.audit_log("cloud_remote_create", username, f"Created remote '{name}' ({remote_type})", _client_ip(request))
        return {"status": "ok"}
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Command timed out") from None
    except FileNotFoundError:
        raise HTTPException(424, "rclone not found") from None


@router.delete("/api/cloud-remotes/{name}")
@handle_errors
def api_cloud_remote_delete(name: str, request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$', name):
        raise HTTPException(400, "Invalid remote name")
    try:
        r = subprocess.run(["rclone", "config", "delete", name],
                          capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            raise HTTPException(422, "Failed to delete remote")
        db.audit_log("cloud_remote_delete", username, f"Deleted remote '{name}'", _client_ip(request))
        return {"status": "ok"}
    except FileNotFoundError:
        raise HTTPException(424, "rclone not found") from None


# ── /api/cloud-test ───────────────────────────────────────────────────────────
@router.post("/api/cloud-test")
@handle_errors
async def api_cloud_test(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    remote = body.get("remote", "").strip()
    if not remote or not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9 ._-]{0,63}$", remote):
        raise HTTPException(400, "Invalid remote name")
    try:
        r = await asyncio.to_thread(subprocess.run, ["rclone", "lsd", remote + ":", "--max-depth", "1"],
                           capture_output=True, text=True, timeout=15)
        err_line = next(
            (line for line in r.stderr.strip().splitlines() if line.strip() and not line.startswith("NOTICE")),
            r.stderr.strip()[:120],
        )
        success = r.returncode == 0
        db.audit_log("cloud_test", username, f"Remote {remote} -> {success}", ip)
        if not success:
            raise HTTPException(422, err_line or "Remote connection failed")
        return {"success": True}
    except subprocess.TimeoutExpired:
        db.audit_log("cloud_test", username, f"Remote {remote} timeout", ip)
        raise HTTPException(504, "Connection timed out (15s)") from None
    except FileNotFoundError:
        raise HTTPException(424, "rclone not found on this system") from None
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Cloud test error: %s", e)
        raise HTTPException(500, "Cloud test error") from None


# ── /api/influxdb/query ──────────────────────────────────────────────────────
@router.post("/api/influxdb/query")
@handle_errors
async def api_influxdb_query(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    query = body.get("query", "")
    if not query:
        raise HTTPException(400, "Query is required")
    cfg = read_yaml_settings()
    url = cfg.get("influxdbUrl", "")
    token = cfg.get("influxdbToken", "")
    org = cfg.get("influxdbOrg", "")
    if not url or not token:
        raise HTTPException(404, "InfluxDB not configured")
    from ..integrations import query_influxdb  # noqa: PLC0415
    db.audit_log("influxdb_query", username, query[:200], ip)
    result = query_influxdb(url, token, org, query)
    if result is None:
        raise HTTPException(502, "InfluxDB query failed")
    return result
