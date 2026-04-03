# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – AI ops, incident management, service dependencies, and config drift endpoints."""
from __future__ import annotations

import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ..agent_store import (
    _agent_cmd_lock, _agent_cmd_results, _agent_commands,
    _agent_data, _agent_data_lock, _AGENT_MAX_AGE,
    _agent_websockets, _agent_ws_lock,
)
from ..deps import (
    _client_ip, _get_auth, _int_param, _read_body,
    _require_admin, _require_operator, db,
    handle_errors,
)
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

router = APIRouter(tags=["intelligence"])


def _get_llm_client() -> object | None:
    """Create an LLMClient from current settings. Returns None if not configured."""
    from ..llm import LLMClient
    cfg = read_yaml_settings()
    if not cfg.get("llmEnabled"):
        return None
    return LLMClient(cfg)


def _build_ai_context() -> str:
    """Build ops context string for the LLM system prompt."""
    from ..llm import build_ops_context
    with _agent_data_lock:
        snapshot = dict(_agent_data)
    return build_ops_context(read_yaml_settings, db, snapshot, _AGENT_MAX_AGE)


# ── Incident endpoints ───────────────────────────────────────────────────────
@router.get("/api/incidents")
@handle_errors
def api_incidents(request: Request, auth=Depends(_get_auth)):
    hours = _int_param(request, "hours", 24, 1, 168)
    return db.get_incidents(limit=200, hours=hours)


