# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Embedded terminal via WebSocket + PTY."""
from __future__ import annotations

import asyncio
import fcntl
import json as _json
import logging
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import threading
import time

from fastapi import WebSocket, WebSocketDisconnect

from .deps import db

logger = logging.getLogger("noba")

MAX_SESSION_SECONDS = int(os.environ.get("NOBA_TERMINAL_TIMEOUT", 1800))
TERMINAL_ENABLED = os.environ.get("NOBA_TERMINAL_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)


async def terminal_handler(ws: WebSocket, username: str, role: str = "admin") -> None:
    """Handle a WebSocket terminal session."""
    if not TERMINAL_ENABLED:
        await ws.close(code=4003, reason="Terminal disabled")
        return

    await ws.accept()

    client_ip = ""
    if ws.client:
        client_ip = ws.client.host or ""

    start_time = time.time()
    logger.info("Terminal session started: user=%s, role=%s, ip=%s", username, role, client_ip)
    db.audit_log("terminal_session_start", username, f"PTY session opened (role={role})", client_ip)

    # Create PTY
    master_fd, slave_fd = pty.openpty()
    shell = os.environ.get("SHELL", "/bin/bash")
    env = {
        **os.environ,
        "TERM": "xterm-256color",
        "COLUMNS": "120",
        "LINES": "30",
    }

    proc = subprocess.Popen(
        [shell, "-l"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        start_new_session=True,
        env=env,
        close_fds=True,
    )
    os.close(slave_fd)

    # Set master_fd to non-blocking
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    shutdown = threading.Event()

    async def read_pty() -> None:
        """Read from PTY and send to WebSocket."""
        loop = asyncio.get_event_loop()
        try:
            while not shutdown.is_set() and proc.poll() is None:
                try:
                    r, _, _ = await loop.run_in_executor(
                        None, lambda: select.select([master_fd], [], [], 0.1)
                    )
                    if r:
                        data = os.read(master_fd, 4096)
                        if data:
                            await ws.send_bytes(data)
                except OSError:
                    break
        except (WebSocketDisconnect, Exception):
            pass

    async def write_pty() -> None:
        """Read from WebSocket and write to PTY."""
        try:
            while not shutdown.is_set() and proc.poll() is None:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                data = msg.get("bytes") or (
                    msg.get("text", "").encode() if msg.get("text") else None
                )
                if not data:
                    continue
                # Check for resize command
                if data.startswith(b"{"):
                    try:
                        cmd = _json.loads(data)
                        if cmd.get("type") == "resize":
                            cols = int(cmd.get("cols", 120))
                            rows = int(cmd.get("rows", 30))
                            winsize = struct.pack("HHHH", rows, cols, 0, 0)
                            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                            continue
                    except (ValueError, _json.JSONDecodeError):
                        pass
                os.write(master_fd, data)
        except (WebSocketDisconnect, Exception):
            pass

    async def timeout_guard() -> None:
        """Kill session after MAX_SESSION_SECONDS."""
        await asyncio.sleep(MAX_SESSION_SECONDS)
        shutdown.set()

    try:
        done, pending = await asyncio.wait(
            [
                asyncio.create_task(read_pty()),
                asyncio.create_task(write_pty()),
                asyncio.create_task(timeout_guard()),
            ],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    finally:
        shutdown.set()
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
                proc.wait(timeout=2)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            await ws.close()
        except Exception:
            pass
        duration = int(time.time() - start_time)
        logger.info("Terminal session ended: user=%s, duration=%ds", username, duration)
        db.audit_log("terminal_session_end", username, f"PTY session closed (duration={duration}s)", client_ip)
