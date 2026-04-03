# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Security posture scoring and scanning endpoints."""
from __future__ import annotations

import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ..agent_config import RISK_LEVELS, check_role_permission
from ..agent_store import (
    _agent_cmd_lock, _agent_commands,
    _agent_data, _agent_data_lock, _AGENT_MAX_AGE,
    _agent_websockets, _agent_ws_lock,
)
from ..deps import _client_ip, _get_auth, _read_body, _require_admin, _require_operator, _safe_int, db, handle_errors

logger = logging.getLogger("noba")

router = APIRouter(tags=["security"])


@router.get("/api/security/score")
@handle_errors
def api_security_score(auth=Depends(_get_auth)):
    """Return aggregate security score + per-agent scores."""
    return db.get_aggregate_security_score()


@router.get("/api/security/findings")
@handle_errors
def api_security_findings(request: Request, auth=Depends(_get_auth)):
    """Return security findings with optional hostname/severity filters."""
    hostname = request.query_params.get("hostname", "") or None
    severity = request.query_params.get("severity", "") or None
    limit = min(_safe_int(request.query_params.get("limit", "200"), 200), 500)
    return db.get_security_findings(hostname=hostname, severity=severity, limit=limit)


@router.get("/api/security/history")
@handle_errors
def api_security_history(request: Request, auth=Depends(_get_auth)):
    """Return historical security scores for charting."""
    hostname = request.query_params.get("hostname", "") or None
    limit = min(_safe_int(request.query_params.get("limit", "50"), 50), 200)
    return db.get_security_score_history(hostname=hostname, limit=limit)


@router.post("/api/security/scan/{hostname}")
@handle_errors
async def api_security_scan(hostname: str, request: Request, auth=Depends(_require_operator)):
    """Trigger a security scan on a specific agent."""
    username, role = auth
    ip = _client_ip(request)
    cmd_type = "security_scan"
    risk = RISK_LEVELS.get(cmd_type, "low")
    if not check_role_permission(role, risk):
        raise HTTPException(403, "Insufficient permissions")

    with _agent_data_lock:
        agent = _agent_data.get(hostname)
    if not agent:
        raise HTTPException(404, f"Agent '{hostname}' not found")

    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": cmd_type, "params": {},
           "queued_by": username, "queued_at": int(time.time())}

    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"type": "command", "id": cmd_id,
                                "cmd": cmd_type, "params": {}})
            delivered = True
        except HTTPException:
            raise
        except Exception:
            with _agent_ws_lock:
                _agent_websockets.pop(hostname, None)

    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)

    db.record_command(cmd_id, hostname, cmd_type, {}, username)
    db.audit_log("security_scan", username,
                 f"host={hostname} id={cmd_id} ws={delivered}", ip)
    return {"status": "sent" if delivered else "queued", "id": cmd_id, "hostname": hostname}


@router.post("/api/security/scan-all")
@handle_errors
async def api_security_scan_all(request: Request, auth=Depends(_require_operator)):
    """Trigger security scan on all online agents."""
    username, role = auth
    ip = _client_ip(request)
    cmd_type = "security_scan"
    risk = RISK_LEVELS.get(cmd_type, "low")
    if not check_role_permission(role, risk):
        raise HTTPException(403, "Insufficient permissions")

    now = time.time()
    results = {}
    with _agent_data_lock:
        online = [
            h for h, d in _agent_data.items()
            if (now - d.get("_received", 0)) < _AGENT_MAX_AGE
        ]

    for hostname in online:
        cmd_id = secrets.token_hex(8)
        cmd = {"id": cmd_id, "type": cmd_type, "params": {},
               "queued_by": username, "queued_at": int(time.time())}

        delivered = False
        with _agent_ws_lock:
            ws = _agent_websockets.get(hostname)
        if ws:
            try:
                await ws.send_json({"type": "command", "id": cmd_id,
                                    "cmd": cmd_type, "params": {}})
                delivered = True
            except HTTPException:
                raise
            except Exception:
                with _agent_ws_lock:
                    _agent_websockets.pop(hostname, None)

        if not delivered:
            with _agent_cmd_lock:
                _agent_commands.setdefault(hostname, []).append(cmd)

        db.record_command(cmd_id, hostname, cmd_type, {}, username)
        results[hostname] = {"id": cmd_id, "websocket": delivered}

    db.audit_log("security_scan_all", username,
                 f"targets={len(online)}", ip)
    return {"status": "queued", "agents": results, "count": len(online)}


@router.post("/api/security/record")
@handle_errors
async def api_security_record(request: Request, auth=Depends(_require_admin)):
    """Record security scan results from an agent (called internally after scan completes)."""
    body = await _read_body(request)
    hostname = body.get("hostname", "")
    score = body.get("score")
    findings = body.get("findings", [])
    if not hostname or score is None:
        raise HTTPException(400, "hostname and score are required")
    db.record_security_scan(hostname, int(score), findings)
    return {"status": "ok"}