@router.post("/api/incidents/{incident_id}/resolve")
@handle_errors
def api_resolve_incident(incident_id: int, request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    db.resolve_incident(incident_id)
    db.audit_log("incident_resolved", username, f"id={incident_id}", _client_ip(request))
    return {"status": "ok"}


# ── Incident War Room endpoints ──────────────────────────────────────────────
@router.get("/api/incidents/{incident_id}/messages")
@handle_errors
def api_get_incident_messages(incident_id: int, auth=Depends(_get_auth)):
    """Get the war room message thread for a status incident."""
    incident = db.get_status_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    messages = db.get_incident_messages(incident_id)
    return {"incident_id": incident_id, "messages": messages}


@router.post("/api/incidents/{incident_id}/messages")
@handle_errors
async def api_post_incident_message(
    incident_id: int, request: Request, auth=Depends(_require_operator),
):
    """Post a message to the incident war room (operator+)."""
    username, _ = auth
    incident = db.get_status_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    body = await _read_body(request)
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message is required")
    msg_type = body.get("msg_type", "comment")
    if msg_type not in ("comment", "system", "action", "note"):
        raise HTTPException(400, "msg_type must be comment, system, action, or note")
    msg_id = db.add_incident_message(incident_id, username, message, msg_type=msg_type)
    if not msg_id:
        raise HTTPException(500, "Failed to post message")
    db.audit_log("incident_message", username, f"incident={incident_id}", _client_ip(request))
    return {"id": msg_id, "status": "ok"}


@router.put("/api/incidents/{incident_id}/assign")
@handle_errors
async def api_assign_incident(
    incident_id: int, request: Request, auth=Depends(_require_operator),
):
    """Assign a status incident to a user (operator+)."""
    username, _ = auth
    incident = db.get_status_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    body = await _read_body(request)
    assigned_to = (body.get("assigned_to") or "").strip()
    if not assigned_to:
        raise HTTPException(400, "assigned_to is required")
    ok = db.assign_incident(incident_id, assigned_to)
    if not ok:
        raise HTTPException(500, "Failed to assign incident")
    # Post system message about the assignment
    db.add_incident_message(
        incident_id, username,
        f"Assigned incident to {assigned_to}",
        msg_type="system",
    )
    db.audit_log(
        "incident_assign", username,
        f"incident={incident_id} assigned_to={assigned_to}",
        _client_ip(request),
    )
    return {"status": "ok", "assigned_to": assigned_to}


# ── Service dependency topology endpoints ──────────────────────────────────────
@router.get("/api/dependencies")
@handle_errors
def api_list_dependencies(auth=Depends(_get_auth)):
    """List all service dependencies as graph data (nodes + edges)."""
    deps = db.list_dependencies()
    # Build node set from all mentioned services
    node_set: set[str] = set()
    edges = []
    for d in deps:
        node_set.add(d["source_service"])
        node_set.add(d["target_service"])
        edges.append({
            "id": d["id"],
            "source": d["source_service"],
            "target": d["target_service"],
            "type": d["dependency_type"],
            "auto_discovered": d["auto_discovered"],
        })
    # Determine node health from agent data
    nodes = []
    for name in sorted(node_set):
        health = "unknown"
        with _agent_data_lock:
            agent = _agent_data.get(name)
        if agent:
            age = time.time() - agent.get("last_seen", 0)
            if age < _AGENT_MAX_AGE:
                cpu = agent.get("cpu_percent", 0) or 0
                mem = agent.get("mem_percent", 0) or 0
                if cpu > 90 or mem > 95:
                    health = "critical"
                elif cpu > 70 or mem > 80:
                    health = "warning"
                else:
                    health = "healthy"
            else:
                health = "offline"
        nodes.append({"id": name, "label": name, "health": health})
    return {"nodes": nodes, "edges": edges, "dependencies": deps}


@router.post("/api/dependencies")
@handle_errors
async def api_create_dependency(request: Request, auth=Depends(_require_admin)):
    """Create a manual service dependency."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    source = (body.get("source") or "").strip()
    target = (body.get("target") or "").strip()
    dep_type = (body.get("type") or "requires").strip()
    if not source or not target:
        raise HTTPException(400, "Both 'source' and 'target' are required")
    if source == target:
        raise HTTPException(400, "A service cannot depend on itself")
    if dep_type not in ("requires", "optional", "network"):
        raise HTTPException(400, "Invalid dependency type")
    dep_id = db.create_dependency(source, target, dependency_type=dep_type)
    if dep_id is None:
        raise HTTPException(500, "Failed to create dependency")
    db.audit_log("dependency_create", username,
                 f"id={dep_id} {source}->{target} type={dep_type}", ip)
    return {"status": "ok", "id": dep_id}


@router.delete("/api/dependencies/{dep_id}")
@handle_errors
def api_delete_dependency(dep_id: int, request: Request, auth=Depends(_require_admin)):
    """Delete a service dependency."""
    username, _ = auth
    ip = _client_ip(request)
    ok = db.delete_dependency(dep_id)
    if not ok:
        raise HTTPException(404, "Dependency not found")
    db.audit_log("dependency_delete", username, f"id={dep_id}", ip)
    return {"status": "ok"}


@router.get("/api/dependencies/impact/{service}")
@handle_errors
def api_impact_analysis(service: str, auth=Depends(_get_auth)):
    """Return all services transitively dependent on the given service."""
    affected = db.get_impact_analysis(service)
    return {"service": service, "affected": affected, "count": len(affected)}


@router.post("/api/dependencies/discover/{hostname}")
@handle_errors
async def api_discover_services(hostname: str, request: Request,
                                auth=Depends(_require_operator)):
    """Trigger discover_services command on a remote agent."""
    username, _ = auth
    ip = _client_ip(request)
    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": "discover_services", "params": {}}
    # Try WebSocket delivery first
    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"commands": [cmd]})
            delivered = True
        except HTTPException:
            raise
        except Exception:
            pass
    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)
    db.record_command(cmd_id, hostname, "discover_services", {}, username)
    db.audit_log("discover_services", username,
                 f"host={hostname} id={cmd_id} ws={delivered}", ip)
    return {"status": "sent" if delivered else "queued", "id": cmd_id}


# ── Config drift / baseline endpoints ─────────────────────────────────────────
@router.get("/api/baselines")
@handle_errors
def api_list_baselines(auth=Depends(_get_auth)):
    """List all config baselines with latest drift status summary."""
    return db.list_baselines()


@router.post("/api/baselines")
@handle_errors
async def api_create_baseline(request: Request, auth=Depends(_require_admin)):
    """Create a new config baseline."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    path = (body.get("path") or "").strip()
    expected_hash = (body.get("expected_hash") or "").strip()
    agent_group = (body.get("agent_group") or "__all__").strip()
    if not path:
        raise HTTPException(400, "File path is required")
    if not expected_hash:
        raise HTTPException(400, "Expected hash is required")
    baseline_id = db.create_baseline(path, expected_hash, agent_group=agent_group)
    if baseline_id is None:
        raise HTTPException(500, "Failed to create baseline")
    db.audit_log("baseline_create", username,
                 f"id={baseline_id} path={path} group={agent_group}", ip)
    return {"status": "ok", "id": baseline_id}


@router.delete("/api/baselines/{baseline_id}")
@handle_errors
async def api_delete_baseline(baseline_id: int, request: Request,
                              auth=Depends(_require_admin)):
    """Delete a config baseline and all its drift check history."""
    username, _ = auth
    ip = _client_ip(request)
    ok = db.delete_baseline(baseline_id)
    if not ok:
        raise HTTPException(404, "Baseline not found")
    db.audit_log("baseline_delete", username, f"id={baseline_id}", ip)
    return {"status": "ok"}


@router.post("/api/baselines/{baseline_id}/set-from/{hostname}")
@handle_errors
async def api_baseline_set_from_agent(baseline_id: int, hostname: str,
                                      request: Request,
                                      auth=Depends(_require_admin)):
    """Set a baseline's expected hash from an agent's current file checksum.

    Sends a file_checksum command to the agent and waits for the result,
    then updates the baseline with the hash.
    """
    username, _ = auth
    ip = _client_ip(request)
    baseline = db.get_baseline(baseline_id)
    if not baseline:
        raise HTTPException(404, "Baseline not found")
    # Send file_checksum command to the agent
    cmd_id = secrets.token_hex(8)
    cmd = {
        "id": cmd_id,
        "type": "file_checksum",
        "params": {"path": baseline["path"], "algorithm": "sha256"},
    }
    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"type": "command", "id": cmd_id,
                                "cmd": "file_checksum",
                                "params": cmd["params"]})
            delivered = True
        except HTTPException:
            raise
        except Exception:
            pass
    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)
    db.record_command(cmd_id, hostname, "file_checksum", cmd["params"], username)
    # Poll for result (up to 15s)
    import asyncio
    deadline = time.time() + 15
    agent_result = None
    while time.time() < deadline:
        with _agent_cmd_lock:
            results = _agent_cmd_results.get(hostname, [])
            for i, r in enumerate(results):
                if isinstance(r, dict) and r.get("id") == cmd_id:
                    agent_result = results.pop(i)
                    break
        if agent_result is not None:
            break
        await asyncio.sleep(0.5)
    if agent_result is None:
        raise HTTPException(504, "Agent did not respond in time")
    if agent_result.get("status") != "ok":
        raise HTTPException(502, agent_result.get("error", "Agent error"))
    new_hash = agent_result.get("checksum", "")
    if not new_hash:
        raise HTTPException(502, "Agent returned empty checksum")
    db.complete_command(cmd_id, agent_result)
    db.update_baseline(baseline_id, new_hash)
    db.audit_log("baseline_set_from_agent", username,
                 f"id={baseline_id} host={hostname} hash={new_hash[:16]}...", ip)
    return {"status": "ok", "expected_hash": new_hash}


