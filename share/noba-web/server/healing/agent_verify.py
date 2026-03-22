"""Noba -- Agent-verified healing.

Before healing a remote target, ask the local agent to confirm the
target is actually down from its perspective. Prevents false heals
when the server can't reach a service due to network issues but
the service is fine locally.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("noba")


@dataclass
class VerifyResult:
    """Result of asking an agent to verify a target's state."""

    agent_reachable: bool = False
    confirmed_down: bool | None = None  # None = unknown/can't determine
    detail: str = ""


def _query_agent(hostname: str, target: str) -> dict | None:
    """Send a check command to the agent and wait for response.

    Returns {"status": "up"|"down"|"unknown", "detail": "..."} or None
    if the agent is unreachable.

    This uses the existing agent command infrastructure: queue a
    check_service or container_list command, wait for the result
    with a timeout.
    """
    try:
        import time
        import uuid

        from ..agent_store import (
            _agent_cmd_lock,
            _agent_cmd_results,
            _agent_commands,
            _agent_data,
        )

        # Check if agent is online
        with _agent_cmd_lock:
            if hostname not in _agent_data:
                return None

        # Queue a check command
        cmd_id = str(uuid.uuid4())[:8]
        cmd = {
            "id": cmd_id,
            "command": "check_service",
            "params": {"service": target},
        }
        with _agent_cmd_lock:
            if hostname not in _agent_commands:
                _agent_commands[hostname] = []
            _agent_commands[hostname].append(cmd)

        # Wait for result (max 10 seconds)
        deadline = time.time() + 10
        while time.time() < deadline:
            with _agent_cmd_lock:
                results = _agent_cmd_results.get(hostname, [])
                for r in results:
                    if r.get("id") == cmd_id:
                        output = r.get("output", "")
                        success = r.get("success", False)
                        if success and "running" in str(output).lower():
                            return {"status": "up", "detail": str(output)[:200]}
                        elif success:
                            return {"status": "down", "detail": str(output)[:200]}
                        else:
                            return {"status": "unknown", "detail": str(output)[:200]}
            time.sleep(0.5)

        return None  # timeout
    except Exception as exc:
        logger.error("Agent verify failed for %s@%s: %s", target, hostname, exc)
        return None


def verify_target_with_agent(hostname: str, target: str) -> VerifyResult:
    """Ask an agent to verify if a target is actually down.

    Returns VerifyResult with:
    - agent_reachable: whether the agent responded at all
    - confirmed_down: True if agent confirms down, False if up, None if unknown
    - detail: human-readable detail from the agent
    """
    try:
        response = _query_agent(hostname, target)
    except Exception:
        return VerifyResult(agent_reachable=False, confirmed_down=None, detail="query failed")

    if response is None:
        return VerifyResult(agent_reachable=False, confirmed_down=None, detail="agent unreachable")

    status = response.get("status", "unknown")
    detail = response.get("detail", "")

    if status == "down":
        return VerifyResult(agent_reachable=True, confirmed_down=True, detail=detail)
    elif status == "up":
        return VerifyResult(agent_reachable=True, confirmed_down=False, detail=detail)
    else:
        return VerifyResult(agent_reachable=True, confirmed_down=None, detail=detail)
