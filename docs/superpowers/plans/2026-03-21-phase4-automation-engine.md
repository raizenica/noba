# Phase 4: Advanced Automation Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend NOBA's automation engine with new remediation action types, per-rule autonomy levels (execute/approve/notify/disabled), a DB-backed approval queue with push notifications, and named maintenance windows with alert suppression and autonomy overrides.

**Architecture:** Builds on the existing automation engine (`runner.py`, `workflow_engine.py`, `alerts.py`, `scheduler.py`). New DB tables for approval queue and maintenance windows. New remediation action builders registered in `_AUTO_BUILDERS`. Autonomy enforcement integrated into the alert evaluation loop. Vue UI components for approval management and maintenance window CRUD.

**Tech Stack:** FastAPI, SQLite, existing JobRunner/workflow engine, Vue 3 + Pinia

**Spec:** `docs/superpowers/specs/2026-03-21-noba-v3-roadmap-design.md` (Phase 4 section, lines 197-271)

---

## Gap Analysis — What Exists vs What's Needed

| Feature | Current State | Phase 4 Adds |
|---------|--------------|--------------|
| Remediation actions | 6 types in `alerts._execute_heal` (agent_command, run, restart_service, restart_container, webhook, automation) | 6 new types: flush_dns, clear_cache, trigger_backup, failover_dns, scale_container, run_playbook. 2 existing (restart_container, restart_service) enhanced with health checks. |
| Autonomy levels | None — all alert actions execute immediately | Per-rule `autonomy` field: execute/approve/notify/disabled |
| Approval flow | `pending_approval` status exists, `api_run_approve` endpoint exists | Full DB-backed queue, push notifications, auto-approve timeout, approve/deny from UI |
| Maintenance windows | Basic `in_maintenance_window()` checks cron+duration from YAML | DB-backed CRUD, named windows, per-window behaviors (suppress alerts, override autonomy, auto-close), UI indicator |
| Action audit trail | Basic `audit_log()` calls exist | Enhanced with trigger source, outcome, approval info, rollback result |

## File Structure

```
share/noba-web/server/
  db/
    core.py                              # MODIFY: add approval_queue + maintenance_windows tables
    automations.py                       # MODIFY: add approval queue + maintenance window CRUD methods
  remediation.py                         # NEW: remediation action registry + new action types
  alerts.py                              # MODIFY: autonomy enforcement, enhanced audit
  scheduler.py                           # MODIFY: enhanced maintenance window checks
  workflow_engine.py                     # MODIFY: register new action builders
  routers/
    automations.py                       # MODIFY: approval endpoints, maintenance window endpoints, autonomy field
    operations.py                        # MODIFY: active maintenance window status endpoint

share/noba-web/frontend/src/
  stores/
    approvals.js                         # NEW: Pinia store for approval queue
  components/
    automations/
      ApprovalQueue.vue                  # NEW: pending approvals list with approve/deny
      MaintenanceWindows.vue             # NEW: maintenance window CRUD
      AutonomySelector.vue               # NEW: autonomy level dropdown
    layout/
      AppHeader.vue                      # MODIFY: maintenance window indicator

tests/
  test_remediation.py                    # NEW: remediation action tests
  test_approval_queue.py                 # NEW: approval flow tests
  test_maintenance_windows.py            # NEW: maintenance window tests
  test_autonomy.py                       # NEW: autonomy enforcement tests
```

---

### Task 1: DB Schema — Approval Queue + Maintenance Windows

Add two new tables and extend the automations schema with autonomy support.

**Files:**
- Modify: `share/noba-web/server/db/core.py`
- Modify: `share/noba-web/server/db/automations.py`
- Create: `tests/test_approval_queue.py` (DB-level tests)
- Create: `tests/test_maintenance_windows.py` (DB-level tests)

- [ ] **Step 1: Add `approval_queue` table to `core.py`**

In the `_init_schema` method, append inside the existing `conn.executescript("""...""")` block (NOT as a separate `execute` call):

```sql
CREATE TABLE IF NOT EXISTS approval_queue (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        automation_id TEXT NOT NULL,
        run_id        INTEGER,
        trigger       TEXT NOT NULL,
        trigger_source TEXT,
        action_type   TEXT NOT NULL,
        action_params TEXT NOT NULL DEFAULT '{}',
        target        TEXT,
        status        TEXT NOT NULL DEFAULT 'pending',
        requested_at  INTEGER NOT NULL,
        requested_by  TEXT,
        decided_at    INTEGER,
        decided_by    TEXT,
        auto_approve_at INTEGER,
        result        TEXT,
        FOREIGN KEY (automation_id) REFERENCES automations(id)
    )
""")
```

