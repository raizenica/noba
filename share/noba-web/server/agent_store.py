"""Noba – Shared agent data stores and their locks."""
from __future__ import annotations

import threading

_agent_data: dict[str, dict] = {}
_agent_data_lock = threading.Lock()
_AGENT_MAX_AGE = 120  # Consider agent offline after 2 minutes
_agent_commands: dict[str, list] = {}  # hostname -> pending commands
_agent_cmd_results: dict[str, list] = {}  # hostname -> recent results
_agent_cmd_lock = threading.Lock()
