"""Noba -- Healing pipeline API endpoints."""
from __future__ import annotations

import json
import logging
import re
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ..agent_store import _agent_cmd_lock, _agent_commands, _agent_data, _agent_data_lock
from ..deps import _get_auth, _require_admin, _require_operator, db

logger = logging.getLogger("noba")


def _parse_duration(s: str) -> int:
    """Parse '30m', '1h', '2h30m' into seconds."""
    total = 0
    for amount, unit in re.findall(r'(\d+)(h|m|s)', s):
        amount = int(amount)
        if unit == 'h':
            total += amount * 3600
        elif unit == 'm':
            total += amount * 60
        elif unit == 's':
            total += amount
    return total or 1800  # default 30 min

router = APIRouter()


@router.get("/api/healing/ledger")
def api_healing_ledger(request: Request, auth=Depends(_get_auth)):
    limit = int(request.query_params.get("limit", 50))
    rule_id = request.query_params.get("rule_id")
    target = request.query_params.get("target")
    return db.get_heal_outcomes(limit=limit, rule_id=rule_id, target=target)


@router.get("/api/healing/effectiveness")
def api_healing_effectiveness(request: Request, auth=Depends(_get_auth)):
    action_type = request.query_params.get("action_type", "")
    condition = request.query_params.get("condition", "")
    target = request.query_params.get("target")
    if not action_type or not condition:
        raise HTTPException(400, "action_type and condition required")
    rate = db.get_heal_success_rate(action_type, condition, target=target)
    return {"action_type": action_type, "condition": condition, "success_rate": rate}


@router.get("/api/healing/suggestions")
def api_healing_suggestions(auth=Depends(_get_auth)):
    return db.list_heal_suggestions()


@router.post("/api/healing/suggestions/{suggestion_id}/dismiss")
def api_dismiss_suggestion(suggestion_id: int, auth=Depends(_require_operator)):
    db.dismiss_heal_suggestion(suggestion_id)
    return {"success": True}


@router.get("/api/healing/trust")
def api_healing_trust(auth=Depends(_get_auth)):
    return db.list_trust_states()


@router.post("/api/healing/trust/{rule_id}/promote")
async def api_promote_trust(rule_id: str, request: Request, auth=Depends(_require_admin)):
    from ..deps import _read_body
    body = await _read_body(request)
    target_level = body.get("level", "approve")
    if target_level not in ("approve", "execute"):
        raise HTTPException(400, "level must be 'approve' or 'execute'")
    state = db.get_trust_state(rule_id)
    if not state:
        raise HTTPException(404, f"No trust state for rule: {rule_id}")
    db.upsert_trust_state(rule_id, target_level, state["ceiling"])
    username, _ = auth
    db.audit_log("trust_promote", username, f"{rule_id}: {state['current_level']} -> {target_level}")
    return {"success": True, "rule_id": rule_id, "new_level": target_level}


@router.get("/api/healing/capabilities/{hostname}")
def api_get_capabilities(hostname: str, auth=Depends(_get_auth)):
    """Return the capability manifest for a given agent hostname."""
    row = db.get_capability_manifest(hostname)
    if row is None:
        raise HTTPException(404, f"No manifest for {hostname}")
    # Parse the manifest JSON string into a dict
    try:
        manifest_data = json.loads(row["manifest"])
    except (json.JSONDecodeError, KeyError):
        manifest_data = {}
    return {
        "hostname": row["hostname"],
        "manifest": manifest_data,
        "probed_at": row.get("probed_at"),
        "degraded_capabilities": json.loads(row.get("degraded_capabilities") or "[]"),
    }


@router.get("/api/healing/dependencies")
def api_list_dependencies(auth=Depends(_get_auth)):
    """Return all dependency graph nodes from the DB."""
    return db.list_dep_graph_nodes()