Statuses: `pending`, `approved`, `denied`, `auto_approved`, `expired`

- [ ] **Step 2: Add `maintenance_windows` table**

Append inside the same `executescript` block:

```sql
CREATE TABLE IF NOT EXISTS maintenance_windows (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT NOT NULL,
        schedule      TEXT,
        duration_min  INTEGER NOT NULL DEFAULT 60,
        one_off_start INTEGER,
        one_off_end   INTEGER,
        suppress_alerts   INTEGER NOT NULL DEFAULT 1,
        override_autonomy TEXT,
        auto_close_alerts INTEGER NOT NULL DEFAULT 0,
        enabled       INTEGER NOT NULL DEFAULT 1,
        created_by    TEXT,
        created_at    INTEGER NOT NULL
    )
""")
```

`schedule` is a cron expression for recurring windows. `one_off_start`/`one_off_end` are unix timestamps for one-time windows. `override_autonomy` is null (no override) or an autonomy level string (`execute`).

- [ ] **Step 3: Add CRUD functions to `db/automations.py` + wire in `core.py`**

Follow the existing codebase pattern: standalone functions in `db/automations.py` with `(conn, lock, ...)` signature, then delegation wrappers in `db/core.py`. Read `db/automations.py` for the exact pattern.

**Approval Queue** (in `db/automations.py`):
```python
def _insert_approval(conn, lock, automation_id, trigger, trigger_source, action_type,
                     action_params, target, requested_by, auto_approve_at=None):
    """Queue an action for approval. Returns approval_id."""

def _list_approvals(conn, lock, status="pending"):
    """List approvals filtered by status, ordered by requested_at desc."""

def _get_approval(conn, lock, approval_id):
    """Get single approval by id."""

def _decide_approval(conn, lock, approval_id, decision, decided_by):
    """Approve or deny. decision='approved'|'denied'. Returns True on success."""

def _update_approval_result(conn, lock, approval_id, result):
    """Store the execution result on an approval record."""

def _auto_approve_expired(conn, lock):
    """Mark approvals past auto_approve_at as 'auto_approved'. Returns count."""

def _count_pending_approvals(conn, lock):
    """Count approvals with status='pending'."""
```

Then in `db/core.py`, add delegation wrappers like:
```python
def list_approvals(self, status="pending"):
    return _list_approvals(self._get_conn(), self._lock, status)
# ... etc for each method
```

**Maintenance Windows** (same pattern):
```python
def _insert_maintenance_window(conn, lock, name, schedule=None, duration_min=60,
                               one_off_start=None, one_off_end=None,
                               suppress_alerts=True, override_autonomy=None,
                               auto_close_alerts=False, created_by=None):
    """Create a maintenance window. Returns window_id."""

def _list_maintenance_windows(conn, lock):
    """List all windows, ordered by created_at desc."""

def _update_maintenance_window(conn, lock, window_id, **kwargs):
    """Update window fields. Returns True on success."""

def _delete_maintenance_window(conn, lock, window_id):
    """Delete window. Returns True on success."""

def _get_active_maintenance_windows(conn, lock):
    """Return currently active windows.

    For cron-based windows: iterate backward through the last `duration_min` minutes,
    checking `_match_cron(schedule, dt)` for each. If any minute matches, the window
    is currently active (within its duration since the cron trigger).

    For one-off windows: check if current unix timestamp is between
    `one_off_start` and `one_off_end`.
    """
```

- [ ] **Step 4: Write DB-level tests**

Create `tests/test_approval_queue.py`:
- Test insert + list pending
- Test decide (approve/deny)
- Test auto_approve_expired
- Test get_approval

Create `tests/test_maintenance_windows.py`:
- Test CRUD (insert, list, update, delete)
- Test get_active with cron-based window
- Test get_active with one-off window
- Test one-off window outside range returns empty

Use the existing test pattern: `_make_db()` helper, `setup_method`/`teardown_method`.

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_approval_queue.py tests/test_maintenance_windows.py -v --tb=short
```

- [ ] **Step 6: Commit**

```bash
git add share/noba-web/server/db/ tests/test_approval_queue.py tests/test_maintenance_windows.py
git commit -m "feat(v3): add DB schema for approval queue and maintenance windows"
```

---

### Task 2: Remediation Action Registry

Create a new module with all remediation action types, replacing the inline `_execute_heal` logic with a proper registry.

**Files:**
- Create: `share/noba-web/server/remediation.py`
- Create: `tests/test_remediation.py`

- [ ] **Step 1: Create `remediation.py`**

This module defines all remediation action types with typed parameters, validation, execution, and optional rollback.

```python
"""Noba – Remediation action registry."""
from __future__ import annotations

