# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Agent management: report, list, detail, bulk command, WebSocket."""
from __future__ import annotations

import contextlib
import json
import logging
import secrets
import time
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from ..agent_config import (
    RISK_LEVELS,
    check_role_permission,
    validate_command_params,
)
from ..agent_store import (
    _AGENT_MAX_AGE,
    _COMMAND_DELIVERY_TIMEOUT,
    _STREAM_LINES_MAX,
    _agent_cmd_lock,
    _agent_cmd_ready,
    _agent_cmd_results,
    _agent_commands,
    _agent_data,
    _agent_data_lock,
    _agent_stream_lines,
    _agent_stream_lines_lock,
    _agent_websockets,
    _agent_ws_lock,
    _delivered_commands,
    notify_rdp_subscribers,
    notify_terminal_subscribers,
    pop_clipboard_request,
)
from ..constants import (
    STREAM_BUFFER_MAX,
    WS_CLOSE_NORMAL,
)
from ..deps import (
    _client_ip,
    _get_auth,
    _read_body,
    _require_operator,
    db,
    handle_errors,
)
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")
_ws_logger = logging.getLogger("noba.agent.ws")

_WEB_DIR = Path(__file__).resolve().parent.parent.parent  # share/noba-web/
_HOSTNAME_RE = __import__("re").compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$')
_HOSTNAME_WS_RE = __import__("re").compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,252}$')

router = APIRouter(tags=["agents"])


# ── Agent helpers ─────────────────────────────────────────────────────────────

def _validate_agent_key(key: str) -> bool:
    """Check an agent key against configured keys (shared by report + WebSocket)."""
    if not key:
        return False
    import secrets as _secrets
    cfg = read_yaml_settings()
    valid_keys = [k.strip() for k in cfg.get("agentKeys", "").split(",") if k.strip()]
    return any(_secrets.compare_digest(key, vk) for vk in valid_keys)


# ── Report sub-handlers ───────────────────────────────────────────────────────

def _store_capability_manifest(hostname: str, capabilities: dict | None) -> None:
    """Persist the agent capability manifest if present."""
    if not capabilities or not isinstance(capabilities, dict):
        return
    try:
        db.upsert_capability_manifest(hostname, json.dumps(capabilities))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to store capability manifest for %s: %s", hostname, exc)


def _record_security_scan(hostname: str, cr: dict) -> None:
    """Record a security scan result from a command result."""
    if cr.get("type") == "security_scan" and cr.get("status") == "ok":
        try:
            db.record_security_scan(
                hostname,
                int(cr.get("score", 0)),
                cr.get("findings", []),
            )
        except HTTPException:
            raise
        except Exception:
            pass


