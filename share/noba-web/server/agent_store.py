"""Noba – Shared agent data stores and their locks."""
from __future__ import annotations

import os
import tempfile
import threading

from starlette.websockets import WebSocket

_agent_data: dict[str, dict] = {}
_agent_data_lock = threading.Lock()
_AGENT_MAX_AGE = 120  # Consider agent offline after 2 minutes
_agent_commands: dict[str, list] = {}  # hostname -> pending commands
_agent_cmd_results: dict[str, list] = {}  # hostname -> recent results
_agent_cmd_lock = threading.Lock()

# WebSocket connection registry (Phase 1b)
_agent_websockets: dict[str, WebSocket] = {}  # hostname -> active WebSocket
_agent_ws_lock = threading.Lock()

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
