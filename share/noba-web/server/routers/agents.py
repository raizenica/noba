"""Noba – Agent management: CRUD, commands, WebSocket, deploy, file transfer."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from ..agent_config import (
    RISK_LEVELS, check_role_permission, get_agent_capabilities,
    validate_command_params,
)
from ..agent_store import (
    _agent_cmd_lock, _agent_cmd_results, _agent_commands,
    _agent_data, _agent_data_lock, _AGENT_MAX_AGE,
    _agent_stream_lines, _agent_stream_lines_lock, _STREAM_LINES_MAX,
    _agent_streams, _agent_streams_lock,
    _agent_websockets, _agent_ws_lock,
    _terminal_subscribers, _terminal_sub_lock,
    notify_terminal_subscribers,
    _CHUNK_SIZE, _MAX_TRANSFER_SIZE, _TRANSFER_DIR,
    _transfer_lock, _transfers,
)
from ..deps import (
    _client_ip, _get_auth, _read_body,
    _require_admin, _require_operator, _safe_int, db,
)
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")
_ws_logger = logging.getLogger("noba.agent.ws")

_WEB_DIR = Path(__file__).resolve().parent.parent.parent  # share/noba-web/

router = APIRouter(tags=["agents"])


# ── Agent helpers ─────────────────────────────────────────────────────────────

def _validate_agent_key(key: str) -> bool:
    """Check an agent key against configured keys (shared by report + WebSocket)."""
    if not key:
        return False
    cfg = read_yaml_settings()
    valid_keys = [k.strip() for k in cfg.get("agentKeys", "").split(",") if k.strip()]
    return bool(valid_keys and key in valid_keys)


# ── Agent endpoints ───────────────────────────────────────────────────────────
@router.post("/api/agent/report")
async def api_agent_report(request: Request):
    """Receive metrics from a NOBA agent.  Auth via X-Agent-Key header."""
    key = request.headers.get("X-Agent-Key", "")
    if not key:
        raise HTTPException(401, "Missing X-Agent-Key")
    cfg = read_yaml_settings()
    valid_keys = [k.strip() for k in cfg.get("agentKeys", "").split(",") if k.strip()]
    if not valid_keys or key not in valid_keys:
        raise HTTPException(403, "Invalid agent key")
    body = await _read_body(request)
    hostname = body.get("hostname", "unknown")[:253]
    body["_received"] = time.time()
    body["_ip"] = _client_ip(request)
    cmd_results = body.pop("_cmd_results", None)
    if cmd_results:
        with _agent_cmd_lock:
            existing = _agent_cmd_results.get(hostname, [])
            existing.extend(cmd_results)
            # Keep only last 50 results
            _agent_cmd_results[hostname] = existing[-50:]
        for cr in cmd_results:
            cr_id = cr.get("id", "")
            if cr_id:
                db.complete_command(cr_id, cr)
            # Auto-record security scan results
            if cr.get("type") == "security_scan" and cr.get("status") == "ok":
                try:
                    db.record_security_scan(
                        hostname,
                        int(cr.get("score", 0)),
                        cr.get("findings", []),
                    )
                except Exception:
                    pass
            # Persist discovered network devices
            if cr.get("type") == "network_discover" and cr.get("status") == "ok":
                for dev in cr.get("devices", []):
                    try:
                        db.upsert_network_device(
                            ip=dev.get("ip", ""),
                            mac=dev.get("mac"),
                            hostname=dev.get("hostname"),
                            open_ports=dev.get("open_ports"),
                            discovered_by=hostname,
                        )
                    except Exception as e:
                        logger.warning("Failed to persist discovered device: %s", e)
            # Persist backup verification results
            if cr.get("type") == "verify_backup":
                try:
                    details = cr.get("details")
                    db.record_backup_verification(
                        backup_path=cr.get("path", ""),
                        hostname=hostname,
                        verification_type=cr.get("verification_type", ""),
                        status=cr.get("status", "error"),
                        details=json.dumps(details) if details else None,
                    )
                except Exception as e:
                    logger.warning("Failed to persist backup verification: %s", e)
    # Store stream data if present
    stream_data = body.pop("_stream_data", None)
    if stream_data and isinstance(stream_data, dict):
        with _agent_stream_lines_lock:
            for stream_id, lines in stream_data.items():
                if isinstance(lines, list):
                    buf = _agent_stream_lines.setdefault(stream_id, [])
                    buf.extend(lines)
                    # Trim to max size
                    if len(buf) > _STREAM_LINES_MAX:
                        _agent_stream_lines[stream_id] = buf[-_STREAM_LINES_MAX:]
    with _agent_data_lock:
        stale = [h for h, d in _agent_data.items() if time.time() - d.get("_received", 0) > 86400]
        for h in stale:
            del _agent_data[h]
        _agent_data[hostname] = body
    try:
        db.upsert_agent(
            hostname=hostname,
            ip=body.get("_ip", ""),
            platform_name=body.get("platform", ""),
            arch=body.get("arch", ""),
            agent_version=body.get("agent_version", ""),
        )
    except Exception:
        pass
    try:
        agent_metrics = [
            (f"agent_{hostname}_cpu", body.get("cpu_percent", 0), ""),
            (f"agent_{hostname}_mem", body.get("mem_percent", 0), ""),
        ]
        for disk in body.get("disks", [])[:1]:
            agent_metrics.append((f"agent_{hostname}_disk", disk.get("percent", 0), disk.get("mount", "/")))
        db.insert_metrics(agent_metrics)
    except Exception:
        pass
    pending = []
    with _agent_cmd_lock:
        if hostname in _agent_commands:
            pending = _agent_commands.pop(hostname)
        stale_cmds = [h for h, cmds in _agent_commands.items()
                      if cmds and cmds[0].get("queued_at", 0) < time.time() - 600]
        for h in stale_cmds:
            del _agent_commands[h]
    logger.info("Agent report", extra={"hostname": hostname, "ip": body.get("_ip")})

    # Include heal policy if available
    heal_policy = {}
    try:
        from ..healing.agent_runtime import build_agent_policy
        cfg = read_yaml_settings()
        alert_rules = cfg.get("alertRules", [])
        rules_cfg = {}
        for rule in alert_rules:
            rid = rule.get("id", "")
            if rid:
                rules_cfg[rid] = {
                    "escalation_chain": rule.get("escalation_chain", []),
                    "condition": rule.get("condition", ""),
                }
        heal_policy = build_agent_policy(hostname, rules_cfg, db)
    except Exception:
        pass

    # Ingest heal reports if present
    heal_reports = body.pop("_heal_reports", None)
    if heal_reports and isinstance(heal_reports, list):
        try:
            from ..healing.agent_runtime import ingest_agent_heal_reports
            ingest_agent_heal_reports(hostname, heal_reports, db)
        except Exception as exc:
            logger.warning("Failed to ingest heal reports from %s: %s", hostname, exc)

    return {"status": "ok", "commands": pending, "heal_policy": heal_policy}


# ── Agent WebSocket (Phase 1b) ───────────────────────────────────────────────

@router.websocket("/api/agent/ws")
async def agent_websocket(ws: WebSocket):
    """WebSocket endpoint for real-time agent communication."""
    key = ws.query_params.get("key", "")
    if not _validate_agent_key(key):
        await ws.close(code=4001, reason="Invalid agent key")
        return

    await ws.accept()
    hostname = None
    try:
        ident = await ws.receive_json()
        if ident.get("type") != "identify":
            await ws.close(code=4002, reason="Expected identify message")
            return
        hostname = ident.get("hostname", "")
        if not hostname:
            await ws.close(code=4002, reason="No hostname")
            return

        with _agent_ws_lock:
            old = _agent_websockets.get(hostname)
            _agent_websockets[hostname] = ws
        if old:
            try:
                await old.close(code=1000, reason="Replaced by new connection")
            except Exception:
                pass

        _ws_logger.info("[ws] Agent %s connected via WebSocket", hostname)

        # Send any queued commands immediately
        with _agent_cmd_lock:
            queued = _agent_commands.pop(hostname, [])
        for cmd in queued:
            await ws.send_json({"type": "command", "id": cmd.get("id", ""),
                                "cmd": cmd.get("type", ""), "params": cmd.get("params", {})})

        while True:
            msg = await ws.receive_json()
            msg_type = msg.get("type", "")

            # Detect results from old agents (pre-fix): the "type" key
            # contains the command name instead of "result" due to a dict
            # unpacking collision.  Normalise so the rest of the handler
            # works identically for old and new agents.
            is_result = msg_type == "result"
            if not is_result and msg_type in RISK_LEVELS and "id" in msg:
                # Old-format result: {"type": "disk_usage", "id": "...", ...}
                is_result = True
                msg["cmd"] = msg_type       # stash command type
                msg["type"] = "result"      # fix discriminator
                msg_type = "result"

            if is_result:
                with _agent_cmd_lock:
                    _agent_cmd_results.setdefault(hostname, []).append(msg)
                    if len(_agent_cmd_results[hostname]) > 50:
                        _agent_cmd_results[hostname] = _agent_cmd_results[hostname][-50:]
                # Forward to browser terminal subscribers
                notify_terminal_subscribers(hostname, msg)
                # Complete command in history DB (same as HTTP report path)
                cmd_id = msg.get("id", "")
                if cmd_id:
                    try:
                        db.complete_command(cmd_id, msg)
                    except Exception:
                        pass
                # Auto-record security scan results via WebSocket
                cmd_name = msg.get("cmd", "")
                if cmd_name == "security_scan" and msg.get("status") == "ok":
                    try:
                        db.record_security_scan(
                            hostname,
                            int(msg.get("score", 0)),
                            msg.get("findings", []),
                        )
                    except Exception:
                        pass
                # Auto-record backup verification results via WebSocket
                if cmd_name == "verify_backup":
                    try:
                        details = msg.get("details")
                        db.record_backup_verification(
                            backup_path=msg.get("path", ""),
                            hostname=hostname,
                            verification_type=msg.get("verification_type", ""),
                            status=msg.get("status", "error"),
                            details=json.dumps(details) if details else None,
                        )
                    except Exception:
                        pass

            elif msg_type == "stream":
                cmd_id = msg.get("id", "")
                with _agent_cmd_lock:
                    stream_key = f"_stream_{hostname}_{cmd_id}"
                    buf = _agent_cmd_results.setdefault(stream_key, [])
                    buf.append(msg)
                    if len(buf) > 500:
                        _agent_cmd_results[stream_key] = buf[-500:]
                # Forward stream lines to browser terminal
                notify_terminal_subscribers(hostname, msg)

            elif msg_type in ("pty_output", "pty_exit", "pty_opened", "pty_error"):
                # Forward PTY messages to browser terminal subscribers
                notify_terminal_subscribers(hostname, msg)

            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        _ws_logger.warning("[ws] Error for %s: %s", hostname, exc)
    finally:
        if hostname:
            with _agent_ws_lock:
                if _agent_websockets.get(hostname) is ws:
                    del _agent_websockets[hostname]
            _ws_logger.info("[ws] Agent %s disconnected", hostname)


@router.websocket("/api/agents/{hostname}/terminal")
async def agent_terminal_ws(hostname: str, ws: WebSocket):
    """Browser-facing WebSocket for real-time terminal interaction with an agent."""
    import asyncio

    # Auth via query param token (WebSocket can't set headers)
    token = ws.query_params.get("token", "")
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return
    from ..deps import token_store
    username, role = token_store.validate(token)
    if not username:
        await ws.close(code=4001, reason="Invalid token")
        return
    if role not in ("operator", "admin"):
        await ws.close(code=4003, reason="Operator access required")
        return

    await ws.accept()

    # Subscribe to agent results
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    with _terminal_sub_lock:
        _terminal_subscribers.setdefault(hostname, []).append(q)

    async def forward_results():
        """Forward agent results to browser."""
        try:
            while True:
                msg = await q.get()
                try:
                    await ws.send_json(msg)
                except Exception:
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    forward_task = asyncio.create_task(forward_results())

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "exec")

            # PTY messages — forward directly to agent WS
            if msg_type in ("pty_open", "pty_input", "pty_resize", "pty_close"):
                with _agent_ws_lock:
                    agent_ws = _agent_websockets.get(hostname)
                if agent_ws:
                    try:
                        await agent_ws.send_json(data)
                    except Exception:
                        await ws.send_json({"type": "pty_error", "error": "Agent WebSocket disconnected"})
                else:
                    await ws.send_json({"type": "pty_error", "error": "Agent not connected via WebSocket"})
                continue

            # Regular command execution
            cmd_type = msg_type
            params = data.get("params", {})
            if cmd_type == "exec" and "command" in data:
                params = {"command": data["command"], "timeout": data.get("timeout", 30)}

            # Validate
            risk = RISK_LEVELS.get(cmd_type)
            if not risk:
                await ws.send_json({"type": "error", "error": f"Unknown command: {cmd_type}"})
                continue
            if not check_role_permission(role, risk):
                await ws.send_json({"type": "error", "error": f"Insufficient permissions for {cmd_type}"})
                continue

            cmd_id = secrets.token_hex(8)
            # Try agent WebSocket first
            delivered = False
            with _agent_ws_lock:
                agent_ws = _agent_websockets.get(hostname)
            if agent_ws:
                try:
                    await agent_ws.send_json({
                        "type": "command", "id": cmd_id,
                        "cmd": cmd_type, "params": params,
                    })
                    delivered = True
                except Exception:
                    with _agent_ws_lock:
                        _agent_websockets.pop(hostname, None)

            if not delivered:
                cmd = {"id": cmd_id, "type": cmd_type, "params": params,
                       "queued_by": username, "queued_at": int(time.time())}
                with _agent_cmd_lock:
                    _agent_commands.setdefault(hostname, []).append(cmd)

            db.record_command(cmd_id, hostname, cmd_type, params, username)
            await ws.send_json({
                "type": "ack", "id": cmd_id,
                "delivery": "websocket" if delivered else "queued",
            })

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        _ws_logger.warning("[terminal] Error for %s: %s", hostname, exc)
    finally:
        # Close any PTY sessions opened through this terminal
        with _agent_ws_lock:
            agent_ws = _agent_websockets.get(hostname)
        if agent_ws:
            try:
                await agent_ws.send_json({"type": "pty_close", "session": f"term-{hostname}"})
            except Exception:
                pass
        forward_task.cancel()
        with _terminal_sub_lock:
            subs = _terminal_subscribers.get(hostname, [])
            if q in subs:
                subs.remove(q)
            if not subs:
                _terminal_subscribers.pop(hostname, None)


@router.get("/api/agents/{hostname}/stream/{cmd_id}")
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


@router.get("/api/agents")
def api_agents(auth=Depends(_get_auth)):
    """List all reporting agents and their latest metrics."""
    now = time.time()
    with _agent_data_lock:
        agents = []
        for hostname, data in sorted(_agent_data.items()):
            age = now - data.get("_received", 0)
            agents.append({
                **{k: v for k, v in data.items() if not k.startswith("_")},
                "online": age < _AGENT_MAX_AGE,
                "last_seen_s": int(age),
            })
    return agents


@router.get("/api/agents/command-history")
def api_command_history(request: Request, auth=Depends(_get_auth)):
    """Get command execution history, optionally filtered by hostname."""
    hostname = request.query_params.get("hostname", "")
    limit = min(int(request.query_params.get("limit", "50")), 200)
    return db.get_command_history(hostname=hostname or None, limit=limit)


@router.get("/api/agents/{hostname}")
def api_agent_detail(hostname: str, auth=Depends(_get_auth)):
    """Get detailed metrics for a specific agent."""
    with _agent_data_lock:
        data = _agent_data.get(hostname)
    if not data:
        raise HTTPException(404, "Agent not found")
    age = time.time() - data.get("_received", 0)
    with _agent_cmd_lock:
        cmd_results = _agent_cmd_results.get(hostname, [])
    return {
        **{k: v for k, v in data.items() if not k.startswith("_")},
        "online": age < _AGENT_MAX_AGE,
        "last_seen_s": int(age),
        "cmd_results": cmd_results,
    }


@router.post("/api/agents/bulk-command")
async def api_bulk_command(request: Request, auth=Depends(_require_operator)):
    """Send a command to multiple agents at once."""
    username, role = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    hostnames = body.get("hostnames", [])
    cmd_type = body.get("type", "")
    params = body.get("params", {})

    risk = RISK_LEVELS.get(cmd_type)
    if not risk:
        raise HTTPException(400, f"Unknown command type: {cmd_type!r}")
    if not check_role_permission(role, risk):
        raise HTTPException(403, "Insufficient permissions")
    err = validate_command_params(cmd_type, params)
    if err:
        raise HTTPException(400, err)

    if not hostnames:
        with _agent_data_lock:
            hostnames = list(_agent_data.keys())

    results = {}
    for hostname in hostnames:
        cmd_id = secrets.token_hex(8)
        cmd = {"id": cmd_id, "type": cmd_type, "params": params,
               "queued_by": username, "queued_at": int(time.time())}
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)
        results[hostname] = cmd_id
    db.audit_log("agent_bulk_command", username,
                 f"type={cmd_type} targets={len(hostnames)}", ip)
    return {"status": "queued", "commands": results}


@router.post("/api/agents/{hostname}/command")
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


@router.post("/api/agents/{hostname}/uninstall")
async def api_agent_uninstall(hostname: str, request: Request, auth=Depends(_require_admin)):
    """Queue uninstall command and mark agent for removal."""
    username, _ = auth
    ip = _client_ip(request)
    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": "uninstall_agent", "params": {"confirm": True},
           "queued_by": username, "queued_at": int(time.time())}
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)
    db.audit_log("agent_uninstall", username, f"host={hostname} id={cmd_id}", ip)
    return {"status": "queued", "id": cmd_id}


@router.delete("/api/agents/{hostname}")
def api_agent_delete(hostname: str, request: Request, auth=Depends(_require_admin)):
    """Remove an agent from the dashboard (DB + in-memory). Admin only."""
    username, _ = auth
    ip = _client_ip(request)
    with _agent_data_lock:
        _agent_data.pop(hostname, None)
    with _agent_cmd_lock:
        _agent_commands.pop(hostname, None)
        _agent_cmd_results.pop(hostname, None)
    with _agent_ws_lock:
        _agent_websockets.pop(hostname, None)
    db.delete_agent(hostname)
    db.audit_log("agent_delete", username, f"host={hostname}", ip)
    return {"status": "ok"}


@router.get("/api/agents/{hostname}/results")
def api_agent_results(hostname: str, auth=Depends(_get_auth)):
    """Get command execution results for an agent."""
    with _agent_cmd_lock:
        return _agent_cmd_results.get(hostname, [])


@router.get("/api/agents/{hostname}/history")
def api_agent_history(hostname: str, request: Request, auth=Depends(_get_auth)):
    """Get historical metrics for an agent (CPU, RAM, disk)."""
    hours = min(int(request.query_params.get("hours", "24")), 168)
    metric = request.query_params.get("metric", "cpu")
    metric_key = f"agent_{hostname}_{metric}"
    return db.get_history(metric_key, range_hours=hours, resolution=120)


# ── Network traffic analysis endpoint ─────────────────────────────────────────

@router.post("/api/agents/{hostname}/network-stats")
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
            import asyncio
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
                        # Store interface metrics for trending
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
                        except Exception:
                            pass
                        db.audit_log("agent_network_stats", username,
                                     f"host={hostname} id={cmd_id}", ip)
                        return result
                await asyncio.sleep(0.1)
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
async def api_agent_stream_logs(hostname: str, request: Request, auth=Depends(_require_admin)):
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
async def api_agent_stop_stream(hostname: str, cmd_id: str, auth=Depends(_require_admin)):
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
def api_agent_active_streams(hostname: str, auth=Depends(_get_auth)):
    """List active log streams for an agent."""
    with _agent_streams_lock:
        streams = _agent_streams.get(hostname, {})
    return {"streams": [{"stream_id": sid, **info} for sid, info in streams.items()]}


@router.get("/api/sla/summary")
def api_sla_summary(request: Request, auth=Depends(_get_auth)):
    """SLA uptime summary across all agents and key services."""
    hours = min(int(request.query_params.get("hours", "720")), 8760)
    incidents = db.get_incidents(limit=1000, hours=hours)
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


@router.get("/api/agent/update")
def api_agent_update(request: Request):
    """Serve the latest agent.py for self-update. Auth via X-Agent-Key."""
    key = request.headers.get("X-Agent-Key", "")
    if not key:
        raise HTTPException(401, "Missing X-Agent-Key")
    cfg = read_yaml_settings()
    valid_keys = [k.strip() for k in cfg.get("agentKeys", "").split(",") if k.strip()]
    if not valid_keys or key not in valid_keys:
        raise HTTPException(403, "Invalid agent key")
    agent_path = _WEB_DIR.parent / "noba-agent" / "agent.py"
    if not agent_path.exists():
        raise HTTPException(404, "Agent file not found")
    return FileResponse(agent_path, media_type="text/x-python")


@router.get("/api/agent/install-script")
def api_agent_install_script(request: Request):
    """Generate a one-liner install script. Auth via X-Agent-Key."""
    key = request.headers.get("X-Agent-Key", "") or request.query_params.get("key", "")
    if not key:
        raise HTTPException(401, "Missing agent key")
    cfg = read_yaml_settings()
    valid_keys = [k.strip() for k in cfg.get("agentKeys", "").split(",") if k.strip()]
    if not valid_keys or key not in valid_keys:
        raise HTTPException(403, "Invalid agent key")
    host = request.headers.get("X-Forwarded-Host", request.headers.get("Host", "localhost:8080"))
    scheme = request.headers.get("X-Forwarded-Proto", "http")
    server_url = f"{scheme}://{host}"
    script = f"""#!/bin/bash