@router.post("/api/baselines/check")
@handle_errors
async def api_trigger_drift_check(request: Request, auth=Depends(_require_operator)):
    """Trigger an immediate drift check across all baselines."""
    username, _ = auth
    ip = _client_ip(request)
    from ..scheduler import drift_checker
    import threading
    threading.Thread(
        target=drift_checker.run_check_now, daemon=True, name="drift-check-manual"
    ).start()
    db.audit_log("drift_check_trigger", username, "manual", ip)
    return {"status": "ok", "message": "Drift check started"}


@router.get("/api/baselines/{baseline_id}/results")
@handle_errors
def api_baseline_results(baseline_id: int, auth=Depends(_get_auth)):
    """Get drift check results per agent for a specific baseline."""
    baseline = db.get_baseline(baseline_id)
    if not baseline:
        raise HTTPException(404, "Baseline not found")
    results = db.get_drift_results(baseline_id=baseline_id)
    return {
        "baseline": baseline,
        "results": results,
    }


# ── AI / LLM endpoints ────────────────────────────────────────────────────────

@router.get("/api/ai/status")
@handle_errors
def api_ai_status(auth=Depends(_get_auth)):
    """Return AI/LLM configuration status."""
    cfg = read_yaml_settings()
    return {
        "enabled": bool(cfg.get("llmEnabled")),
        "provider": cfg.get("llmProvider", ""),
        "model": cfg.get("llmModel", ""),
    }


@router.post("/api/ai/chat")
@handle_errors
async def api_ai_chat(request: Request, auth=Depends(_require_operator)):
    """Send a message to the AI assistant with optional conversation history."""
    from ..llm import extract_actions
    client = _get_llm_client()
    if not client:
        raise HTTPException(503, "LLM not configured")
    body = await _read_body(request)
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(400, "message is required")
    history = body.get("history", [])
    # Build messages list from history + current message
    messages: list[dict] = []
    for h in history[-20:]:  # Cap history at 20 turns
        role = h.get("role", "user")
        content = h.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    system = _build_ai_context()
    try:
        response = await client.chat(messages, system)
        actions = extract_actions(response)
        return {"response": response, "actions": actions}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI chat error: %s", e)
        raise HTTPException(502, "LLM request failed") from None


