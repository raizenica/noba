# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Read-only data endpoints (stats, history, metrics, alerts, notifications, dashboard)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse, StreamingResponse

from .. import deps as _deps  # noqa: F401 – runtime access to bg_collector
from ..deps import handle_errors
from ..collector import collect_stats, get_shutdown_flag
from ..config import HISTORY_METRICS
from ..deps import (
    _client_ip, _get_auth, _get_auth_sse, _int_param, _read_body,
    _require_admin, _safe_int, db,
)
from ..plugins import plugin_manager
from ..yaml_config import read_yaml_settings, write_yaml_settings

logger = logging.getLogger("noba")  # noqa: E402
router = APIRouter()


def _get_server_start_time() -> float:
    """Retrieve server start time stored at module level in app."""
    from ..app import _server_start_time  # noqa: PLC0415
    return _server_start_time


# ── /api/health ───────────────────────────────────────────────────────────────
@router.get("/api/health")
@handle_errors
def api_health() -> dict:
    from ..config import VERSION  # noqa: PLC0415
    return {"status": "ok", "version": VERSION, "uptime_s": round(time.time() - _get_server_start_time())}


# ── /api/me ───────────────────────────────────────────────────────────────────
@router.get("/api/me")
@handle_errors
def api_me(auth=Depends(_get_auth)):
    username, role = auth
    from ..auth import get_permissions  # noqa: PLC0415
    return {"username": username, "role": role, "permissions": get_permissions(role)}


@router.get("/api/permissions")
@handle_errors
def api_permissions(auth=Depends(_get_auth)):
    """List all available permissions and which roles have them."""
    from ..auth import PERMISSIONS  # noqa: PLC0415
    return {role: sorted(perms) for role, perms in PERMISSIONS.items()}


# ── /api/plugins ─────────────────────────────────────────────────────────────
@router.get("/api/plugins")
@handle_errors
def api_plugins(auth=Depends(_get_auth)):
    return plugin_manager.get_all()


# ── /api/stats ────────────────────────────────────────────────────────────────
@router.get("/api/stats")
@handle_errors
def api_stats(request: Request, auth=Depends(_get_auth)):
    qs = dict(request.query_params)
    qs_lists = {k: [v] for k, v in qs.items()}
    _deps.bg_collector.update_qs(qs_lists)
    data = _deps.bg_collector.get() or collect_stats(qs_lists)

    # Check collector health: if pulse is > 2.5x interval, it's likely hung
    from ..collector import STATS_INTERVAL
    pulse = _deps.bg_collector.get_pulse()
    collector_status = "healthy"
    if pulse > STATS_INTERVAL * 2.5:
        collector_status = "stalled"
        logger.warning("Collector heartbeat lost: last tick %.1fs ago", pulse)

    return {
        **data,
        "collector_pulse": round(pulse, 1),
        "collector_status": collector_status,
    }


# ── /api/stream (SSE) ────────────────────────────────────────────────────────
@router.get("/api/stream")
async def api_stream(request: Request, auth=Depends(_get_auth_sse)):
    qs = {k: [v] for k, v in request.query_params.items()}
    _deps.bg_collector.update_qs(qs)
    shutdown = get_shutdown_flag()

    from ..collector import STATS_INTERVAL

    async def generate():
        loop = asyncio.get_running_loop()
        first = await loop.run_in_executor(None, lambda: _deps.bg_collector.get() or collect_stats(qs))
        
        # Enrich with pulse info
        pulse = _deps.bg_collector.get_pulse()
        collector_status = "healthy"
        if pulse > STATS_INTERVAL * 2.5:
            collector_status = "stalled"
        
        first_enriched = {**first, "collector_pulse": round(pulse, 1), "collector_status": collector_status}
        yield f"data: {json.dumps(first_enriched)}\n\n"
        
        last_hb = time.time()
        while not shutdown.is_set():
            if await request.is_disconnected():
                break
            await asyncio.sleep(5)
            if shutdown.is_set():
                break
            data = _deps.bg_collector.get()
            if data:
                pulse = _deps.bg_collector.get_pulse()
                collector_status = "healthy"
                if pulse > STATS_INTERVAL * 2.5:
                    collector_status = "stalled"
                
                data_enriched = {**data, "collector_pulse": round(pulse, 1), "collector_status": collector_status}
                yield f"data: {json.dumps(data_enriched)}\n\n"
            if time.time() - last_hb >= 15:
                yield ": ping\n\n"
                last_hb = time.time()

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


