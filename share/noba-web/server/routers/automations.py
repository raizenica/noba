"""Noba – Automation, workflow, and script execution endpoints."""
from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import threading

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..auth import authenticate
from ..config import ALLOWED_AUTO_TYPES, SCRIPT_DIR, SCRIPT_MAP
from ..deps import (
    _client_ip, _get_auth, _int_param, _read_body, _require_admin,
    _require_operator, _safe_int, db,
)
from ..runner import job_runner
from ..workflow_engine import (
    _AUTO_BUILDERS, _run_graph_workflow, _run_parallel_workflow, _run_workflow,
    _validate_auto_config,
)
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

router = APIRouter()

_AUTO_TYPES = ALLOWED_AUTO_TYPES


# ── Build command helper ─────────────────────────────────────────────────────
def _build_command(script: str, safe_args: list[str], args_in) -> list[str] | None:
    """Resolve a script name to a command list.  Returns None on failure."""
    if script == "custom":
        cfg = read_yaml_settings()
        custom_id = args_in if isinstance(args_in, str) else (safe_args[0] if safe_args else "")
        act = next((a for a in cfg.get("customActions", []) if a.get("id") == custom_id), None)
        if act and act.get("command"):
            return ["bash", "-c", act["command"]]
        return None
    if script == "speedtest":
        return ["speedtest-cli", "--simple"] + safe_args
    if script in SCRIPT_MAP:
        sfile = os.path.join(SCRIPT_DIR, SCRIPT_MAP[script])
        if os.path.isfile(sfile):
            return [sfile, "--verbose"] + safe_args
    return None


# ── /api/run-status (legacy compat) ──────────────────────────────────────────
@router.get("/api/run-status")
def api_run_status(auth=Depends(_get_auth)):
    active = job_runner.get_active_ids()
    if not active:
        return {"status": "idle"}
    run = db.get_job_run(active[0])
    if run:
        return {"status": run["status"], "run_id": run["id"],
                "trigger": run["trigger"], "started": run["started_at"]}
    return {"status": "running", "run_ids": active}


# ── /api/runs ─────────────────────────────────────────────────────────────────
@router.get("/api/runs")
def api_runs(request: Request, auth=Depends(_get_auth)):
    limit = _int_param(request, "limit", 50, 1, 500)
    status = request.query_params.get("status")
    auto_id = request.query_params.get("automation_id")
    trigger_prefix = request.query_params.get("trigger_prefix")
    return db.get_job_runs(automation_id=auto_id, limit=limit, status=status,
                           trigger_prefix=trigger_prefix)


@router.get("/api/runs/{run_id}")
def api_run_detail(run_id: int, auth=Depends(_get_auth)):
    run = db.get_job_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/api/runs/{run_id}/cancel")
