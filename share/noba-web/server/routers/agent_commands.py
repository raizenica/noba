# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Agent commands, results, streaming, and SLA endpoints."""
from __future__ import annotations

import asyncio
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ..agent_config import (
    RISK_LEVELS,
    check_role_permission,
    get_agent_capabilities,
    validate_command_params,
)
from ..agent_store import (
    _agent_cmd_lock,
    _agent_cmd_results,
    _agent_commands,
    _agent_data,
    _agent_data_lock,
    _agent_stream_lines,
    _agent_stream_lines_lock,
    _agent_streams,
    _agent_streams_lock,
    _agent_websockets,
    _agent_ws_lock,
)
from ..constants import (
    COMMAND_HISTORY_LIMIT,
    SLA_INCIDENT_LIMIT,
)
from ..deps import (
    _client_ip,
    _get_auth,
    _int_param,
    _read_body,
    _require_operator,
    _safe_int,
    db,
    handle_errors,
)

logger = __import__("logging").getLogger("noba")

router = APIRouter(tags=["agents"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _store_interface_metrics(hostname: str, result: dict) -> None:
    """Store per-interface byte counters from a network_stats result."""
    try:
        iface_metrics = []
        for iface in result.get("interfaces", []):
            iname = iface.get("name", "").replace(".", "_")
            iface_metrics.append(
                (f"net_if_{hostname}_{iname}_rx", iface.get("rx_bytes", 0), "")
            )
            iface_metrics.append(
                (f"net_if_{hostname}_{iname}_tx", iface.get("tx_bytes", 0), "")
            )
        if iface_metrics:
            db.insert_metrics(iface_metrics)
    except HTTPException:
        raise
    except Exception:
        pass


# ── Command endpoints ────────────────────────────────────────────────────────

@router.post("/api/agents/{hostname}/command")
@handle_errors
async def api_agent_command(hostname: str, request: Request, auth=Depends(_require_operator)):
    """Queue a command for an agent. Risk-tiered authorization."""
    username, role = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    cmd_type = body.get("type", "")
    params = body.get("params", {})

    risk = RISK_LEVELS.get(cmd_type)
    if not risk:
        raise HTTPException(400, f"Unknown command type: {cmd_type!r}")
    if not check_role_permission(role, risk):
        raise HTTPException(403, f"Insufficient permissions: {cmd_type} requires {risk} access")

    with _agent_data_lock:
        agent = _agent_data.get(hostname)
    if agent:
        version = agent.get("agent_version", "1.1.0")
        caps = get_agent_capabilities(version)
        if cmd_type not in caps:
            raise HTTPException(400, f"Agent v{version} does not support '{cmd_type}'")

    err = validate_command_params(cmd_type, params)
    if err:
        raise HTTPException(400, err)

    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": cmd_type, "params": params,
           "queued_by": username, "queued_at": int(time.time())}

    # Dual-path: try WebSocket first, fall back to queue
    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"type": "command", "id": cmd_id,
                                "cmd": cmd_type, "params": params})
            delivered = True
        except HTTPException:
            raise
        except Exception:
            with _agent_ws_lock:
                _agent_websockets.pop(hostname, None)

    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)

    db.record_command(cmd_id, hostname, cmd_type, params, username)
    db.audit_log("agent_command", username,
                 f"host={hostname} type={cmd_type} id={cmd_id} ws={delivered}", ip)
    return {"status": "sent" if delivered else "queued", "id": cmd_id, "websocket": delivered}


@router.get("/api/agents/{hostname}/results")
@handle_errors
def api_agent_results(hostname: str, auth=Depends(_require_operator)):
    """Get command execution results for an agent."""
    with _agent_cmd_lock:
        return _agent_cmd_results.get(hostname, [])


@router.get("/api/agents/{hostname}/history")
@handle_errors
def api_agent_history(hostname: str, request: Request, auth=Depends(_get_auth)):
    """Get historical metrics for an agent (CPU, RAM, disk)."""
    hours = _int_param(request, "hours", 24, 1, 168)
    metric = request.query_params.get("metric", "cpu")
    metric_key = f"agent_{hostname}_{metric}"
    return db.get_history(metric_key, range_hours=hours, resolution=120)


