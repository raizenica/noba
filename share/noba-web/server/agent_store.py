"""Noba – Shared agent data stores and their locks."""
from __future__ import annotations

import logging
import os
import secrets
import tempfile
import threading
import time

from starlette.websockets import WebSocket

logger = logging.getLogger("noba")

_agent_data: dict[str, dict] = {}
_agent_data_lock = threading.Lock()
_AGENT_MAX_AGE = 120  # Consider agent offline after 2 minutes
_agent_commands: dict[str, list] = {}  # hostname -> pending commands
_agent_cmd_results: dict[str, list] = {}  # hostname -> recent results
_agent_cmd_lock = threading.Lock()

# WebSocket connection registry (Phase 1b)
_agent_websockets: dict[str, WebSocket] = {}  # hostname -> active WebSocket
_agent_ws_lock = threading.Lock()

# Browser terminal WebSocket subscribers: {hostname: [asyncio.Queue, ...]}
_terminal_subscribers: dict[str, list] = {}
_terminal_sub_lock = threading.Lock()


def notify_terminal_subscribers(hostname: str, msg: dict) -> None:
    """Push a message to all browser terminal WS subscribers for a hostname."""
    with _terminal_sub_lock:
        subs = _terminal_subscribers.get(hostname, [])
        dead: list = []
        for q in subs:
            try:
                q.put_nowait(msg)
            except Exception:
                dead.append(q)
        for q in dead:
            subs.remove(q)


# ── Live log stream state ─────────────────────────────────────────────────────
# Buffered stream lines from agents: {stream_id: [line, ...]}
_agent_stream_lines: dict[str, list[str]] = {}
_agent_stream_lines_lock = threading.Lock()
_STREAM_LINES_MAX = 2000  # Max total lines kept per stream
# Active log stream tracking: {hostname: {stream_id: {"started": timestamp}}}
_agent_streams: dict[str, dict[str, dict]] = {}
_agent_streams_lock = threading.Lock()

# ── File transfer state (Phase 1c) ──────────────────────────────────────────
_TRANSFER_DIR = os.path.join(tempfile.gettempdir(), "noba-transfers")
_MAX_TRANSFER_SIZE = 50 * 1024 * 1024  # 50 MB
_CHUNK_SIZE = 256 * 1024  # 256 KB
_TRANSFER_MAX_AGE = 3600  # 1 hour cleanup

# Active transfers: transfer_id -> {hostname, filename, checksum, total_chunks,
#                                    received_chunks: set, created_at, direction}
_transfers: dict[str, dict] = {}
_transfer_lock = threading.Lock()

os.makedirs(_TRANSFER_DIR, exist_ok=True)


# ── Agent command helpers ────────────────────────────────────────────────────

def get_online_agents() -> list[str]:
    """Return hostnames of all agents seen within the max-age window."""
    now = time.time()
    with _agent_data_lock:
        return [
            h for h, d in _agent_data.items()
            if now - d.get("_received", 0) < _AGENT_MAX_AGE
        ]


def queue_agent_command(hostname: str, cmd_type: str, params: dict,
                        queued_by: str = "system") -> str:
    """Queue a command for a single agent and return the generated cmd_id."""
    cmd_id = secrets.token_hex(8)
    cmd = {
        "id": cmd_id,
        "type": cmd_type,
        "params": params,
        "queued_by": queued_by,
        "queued_at": int(time.time()),
    }
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)
    return cmd_id


def _poll_result(hostname: str, cmd_id: str, timeout: float) -> dict | None:
    """Poll _agent_cmd_results until a result with matching cmd_id appears."""
    deadline = time.monotonic() + timeout
    interval = 0.25
    while time.monotonic() < deadline:
        with _agent_cmd_lock:
            results = _agent_cmd_results.get(hostname, [])
            for r in results:
                if r.get("id") == cmd_id:
                    return r
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
        interval = min(interval * 1.5, 2.0)  # back off gently
    return None


def queue_agent_command_and_wait(
    hostname: str,
    cmd_type: str,
    params: dict,
    timeout: float = 30,
    queued_by: str = "system",
) -> dict | None:
    """Queue a command and block until a result arrives (or timeout).

    If *hostname* is ``"__all__"``, the command is broadcast to every online
    agent and a dict of ``{hostname: result_or_None}`` is returned instead.

    Returns the result dict for a single host, or ``None`` on timeout.
    """
    if hostname == "__all__":
        targets = get_online_agents()
        if not targets:
            logger.warning("agent_command __all__: no online agents")
            return None
        aggregate: dict[str, dict | None] = {}
        for h in targets:
            aggregate[h] = queue_agent_command_and_wait(
                h, cmd_type, params, timeout=timeout, queued_by=queued_by,
            )
        return {"__all__": True, "results": aggregate}

    cmd_id = queue_agent_command(hostname, cmd_type, params, queued_by)
    logger.info("Queued agent_command %s on %s (id=%s), waiting %ss",
                cmd_type, hostname, cmd_id, timeout)
    result = _poll_result(hostname, cmd_id, timeout)
    if result is None:
        logger.warning("agent_command %s on %s timed out (id=%s)",
                       cmd_type, hostname, cmd_id)
    return result