@router.post("/api/healing/dependencies/validate")
async def api_validate_dependencies(request: Request, auth=Depends(_require_operator)):
    """Validate a dependency config list for cycles and missing references."""
    from ..deps import _read_body
    body = await _read_body(request)
    config: list = body.get("config", [])

    errors: list[str] = []

    # Build a set of known targets from the config
    targets = {node["target"] for node in config if isinstance(node, dict) and "target" in node}

    # Check for required fields and missing references
    for node in config:
        if not isinstance(node, dict):
            errors.append("Each config entry must be an object.")
            continue
        target = node.get("target")
        node_type = node.get("node_type")
        if not target:
            errors.append("A node is missing the required 'target' field.")
        if not node_type:
            errors.append(f"Node '{target}' is missing the required 'node_type' field.")
        depends_on_raw = node.get("depends_on")
        if depends_on_raw:
            try:
                deps = json.loads(depends_on_raw) if isinstance(depends_on_raw, str) else depends_on_raw
                for dep in deps:
                    # Strip optional type prefix (e.g. "network:site-a" -> "site-a")
                    dep_target = dep.split(":", 1)[-1] if ":" in dep else dep
                    if dep_target not in targets:
                        errors.append(
                            f"Node '{target}' depends on '{dep}' which is not defined in this config."
                        )
            except (json.JSONDecodeError, TypeError):
                errors.append(f"Node '{target}' has malformed 'depends_on' value.")

    # Cycle detection via DFS
    if not errors:
        adj: dict[str, list[str]] = {}
        for node in config:
            if not isinstance(node, dict):
                continue
            t = node.get("target", "")
            depends_on_raw = node.get("depends_on")
            deps: list[str] = []
            if depends_on_raw:
                try:
                    raw_deps = json.loads(depends_on_raw) if isinstance(depends_on_raw, str) else depends_on_raw
                    deps = [d.split(":", 1)[-1] if ":" in d else d for d in raw_deps]
                except (json.JSONDecodeError, TypeError):
                    pass
            adj[t] = [d for d in deps if d in targets]

        visited: set[str] = set()
        in_stack: set[str] = set()

        def _has_cycle(node: str) -> bool:
            visited.add(node)
            in_stack.add(node)
            for neighbour in adj.get(node, []):
                if neighbour not in visited:
                    if _has_cycle(neighbour):
                        return True
                elif neighbour in in_stack:
                    return True
            in_stack.discard(node)
            return False

        for t in targets:
            if t not in visited:
                if _has_cycle(t):
                    errors.append("Cycle detected in dependency graph.")
                    break

    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True}


@router.post("/api/healing/capabilities/{hostname}/refresh")
def api_refresh_capabilities(hostname: str, auth=Depends(_require_operator)):
    """Queue a refresh_capabilities command to the named agent."""
    with _agent_data_lock:
        known = hostname in _agent_data
    if not known:
        raise HTTPException(404, f"No known agent: {hostname}")
    cmd_id = secrets.token_hex(8)
    username, _ = auth
    cmd = {
        "id": cmd_id,
        "type": "refresh_capabilities",
        "params": {},
        "queued_by": username,
        "queued_at": int(time.time()),
    }
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)
    return {"status": "refresh_queued", "hostname": hostname}


# ── Maintenance Windows ───────────────────────────────────────────────────────

@router.get("/api/healing/maintenance")
def api_list_maintenance(auth=Depends(_get_auth)):
    """Return all active maintenance windows."""
    return db.get_active_heal_maintenance_windows()


@router.post("/api/healing/maintenance")
async def api_create_maintenance(request: Request, auth=Depends(_require_operator)):
    """Create a maintenance window.

    Body: {"target": str, "duration": str, "reason": str, "action": str}
    """
    from ..deps import _read_body
    body = await _read_body(request)
    target = body.get("target")
    duration_raw = body.get("duration")
    reason = body.get("reason")
    action = body.get("action", "suppress")

    if not target or not duration_raw:
        raise HTTPException(400, "target and duration are required")

    duration_s = _parse_duration(str(duration_raw))
    username, _ = auth
    window_id = db.insert_heal_maintenance_window(
        target=target,
        duration_s=duration_s,
        reason=reason,
        action=action,
        created_by=username,
    )
    db.audit_log("maintenance_create", username,
                 f"target={target} duration={duration_s}s action={action}")
    return {"id": window_id, "status": "created"}


@router.delete("/api/healing/maintenance/{window_id}")
def api_delete_maintenance(window_id: int, auth=Depends(_require_operator)):
    """End a maintenance window early."""
    found = db.end_heal_maintenance_window(window_id)
    if not found:
        raise HTTPException(404, f"No active maintenance window with id {window_id}")
    username, _ = auth
    db.audit_log("maintenance_end", username, f"window_id={window_id}")
    return {"status": "ended"}


# ── Rollback ──────────────────────────────────────────────────────────────────

@router.post("/api/healing/rollback/{ledger_id}")
def api_rollback(ledger_id: int, auth=Depends(_require_admin)):
    """Execute a rollback for a heal ledger entry using its pre-heal snapshot."""
    from ..healing.snapshots import execute_rollback, get_snapshot_by_ledger, is_reversible
    from ..db import db as _db

    conn = _db._get_conn()
    lock = _db._lock

    snapshot = get_snapshot_by_ledger(conn, lock, ledger_id)
    if snapshot is None:
        raise HTTPException(404, f"No snapshot found for ledger entry {ledger_id}")

    action_type = snapshot.get("action_type", "")
    if not is_reversible(action_type):
        raise HTTPException(400, f"Action '{action_type}' is not reversible")

    import json as _json
    try:
        snapshot_state = _json.loads(snapshot.get("state") or "{}")
    except (ValueError, TypeError):
        snapshot_state = {}

    result = execute_rollback(
        action_type=action_type,
        target=snapshot.get("target", ""),
        snapshot_state=snapshot_state,
    )
    username, _ = auth
    db.audit_log("rollback", username,
                 f"ledger_id={ledger_id} action_type={action_type} success={result.get('success')}")
    return result