# ── /api/history ──────────────────────────────────────────────────────────────
@router.get("/api/history/multi")
@handle_errors
def api_history_multi(request: Request, auth=Depends(_get_auth)):
    """Get multiple metrics for overlay charting."""
    metrics_param = request.query_params.get("metrics", "")
    if not metrics_param:
        raise HTTPException(400, "Provide comma-separated metrics")
    metric_list = [m.strip() for m in metrics_param.split(",") if m.strip()]
    range_h = _int_param(request, "range", 24, 1, 8760)
    resolution = _int_param(request, "resolution", 60, 1, 3600)
    result = {}
    for metric in metric_list[:10]:
        if metric not in HISTORY_METRICS:
            continue
        result[metric] = db.get_history(metric, range_h, resolution)
    return result


@router.get("/api/history/{metric}")
@handle_errors
def api_history(metric: str, request: Request, auth=Depends(_get_auth)):
    if metric not in HISTORY_METRICS:
        raise HTTPException(400, "Unknown metric")
    range_h    = _int_param(request, "range", 24, 1, 8760)
    resolution = _int_param(request, "resolution", 60, 1, 3600)
    anomaly    = request.query_params.get("anomaly", "0") == "1"
    return db.get_history(metric, range_h, resolution, anomaly)


@router.get("/api/history/{metric}/export")
@handle_errors
def api_history_export(metric: str, request: Request, auth=Depends(_get_auth)):
    if metric not in HISTORY_METRICS:
        raise HTTPException(400, "Unknown metric")
    range_h    = _int_param(request, "range", 24, 1, 8760)
    resolution = _int_param(request, "resolution", 60, 1, 3600)
    rows = db.get_history(metric, range_h, resolution)
    lines = ["timestamp_unix,datetime,value"]
    for row in rows:
        ts = row["time"]
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")
        lines.append(f"{ts},{dt},{row['value']}")
    body = "\n".join(lines)
    fname = f"noba-{metric}-{range_h}h.csv"
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/api/history/{metric}/trend")
@handle_errors
def api_history_trend(metric: str, request: Request, auth=Depends(_get_auth)):
    if metric not in HISTORY_METRICS:
        raise HTTPException(400, "Unknown metric")
    range_h = _int_param(request, "range", 168, 1, 8760)
    project_h = _int_param(request, "project", 168, 1, 8760)
    return db.get_trend(metric, range_hours=range_h, projection_hours=project_h)


# ── /api/metrics ─────────────────────────────────────────────────────────────
@router.get("/api/metrics/available")
@handle_errors
def api_metrics_available(auth=Depends(_get_auth)):
    """List all available metric names with current values for the UI metric picker."""
    stats = _deps.bg_collector.get() or {}
    metrics = []
    for k, v in sorted(stats.items()):
        if isinstance(v, (int, float)):
            metrics.append({"name": k, "value": round(v, 2), "type": "number"})
        elif isinstance(v, str) and v not in ("N/A", "--", ""):
            try:
                float(v.replace("\u00b0C", "").replace("%", ""))
                metrics.append({"name": k, "value": v, "type": "string_numeric"})
            except ValueError:
                pass
    for m in HISTORY_METRICS:
        if not any(x["name"] == m for x in metrics):
            metrics.append({"name": m, "value": None, "type": "history"})
    return metrics


