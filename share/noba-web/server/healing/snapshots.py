# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Pre-heal state snapshots and rollback.

Captures target state before each heal action. If the heal fails
verification, the snapshot enables rollback to the pre-action state
for reversible actions.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("noba")


def _fetch_target_state(target: str, action_type: str, params: dict) -> dict:
    """Fetch current state of a target before healing.

    This is a best-effort capture. Failures return partial dict
    (the heal still proceeds, just without full rollback capability).
    """
    import subprocess

    state: dict = {"target": target, "action_type": action_type}
    try:
        if action_type in ("restart_container", "scale_container"):
            r = subprocess.run(
                ["docker", "inspect", "--format",
                 '{"status":"{{.State.Status}}","image":"{{.Config.Image}}","restartCount":{{.RestartCount}}}',
                 target],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                import json
                state["container"] = json.loads(r.stdout.strip())
        elif action_type in ("restart_service",):
            r = subprocess.run(
                ["systemctl", "show", target, "--no-pager",
                 "--property=ActiveState,SubState,MainPID,NRestarts"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                props = {}
                for line in r.stdout.strip().splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        props[k] = v
                state["service"] = props
        elif action_type == "clear_cache":
            import shutil
            cache_path = params.get("path", "/tmp")
            usage = shutil.disk_usage(cache_path)
            state["disk_before"] = {"used": usage.used, "free": usage.free}
        elif action_type == "failover_dns":
            r = subprocess.run(
                ["cat", "/etc/resolv.conf"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                state["resolv_conf"] = r.stdout
    except Exception as exc:
        logger.debug("Snapshot capture failed for %s/%s: %s", target, action_type, exc)

    return state


def capture_snapshot(target: str, action_type: str, params: dict) -> dict:
    """Capture pre-heal state snapshot."""
    state = _fetch_target_state(target, action_type, params)
    return {
        "target": target,
        "action_type": action_type,
        "state": state,
        "timestamp": time.time(),
    }


def store_snapshot(conn, lock, *, ledger_id: int, target: str,
                   action_type: str, state: str) -> int:
    """Store snapshot in DB. Returns snapshot ID."""
    now = int(time.time())
    with lock:
        cur = conn.execute(
            "INSERT INTO heal_snapshots (ledger_id, target, action_type, state, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ledger_id, target, action_type, state, now),
        )
        conn.commit()
        return cur.lastrowid


def get_snapshot(conn, lock, snap_id: int) -> dict | None:
    """Get snapshot by ID."""
    with lock:
        row = conn.execute(
            "SELECT * FROM heal_snapshots WHERE id = ?", (snap_id,),
        ).fetchone()
    if not row:
        return None
    return {**dict(row), "state": row["state"]}


def get_snapshot_by_ledger(conn, lock, ledger_id: int) -> dict | None:
    """Get snapshot by ledger ID."""
    with lock:
        row = conn.execute(
            "SELECT * FROM heal_snapshots WHERE ledger_id = ? ORDER BY id DESC LIMIT 1",
            (ledger_id,),
        ).fetchone()
    if not row:
        return None
    return {**dict(row), "state": row["state"]}


def is_reversible(action_type: str) -> bool:
    """Check if an action type is reversible."""
    from ..remediation import ACTION_TYPES
    defn = ACTION_TYPES.get(action_type, {})
    return defn.get("reversible", False)


def _execute_reverse_action(action_type: str, target: str, snapshot_state: dict) -> dict:
    """Execute the reverse action using snapshot state."""
    from ..remediation import ACTION_TYPES
    defn = ACTION_TYPES.get(action_type, {})
    reverse = defn.get("reverse_action")
    if not reverse:
        return {"success": False, "error": "No reverse action defined"}

    # Execute reverse action with snapshot params
    try:
        from ..remediation import execute_action
        return execute_action(
            reverse, snapshot_state,
            triggered_by="rollback", trigger_type="rollback",
            target=target,
        )
    except Exception as exc:
        logger.error("Rollback execution failed for %s: %s", target, exc)
        return {"success": False, "error": "Rollback execution failed"}


def execute_rollback(*, action_type: str, target: str, snapshot_state: dict) -> dict:
    """Execute rollback for a heal action using its snapshot.

    Returns {"success": bool, "output": str} or {"success": False, "error": str}
    """
    if not is_reversible(action_type):
        return {"success": False, "error": f"Action '{action_type}' is irreversible"}

    return _execute_reverse_action(action_type, target, snapshot_state)