# ── Network traffic analysis endpoint ────────────────────────────────────────

@router.post("/api/agents/{hostname}/network-stats")
@handle_errors
async def api_agent_network_stats(hostname: str, request: Request, auth=Depends(_require_operator)):
    """Trigger network_stats command on an agent and return the results.

    Sends the command via WebSocket if the agent is connected, otherwise
    queues it for the next poll.  The endpoint also stores per-interface
    byte counters as metrics for historical trending.
    """
    username, role = auth
    ip = _client_ip(request)

    risk = RISK_LEVELS.get("network_stats", "low")
    if not check_role_permission(role, risk):
        raise HTTPException(403, "Insufficient permissions")

    # Check agent existence
    with _agent_data_lock:
        agent = _agent_data.get(hostname)
    if not agent:
        raise HTTPException(404, f"Agent '{hostname}' not found or offline")

    version = agent.get("agent_version", "1.1.0")
    caps = get_agent_capabilities(version)
    if "network_stats" not in caps:
        raise HTTPException(400, f"Agent v{version} does not support 'network_stats'")

    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": "network_stats", "params": {},
           "queued_by": username, "queued_at": int(time.time())}

    # Try WebSocket first for instant results
    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"type": "command", "id": cmd_id,
                                "cmd": "network_stats", "params": {}})
            delivered = True
            # Wait for result (up to 5s)
            for _ in range(50):
                with _agent_cmd_lock:
                    results = _agent_cmd_results.get(hostname, [])
                    match = [r for r in results if r.get("id") == cmd_id]
                    if match:
                        result = match[0]
                        _store_interface_metrics(hostname, result)
                        db.audit_log("agent_network_stats", username,
                                     f"host={hostname} id={cmd_id}", ip)
                        return result
                await asyncio.sleep(0.1)
        except HTTPException:
            raise
        except Exception:
            delivered = False

    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)

    db.record_command(cmd_id, hostname, "network_stats", {}, username)
    db.audit_log("agent_network_stats", username,
                 f"host={hostname} id={cmd_id} ws={delivered}", ip)
    return {"status": "queued", "id": cmd_id, "message": "Command queued; check results endpoint."}


# ── Agent log streaming endpoints ────────────────────────────────────────────