# NOBA Agent -- Auto-installer
set -e
INSTALL_DIR="/opt/noba-agent"
SERVER="{server_url}"
KEY="{key}"
HOSTNAME="$(hostname)"

echo "[noba] Installing agent on $HOSTNAME..."
sudo mkdir -p "$INSTALL_DIR"
curl -sf "$SERVER/api/agent/update" -H "X-Agent-Key: $KEY" -o "$INSTALL_DIR/agent.py"
sudo chmod +x "$INSTALL_DIR/agent.py"

# Install psutil if possible
command -v apt-get &>/dev/null && sudo apt-get install -y python3-psutil 2>/dev/null || true
command -v dnf &>/dev/null && sudo dnf install -y python3-psutil 2>/dev/null || true

# Write config
sudo tee /etc/noba-agent.yaml > /dev/null <<EOF
server: $SERVER
api_key: $KEY
interval: 30
hostname: $HOSTNAME
EOF

# Install systemd service
sudo tee /etc/systemd/system/noba-agent.service > /dev/null <<EOF
[Unit]
Description=NOBA Agent
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=$(command -v python3) $INSTALL_DIR/agent.py --config /etc/noba-agent.yaml
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now noba-agent
echo "[noba] Agent installed and running on $HOSTNAME"
"""
    return Response(content=script, media_type="text/x-shellscript",
                    headers={"Content-Disposition": "inline"})


@router.post("/api/agents/deploy")
async def api_agent_deploy(request: Request, auth=Depends(_require_admin)):
    """Remote deploy: SSH into a node and install the agent."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    target_host = body.get("host", "")
    ssh_user = body.get("ssh_user", "")
    ssh_pass = body.get("ssh_pass", "")
    target_port = _safe_int(body.get("ssh_port", 22), 22)
    if target_port < 1 or target_port > 65535:
        target_port = 22

    if not target_host or not ssh_user:
        raise HTTPException(400, "host and ssh_user are required")

    if not re.match(r'^[a-zA-Z0-9._:-]+$', target_host):
        raise HTTPException(400, "Invalid hostname")
    if not re.match(r'^[a-zA-Z0-9._-]+$', ssh_user) or len(ssh_user) > 64:
        raise HTTPException(400, "Invalid ssh_user")

    cfg = read_yaml_settings()
    agent_keys = cfg.get("agentKeys", "")
    if not agent_keys:
        raise HTTPException(400, "No agent keys configured. Set agentKeys in settings first.")
    agent_key = agent_keys.split(",")[0].strip()

    # Validate server_url from config rather than trusting the Host header
    server_url = cfg.get("serverUrl", "").strip()
    if not server_url:
        host_header = request.headers.get("Host", "localhost:8080")
        server_url = f"http://{host_header}"
    if not re.match(r'^https?://[a-zA-Z0-9._:/-]+$', server_url):
        raise HTTPException(400, "Invalid serverUrl configuration")

    agent_path = _WEB_DIR.parent / "noba-agent" / "agent.py"
    if not agent_path.exists():
        raise HTTPException(500, "Agent file not found on server")

    import shutil
    if ssh_pass and not shutil.which("sshpass"):
        raise HTTPException(400, "sshpass not installed on server. Use the install script method instead.")

    target = f"{ssh_user}@{target_host}"
    env = {**os.environ, "SSHPASS": ssh_pass} if ssh_pass else os.environ

    # Build list-form commands (no shell=True) to prevent shell injection
    _ssh_common = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
    if ssh_pass:
        scp_cmd = ["sshpass", "-e", "scp", "-P", str(target_port)] + _ssh_common
        ssh_cmd = ["sshpass", "-e", "ssh", "-p", str(target_port)] + _ssh_common
    else:
        scp_cmd = ["scp", "-P", str(target_port)] + _ssh_common
        ssh_cmd = ["ssh", "-p", str(target_port)] + _ssh_common

    try:
        result = subprocess.run(
            scp_cmd + [str(agent_path), f"{target}:/tmp/noba-agent.py"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if result.returncode != 0:
            return {"status": "error", "step": "copy", "error": result.stderr[:500]}

        install_cmds = f"""
sudo mkdir -p /opt/noba-agent
sudo cp /tmp/noba-agent.py /opt/noba-agent/agent.py
sudo chmod +x /opt/noba-agent/agent.py
command -v apt-get >/dev/null && sudo apt-get install -y python3-psutil 2>/dev/null || true
command -v dnf >/dev/null && sudo dnf install -y python3-psutil 2>/dev/null || true
sudo tee /etc/noba-agent.yaml > /dev/null <<AGENTCFG
server: {server_url}
api_key: {agent_key}
interval: 30
hostname: $(hostname)
AGENTCFG
sudo tee /etc/systemd/system/noba-agent.service > /dev/null <<SVC
[Unit]
Description=NOBA Agent
After=network-online.target
[Service]
Type=simple
ExecStart=$(command -v python3 || echo /usr/bin/python3) /opt/noba-agent/agent.py --config /etc/noba-agent.yaml
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
SVC
sudo systemctl daemon-reload
sudo systemctl enable --now noba-agent 2>&1
systemctl is-active noba-agent
"""
        result = subprocess.run(
            ssh_cmd + [target, "bash", "-s"],
            input=install_cmds, capture_output=True, text=True,
            timeout=60, env=env,
        )
        success = "active" in result.stdout
        db.audit_log("agent_deploy", username, f"host={target_host} user={ssh_user} ok={success}", ip)
        return {
            "status": "ok" if success else "error",
            "host": target_host,
            "output": result.stdout[:1000],
            "error": result.stderr[:500] if not success else "",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "SSH connection timed out"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── File transfer endpoints (Phase 1c) ──────────────────────────────────────
@router.post("/api/agent/file-upload")
async def api_agent_file_upload(request: Request):
    """Receive a file chunk from an agent."""
    key = request.headers.get("X-Agent-Key", "")
    if not _validate_agent_key(key):
        raise HTTPException(401, "Invalid agent key")

    transfer_id = request.headers.get("X-Transfer-Id", "")
    chunk_index_raw = request.headers.get("X-Chunk-Index", "-1")
    total_chunks_raw = request.headers.get("X-Total-Chunks", "0")
    filename = os.path.basename(request.headers.get("X-Filename", "unknown"))
    if not filename or filename.startswith("."):
        filename = "unknown"
    checksum = request.headers.get("X-File-Checksum", "")
    hostname = request.headers.get("X-Agent-Hostname", "unknown")

    try:
        chunk_index = int(chunk_index_raw)
        total_chunks = int(total_chunks_raw)
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid chunk headers")

    if not transfer_id or chunk_index < 0 or total_chunks <= 0:
        raise HTTPException(400, "Missing transfer headers")

    body = await request.body()
    if len(body) > _CHUNK_SIZE + 1024:
        raise HTTPException(413, "Chunk too large")

    # Initialize transfer on first chunk
    with _transfer_lock:
        if transfer_id not in _transfers:
            _transfers[transfer_id] = {
                "hostname": hostname,
                "filename": filename,
                "checksum": checksum,
                "total_chunks": total_chunks,
                "received_chunks": set(),
                "created_at": int(time.time()),
                "direction": "upload",
            }

    # Write chunk to disk
    chunk_path = os.path.join(_TRANSFER_DIR, f"{transfer_id}.chunk{chunk_index}")
    with open(chunk_path, "wb") as f:
        f.write(body)

    with _transfer_lock:
        _transfers[transfer_id]["received_chunks"].add(chunk_index)
        received = len(_transfers[transfer_id]["received_chunks"])
        complete = received == total_chunks

    result: dict = {"status": "ok", "received": chunk_index, "progress": f"{received}/{total_chunks}"}

    # If all chunks received, reassemble and verify
    if complete:
        final_path = os.path.join(_TRANSFER_DIR, f"{transfer_id}_{filename}")
        with open(final_path, "wb") as out:
            for i in range(total_chunks):
                cp = os.path.join(_TRANSFER_DIR, f"{transfer_id}.chunk{i}")
                with open(cp, "rb") as chunk_f:
                    out.write(chunk_f.read())
                os.remove(cp)

        # Verify checksum
        if checksum.startswith("sha256:"):
            expected = checksum.split(":", 1)[1]
            h = hashlib.sha256()
            with open(final_path, "rb") as f:
                while True:
                    block = f.read(65536)
                    if not block:
                        break
                    h.update(block)
            actual = h.hexdigest()
            if actual != expected:
                os.remove(final_path)
                with _transfer_lock:
                    _transfers.pop(transfer_id, None)
                raise HTTPException(422, f"Checksum mismatch: expected {expected}, got {actual}")

        with _transfer_lock:
            _transfers[transfer_id]["final_path"] = final_path
            _transfers[transfer_id]["complete"] = True

        result["complete"] = True
        result["path"] = final_path

    return result


@router.get("/api/agent/file-download/{transfer_id}")
async def api_agent_file_download(transfer_id: str, request: Request):
    """Serve a file to an agent for file_push command."""
    key = request.headers.get("X-Agent-Key", "")
    if not _validate_agent_key(key):
        raise HTTPException(401, "Invalid agent key")

    with _transfer_lock:
        transfer = _transfers.get(transfer_id)
    if not transfer:
        raise HTTPException(404, "Transfer not found")
    if transfer.get("direction") != "download":
        raise HTTPException(400, "Not a download transfer")

    file_path = transfer.get("final_path", "")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(404, "File not found")

    return FileResponse(
        file_path,
        filename=transfer.get("filename", "download"),
        media_type="application/octet-stream",
        headers={"X-File-Checksum": transfer.get("checksum", "")},
    )


@router.post("/api/agents/{hostname}/transfer")
async def api_agent_transfer(hostname: str, request: Request, auth=Depends(_require_admin)):
    """Initiate a file push to an agent. Admin uploads the file first."""
    username, _ = auth
    ip = _client_ip(request)

    dest_path = request.query_params.get("path", "")
    if not dest_path:
        raise HTTPException(400, "Destination path required (?path=...)")

    body = await request.body()
    if len(body) > _MAX_TRANSFER_SIZE:
        raise HTTPException(413, f"File too large (max {_MAX_TRANSFER_SIZE // 1024 // 1024}MB)")

    checksum = f"sha256:{hashlib.sha256(body).hexdigest()}"

    transfer_id = secrets.token_hex(16)
    filename = os.path.basename(dest_path) or "file"
    file_path = os.path.join(_TRANSFER_DIR, f"{transfer_id}_{filename}")
    with open(file_path, "wb") as f:
        f.write(body)

    with _transfer_lock:
        _transfers[transfer_id] = {
            "hostname": hostname,
            "filename": filename,
            "checksum": checksum,
            "final_path": file_path,
            "created_at": int(time.time()),
            "direction": "download",
            "dest_path": dest_path,
            "complete": True,
        }

    # Queue file_push command for the agent
    cmd_id = secrets.token_hex(8)
    cmd = {
        "id": cmd_id,
        "type": "file_push",
        "params": {"path": dest_path, "transfer_id": transfer_id},
        "queued_by": username,
        "queued_at": int(time.time()),
    }

    # Try WebSocket first, fall back to queue
    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"type": "command", "cmd": "file_push", **cmd})
            delivered = True
        except Exception:
            pass
    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)

    db.audit_log("agent_file_push", username,
                 f"host={hostname} path={dest_path} id={transfer_id}", ip)
    return {"status": "queued", "transfer_id": transfer_id, "cmd_id": cmd_id}
