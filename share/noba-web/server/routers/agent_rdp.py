# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Agent remote desktop browser WebSocket endpoint."""
from __future__ import annotations

import asyncio
import contextlib
import secrets

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..agent_store import (
    _agent_websockets,
    _agent_ws_lock,
    _rdp_sub_lock,
    _rdp_subscribers,
    register_clipboard_request,
)
from ..constants import RDP_QUEUE_MAXSIZE
from ..deps import check_ws_origin, ws_token_store

logger = __import__("logging").getLogger("noba.agent.rdp")

router = APIRouter(tags=["agents"])


@router.websocket("/api/agents/{hostname}/rdp")
async def agent_rdp_ws(hostname: str, ws: WebSocket):
    """Browser-facing WebSocket for remote desktop viewing/control of an agent.

    Auth: query param ``token`` (same pattern as terminal WS — EventSource cannot
    set custom headers so we fall back to URL-param tokens here too).

    Viewers receive ``rdp_frame`` messages with base64-encoded PNG frames.
    Operators/admins may additionally send ``rdp_input`` messages to inject
    mouse/keyboard events on the remote machine.

    Multiple viewers can connect simultaneously — the agent captures once and the
    server fans frames out to all subscribers (same pattern as terminal PTY output).
    """
    # CSWSH protection: reject WebSocket connections from cross-origin pages
    # BEFORE accept(). Must run first because ws.close() only works after
    # the handshake is complete, and rejecting here means the browser
    # attacker page gets an immediate 403 instead of a live WS handle.
    if not check_ws_origin(
        ws.headers.get("origin", ""),
        ws.headers.get("host", ""),
    ):
        await ws.close(code=4003, reason="Origin not allowed")
        return

    token = ws.query_params.get("token", "")
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return

    username, role = ws_token_store.consume(token)
    if not username:
        await ws.close(code=4001, reason="Invalid or expired token")
        return

    # RDP desktop viewing requires at least operator role
    if role not in ("operator", "admin"):
        await ws.close(code=4003, reason="Operator access required")
        return

    await ws.accept()

    q: asyncio.Queue = asyncio.Queue(maxsize=RDP_QUEUE_MAXSIZE)
    with _rdp_sub_lock:
        _rdp_subscribers.setdefault(hostname, []).append(q)

    async def _forward_frames() -> None:
        """Drain the frame queue and push frames to the browser."""
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

    forward_task = asyncio.create_task(_forward_frames())

    # Tell the agent to start capturing.  If the agent is not connected via WS
    # yet, the rdp_start will arrive as soon as it connects (commands are queued).
    quality = max(10, min(100, int(ws.query_params.get("quality", 70))))
    fps = max(1, min(30, int(ws.query_params.get("fps", 5))))
    with _agent_ws_lock:
        agent_ws = _agent_websockets.get(hostname)
    if agent_ws:
        with contextlib.suppress(Exception):
            await agent_ws.send_json({"type": "rdp_start", "quality": quality, "fps": fps})

    # Notify browser of session parameters
    await ws.send_json({"type": "rdp_ready", "hostname": hostname, "quality": quality, "fps": fps})

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            if msg_type in ("rdp_input", "rdp_clipboard_paste", "rdp_clipboard_get"):
                # Only operators/admins may inject input or use the clipboard bridge
                if role in ("operator", "admin"):
                    with _agent_ws_lock:
                        agent_ws = _agent_websockets.get(hostname)
                    if agent_ws:
                        try:
                            if msg_type == "rdp_clipboard_get":
                                # Tag the request so the response is routed back
                                # only to this viewer, not broadcast to all.
                                req_id = secrets.token_hex(8)
                                register_clipboard_request(req_id, q)
                                await agent_ws.send_json({**data, "_req_id": req_id})
                            else:
                                await agent_ws.send_json(data)
                        except Exception:
                            pass

            elif msg_type == "rdp_quality":
                # Browser can adjust quality mid-session
                new_quality = max(10, min(100, int(data.get("quality", quality))))
                new_fps = max(1, min(30, int(data.get("fps", fps))))
                with _agent_ws_lock:
                    agent_ws = _agent_websockets.get(hostname)
                if agent_ws:
                    with contextlib.suppress(Exception):
                        await agent_ws.send_json({
                            "type": "rdp_start",
                            "quality": new_quality,
                            "fps": new_fps,
                        })

    except WebSocketDisconnect:
        pass
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[rdp] Browser error for %s: %s", hostname, exc)
    finally:
        forward_task.cancel()

        remaining = 0
        with _rdp_sub_lock:
            subs = _rdp_subscribers.get(hostname, [])
            if q in subs:
                subs.remove(q)
            remaining = len(subs)
            if not subs:
                _rdp_subscribers.pop(hostname, None)

        # Stop agent capture when the last viewer disconnects
        if remaining == 0:
            with _agent_ws_lock:
                agent_ws = _agent_websockets.get(hostname)
            if agent_ws:
                with contextlib.suppress(Exception):
                    await agent_ws.send_json({"type": "rdp_stop"})
        logger.debug("[rdp] Browser disconnected from %s (%d viewers remaining)", hostname, remaining)
