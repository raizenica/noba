# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Agent browser terminal WebSocket endpoint."""
from __future__ import annotations

import asyncio
import secrets
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..agent_config import RISK_LEVELS, check_role_permission
from ..agent_store import (
    _agent_cmd_lock,
    _agent_commands,
    _agent_websockets,
    _agent_ws_lock,
    _terminal_sub_lock,
    _terminal_subscribers,
)
from ..constants import TERMINAL_QUEUE_MAXSIZE
from ..deps import check_ws_origin, db, ws_token_store

logger = __import__("logging").getLogger("noba.agent.ws")

router = APIRouter(tags=["agents"])


# ── PTY helpers ──────────────────────────────────────────────────────────────

async def _forward_pty_to_agent(hostname: str, data: dict, role: str, ws: WebSocket) -> None:
    """Forward a PTY message from the browser terminal to the agent WebSocket."""
    if data.get("type") == "pty_open":
        data["role"] = role
    with _agent_ws_lock:
        agent_ws = _agent_websockets.get(hostname)
    if agent_ws:
        try:
            await agent_ws.send_json(data)
        except HTTPException:
            raise
        except Exception:
            await ws.send_json({"type": "pty_error", "error": "Agent WebSocket disconnected"})
    else:
        await ws.send_json({"type": "pty_error", "error": "Agent not connected via WebSocket"})


async def _dispatch_terminal_command(
    hostname: str, ws: WebSocket, data: dict, role: str, username: str,
) -> None:
    """Validate and dispatch a command from the browser terminal to the agent."""
    cmd_type = data.get("type", "exec")
    params = data.get("params", {})
    if cmd_type == "exec" and "command" in data:
        params = {"command": data["command"], "timeout": data.get("timeout", 30)}

    risk = RISK_LEVELS.get(cmd_type)
    if not risk:
        await ws.send_json({"type": "error", "error": f"Unknown command: {cmd_type}"})
        return
    if not check_role_permission(role, risk):
        await ws.send_json({"type": "error", "error": f"Insufficient permissions for {cmd_type}"})
        return

    cmd_id = secrets.token_hex(8)
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
        except HTTPException:
            raise
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


# ── Browser terminal WebSocket ───────────────────────────────────────────────

@router.websocket("/api/agents/{hostname}/terminal")
async def agent_terminal_ws(hostname: str, ws: WebSocket):
    """Browser-facing WebSocket for real-time terminal interaction with an agent."""
    # CSWSH protection: reject cross-origin WebSocket connections BEFORE
    # any authentication work happens. Must run first because an attacker
    # page opening a WS against this endpoint would otherwise reach the
    # token consume stage with a one-shot URL-param token stolen via some
    # other vector.
    if not check_ws_origin(
        ws.headers.get("origin", ""),
        ws.headers.get("host", ""),
    ):
        await ws.close(code=4003, reason="Origin not allowed")
        return

    # Auth via query param token (WebSocket can't set headers)
    token = ws.query_params.get("token", "")
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return
    username, role = ws_token_store.consume(token)
    if not username:
        await ws.close(code=4001, reason="Invalid or expired token")
        return
    if role not in ("operator", "admin"):
        await ws.close(code=4003, reason="Operator access required")
        return

    await ws.accept()

    # Subscribe to agent results
    q: asyncio.Queue = asyncio.Queue(maxsize=TERMINAL_QUEUE_MAXSIZE)
    with _terminal_sub_lock:
        _terminal_subscribers.setdefault(hostname, []).append(q)

    async def forward_results():
        """Forward agent results to browser."""
        try:
            while True:
                msg = await q.get()
                try:
                    await ws.send_json(msg)
                except HTTPException:
                    raise
                except Exception:
                    break
        except asyncio.CancelledError:
            pass
        except HTTPException:
            raise
        except Exception:
            pass

    forward_task = asyncio.create_task(forward_results())

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "exec")

            if msg_type in ("pty_open", "pty_input", "pty_resize", "pty_close"):
                await _forward_pty_to_agent(hostname, data, role, ws)
                continue

            await _dispatch_terminal_command(hostname, ws, data, role, username)

    except WebSocketDisconnect:
        pass
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[terminal] Error for %s: %s", hostname, exc)
    finally:
        # Close any PTY sessions opened through this terminal
        with _agent_ws_lock:
            agent_ws = _agent_websockets.get(hostname)
        if agent_ws:
            try:
                await agent_ws.send_json({"type": "pty_close", "session": f"term-{hostname}"})
            except HTTPException:
                raise
            except Exception:
                pass
        forward_task.cancel()
        with _terminal_sub_lock:
            subs = _terminal_subscribers.get(hostname, [])
            if q in subs:
                subs.remove(q)
            if not subs:
                _terminal_subscribers.pop(hostname, None)