@router.get("/api/metrics/prometheus")
@handle_errors
def api_prometheus(auth=Depends(_get_auth)):
    """Expose metrics in Prometheus exposition format."""
    data = _deps.bg_collector.get()
    if not data:
        return PlainTextResponse("# no data\n")
    lines = []
    lines.append(f'noba_cpu_percent {data.get("cpuPercent", 0)}')
    lines.append(f'noba_mem_percent {data.get("memPercent", 0)}')
    def _prom_escape(v: str) -> str:
        return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    for disk in data.get("disks", []):
        mount = _prom_escape(disk["mount"])
        lines.append(f'noba_disk_percent{{mount="{mount}"}} {disk["percent"]}')
    lines.append(f'noba_net_rx_bps {data.get("netRxRaw", 0):.0f}')
    lines.append(f'noba_net_tx_bps {data.get("netTxRaw", 0):.0f}')
    for svc in data.get("services", []):
        val = 1 if svc["status"] == "active" else 0
        lines.append(f'noba_service_up{{name="{_prom_escape(svc["name"])}"}} {val}')
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.get("/api/metrics/correlate")
@handle_errors
def api_metrics_correlate(request: Request, auth=Depends(_get_auth)):
    """Get multiple metrics aligned on the same timeline for correlation."""
    metrics_param = request.query_params.get("metrics", "")
    hours = min(_safe_int(request.query_params.get("hours", "6"), 6), 168)
    if not metrics_param:
        raise HTTPException(400, "metrics parameter required (comma-separated)")
    metric_names = [m.strip() for m in metrics_param.split(",") if m.strip()][:8]
    result = {}
    for metric in metric_names:
        history = db.get_history(metric, range_hours=hours, resolution=120)
        result[metric] = [{"time": h["time"], "value": h["value"]} for h in history]
    return result


# ── /api/alert-rules ─────────────────────────────────────────────────────────
@router.get("/api/alert-rules")
@handle_errors
def api_alert_rules(auth=Depends(_get_auth)):
    """List all configured alert rules."""
    cfg = read_yaml_settings()
    return cfg.get("alertRules", [])


@router.put("/api/alert-rules")
@handle_errors
async def api_alert_rules_batch(request: Request, auth=Depends(_require_admin)):
    """Replace all alert rules (batch save from settings UI)."""
    username, _ = auth
    body = await _read_body(request)
    rules = body.get("rules")
    if not isinstance(rules, list):
        raise HTTPException(400, "Expected {rules: [...]}")
    from ..healing.condition_eval import validate_condition

    for i, r in enumerate(rules):
        cond = r.get("condition", "") if isinstance(r, dict) else ""
        err = validate_condition(cond)
        if err:
            raise HTTPException(400, f"Rule #{i + 1}: {err}")
    cfg = read_yaml_settings()
    cfg["alertRules"] = rules
    write_yaml_settings(cfg)
    db.audit_log("alert_rules_batch", username, f"Saved {len(rules)} rules", _client_ip(request))
    return {"status": "ok", "count": len(rules)}


@router.post("/api/alert-rules")
@handle_errors
async def api_alert_rules_create(request: Request, auth=Depends(_require_admin)):
    """Add a new alert rule."""
    import uuid

    username, _ = auth
    body = await _read_body(request)
    rule_id = body.get("id") or uuid.uuid4().hex[:8]
    from ..healing.condition_eval import validate_condition

    condition = body.get("condition", "")
    err = validate_condition(condition)
    if err:
        raise HTTPException(400, err)
    rule = {
        "id": rule_id,
        "condition": condition,
        "severity": body.get("severity", "warning"),
        "message": body.get("message", condition),
        "channels": body.get("channels", []),
        "cooldown": _safe_int(body.get("cooldown", 300), 300),
        "action": body.get("action"),
        "max_retries": _safe_int(body.get("max_retries", 3), 3),
        "group": body.get("group", ""),
        "escalation": body.get("escalation", []),
    }
    cfg = read_yaml_settings()
    rules = cfg.get("alertRules", [])
    rules.append(rule)
    cfg["alertRules"] = rules
    write_yaml_settings(cfg)
    db.audit_log("alert_rule_create", username, f"Created rule '{rule_id}'", _client_ip(request))
    return {"status": "ok", "id": rule_id}


@router.put("/api/alert-rules/{rule_id}")
@handle_errors
async def api_alert_rules_update(rule_id: str, request: Request, auth=Depends(_require_admin)):
    """Update an existing alert rule."""
    username, _ = auth
    body = await _read_body(request)
    cfg = read_yaml_settings()
    rules = cfg.get("alertRules", [])
    idx = next((i for i, r in enumerate(rules) if r.get("id") == rule_id), None)
    if idx is None:
        raise HTTPException(404, "Rule not found")
    if "condition" in body:
        from ..healing.condition_eval import validate_condition

        err = validate_condition(body["condition"])
        if err:
            raise HTTPException(400, err)
    for key in ("condition", "severity", "message", "channels", "cooldown", "action",
                "max_retries", "group", "escalation"):
        if key in body:
            rules[idx][key] = body[key]
    cfg["alertRules"] = rules
    write_yaml_settings(cfg)
    db.audit_log("alert_rule_update", username, f"Updated rule '{rule_id}'", _client_ip(request))
    return {"status": "ok"}