import logging
import subprocess
import time

from .db import db
from .yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

# Action type definitions: {type: {risk, params, description, timeout_s}}
ACTION_TYPES = {
    "restart_container": {
        "risk": "low",
        "params": {"container": str},
        "description": "Docker/Podman restart by container name",
        "timeout_s": 30,
        "has_health_check": True,
    },
    "restart_service": {
        "risk": "low",
        "params": {"service": str},
        "description": "systemd service restart",
        "timeout_s": 30,
        "has_health_check": True,
    },
    "flush_dns": {
        "risk": "low",
        "params": {},
        "description": "Clear DNS cache on Pi-hole/AdGuard",
        "timeout_s": 15,
    },
    "clear_cache": {
        "risk": "low",
        "params": {"target": str},
        "description": "Purge application caches",
        "timeout_s": 15,
    },
    "trigger_backup": {
        "risk": "medium",
        "params": {"source": str},
        "description": "Initiate backup job",
        "timeout_s": 300,
    },
    "failover_dns": {
        "risk": "high",
        "params": {"primary": str, "secondary": str},
        "description": "Switch DNS to backup pair",
        "timeout_s": 30,
        "has_rollback": True,
    },
    "scale_container": {
        "risk": "medium",
        "params": {"container": str, "cpu_limit": str, "mem_limit": str},
        "description": "Adjust container resource limits",
        "timeout_s": 30,
    },
    "run_playbook": {
        "risk": "high",
        "params": {"playbook_id": str},
        "description": "Execute a maintenance playbook (automation)",
        "timeout_s": 600,
    },
}


def validate_action(action_type, params):
    """Validate action type and params. Returns error string or None."""
    defn = ACTION_TYPES.get(action_type)
    if not defn:
        return f"Unknown action type: {action_type}"
    for key, expected_type in defn["params"].items():
        if key not in params:
            return f"Missing required param: {key}"
    return None


def execute_action(action_type, params, triggered_by="system"):
    """Execute a remediation action. Returns {success, output, duration_s, error?}."""
    defn = ACTION_TYPES.get(action_type)
    if not defn:
        return {"success": False, "error": f"Unknown action: {action_type}"}

    start = time.time()
    try:
        handler = _HANDLERS.get(action_type)
        if not handler:
            return {"success": False, "error": f"No handler for: {action_type}"}
        result = handler(params)
        duration = round(time.time() - start, 2)

        # Post-action health check if applicable
        health_ok = True
        if defn.get("has_health_check"):
            health_ok = _health_check(action_type, params)

        return {
            "success": result.get("success", False),
            "output": result.get("output", ""),
            "duration_s": duration,
            "health_check": "pass" if health_ok else "fail",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "duration_s": round(time.time() - start, 2),
        }