@router.post("/api/ai/analyze-alert/{alert_id}")
@handle_errors
async def api_ai_analyze_alert(alert_id: int, auth=Depends(_require_operator)):
    """Ask the AI to analyze a specific alert."""
    from ..llm import extract_actions
    client = _get_llm_client()
    if not client:
        raise HTTPException(503, "LLM not configured")
    # Fetch alert details
    alerts = db.get_alert_history(limit=100)
    alert = None
    for a in alerts:
        if a.get("id") == alert_id:
            alert = a
            break
    if not alert:
        raise HTTPException(404, "Alert not found")
    prompt = (
        f"Analyze this infrastructure alert and suggest remediation steps:\n\n"
        f"**Rule:** {alert.get('rule_id', 'unknown')}\n"
        f"**Severity:** {alert.get('severity', 'unknown')}\n"
        f"**Message:** {alert.get('message', 'N/A')}\n"
        f"**Time:** {alert.get('timestamp', 'unknown')}\n"
        f"**Resolved:** {'Yes' if alert.get('resolved_at') else 'No'}\n\n"
        f"What is likely causing this? What should the operator do? "
        f"If a command can fix it, include it as [ACTION:cmd:host:params]."
    )
    system = _build_ai_context()
    try:
        response = await client.chat([{"role": "user", "content": prompt}], system)
        actions = extract_actions(response)
        return {"response": response, "actions": actions}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI analyze-alert error: %s", e)
        raise HTTPException(502, "LLM request failed") from None


@router.post("/api/ai/analyze-logs")
@handle_errors
async def api_ai_analyze_logs(request: Request, auth=Depends(_require_operator)):
    """Ask the AI to analyze a log excerpt."""
    from ..llm import extract_actions
    client = _get_llm_client()
    if not client:
        raise HTTPException(503, "LLM not configured")
    body = await _read_body(request)
    logs = body.get("logs", "").strip()
    if not logs:
        raise HTTPException(400, "logs field is required")
    # Truncate to ~8000 chars to stay within reasonable token limits
    if len(logs) > 8000:
        logs = logs[:8000] + "\n... (truncated)"
    prompt = (
        f"Analyze these log entries and identify any issues, errors, or anomalies. "
        f"Explain what happened and suggest fixes.\n\n```\n{logs}\n```\n\n"
        f"If a command can fix the issue, include it as [ACTION:cmd:host:params]."
    )
    system = _build_ai_context()
    try:
        response = await client.chat([{"role": "user", "content": prompt}], system)
        actions = extract_actions(response)
        return {"response": response, "actions": actions}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI analyze-logs error: %s", e)
        raise HTTPException(502, "LLM request failed") from None


@router.post("/api/ai/summarize-incident/{incident_id}")
@handle_errors
async def api_ai_summarize_incident(incident_id: int, auth=Depends(_require_operator)):
    """Generate an AI summary/report for an incident."""
    from ..llm import extract_actions
    client = _get_llm_client()
    if not client:
        raise HTTPException(503, "LLM not configured")
    incidents = db.get_incidents(limit=200, hours=168)
    incident = None
    for inc in incidents:
        if inc.get("id") == incident_id:
            incident = inc
            break
    if not incident:
        raise HTTPException(404, "Incident not found")
    prompt = (
        f"Generate a brief incident report for the following event:\n\n"
        f"**ID:** {incident.get('id')}\n"
        f"**Severity:** {incident.get('severity', 'unknown')}\n"
        f"**Source:** {incident.get('source', 'unknown')}\n"
        f"**Title:** {incident.get('title', 'N/A')}\n"
        f"**Details:** {incident.get('details', 'N/A')}\n"
        f"**Status:** {'Resolved' if incident.get('resolved_at') else 'Open'}\n\n"
        f"Include: root cause hypothesis, impact assessment, and recommended next steps. "
        f"If a command can help, include it as [ACTION:cmd:host:params]."
    )
    system = _build_ai_context()
    try:
        response = await client.chat([{"role": "user", "content": prompt}], system)
        actions = extract_actions(response)
        return {"response": response, "actions": actions}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI summarize-incident error: %s", e)
        raise HTTPException(502, "LLM request failed") from None


# ── Prediction endpoints ──────────────────────────────────────────────────────

@router.get("/api/predict/capacity")
@handle_errors
def api_predict_capacity(request: Request, auth=Depends(_get_auth)):
    """Multi-metric capacity prediction with confidence intervals."""
    from ..prediction import predict_capacity
    metrics = request.query_params.get("metrics", "disk_percent").split(",")
    range_h = _int_param(request, "range", 168, 1, 720)
    proj_h = _int_param(request, "projection", 720, 1, 2160)
    return predict_capacity(metrics, range_hours=range_h, projection_hours=proj_h)


@router.post("/api/ai/test")
@handle_errors
async def api_ai_test(auth=Depends(_require_admin)):
    """Test the LLM connection by sending a simple prompt."""
    client = _get_llm_client()
    if not client:
        raise HTTPException(503, "LLM not configured")
    try:
        response = await client.chat(
            [{"role": "user", "content": "Reply with exactly: NOBA AI connection successful."}],
            system="You are a connection test. Reply with exactly the text requested.",
        )
        return {"status": "ok", "response": response.strip()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI test error: %s", e)
        raise HTTPException(502, "LLM connection test failed") from None