@router.delete("/api/alert-rules/{rule_id}")
@handle_errors
def api_alert_rules_delete(rule_id: str, request: Request, auth=Depends(_require_admin)):
    """Delete an alert rule."""
    username, _ = auth
    cfg = read_yaml_settings()
    rules = cfg.get("alertRules", [])
    new_rules = [r for r in rules if r.get("id") != rule_id]
    if len(new_rules) == len(rules):
        raise HTTPException(404, "Rule not found")
    cfg["alertRules"] = new_rules
    write_yaml_settings(cfg)
    db.audit_log("alert_rule_delete", username, f"Deleted rule '{rule_id}'", _client_ip(request))
    return {"status": "ok"}


@router.get("/api/alert-rules/test/{rule_id}")
@handle_errors
def api_alert_rule_test(rule_id: str, auth=Depends(_require_admin)):
    """Test an alert rule against current stats."""
    cfg = read_yaml_settings()
    rules = cfg.get("alertRules", [])
    rule = next((r for r in rules if r.get("id") == rule_id), None)
    if not rule:
        raise HTTPException(404, "Rule not found")
    from ..healing.condition_eval import safe_eval as _safe_eval  # noqa: PLC0415

    stats = _deps.bg_collector.get() or {}
    flat = {}
    for k, v in stats.items():
        if isinstance(v, (int, float, str)):
            flat[k] = v
    result = _safe_eval(rule.get("condition", ""), flat)
    return {"rule_id": rule_id, "condition": rule.get("condition"), "result": result,
            "available_metrics": sorted(flat.keys())[:50]}


# ── /api/sla ──────────────────────────────────────────────────────────────────
@router.get("/api/sla/{rule_id}")
@handle_errors
def api_sla(rule_id: str, request: Request, auth=Depends(_get_auth)):
    window = _int_param(request, "window", 720, 1, 8760)
    return db.get_sla(rule_id, window_hours=window)


# ── /api/alert-history ────────────────────────────────────────────────────────
@router.get("/api/alert-history")
@handle_errors
def api_alert_history(request: Request, auth=Depends(_get_auth)):
    limit = _int_param(request, "limit", 100, 1, 1000)
    rule_id = request.query_params.get("rule_id", "")
    from_ts = _safe_int(request.query_params.get("from", 0), 0)
    to_ts = _safe_int(request.query_params.get("to", 0), 0)
    return db.get_alert_history(limit=limit, rule_id=rule_id, from_ts=from_ts, to_ts=to_ts)


# ── /api/notifications ───────────────────────────────────────────────────────
@router.get("/api/notifications")
@handle_errors
def api_notifications(request: Request, auth=Depends(_get_auth)):
    username, _ = auth
    unread = request.query_params.get("unread", "0") == "1"
    limit = _int_param(request, "limit", 50, 1, 200)
    return {"notifications": db.get_notifications(username, unread, limit),
            "unread_count": db.get_unread_count(username)}


@router.post("/api/notifications/{notif_id}/read")
@handle_errors
def api_notification_read(notif_id: int, auth=Depends(_get_auth)):
    username, _ = auth
    db.mark_notification_read(notif_id, username)
    return {"status": "ok"}


@router.post("/api/notifications/read-all")
@handle_errors
def api_notifications_read_all(auth=Depends(_get_auth)):
    username, _ = auth
    db.mark_all_notifications_read(username)
    return {"status": "ok"}


# ── /api/dashboard ────────────────────────────────────────────────────────────
@router.get("/api/dashboard")
@handle_errors
def api_dashboard_get(auth=Depends(_get_auth)):
    username, _ = auth
    return db.get_user_dashboard(username) or {}


@router.post("/api/dashboard")
@handle_errors
async def api_dashboard_save(request: Request, auth=Depends(_get_auth)):
    username, _ = auth
    body = await _read_body(request)
    db.save_user_dashboard(username, body.get("card_order"), body.get("card_vis"), body.get("card_theme"))
    return {"status": "ok"}