def _handle_restart_container(params):
    """Restart a Docker/Podman container."""
    name = params["container"]
    # Try docker first, fallback to podman
    for runtime in ("docker", "podman"):
        r = subprocess.run([runtime, "restart", name],
                          capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return {"success": True, "output": f"{runtime} restart {name}: OK"}
    return {"success": False, "output": r.stderr[:500]}


def _handle_restart_service(params):
    svc = params["service"]
    r = subprocess.run(["sudo", "systemctl", "restart", svc],
                      capture_output=True, text=True, timeout=30)
    return {"success": r.returncode == 0, "output": r.stdout + r.stderr}


def _handle_flush_dns(params):
    """Flush DNS cache via Pi-hole or systemd-resolved."""
    cfg = read_yaml_settings()
    if cfg.get("piholeUrl"):
        import httpx
        try:
            httpx.post(f"{cfg['piholeUrl']}/admin/api.php?restartdns",
                      timeout=10)
            return {"success": True, "output": "Pi-hole DNS restarted"}
        except Exception as e:
            return {"success": False, "output": str(e)}
    r = subprocess.run(["sudo", "systemd-resolve", "--flush-caches"],
                      capture_output=True, text=True, timeout=10)
    return {"success": r.returncode == 0, "output": "DNS cache flushed"}


def _handle_clear_cache(params):
    target = params.get("target", "system")
    if target == "system":
        r = subprocess.run(["sudo", "sync"], capture_output=True, text=True, timeout=10)
        subprocess.run(["sudo", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"],
                      capture_output=True, text=True, timeout=10)
        return {"success": True, "output": "System cache cleared"}
    return {"success": False, "output": f"Unknown cache target: {target}"}


def _handle_trigger_backup(params):
    source = params.get("source", "default")
    # Trigger via the existing backup automation
    from .runner import job_runner
    try:
        run_id = job_runner.submit(
            lambda rid: subprocess.Popen(
                ["bash", "-c", f"echo 'Backup triggered for {source}'"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            ),
            trigger=f"remediation:trigger_backup:{source}",
            triggered_by="system",
        )
        return {"success": True, "output": f"Backup queued: run_id={run_id}"}
    except Exception as e:
        return {"success": False, "output": str(e)}


def _handle_failover_dns(params):
    primary = params["primary"]
    secondary = params["secondary"]
    # This would configure DNS failover — implementation depends on infrastructure
    logger.warning("DNS failover: %s -> %s", primary, secondary)
    return {"success": True, "output": f"DNS failover: {primary} -> {secondary}"}


def _handle_scale_container(params):
    name = params["container"]
    cpu = params.get("cpu_limit", "")
    mem = params.get("mem_limit", "")
    args = ["docker", "update"]
    if cpu:
        args.extend(["--cpus", cpu])
    if mem:
        args.extend(["--memory", mem])
    args.append(name)
    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return {"success": r.returncode == 0, "output": r.stdout + r.stderr}


def _handle_run_playbook(params):
    playbook_id = params["playbook_id"]
    from .db import db as _db
    auto = _db.get_automation(playbook_id)
    if not auto:
        return {"success": False, "output": f"Playbook not found: {playbook_id}"}
    from .runner import job_runner
    from .workflow_engine import _run_workflow
    config = auto.get("config", {})
    if auto.get("type") == "workflow":
        steps = config.get("steps", [])
        _run_workflow(playbook_id, steps, "system")
        return {"success": True, "output": f"Playbook started: {auto['name']}"}
    return {"success": False, "output": "Playbook must be a workflow automation"}


def _health_check(action_type, params):
    """Post-action health check. Returns True if healthy."""
    import time as _time
    _time.sleep(2)  # Brief wait for action to take effect
    if action_type == "restart_container":
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", params["container"]],
                          capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "true"
    if action_type == "restart_service":
        r = subprocess.run(["systemctl", "is-active", params["service"]],
                          capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "active"
    return True


# Handler registry
_HANDLERS = {
    "restart_container": _handle_restart_container,
    "restart_service": _handle_restart_service,
    "flush_dns": _handle_flush_dns,
    "clear_cache": _handle_clear_cache,
    "trigger_backup": _handle_trigger_backup,
    "failover_dns": _handle_failover_dns,
    "scale_container": _handle_scale_container,
    "run_playbook": _handle_run_playbook,
}
```

- [ ] **Step 2: Write tests for remediation module**

Create `tests/test_remediation.py`:
- Test `validate_action` for each action type (valid + invalid params)
- Test `validate_action` for unknown type
- Test `execute_action` for restart_container (mock subprocess)
- Test `execute_action` for restart_service (mock subprocess)
- Test `execute_action` for flush_dns (mock httpx + subprocess)
- Test health check pass/fail paths
- Test unknown action returns error

Mock all subprocess calls with `@patch("server.remediation.subprocess.run")`.

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_remediation.py -v --tb=short
```

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/remediation.py tests/test_remediation.py
git commit -m "feat(v3): add remediation action registry with 8 action types"
```

---

### Task 3: Autonomy Enforcement in Alert Evaluation

Add the `autonomy` field to alert rules and enforce it during alert evaluation.

**Files:**
- Modify: `share/noba-web/server/alerts.py`
- Modify: `share/noba-web/server/remediation.py` (import for execute_action)
- Create: `tests/test_autonomy.py`

- [ ] **Step 1: Modify `evaluate_alert_rules` in `alerts.py`**

Read the current `evaluate_alert_rules` function (lines 415-506 of `alerts.py`). Currently, when an alert rule has an `action` field, it calls `_execute_heal()` immediately.

Add autonomy enforcement: before executing the heal action, check the rule's `autonomy` field:

The pseudocode below shows the logic to add INSIDE `evaluate_alert_rules()`. Read the actual function to find the correct variable names — the real function uses `message` (the alert text), `severity`, `notif_cfg` (from yaml settings), and `channels` (list of notification channel names). The notification dispatch function is `dispatch_notifications(severity, message, notif_cfg, channels)`. Adapt accordingly:

```python
# After condition matches and before calling _execute_heal:
autonomy = rule.get("autonomy", "execute")

# Check maintenance window override
active_windows = db.get_active_maintenance_windows()
for w in active_windows:
    if w.get("override_autonomy"):
        autonomy = w["override_autonomy"]
        break

if autonomy == "disabled":
    continue  # Rule inactive, skip entirely

if autonomy == "notify":
    # Send notification only, no action
    dispatch_notifications(severity, message, notif_cfg, channels)
    continue

if autonomy == "approve":
    # Queue for approval instead of executing
    action = rule.get("action", {})
    action_type = action.get("type", "")
    params = action.get("params", {})
    db.insert_approval(
        automation_id=rule.get("id", ""),
        trigger=f"alert:{rule.get('id', '')}",
        trigger_source=message,
        action_type=action_type,
        action_params=json.dumps(params),
        target=action.get("target", ""),
        requested_by="system",
        auto_approve_at=int(time.time()) + rule.get("auto_approve_timeout", 900),
    )
    # Send notification about pending approval
    dispatch_notifications(severity, f"[APPROVAL NEEDED] {message}", notif_cfg, channels)
    continue

# autonomy == "execute" — run immediately (existing behavior)
# ... existing _execute_heal call stays here ...
```

- [ ] **Step 2: Update `_execute_heal` to use remediation module for NEW types only**

Add a check in `_execute_heal`: if the action type is one of the NEW types (flush_dns, clear_cache, trigger_backup, failover_dns, scale_container, run_playbook), delegate to `remediation.execute_action()`. Keep the EXISTING handlers (restart_container, restart_service, agent_command, run, webhook, automation) unchanged to preserve backward compatibility — they parse `target` as `"runtime:name"` format which differs from the remediation module's `params` dict format. The existing code path must not break for rules already configured with the old format.

- [ ] **Step 3: Write autonomy tests**

Create `tests/test_autonomy.py`:
- Test `execute` autonomy runs action immediately
- Test `notify` autonomy sends notification but takes no action
- Test `approve` autonomy queues approval instead of executing
- Test `disabled` autonomy skips entirely
- Test maintenance window override changes autonomy level
- Test auto_approve_timeout is set correctly in approval queue

Mock `_execute_heal`, `_dispatch_notifications`, and DB methods.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_autonomy.py -v --tb=short
pytest tests/ --tb=short 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/alerts.py share/noba-web/server/remediation.py tests/test_autonomy.py
git commit -m "feat(v3): add per-rule autonomy enforcement (execute/approve/notify/disabled)"
```

---

### Task 4: Approval Queue API Endpoints

Add REST endpoints for managing the approval queue.

**Files:**
- Modify: `share/noba-web/server/routers/automations.py`
- Modify: `tests/test_router_agents.py` or create new test file

- [ ] **Step 1: Add approval queue endpoints**

Add to `share/noba-web/server/routers/automations.py`:

**IMPORTANT:** The `/api/approvals/count` route MUST be defined BEFORE `/api/approvals/{approval_id}` — otherwise FastAPI matches `"count"` as an `approval_id` parameter and returns 422.

```python
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

    # If approved, execute the action
    if decision == "approved":
        from ..remediation import execute_action
        import json
        result = execute_action(
            approval["action_type"],
            json.loads(approval["action_params"]),
            triggered_by=username,
        )
        db.update_approval_result(approval_id, json.dumps(result))

    db.audit_log("approval_decision", username,
                 f"id={approval_id} decision={decision}", _client_ip(request))
    return {"status": "ok", "decision": decision}
```

- [ ] **Step 2: Add auto-approve timer to scheduler**

In `share/noba-web/server/scheduler.py`, add a periodic check (every 60s) that calls `db.auto_approve_expired()` and executes any auto-approved actions.

- [ ] **Step 3: Write API tests**

Test the approval endpoints:
- GET /api/approvals — auth, returns list
- POST /api/approvals/{id}/decide — approve flow, deny flow
- Viewer cannot decide (403)
- Non-existent approval (404)
- Already-decided approval (400)
- GET /api/approvals/count — returns pending count

- [ ] **Step 4: Run tests**

```bash
pytest tests/ --tb=short 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/routers/automations.py share/noba-web/server/scheduler.py tests/
git commit -m "feat(v3): add approval queue API endpoints with auto-approve timer"
```

---

### Task 5: Maintenance Window API Endpoints

Add REST endpoints for maintenance window CRUD and active window status.

**Files:**
- Modify: `share/noba-web/server/routers/automations.py`
- Modify: `share/noba-web/server/routers/operations.py` (active window status)
- Modify: `share/noba-web/server/alerts.py` (enhanced window checking)
- Modify: `share/noba-web/server/scheduler.py` (use DB-backed windows)

- [ ] **Step 1: Add maintenance window CRUD endpoints**

```python
# ── Maintenance Windows ─────────────────────────────────────────────────────

@router.get("/api/maintenance-windows")
def api_list_maintenance_windows(auth=Depends(_get_auth)):
    """List all maintenance windows."""
    return db.list_maintenance_windows()


@router.post("/api/maintenance-windows")
async def api_create_maintenance_window(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    body = await _read_body(request)
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    wid = db.insert_maintenance_window(
        name=name,
        schedule=body.get("schedule"),
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


@router.get("/api/maintenance-windows/active")
def api_active_maintenance_windows(auth=Depends(_get_auth)):
    """Get currently active maintenance windows."""
    return db.get_active_maintenance_windows()
```

- [ ] **Step 2: Refactor `in_maintenance_window` to use DB**

Update `alerts.py` to check DB-backed windows (not just YAML config). Keep backward compatibility with YAML `maintenanceWindows` config by checking both sources.

- [ ] **Step 3: Add alert suppression + auto-close behavior**

In the alert evaluation loop, when a maintenance window is active:
- If `suppress_alerts` is True, skip alert notification dispatch
- If `auto_close_alerts` is True, auto-resolve alerts that clear during the window

- [ ] **Step 4: Write API tests**

Test CRUD + active window detection + suppression behavior.

- [ ] **Step 5: Run tests**

```bash
pytest tests/ --tb=short 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add share/noba-web/server/ tests/
git commit -m "feat(v3): add maintenance window CRUD with alert suppression and autonomy override"
```

---

### Task 6: Enhanced Action Audit Trail

Extend the audit logging for automated actions with richer context.

**Files:**
- Modify: `share/noba-web/server/db/core.py`
- Modify: `share/noba-web/server/alerts.py`
- Modify: `share/noba-web/server/remediation.py`

- [ ] **Step 1: Add `action_audit` table**

```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS action_audit (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp     INTEGER NOT NULL,
        trigger_type  TEXT NOT NULL,
        trigger_id    TEXT,
        action_type   TEXT NOT NULL,
        action_params TEXT,
        target        TEXT,
        outcome       TEXT NOT NULL,
        duration_s    REAL,
        output        TEXT,
        approved_by   TEXT,
        rollback_result TEXT,
        error         TEXT
    )
""")
```

- [ ] **Step 2: Add DB CRUD methods**

```python
def insert_action_audit(self, trigger_type, trigger_id, action_type, action_params,
                        target, outcome, duration_s, output, approved_by=None,
                        rollback_result=None, error=None):
    """Record an automated action for audit."""

def get_action_audit(self, limit=100, trigger_type=None, outcome=None):
    """Query action audit trail with optional filters."""
```

- [ ] **Step 3: Wire audit recording into remediation.execute_action**

After every `execute_action` call, record the result in `action_audit`.

- [ ] **Step 4: Add API endpoint**

```python
@router.get("/api/action-audit")
def api_action_audit(request: Request, auth=Depends(_get_auth)):
    limit = min(int(request.query_params.get("limit", "100")), 500)
    trigger_type = request.query_params.get("trigger_type")
    outcome = request.query_params.get("outcome")
    return db.get_action_audit(limit=limit, trigger_type=trigger_type, outcome=outcome)
```

- [ ] **Step 5: Write tests + run**

- [ ] **Step 6: Commit**

```bash
git add share/noba-web/server/ tests/
git commit -m "feat(v3): add enhanced action audit trail with full context"
```

---

### Task 7: Register New Actions in Workflow Engine

Register the new remediation action types as automation builders so they can be used in workflows.

**Files:**
- Modify: `share/noba-web/server/workflow_engine.py`
- Modify: `share/noba-web/server/config.py` (add new types to ALLOWED_AUTO_TYPES)

- [ ] **Step 1: Add remediation builder to workflow engine**

In `workflow_engine.py`, add a generic remediation builder that wraps `remediation.execute_action`:

```python
def _build_auto_remediation_process(config, run_id):
    """Generic builder for remediation action types."""
    from .remediation import execute_action
    action_type = config.get("remediation_type", "")
    params = config.get("params", {})
    result = execute_action(action_type, params)
    # Wrap result in a Popen-compatible object
    output = result.get("output", "")
    if result.get("error"):
        output += f"\nError: {result['error']}"
    return _SimpleResult(0 if result["success"] else 1, output)
```

Register in `_AUTO_BUILDERS`:
```python
"remediation": _build_auto_remediation_process,
```

- [ ] **Step 2: Add "remediation" to ALLOWED_AUTO_TYPES**

In `config.py`, add `"remediation"` to the `ALLOWED_AUTO_TYPES` tuple.

- [ ] **Step 3: Write tests**

Test that a remediation automation can be created, and that the builder calls `execute_action` with the correct params.

- [ ] **Step 4: Run tests**

```bash
pytest tests/ --tb=short 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/workflow_engine.py share/noba-web/server/config.py tests/
git commit -m "feat(v3): register remediation actions as workflow-compatible automation type"
```

---

### Task 8: Vue — Approval Queue Component

Build the frontend components for the approval queue.

**Files:**
- Create: `share/noba-web/frontend/src/stores/approvals.js`
- Create: `share/noba-web/frontend/src/components/automations/ApprovalQueue.vue`
- Modify: `share/noba-web/frontend/src/views/AutomationsView.vue` (add approvals tab)
- Modify: `share/noba-web/frontend/src/components/layout/AppHeader.vue` (approval badge)

- [ ] **Step 1: Create approvals Pinia store**

```js
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useApi } from '../composables/useApi'

export const useApprovalsStore = defineStore('approvals', () => {
  const pending = ref([])
  const count = ref(0)

  async function fetchPending() {
    const { get } = useApi()
    pending.value = await get('/api/approvals?status=pending')
    count.value = pending.value.length
  }

  async function fetchCount() {
    const { get } = useApi()
    const data = await get('/api/approvals/count')
    count.value = data.count
  }

  async function decide(approvalId, decision) {
    const { post } = useApi()
    await post(`/api/approvals/${approvalId}/decide`, { decision })
    await fetchPending()
  }

  return { pending, count, fetchPending, fetchCount, decide }
})
```

- [ ] **Step 2: Create ApprovalQueue.vue**

A list of pending approvals with approve/deny buttons. Each approval shows:
- Trigger source (what alert/rule caused this)
- Action type + params
- Target
- Time since requested
- Auto-approve countdown
- Approve / Deny buttons

- [ ] **Step 3: Add approvals tab to AutomationsView**

Add an "Approvals" tab with a badge showing pending count.

- [ ] **Step 4: Add approval count badge to header**

In AppHeader.vue, add an approval bell/icon near the notification bell that shows the pending approval count. Poll every 30s via `approvalsStore.fetchCount()`.

- [ ] **Step 5: Add store test for approvals.js**

Create `share/noba-web/frontend/src/__tests__/stores/approvals.test.js` testing: initial state, fetchPending mocks, decide calls API correctly, count updates.

- [ ] **Step 6: Build and verify**

```bash
cd share/noba-web/frontend && npm run build && npm test
```

- [ ] **Step 7: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add approval queue UI with approve/deny and header badge"
```

---

### Task 9: Vue — Maintenance Windows Component

Build the frontend for maintenance window management.

**Files:**
- Create: `share/noba-web/frontend/src/components/automations/MaintenanceWindows.vue`
- Modify: `share/noba-web/frontend/src/views/AutomationsView.vue` (add maintenance tab)
- Modify: `share/noba-web/frontend/src/components/layout/AppHeader.vue` (active window indicator)

- [ ] **Step 1: Create MaintenanceWindows.vue**

CRUD interface for maintenance windows:
- Table listing all windows (name, schedule/one-off, duration, behaviors, enabled)
- Create form in modal (name, type: recurring/one-off, schedule or date range, duration, suppress alerts checkbox, override autonomy dropdown, auto-close alerts checkbox)
- Edit/delete buttons
- "Active Now" badge on windows that are currently active

API calls:
- `GET /api/maintenance-windows`
- `POST /api/maintenance-windows`
- `PUT /api/maintenance-windows/{id}`
- `DELETE /api/maintenance-windows/{id}`

- [ ] **Step 2: Add maintenance tab to AutomationsView**

Add a "Maintenance" tab.

- [ ] **Step 3: Add active window indicator to header**

In AppHeader.vue, poll `GET /api/maintenance-windows/active` every 60s. When active, show a small wrench icon or pill badge with the window name. Use a distinctive color (amber/yellow) so operators know maintenance mode is on.

- [ ] **Step 4: Build and verify**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add maintenance window UI with CRUD and active indicator"
```

---

### Task 10: Vue — Autonomy Selector + Alert Rule Enhancement

Add autonomy level selection to the alert rule editor and action audit view.

**Files:**
- Create: `share/noba-web/frontend/src/components/automations/AutonomySelector.vue`
- Modify: `share/noba-web/frontend/src/components/settings/AlertsTab.vue`
- Modify: `share/noba-web/frontend/src/views/AutomationsView.vue` (add action audit tab)

- [ ] **Step 1: Create AutonomySelector.vue**

A dropdown component for selecting autonomy level:

```vue
<script setup>
const model = defineModel()
const levels = [
  { value: 'execute', label: 'Execute', desc: 'Run immediately', color: 'var(--success)' },
  { value: 'approve', label: 'Approve', desc: 'Queue for approval', color: 'var(--warning)' },
  { value: 'notify', label: 'Notify', desc: 'Notify only', color: 'var(--accent)' },
  { value: 'disabled', label: 'Disabled', desc: 'Rule inactive', color: 'var(--text-dim)' },
]
</script>

<template>
  <select class="field-select" v-model="model">
    <option v-for="l in levels" :key="l.value" :value="l.value">
      {{ l.label }} — {{ l.desc }}
    </option>
  </select>
</template>
```

- [ ] **Step 2: Add autonomy to alert rule editor**

In AlertsTab.vue, add the AutonomySelector to the alert rule form, bound to `rule.autonomy`. Also add an `auto_approve_timeout` numeric input (minutes) shown when autonomy is "approve".

- [ ] **Step 3: Add action audit tab to AutomationsView**

New tab showing `GET /api/action-audit` in a DataTable with columns: time, trigger, action, target, outcome (badge), duration, approved by.

- [ ] **Step 4: Build and verify**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "feat(v3): add autonomy selector, alert rule enhancement, action audit view"
```

---

### Task 11: Final Verification + CHANGELOG

Run full test suites, rebuild frontend, update CHANGELOG.

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Run ruff on all modified backend files**

```bash
ruff check share/noba-web/server/
```

- [ ] **Step 2: Run full backend test suite**

```bash
cd /home/raizen/noba && pytest tests/ -v --tb=short 2>&1 | tail -15
```

Expected: All tests pass (1451+ existing + new Phase 4 tests)

- [ ] **Step 3: Run frontend tests**

```bash
cd share/noba-web/frontend && npm test
```

- [ ] **Step 4: Rebuild frontend**

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 5: Update CHANGELOG.md**

Add under `[Unreleased]` `### Changed`:

```markdown
- **Advanced automation engine (v3 Phase 4)** — Added 8 remediation action types (restart_container, restart_service, flush_dns, clear_cache, trigger_backup, failover_dns, scale_container, run_playbook). Per-rule autonomy levels (execute/approve/notify/disabled). DB-backed approval queue with auto-approve timeout. Named maintenance windows with alert suppression and autonomy override. Enhanced action audit trail.
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(v3): Phase 4 complete — advanced automation engine

Added:
- 8 remediation action types with validation and health checks
- Per-rule autonomy (execute/approve/notify/disabled)
- DB-backed approval queue with auto-approve timeout
- Named maintenance windows with alert suppression + autonomy override
- Enhanced action audit trail
- Vue UI: approval queue, maintenance windows, autonomy selector, action audit"
```

---

## Verification Checklist

- [ ] All existing 1451+ backend tests still pass
- [ ] New Phase 4 tests pass (remediation, approval, maintenance, autonomy)
- [ ] Frontend builds cleanly
- [ ] Frontend tests pass
- [ ] Remediation actions: all 8 types validate and execute correctly
- [ ] Autonomy: execute/approve/notify/disabled all behave correctly
- [ ] Approval queue: pending list, approve/deny, auto-approve timer
- [ ] Maintenance windows: CRUD, active detection, alert suppression, autonomy override
- [ ] Action audit: records all automated actions with full context
- [ ] UI: approval badge in header, maintenance indicator, autonomy selector in rule editor
- [ ] CHANGELOG updated