def _store_device_discovery(hostname: str, cr: dict) -> None:
    """Persist discovered network devices from a network_discover result."""
    if cr.get("type") != "network_discover" or cr.get("status") != "ok":
        return
    for dev in cr.get("devices", []):
        try:
            db.upsert_network_device(
                ip=dev.get("ip", ""),
                mac=dev.get("mac"),
                hostname=dev.get("hostname"),
                open_ports=dev.get("open_ports"),
                discovered_by=hostname,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Failed to persist discovered device: %s", e)


def _store_backup_verification(hostname: str, cr: dict) -> None:
    """Persist backup verification results from a verify_backup result."""
    if cr.get("type") != "verify_backup":
        return
    try:
        details = cr.get("details")
        db.record_backup_verification(
            backup_path=cr.get("path", ""),
            hostname=hostname,
            verification_type=cr.get("verification_type", ""),
            status=cr.get("status", "error"),
            details=json.dumps(details) if details else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Failed to persist backup verification: %s", e)


def _store_cmd_results(hostname: str, cmd_results: list | None) -> None:
    """Process and persist command results from an agent report."""
    if not cmd_results:
        return
    with _agent_cmd_ready:
        existing = _agent_cmd_results.get(hostname, [])
        existing.extend(cmd_results)
        _agent_cmd_results[hostname] = existing[-50:]
        _agent_cmd_ready.notify_all()
    for cr in cmd_results:
        cr_id = cr.get("id", "")
        if cr_id:
            db.complete_command(cr_id, cr)
        _record_security_scan(hostname, cr)
        _store_device_discovery(hostname, cr)
        _store_backup_verification(hostname, cr)


def _store_stream_data(stream_data: dict | None) -> None:
    """Buffer incoming stream lines from agent report payload."""
    if not stream_data or not isinstance(stream_data, dict):
        return
    with _agent_stream_lines_lock:
        for stream_id, lines in stream_data.items():
            if isinstance(lines, list):
                buf = _agent_stream_lines.setdefault(stream_id, [])
                buf.extend(lines)
                if len(buf) > _STREAM_LINES_MAX:
                    _agent_stream_lines[stream_id] = buf[-_STREAM_LINES_MAX:]


def _store_agent_metrics(hostname: str, body: dict) -> None:
    """Upsert agent record and insert CPU/mem/disk metrics."""
    try:
        db.upsert_agent(
            hostname=hostname,
            ip=body.get("_ip", ""),
            platform_name=body.get("platform", ""),
            arch=body.get("arch", ""),
            agent_version=body.get("agent_version", ""),
        )
    except HTTPException:
        raise
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
    except HTTPException:
        raise
    except Exception:
        pass


def _build_heal_policy(hostname: str) -> dict:
    """Build heal policy for an agent from alert rules config."""
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
        return build_agent_policy(hostname, rules_cfg, db)
    except HTTPException:
        raise
    except Exception:
        return {}


def _ingest_heal_reports(hostname: str, body: dict) -> None:
    """Ingest heal reports if present in the agent report body."""
    heal_reports = body.pop("_heal_reports", None)
    if not heal_reports or not isinstance(heal_reports, list):
        return
    try:
        from ..healing.agent_runtime import ingest_agent_heal_reports
        ingest_agent_heal_reports(hostname, heal_reports, db)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to ingest heal reports from %s: %s", hostname, exc)


def _check_auto_update(hostname: str, body: dict, pending: list) -> None:
    """Queue an auto-update command if the agent version is outdated."""
    agent_version = body.get("agent_version", "")
    if not agent_version or pending is None:
        return
    try:
        import zipfile
        server_agent_path = _WEB_DIR.parent / "noba-agent.pyz"
        server_version = None
        if server_agent_path.exists():
            # Combined nested context manager — single with-statement
            # closes both the zipfile and the inner stream on any exit path.
            with zipfile.ZipFile(server_agent_path) as zf, zf.open("__main__.py") as f:
                for raw in f:
                    line = raw.decode("utf-8", errors="replace")
                    if line.startswith("VERSION"):
                        server_version = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        if (
            server_version
            and server_version != agent_version
            and not any(c.get("type") == "update_agent" for c in pending)
        ):
            pending.append({
                "id": f"auto-update-{int(time.time())}",
                "type": "update_agent",
                "params": {},
                "queued_by": "auto-update",
                "queued_at": int(time.time()),
            })
            logger.info(
                "Auto-update queued for %s: %s -> %s",
                hostname, agent_version, server_version,
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Auto-update enqueue is best-effort — log so operators can notice
        # persistent failures but don't block agent check-in on it.
        logger.debug("Auto-update enqueue failed for %s: %s", hostname, exc)


# ── Agent endpoints ───────────────────────────────────────────────────────────
@router.post("/api/agent/report")
@handle_errors
async def api_agent_report(request: Request):
    """Receive metrics from a NOBA agent.  Auth via X-Agent-Key header."""
    key = request.headers.get("X-Agent-Key", "")
    if not key:
        raise HTTPException(401, "Missing X-Agent-Key")
    if not _validate_agent_key(key):
        raise HTTPException(403, "Invalid agent key")
    body = await _read_body(request)
    hostname = body.get("hostname", "unknown")[:253]
    if not _HOSTNAME_RE.match(hostname):
        raise HTTPException(400, "Invalid hostname")
    body["_received"] = time.time()
    body["_ip"] = _client_ip(request)

    _store_capability_manifest(hostname, body.pop("_capabilities", None))
    _store_cmd_results(hostname, body.pop("_cmd_results", None))
    _store_stream_data(body.pop("_stream_data", None))

    with _agent_data_lock:
        stale = [h for h, d in _agent_data.items() if time.time() - d.get("_received", 0) > 86400]
        for h in stale:
            del _agent_data[h]
        _agent_data[hostname] = body

    _store_agent_metrics(hostname, body)

    pending = []
    now = time.time()
    with _agent_cmd_lock:
        if hostname in _agent_commands:
            pending = _agent_commands.pop(hostname)
            # Track delivered commands for retry on failure
            for cmd in pending:
                cmd["delivered_at"] = now
            _delivered_commands.setdefault(hostname, []).extend(pending)
        # Confirm delivery for commands whose results have arrived
        cmd_results = body.get("cmd_results", [])
        if cmd_results and hostname in _delivered_commands:
            confirmed_ids = {r.get("id") for r in cmd_results if isinstance(r, dict)}
            _delivered_commands[hostname] = [
                c for c in _delivered_commands[hostname]
                if c.get("id") not in confirmed_ids
            ]
            if not _delivered_commands[hostname]:
                del _delivered_commands[hostname]
        # Re-queue commands that were delivered but never confirmed (timeout)
        if hostname in _delivered_commands:
            timed_out = [c for c in _delivered_commands[hostname]
                         if now - c.get("delivered_at", 0) > _COMMAND_DELIVERY_TIMEOUT]
            if timed_out:
                logger.warning("Agent %s: %d commands timed out without confirmation",
                               hostname, len(timed_out))
                _delivered_commands[hostname] = [
                    c for c in _delivered_commands[hostname] if c not in timed_out
                ]
                if not _delivered_commands[hostname]:
                    del _delivered_commands[hostname]
        # Clean stale pending queues
        stale_cmds = [h for h, cmds in _agent_commands.items()
                      if cmds and cmds[0].get("queued_at", 0) < now - 600]
        for h in stale_cmds:
            del _agent_commands[h]
    logger.info("Agent report", extra={"hostname": hostname, "ip": body.get("_ip")})

    heal_policy = _build_heal_policy(hostname)
    _ingest_heal_reports(hostname, body)
    _check_auto_update(hostname, body, pending)

    return {"status": "ok", "commands": pending, "heal_policy": heal_policy}


# ── WebSocket sub-handlers ────────────────────────────────────────────────────

def _handle_ws_result(hostname: str, msg: dict) -> None:
    """Process a command result received via agent WebSocket."""
    with _agent_cmd_ready:
        _agent_cmd_results.setdefault(hostname, []).append(msg)
        if len(_agent_cmd_results[hostname]) > 50:
            _agent_cmd_results[hostname] = _agent_cmd_results[hostname][-50:]
        _agent_cmd_ready.notify_all()
    notify_terminal_subscribers(hostname, msg)
    cmd_id = msg.get("id", "")
    if cmd_id:
        try:
            db.complete_command(cmd_id, msg)
        except HTTPException:
            raise
        except Exception:
            pass
    # Reuse report helpers for security scan / backup verification
    cmd_name = msg.get("cmd", "")
    # Translate WS result format to match report format for shared helpers
    compat = {**msg, "type": cmd_name}
    _record_security_scan(hostname, compat)
    _store_backup_verification(hostname, compat)


def _handle_ws_stream(hostname: str, msg: dict) -> None:
    """Buffer a stream message received via agent WebSocket."""
    cmd_id = msg.get("id", "")
    with _agent_cmd_lock:
        stream_key = f"_stream_{hostname}_{cmd_id}"
        buf = _agent_cmd_results.setdefault(stream_key, [])
        buf.append(msg)
        if len(buf) > STREAM_BUFFER_MAX:
            _agent_cmd_results[stream_key] = buf[-STREAM_BUFFER_MAX:]
    notify_terminal_subscribers(hostname, msg)


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
        if not hostname or not _HOSTNAME_WS_RE.match(hostname):
            await ws.close(code=4002, reason="Invalid or missing hostname")
            return

        with _agent_ws_lock:
            old = _agent_websockets.get(hostname)
            _agent_websockets[hostname] = ws
        if old:
            try:
                await old.close(code=WS_CLOSE_NORMAL, reason="Replaced by new connection")
            except HTTPException:
                raise
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
                _handle_ws_result(hostname, msg)

            elif msg_type == "stream":
                _handle_ws_stream(hostname, msg)

            elif msg_type in ("pty_output", "pty_exit", "pty_opened", "pty_error"):
                # Forward PTY messages to browser terminal subscribers
                notify_terminal_subscribers(hostname, msg)

            elif msg_type in ("rdp_frame", "rdp_unavailable"):
                # Fan out screen frames and unavailability notices to all viewers
                notify_rdp_subscribers(hostname, msg)

            elif msg_type == "rdp_clipboard":
                # Route clipboard response only to the viewer that requested it
                req_id = msg.get("_req_id")
                if req_id:
                    target_q = pop_clipboard_request(req_id)
                    if target_q is not None:
                        import asyncio as _asyncio
                        with contextlib.suppress(_asyncio.QueueFull):
                            target_q.put_nowait(msg)
                else:
                    # No request_id — fall back to broadcast (older agents)
                    notify_rdp_subscribers(hostname, msg)

            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except HTTPException:
        raise
    except Exception as exc:
        _ws_logger.warning("[ws] Error for %s: %s", hostname, exc)
    finally:
        if hostname:
            with _agent_ws_lock:
                if _agent_websockets.get(hostname) is ws:
                    del _agent_websockets[hostname]
            _ws_logger.info("[ws] Agent %s disconnected", hostname)


@router.get("/api/agents")
@handle_errors
def api_agents(auth=Depends(_get_auth)):
    """List all reporting agents and their latest metrics."""
    now = time.time()
    with _agent_data_lock:
        agents = []
        for _hostname, data in sorted(_agent_data.items()):
            age = now - data.get("_received", 0)
            agents.append({
                **{k: v for k, v in data.items() if not k.startswith("_")},
                "online": age < _AGENT_MAX_AGE,
                "last_seen_s": int(age),
            })
    return agents


@router.get("/api/agents/{hostname}")
@handle_errors
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
@handle_errors
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