@router.post("/api/agents/{hostname}/stream-logs")
@handle_errors
async def api_agent_stream_logs(hostname: str, request: Request, auth=Depends(_require_operator)):
    """Start a live log stream on a remote agent via follow_logs command."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    unit = body.get("unit", "")
    priority = body.get("priority", "")
    lines = _safe_int(body.get("lines", 50), 50)
    cmd_id = secrets.token_hex(8)
    cmd = {
        "id": cmd_id, "type": "follow_logs",
        "params": {"unit": unit, "priority": priority, "lines": lines},
        "queued_by": username, "queued_at": int(time.time()),
    }
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)
    with _agent_streams_lock:
        _agent_streams.setdefault(hostname, {})[cmd_id] = {"started": int(time.time())}
    db.audit_log("agent_stream_logs", username, f"host={hostname} id={cmd_id} unit={unit}", ip)
    return {"status": "queued", "stream_id": cmd_id}


@router.delete("/api/agents/{hostname}/stream-logs/{cmd_id}")
@handle_errors
async def api_agent_stop_stream(hostname: str, cmd_id: str, auth=Depends(_require_operator)):
    """Stop a running log stream on a remote agent."""
    username, _ = auth
    stop_id = secrets.token_hex(8)
    cmd = {
        "id": stop_id, "type": "stop_stream",
        "params": {"stream_id": cmd_id},
        "queued_by": username, "queued_at": int(time.time()),
    }
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)
    with _agent_streams_lock:
        host_streams = _agent_streams.get(hostname, {})
        host_streams.pop(cmd_id, None)
    # Clean up server-side line buffer
    with _agent_stream_lines_lock:
        _agent_stream_lines.pop(cmd_id, None)
    return {"status": "queued", "id": stop_id}


@router.get("/api/agents/{hostname}/streams")
@handle_errors
def api_agent_active_streams(hostname: str, auth=Depends(_get_auth)):
    """List active log streams for an agent."""
    with _agent_streams_lock:
        streams = _agent_streams.get(hostname, {})
    return {"streams": [{"stream_id": sid, **info} for sid, info in streams.items()]}


@router.get("/api/agents/{hostname}/stream/{cmd_id}")
@handle_errors
def api_agent_stream(hostname: str, cmd_id: str, request: Request, auth=Depends(_require_operator)):
    """Poll for new log stream lines (or WebSocket stream output).

    Supports cursor-based polling via ``?after=N`` query parameter.
    Returns only new lines since cursor position and the updated cursor.
    """
    # First check if this is a live log stream
    after = _safe_int(request.query_params.get("after", "0"), 0)
    with _agent_stream_lines_lock:
        all_lines = _agent_stream_lines.get(cmd_id)
    if all_lines is not None:
        with _agent_stream_lines_lock:
            all_lines = _agent_stream_lines.get(cmd_id, [])
            new_lines = all_lines[after:]
            total = len(all_lines)
        with _agent_streams_lock:
            host_streams = _agent_streams.get(hostname, {})
            active = cmd_id in host_streams
        return {"lines": new_lines, "cursor": total, "active": active}
    # Stream registered but no data yet — still active, waiting for agent
    with _agent_streams_lock:
        host_streams = _agent_streams.get(hostname, {})
        if cmd_id in host_streams:
            return {"lines": [], "cursor": 0, "active": True}
    # Fall back to WebSocket command stream output
    stream_key = f"_stream_{hostname}_{cmd_id}"
    with _agent_cmd_lock:
        ws_data = _agent_cmd_results.get(stream_key, [])
    return {"lines": ws_data, "cursor": len(ws_data), "active": bool(ws_data)}


@router.get("/api/agents/command-history")
@handle_errors
def api_command_history(request: Request, auth=Depends(_get_auth)):
    """Get command execution history, optionally filtered by hostname."""
    hostname = request.query_params.get("hostname", "")
    limit = _int_param(request, "limit", 50, 1, COMMAND_HISTORY_LIMIT)
    return db.get_command_history(hostname=hostname or None, limit=limit)


@router.get("/api/sla/summary")
@handle_errors
def api_sla_summary(request: Request, auth=Depends(_get_auth)):
    """SLA uptime summary across all agents and key services."""
    hours = _int_param(request, "hours", 720, 1, 8760)
    incidents = db.get_incidents(limit=SLA_INCIDENT_LIMIT, hours=hours)
    total_seconds = hours * 3600
    downtime_by_source: dict[str, int] = {}
    for inc in incidents:
        source = inc.get("source", "unknown")
        duration = (inc.get("resolved_at") or int(time.time())) - inc.get("timestamp", 0)
        downtime_by_source[source] = downtime_by_source.get(source, 0) + max(duration, 0)
    sla = []
    with _agent_data_lock:
        for hostname in _agent_data:
            down = downtime_by_source.get(hostname, 0)
            uptime_pct = round(max(0, (total_seconds - down) / total_seconds * 100), 2)
            sla.append({"name": hostname, "type": "agent", "uptime_pct": uptime_pct,
                        "downtime_s": down, "incidents": sum(1 for i in incidents if i.get("source") == hostname)})
    for source, down in downtime_by_source.items():
        if not any(s["name"] == source for s in sla):
            uptime_pct = round(max(0, (total_seconds - down) / total_seconds * 100), 2)
            sla.append({"name": source, "type": "service", "uptime_pct": uptime_pct,
                        "downtime_s": down, "incidents": sum(1 for i in incidents if i.get("source") == source)})
    sla.sort(key=lambda s: s["uptime_pct"])
    return {"period_hours": hours, "sla": sla}