def api_run_cancel(run_id: int, request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    if not job_runner.cancel(run_id):
        raise HTTPException(404, "Run not active")
    db.audit_log("job_cancel", username, f"Cancelled run {run_id}", _client_ip(request))
    return {"success": True}


@router.post("/api/runs/{run_id}/approve")
async def api_run_approve(run_id: int, request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    run = db.get_job_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run["status"] != "pending_approval":
        raise HTTPException(400, "Run is not pending approval")
    db.update_job_run(run_id, "running")
    db.audit_log("run_approve", username, f"Approved run {run_id}", _client_ip(request))
    return {"status": "ok"}


# ── /api/automations — CRUD + manual trigger ─────────────────────────────────
@router.get("/api/automations")
def api_automations_list(request: Request, auth=Depends(_get_auth)):
    type_filter = request.query_params.get("type")
    return db.list_automations(type_filter=type_filter)


@router.post("/api/automations")
async def api_automations_create(request: Request, auth=Depends(_require_operator)):
    import uuid
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    name = (body.get("name") or "").strip()
    atype = (body.get("type") or "").strip()
    config = body.get("config", {})
    schedule = body.get("schedule") or None
    enabled = body.get("enabled", True)
    if not name:
        raise HTTPException(400, "Name is required")
    if atype not in _AUTO_TYPES:
        raise HTTPException(400, f"Type must be one of: {', '.join(sorted(_AUTO_TYPES))}")
    if not isinstance(config, dict):
        raise HTTPException(400, "Config must be a JSON object")
    _validate_auto_config(atype, config)
    auto_id = uuid.uuid4().hex[:12]
    if not db.insert_automation(auto_id, name, atype, config, schedule, enabled):
        raise HTTPException(500, "Failed to create automation")
    db.audit_log("automation_create", username, f"Created '{name}' ({atype})", ip)
    return {"id": auto_id, "status": "ok"}


@router.put("/api/automations/{auto_id}")
async def api_automations_update(auto_id: str, request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip = _client_ip(request)
    existing = db.get_automation(auto_id)
    if not existing:
        raise HTTPException(404, "Automation not found")
    body = await _read_body(request)
    updates: dict = {}
    if "name" in body:
        updates["name"] = (body["name"] or "").strip()
    if "type" in body:
        if body["type"] not in _AUTO_TYPES:
            raise HTTPException(400, "Invalid type")
        updates["type"] = body["type"]
    if "config" in body:
        atype = body.get("type", existing["type"])
        _validate_auto_config(atype, body["config"])
        updates["config"] = body["config"]
    if "schedule" in body:
        updates["schedule"] = body["schedule"] or None
    if "enabled" in body:
        updates["enabled"] = body["enabled"]
    if not db.update_automation(auto_id, **updates):
        raise HTTPException(500, "Failed to update automation")
    db.audit_log("automation_update", username, f"Updated '{auto_id}'", ip)
    return {"status": "ok"}


@router.delete("/api/automations/{auto_id}")
def api_automations_delete(auto_id: str, request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    ip = _client_ip(request)
    existing = db.get_automation(auto_id)
    if not existing:
        raise HTTPException(404, "Automation not found")
    if not db.delete_automation(auto_id):
        raise HTTPException(500, "Failed to delete automation")
    db.audit_log("automation_delete", username, f"Deleted '{existing['name']}'", ip)
    return {"status": "ok"}


@router.post("/api/automations/{auto_id}/run")
async def api_automations_run(auto_id: str, request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip = _client_ip(request)
    auto = db.get_automation(auto_id)
    if not auto:
        raise HTTPException(404, "Automation not found")
    config = auto["config"]

    # Variable substitution
    body_data = {}
    try:
        raw = await request.body()
        if raw:
            body_data = json.loads(raw)
    except Exception:
        pass
    variables = body_data.get("variables", {}) if isinstance(body_data, dict) else {}
    if variables and isinstance(config, dict):
        config = dict(config)  # don't mutate original
        for key in ("command", "url", "args"):
            if key in config and isinstance(config[key], str):
                try:
                    config[key] = config[key].format_map(
                        {k: v for k, v in variables.items()
                         if isinstance(k, str) and isinstance(v, (str, int, float))}
                    )
                except (KeyError, ValueError, IndexError):
                    pass

    # Workflow: graph or flat step execution
    if auto["type"] == "workflow":
        # Graph format (opt-in): config has "nodes" key
        if config.get("nodes"):
            threading.Thread(
                target=_run_graph_workflow,
                args=(auto_id, config, username),
                daemon=True,
            ).start()
            db.audit_log("automation_run", username,
                         f"Graph workflow '{auto['name']}' started", ip)
            return {"success": True, "run_id": None, "workflow": True, "graph": True}
        # Legacy flat steps format
        steps = config.get("steps", [])
        if not steps:
            raise HTTPException(400, "Workflow has no steps")
        wf_retries = _safe_int(config.get("retries", 0), 0)
        mode = config.get("mode", "sequential")
        if mode == "parallel":
            _run_parallel_workflow(auto_id, steps, username)
        else:
            _run_workflow(auto_id, steps, username, retries=wf_retries)
        db.audit_log("automation_run", username, f"Workflow '{auto['name']}' started ({len(steps)} steps, {mode})", ip)
        return {"success": True, "run_id": None, "workflow": True, "steps": len(steps), "mode": mode}

    builder = _AUTO_BUILDERS.get(auto["type"])
    if not builder:
        raise HTTPException(400, f"Unsupported type: {auto['type']}")

    def make_process(_run_id: int) -> subprocess.Popen | None:
        return builder(config)

    try:
        run_id = job_runner.submit(
            make_process, automation_id=auto_id,
            trigger=f"auto:{auto['type']}:{auto['name']}",
            triggered_by=username,
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    db.audit_log("automation_run", username, f"Run '{auto['name']}' -> run_id={run_id}", ip)
    return {"success": True, "run_id": run_id}


# ── /api/automations/templates ────────────────────────────────────────────────
_AUTOMATION_TEMPLATES = [
    {
        "id": "daily-backup",
        "name": "Daily NAS Backup",
        "description": "Run the backup-to-nas script every night at 3 AM",
        "type": "script",
        "config": {"script": "backup", "args": "--verbose"},
        "schedule": "0 3 * * *",
    },
    {
        "id": "weekly-verify",
        "name": "Weekly Backup Verify",
        "description": "Verify backup integrity every Sunday at 6 AM",
        "type": "script",
        "config": {"script": "verify"},
        "schedule": "0 6 * * 0",
    },
    {
        "id": "disk-cleanup",
        "name": "Disk Sentinel Check",
        "description": "Run disk health check daily at 7 AM",
        "type": "script",
        "config": {"script": "diskcheck"},
        "schedule": "0 7 * * *",
    },
    {
        "id": "cloud-sync",
        "name": "Cloud Backup Sync",
        "description": "Sync backups to cloud storage every 6 hours",
        "type": "script",
        "config": {"script": "cloud"},
        "schedule": "0 */6 * * *",
    },
    {
        "id": "organize-downloads",
        "name": "Organize Downloads",
        "description": "Sort and organize the downloads folder hourly",
        "type": "script",
        "config": {"script": "organize"},
        "schedule": "0 * * * *",
    },
    {
        "id": "health-webhook",
        "name": "Health Check Webhook",
        "description": "POST a health ping to an external monitoring service",
        "type": "webhook",
        "config": {"url": "https://example.com/health", "method": "POST"},
        "schedule": "*/5 * * * *",
    },
    {
        "id": "restart-service",
        "name": "Restart Service on Failure",
        "description": "Restart a systemd service (configure service name)",
        "type": "service",
        "config": {"service": "your-service.service", "action": "restart"},
        "schedule": None,
    },
    {
        "id": "backup-workflow",
        "name": "Full Backup Pipeline",
        "description": "Backup -> Verify -> Cloud sync as a sequential workflow",
        "type": "workflow",
        "config": {"steps": [], "retries": 1},
        "schedule": "0 2 * * *",
    },
]


@router.get("/api/automations/templates")
def api_automation_templates(auth=Depends(_get_auth)):
    return _AUTOMATION_TEMPLATES


# ── /api/playbooks — playbook library ────────────────────────────────────────

@router.get("/api/playbooks")
def api_list_playbooks(auth=Depends(_get_auth)):
    """List available playbook templates."""
    return db.list_playbook_templates()


@router.get("/api/playbooks/{playbook_id}")
def api_get_playbook(playbook_id: str, auth=Depends(_get_auth)):
    """Get a single playbook template by id."""
    template = db.get_playbook_template(playbook_id)
    if not template:
        raise HTTPException(404, "Playbook not found")
    return template


@router.post("/api/playbooks/{playbook_id}/install")
async def api_install_playbook(
    playbook_id: str, request: Request, auth=Depends(_require_operator)
):
    """Install a playbook template as a new workflow automation."""
    import secrets
    username, _ = auth
    template = db.get_playbook_template(playbook_id)
    if not template:
        raise HTTPException(404, "Playbook not found")
    body = await _read_body(request)
    name = body.get("name", template["name"])
    auto_id = secrets.token_hex(6)
    db.insert_automation(auto_id, name, "workflow", template["config"], enabled=False)
    db.audit_log("playbook_install", username,
                 f"template={playbook_id} auto={auto_id}", _client_ip(request))
    return {"id": auto_id, "status": "ok"}


# ── /api/automations/stats ────────────────────────────────────────────────────
@router.get("/api/automations/stats")
def api_automation_stats(auth=Depends(_get_auth)):
    return db.get_automation_stats()


# ── /api/automations/export ───────────────────────────────────────────────────
@router.get("/api/automations/export")
def api_automations_export(auth=Depends(_require_operator)):
    import yaml
    autos = db.list_automations()
    body = yaml.dump({"automations": autos}, default_flow_style=False, sort_keys=False)
    return Response(
        content=body,
        media_type="application/x-yaml",
        headers={"Content-Disposition": 'attachment; filename="noba-automations.yaml"'},
    )


# ── /api/automations/import ───────────────────────────────────────────────────
@router.post("/api/automations/import")
async def api_automations_import(request: Request, auth=Depends(_require_admin)):
    import uuid
    import yaml
    username, _ = auth
    ip = _client_ip(request)
    raw = await request.body()
    if len(raw) > 512 * 1024:
        raise HTTPException(413, "Upload too large (max 512 KB)")
    try:
        text = raw.decode("utf-8")
        parsed = yaml.safe_load(text)
    except Exception:
        raise HTTPException(400, "Invalid YAML")
    if not isinstance(parsed, dict):
        raise HTTPException(400, "Expected a YAML mapping with 'automations' key")
    items = parsed.get("automations", [])
    if not isinstance(items, list):
        raise HTTPException(400, "'automations' must be a list")
    mode = request.query_params.get("mode", "skip")
    imported = 0
    skipped = 0
    for item in items:
        if not isinstance(item, dict) or not item.get("name") or not item.get("type"):
            skipped += 1
            continue
        atype = item["type"]
        if atype not in _AUTO_TYPES:
            skipped += 1
            continue
        existing_id = item.get("id", "")
        existing = db.get_automation(existing_id) if existing_id else None
        if existing:
            if mode == "overwrite":
                db.update_automation(existing_id, name=item["name"], type=atype,
                                     config=item.get("config", {}),
                                     schedule=item.get("schedule"),
                                     enabled=item.get("enabled", True))
                imported += 1
            else:
                skipped += 1
        else:
            auto_id = existing_id if existing_id and len(existing_id) == 12 else uuid.uuid4().hex[:12]
            db.insert_automation(auto_id, item["name"], atype,
                                item.get("config", {}), item.get("schedule"),
                                item.get("enabled", True))
            imported += 1
    db.audit_log("automation_import", username,
                 f"Imported {imported}, skipped {skipped} (mode={mode})", ip)
    return {"imported": imported, "skipped": skipped}


# ── /api/automations/{auto_id}/trigger ────────────────────────────────────────
@router.post("/api/automations/{auto_id}/trigger")
async def api_automations_trigger(auto_id: str, request: Request):
    """Trigger an automation via API key (no login required).

    Accepts either a Bearer token or ``X-Trigger-Key`` header matching
    the automation's ``trigger_key`` config field.
    """
    auto = db.get_automation(auto_id)
    if not auto:
        raise HTTPException(404, "Automation not found")
    config = auto["config"]
    trigger_key = config.get("trigger_key", "")
    if not trigger_key:
        raise HTTPException(403, "No trigger key configured for this automation")
    provided = (request.headers.get("X-Trigger-Key", "")
                or request.query_params.get("key", ""))
    if not provided or provided != trigger_key:
        auth_header = request.headers.get("Authorization", "")
        username, role = authenticate(auth_header)
        if not username or role not in ("admin", "operator"):
            raise HTTPException(401, "Invalid trigger key or credentials")
        triggered_by = username
    else:
        triggered_by = "api-trigger"

    # HMAC validation
    hmac_secret = config.get("hmac_secret", "")
    if hmac_secret:
        import hashlib
        import hmac as _hmac
        raw_body = await request.body()
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + _hmac.new(hmac_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(sig_header, expected):
            raise HTTPException(403, "Invalid HMAC signature")

    if auto["type"] == "workflow":
        steps = config.get("steps", [])
        if not steps:
            raise HTTPException(400, "Workflow has no steps")
        wf_retries = _safe_int(config.get("retries", 0), 0)
        mode = config.get("mode", "sequential")
        if mode == "parallel":
            _run_parallel_workflow(auto_id, steps, triggered_by)
        else:
            _run_workflow(auto_id, steps, triggered_by, retries=wf_retries)
        return {"success": True, "workflow": True, "steps": len(steps)}

    builder = _AUTO_BUILDERS.get(auto["type"])
    if not builder:
        raise HTTPException(400, f"Unsupported type: {auto['type']}")

    def make_process(_run_id: int) -> subprocess.Popen | None:
        return builder(config)

    try:
        run_id = job_runner.submit(
            make_process, automation_id=auto_id,
            trigger=f"api-trigger:{auto['name']}",
            triggered_by=triggered_by,
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"success": True, "run_id": run_id}


# ── /api/automations/{auto_id}/trace ──────────────────────────────────────────
@router.get("/api/automations/{auto_id}/trace")
def api_automation_trace(auto_id: str, auth=Depends(_get_auth)):
    """Get execution trace for a workflow automation."""
    auto = db.get_automation(auto_id)
    if not auto:
        raise HTTPException(404, "Automation not found")
    if auto["type"] != "workflow":
        raise HTTPException(400, "Not a workflow automation")
    limit = 50
    traces = db.get_workflow_trace(auto_id, limit)
    groups: dict = {}
    for t in traces:
        key = t.get("triggered_by", "")
        group_key = f"{key}:{(t.get('started_at', 0) or 0) // 60}"
        if group_key not in groups:
            groups[group_key] = {"triggered_by": key, "started_at": t.get("started_at"), "steps": []}
        groups[group_key]["steps"].append(t)
    sorted_groups = sorted(groups.values(), key=lambda g: g.get("started_at") or 0, reverse=True)
    return {"workflow": auto["name"], "executions": sorted_groups[:20]}


# ── /api/automations/validate-workflow ────────────────────────────────────────
@router.post("/api/automations/validate-workflow")
async def api_validate_workflow(request: Request, auth=Depends(_require_operator)):
    """Validate a workflow definition -- check all step IDs exist."""
    body = await _read_body(request)
    steps = body.get("steps", [])
    if not isinstance(steps, list):
        raise HTTPException(400, "Steps must be a list")
    results = []
    for step_id in steps:
        auto = db.get_automation(step_id)
        if auto:
            results.append({"id": step_id, "name": auto["name"], "type": auto["type"], "valid": True})
        else:
            results.append({"id": step_id, "name": "", "type": "", "valid": False})
    return {"steps": results, "valid": all(r["valid"] for r in results)}


# ── /api/webhook ──────────────────────────────────────────────────────────────
@router.post("/api/webhook")
async def api_webhook(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    hook_id = body.get("id")
    cfg = read_yaml_settings()
    hook = next((a for a in cfg.get("automations", []) if a.get("id") == hook_id), None)
    if not hook or not hook.get("url"):
        raise HTTPException(404, "Webhook not found in config")
    if not hook["url"].startswith(("http://", "https://")):
        raise HTTPException(400, "Invalid webhook URL scheme")
    import urllib.request as _ur
    try:
        method = hook.get("method", "POST").upper()
        req    = _ur.Request(hook["url"], method=method)
        for k, v in (hook.get("headers") or {}).items():
            req.add_header(str(k).replace("\n", ""), str(v).replace("\n", ""))
        hook_body = hook.get("body")
        if hook_body is not None:
            if isinstance(hook_body, (dict, list)):
                req.data = json.dumps(hook_body).encode()
                req.add_header("Content-Type", "application/json")
            elif isinstance(hook_body, str):
                req.data = hook_body.encode()
        with _ur.urlopen(req, timeout=8) as r:
            success = 200 <= r.getcode() < 300
        db.audit_log("webhook", username, f"Webhook {hook_id} {success}", ip)
        return {"success": success}
    except Exception as e:
        logger.error("Webhook %s failed: %s", hook_id, e)
        db.audit_log("webhook", username, f"Webhook {hook_id} failed: {e}", ip)
        raise HTTPException(502, "Webhook failed")


# ── /api/run ──────────────────────────────────────────────────────────────────
@router.post("/api/run")
async def api_run(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    script   = body.get("script", "")
    args_in  = body.get("args",   "")

    safe_args: list[str] = []
    if isinstance(args_in, str) and args_in.strip():
        try:
            safe_args = shlex.split(args_in)
        except ValueError:
            safe_args = args_in.split()
    elif isinstance(args_in, list):
        safe_args = [str(a) for a in args_in if str(a).strip()]

    cmd = _build_command(script, safe_args, args_in)
    if cmd is None:
        raise HTTPException(400, f"Unknown or invalid script: {script}")

    def make_process(_run_id: int) -> subprocess.Popen | None:
        """Called by the runner inside the job thread."""
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True, cwd=SCRIPT_DIR if script in SCRIPT_MAP else None,
        )

    try:
        run_id = job_runner.submit(
            make_process,
            trigger=f"script:{script}",
            triggered_by=username,
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))

    db.audit_log("script_run", username, f"{script} {args_in} -> run_id={run_id}", ip)
    return {"success": True, "status": "running", "script": script, "run_id": run_id}


# ── Webhook Receiver endpoints (Feature 8) ───────────────────────────────────


@router.get("/api/webhooks")
def api_webhooks_list(auth=Depends(_require_admin)):
    """List all webhook endpoints (admin only)."""
    return db.list_webhooks()


@router.post("/api/webhooks")
async def api_webhooks_create(request: Request, auth=Depends(_require_admin)):
    """Create a new webhook endpoint with auto-generated hook_id and secret."""
    import secrets

    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    name = (body.get("name") or "").strip()
    automation_id = body.get("automation_id") or None
    if not name:
        raise HTTPException(400, "Name is required")
    # Validate automation exists if provided
    if automation_id:
        auto = db.get_automation(automation_id)
        if not auto:
            raise HTTPException(400, "Linked automation not found")
    hook_id = secrets.token_urlsafe(16)
    secret = secrets.token_hex(32)
    wh_id = db.create_webhook(name, hook_id, secret, automation_id=automation_id)
    if wh_id is None:
        raise HTTPException(500, "Failed to create webhook")
    db.audit_log("webhook_create", username, f"Created webhook '{name}' (hook_id={hook_id})", ip)
    return {
        "id": wh_id,
        "hook_id": hook_id,
        "secret": secret,
        "status": "ok",
    }


@router.delete("/api/webhooks/{webhook_id}")
def api_webhooks_delete(webhook_id: int, request: Request, auth=Depends(_require_admin)):
    """Delete a webhook endpoint."""
    username, _ = auth
    ip = _client_ip(request)
    if not db.delete_webhook(webhook_id):
        raise HTTPException(404, "Webhook not found")
    db.audit_log("webhook_delete", username, f"Deleted webhook id={webhook_id}", ip)
    return {"status": "ok"}


# ── Maintenance Windows ─────────────────────────────────────────────────────

@router.get("/api/maintenance-windows/active")
def api_active_maintenance_windows(auth=Depends(_get_auth)):
    """Get currently active maintenance windows."""
    return db.get_active_maintenance_windows()


@router.get("/api/maintenance-windows")
def api_list_maintenance_windows(auth=Depends(_get_auth)):
    return db.list_maintenance_windows()


@router.post("/api/maintenance-windows")
async def api_create_maintenance_window(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    body = await _read_body(request)
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    wid = db.insert_maintenance_window(
        name=name, schedule=body.get("schedule"),
        duration_min=body.get("duration_min", 60),
        one_off_start=body.get("one_off_start"),
        one_off_end=body.get("one_off_end"),
        suppress_alerts=body.get("suppress_alerts", True),
        override_autonomy=body.get("override_autonomy"),
        auto_close_alerts=body.get("auto_close_alerts", False),
        created_by=username,
    )
    db.audit_log("maintenance_window_create", username, f"id={wid} name={name}", _client_ip(request))
    return {"id": wid, "status": "ok"}


@router.put("/api/maintenance-windows/{window_id}")
async def api_update_maintenance_window(window_id: int, request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    body = await _read_body(request)
    ok = db.update_maintenance_window(window_id, **body)
    if not ok:
        raise HTTPException(404, "Window not found")
    db.audit_log("maintenance_window_update", username, f"id={window_id}", _client_ip(request))
    return {"status": "ok"}


@router.delete("/api/maintenance-windows/{window_id}")
def api_delete_maintenance_window(window_id: int, request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    ok = db.delete_maintenance_window(window_id)
    if not ok:
        raise HTTPException(404, "Window not found")
    db.audit_log("maintenance_window_delete", username, f"id={window_id}", _client_ip(request))
    return {"status": "ok"}


# ── Approval Queue ──────────────────────────────────────────────────────────

@router.get("/api/approvals/count")
def api_approval_count(auth=Depends(_get_auth)):
    """Get count of pending approvals (for badge in UI)."""
    return {"count": db.count_pending_approvals()}


@router.get("/api/approvals")
def api_list_approvals(request: Request, auth=Depends(_get_auth)):
    """List approvals, filtered by status."""
    status_filter = request.query_params.get("status", "pending")
    return db.list_approvals(status=status_filter)


@router.get("/api/approvals/{approval_id}")
def api_get_approval(approval_id: int, auth=Depends(_get_auth)):
    """Get approval details."""
    a = db.get_approval(approval_id)
    if not a:
        raise HTTPException(404, "Approval not found")
    return a


@router.post("/api/approvals/{approval_id}/decide")
async def api_decide_approval(approval_id: int, request: Request, auth=Depends(_require_operator)):
    """Approve or deny a pending action."""
    username, role = auth
    body = await _read_body(request)
    decision = body.get("decision", "")
    if decision not in ("approved", "denied"):
        raise HTTPException(400, "decision must be 'approved' or 'denied'")

    approval = db.get_approval(approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")
    if approval["status"] != "pending":
        raise HTTPException(400, f"Approval already {approval['status']}")

    ok = db.decide_approval(approval_id, decision, username)
    if not ok:
        raise HTTPException(500, "Failed to update approval")

    # Check for graph workflow context — resume workflow if present
    wf_ctx = db.get_workflow_context(approval_id)
    if wf_ctx:
        next_node_id = wf_ctx.get("approved_next") if decision == "approved" else wf_ctx.get("denied_next")
        if next_node_id:
            auto_id = wf_ctx.get("auto_id", "")
            nodes_list = wf_ctx.get("nodes", [])
            nodes = {n["id"]: n for n in nodes_list}
            edges = wf_ctx.get("edges", [])
            orig_triggered_by = wf_ctx.get("triggered_by", username)
            from ..workflow_engine import _execute_node
            threading.Thread(
                target=_execute_node,
                args=(auto_id, nodes, edges, next_node_id, orig_triggered_by),
                daemon=True,
            ).start()
        else:
            logger.info("Approval %s: no resume node for decision=%s — workflow ends",
                        approval_id, decision)
    elif decision == "approved":
        # Legacy non-graph approval: execute remediation action
        import json as _json
        from ..remediation import execute_action
        action_params = approval.get("action_params") or {}
        if isinstance(action_params, str):
            action_params = _json.loads(action_params)
        result = execute_action(
            approval["action_type"],
            action_params,
            triggered_by=username,
            trigger_type="approval",
            trigger_id=str(approval_id),
            target=approval.get("target"),
            approved_by=username,
        )
        db.update_approval_result(approval_id, _json.dumps(result))

    ip = _client_ip(request)
    db.audit_log("approval_decision", username,
                 f"id={approval_id} decision={decision}", ip)
    return {"status": "ok", "decision": decision}


@router.get("/api/action-audit")
def api_action_audit(request: Request, auth=Depends(_get_auth)):
    """Query the action audit trail."""
    limit = min(int(request.query_params.get("limit", "100")), 500)
    trigger_type = request.query_params.get("trigger_type")
    outcome = request.query_params.get("outcome")
    return db.get_action_audit(limit=limit, trigger_type=trigger_type, outcome=outcome)


@router.post("/api/webhooks/receive/{hook_id}")
async def api_webhooks_receive(hook_id: str, request: Request):
    """PUBLIC endpoint -- receive incoming webhook, validate HMAC, trigger automation."""
    import hashlib
    import hmac as _hmac

    wh = db.get_webhook_by_hook_id(hook_id)
    if not wh:
        raise HTTPException(404, "Not found")
    if not wh["enabled"]:
        raise HTTPException(403, "Webhook is disabled")

    # HMAC-SHA256 signature validation
    raw_body = await request.body()
    secret = wh["secret"]
    expected = _hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    signature = request.headers.get("X-Hub-Signature-256", "").replace("sha256=", "")
    if not signature or not _hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Invalid signature")

    # Record the trigger
    db.record_webhook_trigger(wh["id"])

    # If linked to an automation, run it
    automation_id = wh.get("automation_id")
    if automation_id:
        auto = db.get_automation(automation_id)
        if auto:
            config = auto["config"]

            if auto["type"] == "workflow":
                steps = config.get("steps", [])
                if steps:
                    wf_retries = _safe_int(config.get("retries", 0), 0)
                    mode = config.get("mode", "sequential")
                    if mode == "parallel":
                        _run_parallel_workflow(automation_id, steps, "webhook")
                    else:
                        _run_workflow(automation_id, steps, "webhook", retries=wf_retries)
                    db.audit_log("webhook_trigger", "webhook",
                                 f"Webhook '{wh['name']}' triggered workflow '{auto['name']}'")
                    return {"status": "ok", "automation": auto["name"], "workflow": True}

            builder = _AUTO_BUILDERS.get(auto["type"])
            if builder:
                def make_process(_run_id: int) -> subprocess.Popen | None:
                    return builder(config)

                try:
                    run_id = job_runner.submit(
                        make_process, automation_id=automation_id,
                        trigger=f"webhook:{wh['name']}",
                        triggered_by="webhook",
                    )
                except RuntimeError:
                    raise HTTPException(409, "Too many concurrent jobs")
                db.audit_log("webhook_trigger", "webhook",
                             f"Webhook '{wh['name']}' triggered '{auto['name']}' -> run_id={run_id}")
                return {"status": "ok", "automation": auto["name"], "run_id": run_id}

    db.audit_log("webhook_trigger", "webhook", f"Webhook '{wh['name']}' received (no automation linked)")
    return {"status": "ok", "automation": None}
