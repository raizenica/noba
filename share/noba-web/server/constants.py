# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Centralized constants for magic numbers used across the backend."""
from __future__ import annotations

# ── Admin router: upload / truncation limits ─────────────────────────────────
CONFIG_UPLOAD_MAX_BYTES = 512 * 1024          # max config restore upload size
SNAPSHOT_LIST_LIMIT = 200                     # max snapshots returned
DIR_ENTRIES_LIMIT = 2000                      # max directory entries in browse
DIFF_NAMES_LIMIT = 5000                       # max file names compared in diff
FILE_VERSIONS_LIMIT = 100                     # max versions shown per file
ERROR_TRUNCATE_LEN = 200                      # stderr/output truncation for errors

# ── Admin router: history resolution ─────────────────────────────────────────
HISTORY_RESOLUTION_S = 3600                   # 1-hour resolution for reports

# ── Agents router: WebSocket / streaming ─────────────────────────────────────
WS_CLOSE_NORMAL = 1000                       # WebSocket normal close code
STREAM_BUFFER_MAX = 500                       # max buffered stream messages per key
TERMINAL_QUEUE_MAXSIZE = 100                  # asyncio.Queue maxsize for terminal
RDP_QUEUE_MAXSIZE = 2                         # asyncio.Queue maxsize for RDP (drop old frames when slow)
COMMAND_HISTORY_LIMIT = 200                   # max command history entries returned
SLA_INCIDENT_LIMIT = 1000                     # max incidents for SLA calculation
DEPLOY_OUTPUT_TRUNCATE = 1000                 # deploy stdout truncation
DEPLOY_ERROR_TRUNCATE = 500                   # deploy stderr truncation

# ── Healing: governor ────────────────────────────────────────────────────────
GOVERNOR_BREAKER_OUTCOME_LIMIT = 50           # outcomes checked for circuit breaker
GOVERNOR_PROMOTION_OUTCOME_LIMIT = 200        # outcomes checked for promotion eval

# ── Healing: ledger ──────────────────────────────────────────────────────────
LEDGER_SUGGESTION_OUTCOME_LIMIT = 500         # outcomes analysed for suggestions

# ── Healing: notifications ───────────────────────────────────────────────────
NOTIFICATION_METRIC_LIMIT = 5                 # max key metrics shown in notification

# ── Healing: agent verify ────────────────────────────────────────────────────
AGENT_VERIFY_OUTPUT_TRUNCATE = 200            # agent output truncation in verify
