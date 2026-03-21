"""Noba – DB automation functions (CRUD, job runs, API keys, notifications, dashboards)."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time

from ..config import JOB_RETENTION_DAYS

logger = logging.getLogger("noba")


def _parse_step_from_trigger(trigger: str) -> dict:
    """Parse step index and retry info from a workflow trigger string."""
    # Format: "workflow:<auto_id>:step<N>" or "workflow:<auto_id>:step<N>:retry<M>"
    # or "workflow:<auto_id>:parallel<N>"
    result: dict = {"index": 0, "retry": 0, "mode": "sequential"}
    if ":step" in trigger:
        m = re.search(r":step(\d+)", trigger)
        if m:
            result["index"] = int(m.group(1))
        m = re.search(r":retry(\d+)", trigger)
        if m:
            result["retry"] = int(m.group(1))
    elif ":parallel" in trigger:
        m = re.search(r":parallel(\d+)", trigger)
        if m:
            result["index"] = int(m.group(1))
            result["mode"] = "parallel"
    return result


# ── Automation CRUD ───────────────────────────────────────────────────────────

def insert_automation(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    auto_id: str,
    name: str,
    atype: str,
    config: dict,
    schedule: str | None = None,
    enabled: bool = True,
) -> bool:
    now = int(time.time())
    try:
        with lock:
            conn.execute(
                "INSERT OR IGNORE INTO automations "
                "(id, name, type, config, schedule, enabled, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (auto_id, name, atype, json.dumps(config), schedule,
                 1 if enabled else 0, now, now),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("insert_automation failed: %s", e)
        return False


def update_automation(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    auto_id: str,
    **kwargs,
) -> bool:
    allowed = {"name", "type", "config", "schedule", "enabled"}
    sets = []
    params: list = []
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        if k == "config" and isinstance(v, dict):
            v = json.dumps(v)
        if k == "enabled":
            v = 1 if v else 0
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        return False
    sets.append("updated_at = ?")
    params.append(int(time.time()))
    params.append(auto_id)
    try:
        with lock:
            conn.execute(
                f"UPDATE automations SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("update_automation failed: %s", e)
        return False


def delete_automation(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    auto_id: str,
) -> bool:
    try:
        with lock:
            cur = conn.execute("DELETE FROM automations WHERE id = ?", (auto_id,))
            conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_automation failed: %s", e)
        return False


def list_automations(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    type_filter: str | None = None,
) -> list[dict]:
    try:
        with lock:
            if type_filter:
                rows = conn.execute(
                    "SELECT id, name, type, config, schedule, enabled, created_at, updated_at "
                    "FROM automations WHERE type = ? ORDER BY name",
                    (type_filter,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, name, type, config, schedule, enabled, created_at, updated_at "
                    "FROM automations ORDER BY name"
                ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "type": r[2],
                "config": json.loads(r[3]) if r[3] else {},
                "schedule": r[4], "enabled": bool(r[5]),
                "created_at": r[6], "updated_at": r[7],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("list_automations failed: %s", e)
        return []


def get_automation(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    auto_id: str,
) -> dict | None:
    try:
        with lock:
            r = conn.execute(
                "SELECT id, name, type, config, schedule, enabled, created_at, updated_at "
                "FROM automations WHERE id = ?",
                (auto_id,),
            ).fetchone()
        if not r:
            return None
        return {
            "id": r[0], "name": r[1], "type": r[2],
            "config": json.loads(r[3]) if r[3] else {},
            "schedule": r[4], "enabled": bool(r[5]),
            "created_at": r[6], "updated_at": r[7],
        }
    except Exception as e:
        logger.error("get_automation failed: %s", e)
        return None


# ── Job Runs ──────────────────────────────────────────────────────────────────

def insert_job_run(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    automation_id: str | None,
    trigger: str,
    triggered_by: str,
) -> int | None:
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "INSERT INTO job_runs "
                "(automation_id, trigger, status, started_at, triggered_by) "
                "VALUES (?,?,?,?,?)",
                (automation_id, trigger, "running", now, triggered_by),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error("insert_job_run failed: %s", e)
        return None


def update_job_run(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    run_id: int,
    status: str,
    output: str | None = None,
    exit_code: int | None = None,
    error: str | None = None,
) -> None:
    now = int(time.time())
    try:
        with lock:
            conn.execute(
                "UPDATE job_runs SET status=?, finished_at=?, output=?, "
                "exit_code=?, error=? WHERE id=?",
                (status, now, output, exit_code, error, run_id),
            )
            conn.commit()
    except Exception as e:
        logger.error("update_job_run failed: %s", e)


def get_job_runs(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    automation_id: str | None = None,
    limit: int = 50,
    status: str | None = None,
    trigger_prefix: str | None = None,
) -> list[dict]:
    try:
        clauses = []
        params: list = []
        if automation_id:
            clauses.append("automation_id = ?")
            params.append(automation_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if trigger_prefix:
            clauses.append("trigger LIKE ?")
            params.append(trigger_prefix + "%")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with lock:
            rows = conn.execute(
                "SELECT id, automation_id, trigger, status, started_at, "
                "finished_at, exit_code, triggered_by, error "
                f"FROM job_runs{where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            {
                "id": r[0], "automation_id": r[1], "trigger": r[2],
                "status": r[3], "started_at": r[4], "finished_at": r[5],
                "exit_code": r[6], "triggered_by": r[7], "error": r[8],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("get_job_runs failed: %s", e)
        return []


def get_job_run(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    run_id: int,
) -> dict | None:
    try:
        with lock:
            r = conn.execute(
                "SELECT id, automation_id, trigger, status, started_at, "
                "finished_at, exit_code, output, triggered_by, error "
                "FROM job_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if not r:
            return None
        return {
            "id": r[0], "automation_id": r[1], "trigger": r[2],
            "status": r[3], "started_at": r[4], "finished_at": r[5],
            "exit_code": r[6], "output": r[7], "triggered_by": r[8],
            "error": r[9],
        }
    except Exception as e:
        logger.error("get_job_run failed: %s", e)
        return None


def get_automation_stats(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> dict:
    """Return per-automation success/failure counts and avg duration."""
    try:
        with lock:
            rows = conn.execute("""
                SELECT automation_id,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS ok,
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS fail,
                       AVG(CASE WHEN finished_at IS NOT NULL AND started_at IS NOT NULL
                           THEN finished_at - started_at END) AS avg_dur,
                       MAX(started_at) AS last_run
                FROM job_runs
                WHERE automation_id IS NOT NULL
                GROUP BY automation_id
            """).fetchall()
        return {
            r[0]: {"total": r[1], "ok": r[2], "fail": r[3],
                   "avg_duration": round(r[4], 1) if r[4] else None,
                   "last_run": r[5]}
            for r in rows
        }
    except Exception as e:
        logger.error("get_automation_stats failed: %s", e)
        return {}


def get_workflow_trace(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    workflow_auto_id: str,
    limit: int = 20,
) -> list[dict]:
    """Get execution traces for a workflow — groups runs by trigger timestamp."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, automation_id, trigger, status, started_at, finished_at, "
                "exit_code, output, triggered_by, error "
                "FROM job_runs WHERE trigger LIKE ? "
                "ORDER BY id DESC LIMIT ?",
                (f"workflow:{workflow_auto_id}%", limit),
            ).fetchall()
        return [
            {
                "id": r[0], "automation_id": r[1], "trigger": r[2],
                "status": r[3], "started_at": r[4], "finished_at": r[5],
                "exit_code": r[6], "output": r[7][:500] if r[7] else None,
                "triggered_by": r[8], "error": r[9],
                "step": _parse_step_from_trigger(r[2]),
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("get_workflow_trace failed: %s", e)
        return []


def prune_job_runs(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> None:
    cutoff = int(time.time()) - JOB_RETENTION_DAYS * 86400
    try:
        with lock:
            conn.execute(
                "DELETE FROM job_runs WHERE finished_at IS NOT NULL AND finished_at < ?",
                (cutoff,),
            )
            conn.commit()
    except Exception as e:
        logger.error("prune_job_runs failed: %s", e)


def mark_stale_jobs(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> None:
    """Mark any 'running' jobs as 'failed' on startup (leftover from crash)."""
    try:
        with lock:
            conn.execute(
                "UPDATE job_runs SET status='failed', error='Server restarted' "
                "WHERE status IN ('running', 'queued')"
            )
            conn.commit()
    except Exception as e:
        logger.error("mark_stale_jobs failed: %s", e)


# ── API Keys ──────────────────────────────────────────────────────────────────

def insert_api_key(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    key_id: str,
    name: str,
    key_hash: str,
    role: str,
    expires_at: int | None = None,
) -> None:
    """Insert a new API key."""
    try:
        with lock:
            conn.execute(
                "INSERT INTO api_keys (id, name, key_hash, role, created_at, expires_at) "
                "VALUES (?,?,?,?,?,?)",
                (key_id, name, key_hash, role, int(time.time()), expires_at),
            )
            conn.commit()
    except Exception as e:
        logger.error("insert_api_key failed: %s", e)


def get_api_key(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    key_hash: str,
) -> dict | None:
    """Look up an API key by its hash and update last_used timestamp."""
    try:
        with lock:
            r = conn.execute(
                "SELECT id, name, key_hash, role, created_at, expires_at, last_used "
                "FROM api_keys WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
            if not r:
                return None
            conn.execute(
                "UPDATE api_keys SET last_used = ? WHERE key_hash = ?",
                (int(time.time()), key_hash),
            )
            conn.commit()
        return {
            "id": r[0], "name": r[1], "key_hash": r[2], "role": r[3],
            "created_at": r[4], "expires_at": r[5], "last_used": r[6],
        }
    except Exception as e:
        logger.error("get_api_key failed: %s", e)
        return None


def list_api_keys(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> list[dict]:
    """List all API keys (excluding key_hash from results)."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, name, role, created_at, expires_at, last_used "
                "FROM api_keys ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "role": r[2],
                "created_at": r[3], "expires_at": r[4], "last_used": r[5],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("list_api_keys failed: %s", e)
        return []


def delete_api_key(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    key_id: str,
) -> bool:
    """Delete an API key by its id."""
    try:
        with lock:
            cur = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
            conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("delete_api_key failed: %s", e)
        return False


# ── Notifications ─────────────────────────────────────────────────────────────

def insert_notification(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    level: str,
    title: str,
    message: str,
    username: str | None = None,
) -> None:
    """Insert a notification."""
    try:
        with lock:
            conn.execute(
                "INSERT INTO notifications (timestamp, level, title, message, username) "
                "VALUES (?,?,?,?,?)",
                (int(time.time()), level, title, message, username),
            )
            conn.commit()
    except Exception as e:
        logger.error("insert_notification failed: %s", e)


def get_notifications(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str | None = None,
    unread_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    """Query notifications with optional filters."""
    try:
        clauses: list[str] = []
        params: list = []
        if username:
            clauses.append("(username = ? OR username IS NULL)")
            params.append(username)
        if unread_only:
            clauses.append("read = 0")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with lock:
            rows = conn.execute(
                "SELECT id, timestamp, level, title, message, read, username "
                f"FROM notifications{where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            {
                "id": r[0], "timestamp": r[1], "level": r[2],
                "title": r[3], "message": r[4], "read": bool(r[5]),
                "username": r[6],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("get_notifications failed: %s", e)
        return []


def mark_notification_read(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    notif_id: int,
    username: str,
) -> None:
    """Mark a single notification as read."""
    try:
        with lock:
            conn.execute(
                "UPDATE notifications SET read = 1 "
                "WHERE id = ? AND (username = ? OR username IS NULL)",
                (notif_id, username),
            )
            conn.commit()
    except Exception as e:
        logger.error("mark_notification_read failed: %s", e)


def mark_all_notifications_read(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
) -> None:
    """Mark all notifications for a user as read."""
    try:
        with lock:
            conn.execute(
                "UPDATE notifications SET read = 1 "
                "WHERE (username = ? OR username IS NULL) AND read = 0",
                (username,),
            )
            conn.commit()
    except Exception as e:
        logger.error("mark_all_notifications_read failed: %s", e)


def get_unread_count(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
) -> int:
    """Return count of unread notifications for a user."""
    try:
        with lock:
            r = conn.execute(
                "SELECT COUNT(*) FROM notifications "
                "WHERE (username = ? OR username IS NULL) AND read = 0",
                (username,),
            ).fetchone()
        return r[0] if r else 0
    except Exception as e:
        logger.error("get_unread_count failed: %s", e)
        return 0


# ── User Dashboards ───────────────────────────────────────────────────────────

def save_user_dashboard(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
    card_order: list | None = None,
    card_vis: dict | None = None,
    card_theme: dict | None = None,
) -> None:
    """Save or update a user's dashboard layout preferences."""
    try:
        with lock:
            conn.execute(
                "INSERT OR REPLACE INTO user_dashboards "
                "(username, card_order, card_vis, card_theme, updated_at) "
                "VALUES (?,?,?,?,?)",
                (
                    username,
                    json.dumps(card_order) if card_order is not None else None,
                    json.dumps(card_vis) if card_vis is not None else None,
                    json.dumps(card_theme) if card_theme is not None else None,
                    int(time.time()),
                ),
            )
            conn.commit()
    except Exception as e:
        logger.error("save_user_dashboard failed: %s", e)


def get_user_dashboard(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
) -> dict | None:
    """Retrieve a user's dashboard layout preferences."""
    try:
        with lock:
            r = conn.execute(
                "SELECT username, card_order, card_vis, card_theme, updated_at "
                "FROM user_dashboards WHERE username = ?",
                (username,),
            ).fetchone()
        if not r:
            return None
        return {
            "username": r[0],
            "card_order": json.loads(r[1]) if r[1] else None,
            "card_vis": json.loads(r[2]) if r[2] else None,
            "card_theme": json.loads(r[3]) if r[3] else None,
            "updated_at": r[4],
        }
    except Exception as e:
        logger.error("get_user_dashboard failed: %s", e)
        return None


# ── Approval Queue ─────────────────────────────────────────────────────────────

def _insert_approval(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    automation_id: str,
    trigger: str,
    trigger_source: str | None,
    action_type: str,
    action_params: dict,
    target: str | None,
    requested_by: str | None,
    auto_approve_at: int | None = None,
    run_id: int | None = None,
) -> int | None:
    """Insert a new approval request, return lastrowid."""
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "INSERT INTO approval_queue "
                "(automation_id, run_id, trigger, trigger_source, action_type, "
                "action_params, target, status, requested_at, requested_by, auto_approve_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    automation_id, run_id, trigger, trigger_source, action_type,
                    json.dumps(action_params), target, "pending", now,
                    requested_by, auto_approve_at,
                ),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error("_insert_approval failed: %s", e)
        return None


def _list_approvals(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    status: str = "pending",
) -> list[dict]:
    """List approvals filtered by status, newest first."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, automation_id, run_id, trigger, trigger_source, "
                "action_type, action_params, target, status, requested_at, "
                "requested_by, decided_at, decided_by, auto_approve_at, result "
                "FROM approval_queue WHERE status = ? "
                "ORDER BY requested_at DESC",
                (status,),
            ).fetchall()
        return [
            {
                "id": r[0], "automation_id": r[1], "run_id": r[2],
                "trigger": r[3], "trigger_source": r[4],
                "action_type": r[5],
                "action_params": json.loads(r[6]) if r[6] else {},
                "target": r[7], "status": r[8],
                "requested_at": r[9], "requested_by": r[10],
                "decided_at": r[11], "decided_by": r[12],
                "auto_approve_at": r[13], "result": r[14],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("_list_approvals failed: %s", e)
        return []


def _get_approval(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    approval_id: int,
) -> dict | None:
    """Fetch a single approval by id."""
    try:
        with lock:
            r = conn.execute(
                "SELECT id, automation_id, run_id, trigger, trigger_source, "
                "action_type, action_params, target, status, requested_at, "
                "requested_by, decided_at, decided_by, auto_approve_at, result "
                "FROM approval_queue WHERE id = ?",
                (approval_id,),
            ).fetchone()
        if not r:
            return None
        return {
            "id": r[0], "automation_id": r[1], "run_id": r[2],
            "trigger": r[3], "trigger_source": r[4],
            "action_type": r[5],
            "action_params": json.loads(r[6]) if r[6] else {},
            "target": r[7], "status": r[8],
            "requested_at": r[9], "requested_by": r[10],
            "decided_at": r[11], "decided_by": r[12],
            "auto_approve_at": r[13], "result": r[14],
        }
    except Exception as e:
        logger.error("_get_approval failed: %s", e)
        return None


def _decide_approval(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    approval_id: int,
    decision: str,
    decided_by: str,
) -> bool:
    """Set status to decision (approved/denied) only if currently pending."""
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "UPDATE approval_queue SET status=?, decided_at=?, decided_by=? "
                "WHERE id=? AND status='pending'",
                (decision, now, decided_by, approval_id),
            )
            conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("_decide_approval failed: %s", e)
        return False


def _update_approval_result(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    approval_id: int,
    result: str,
) -> None:
    """Store the execution result for a resolved approval."""
    try:
        with lock:
            conn.execute(
                "UPDATE approval_queue SET result=? WHERE id=?",
                (result, approval_id),
            )
            conn.commit()
    except Exception as e:
        logger.error("_update_approval_result failed: %s", e)


def _auto_approve_expired(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> int:
    """Auto-approve pending items whose auto_approve_at <= now. Return rowcount."""
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "UPDATE approval_queue SET status='auto_approved', decided_at=? "
                "WHERE status='pending' AND auto_approve_at IS NOT NULL "
                "AND auto_approve_at <= ?",
                (now, now),
            )
            conn.commit()
        return cur.rowcount
    except Exception as e:
        logger.error("_auto_approve_expired failed: %s", e)
        return 0


def _count_pending_approvals(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> int:
    """Return count of pending approval requests."""
    try:
        with lock:
            r = conn.execute(
                "SELECT COUNT(*) FROM approval_queue WHERE status='pending'"
            ).fetchone()
        return r[0] if r else 0
    except Exception as e:
        logger.error("_count_pending_approvals failed: %s", e)
        return 0


def _save_workflow_context(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    approval_id: int,
    context: dict,
) -> bool:
    """Store graph workflow context JSON on an approval_queue row."""
    try:
        with lock:
            conn.execute(
                "UPDATE approval_queue SET workflow_context=? WHERE id=?",
                (json.dumps(context), approval_id),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("_save_workflow_context failed: %s", e)
        return False


def _get_workflow_context(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    approval_id: int,
) -> dict | None:
    """Retrieve graph workflow context for an approval_queue row."""
    try:
        with lock:
            r = conn.execute(
                "SELECT workflow_context FROM approval_queue WHERE id=?",
                (approval_id,),
            ).fetchone()
        if not r or not r[0]:
            return None
        return json.loads(r[0])
    except Exception as e:
        logger.error("_get_workflow_context failed: %s", e)
        return None


# ── Maintenance Windows ────────────────────────────────────────────────────────

def _insert_maintenance_window(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    name: str,
    schedule: str | None = None,
    duration_min: int = 60,
    one_off_start: int | None = None,
    one_off_end: int | None = None,
    suppress_alerts: bool = True,
    override_autonomy: str | None = None,
    auto_close_alerts: bool = False,
    created_by: str | None = None,
) -> int | None:
    """Insert a maintenance window, return lastrowid."""
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "INSERT INTO maintenance_windows "
                "(name, schedule, duration_min, one_off_start, one_off_end, "
                "suppress_alerts, override_autonomy, auto_close_alerts, "
                "enabled, created_by, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    name, schedule, duration_min, one_off_start, one_off_end,
                    1 if suppress_alerts else 0,
                    override_autonomy,
                    1 if auto_close_alerts else 0,
                    1, created_by, now,
                ),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error("_insert_maintenance_window failed: %s", e)
        return None


def _list_maintenance_windows(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> list[dict]:
    """Return all maintenance windows, newest first."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, name, schedule, duration_min, one_off_start, one_off_end, "
                "suppress_alerts, override_autonomy, auto_close_alerts, enabled, "
                "created_by, created_at "
                "FROM maintenance_windows ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "schedule": r[2],
                "duration_min": r[3], "one_off_start": r[4], "one_off_end": r[5],
                "suppress_alerts": bool(r[6]), "override_autonomy": r[7],
                "auto_close_alerts": bool(r[8]), "enabled": bool(r[9]),
                "created_by": r[10], "created_at": r[11],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("_list_maintenance_windows failed: %s", e)
        return []


def _update_maintenance_window(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    window_id: int,
    **kwargs,
) -> bool:
    """Update specified fields on a maintenance window."""
    allowed = {
        "name", "schedule", "duration_min", "one_off_start", "one_off_end",
        "suppress_alerts", "override_autonomy", "auto_close_alerts", "enabled",
    }
    sets: list[str] = []
    params: list = []
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        if k in ("suppress_alerts", "auto_close_alerts", "enabled"):
            v = 1 if v else 0
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        return False
    params.append(window_id)
    try:
        with lock:
            cur = conn.execute(
                f"UPDATE maintenance_windows SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("_update_maintenance_window failed: %s", e)
        return False


def _delete_maintenance_window(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    window_id: int,
) -> bool:
    """Delete a maintenance window. Return True if a row was deleted."""
    try:
        with lock:
            cur = conn.execute(
                "DELETE FROM maintenance_windows WHERE id = ?", (window_id,)
            )
            conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("_delete_maintenance_window failed: %s", e)
        return False


# ── Action Audit Trail ─────────────────────────────────────────────────────────

def _insert_action_audit(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    trigger_type: str,
    trigger_id: str | None,
    action_type: str,
    action_params: dict | None,
    target: str | None,
    outcome: str,
    duration_s: float | None = None,
    output: str | None = None,
    approved_by: str | None = None,
    rollback_result: str | None = None,
    error: str | None = None,
) -> int | None:
    """Record an automated action for audit."""
    now = int(time.time())
    try:
        with lock:
            cur = conn.execute(
                "INSERT INTO action_audit "
                "(timestamp, trigger_type, trigger_id, action_type, action_params, "
                "target, outcome, duration_s, output, approved_by, rollback_result, error) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    now, trigger_type, trigger_id,
                    action_type, json.dumps(action_params) if action_params else None,
                    target, outcome, duration_s, output, approved_by,
                    rollback_result, error,
                ),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error("_insert_action_audit failed: %s", e)
        return None


def _get_action_audit(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    limit: int = 100,
    trigger_type: str | None = None,
    outcome: str | None = None,
) -> list[dict]:
    """Query action audit trail with optional filters."""
    try:
        clauses: list[str] = []
        params: list = []
        if trigger_type:
            clauses.append("trigger_type = ?")
            params.append(trigger_type)
        if outcome:
            clauses.append("outcome = ?")
            params.append(outcome)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with lock:
            rows = conn.execute(
                "SELECT id, timestamp, trigger_type, trigger_id, action_type, "
                "action_params, target, outcome, duration_s, output, "
                "approved_by, rollback_result, error "
                f"FROM action_audit{where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            {
                "id": r[0], "timestamp": r[1], "trigger_type": r[2],
                "trigger_id": r[3], "action_type": r[4],
                "action_params": json.loads(r[5]) if r[5] else None,
                "target": r[6], "outcome": r[7], "duration_s": r[8],
                "output": r[9], "approved_by": r[10],
                "rollback_result": r[11], "error": r[12],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("_get_action_audit failed: %s", e)
        return []


def _get_active_maintenance_windows(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> list[dict]:
    """Return windows that are currently active.

    - One-off: active when one_off_start <= now <= one_off_end.
    - Cron-based: active when any minute in the past duration_min minutes
      matches the cron expression.
    Disabled windows (enabled=0) are never returned.
    """
    from ..scheduler import _match_cron
    from datetime import datetime, timezone

    now = int(time.time())
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, name, schedule, duration_min, one_off_start, one_off_end, "
                "suppress_alerts, override_autonomy, auto_close_alerts, enabled, "
                "created_by, created_at "
                "FROM maintenance_windows WHERE enabled = 1"
            ).fetchall()
    except Exception as e:
        logger.error("_get_active_maintenance_windows failed: %s", e)
        return []

    active = []
    for r in rows:
        window = {
            "id": r[0], "name": r[1], "schedule": r[2],
            "duration_min": r[3], "one_off_start": r[4], "one_off_end": r[5],
            "suppress_alerts": bool(r[6]), "override_autonomy": r[7],
            "auto_close_alerts": bool(r[8]), "enabled": bool(r[9]),
            "created_by": r[10], "created_at": r[11],
        }
        one_off_start = r[4]
        one_off_end = r[5]
        schedule = r[2]
        duration_min = r[3] or 60

        if one_off_start is not None and one_off_end is not None:
            # One-off window: directly check time range
            if one_off_start <= now <= one_off_end:
                active.append(window)
        elif schedule:
            # Cron-based: check if any minute in the last duration_min matches
            matched = False
            for offset in range(duration_min):
                ts = now - offset * 60
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
                if _match_cron(schedule, dt):
                    matched = True
                    break
            if matched:
                active.append(window)

    return active


# ── Playbook Templates ────────────────────────────────────────────────────────

def _list_playbook_templates(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> list[dict]:
    """List all playbook templates."""
    try:
        with lock:
            rows = conn.execute(
                "SELECT id, name, description, category, config, version "
                "FROM playbook_templates ORDER BY category, name"
            ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "description": r[2],
                "category": r[3],
                "config": json.loads(r[4]) if r[4] else {},
                "version": r[5],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("_list_playbook_templates failed: %s", e)
        return []


def _get_playbook_template(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    template_id: str,
) -> dict | None:
    """Get single template by id."""
    try:
        with lock:
            r = conn.execute(
                "SELECT id, name, description, category, config, version "
                "FROM playbook_templates WHERE id = ?",
                (template_id,),
            ).fetchone()
        if not r:
            return None
        return {
            "id": r[0], "name": r[1], "description": r[2],
            "category": r[3],
            "config": json.loads(r[4]) if r[4] else {},
            "version": r[5],
        }
    except Exception as e:
        logger.error("_get_playbook_template failed: %s", e)
        return None


def _upsert_playbook_template(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    template_id: str,
    name: str,
    description: str | None,
    category: str | None,
    config: dict,
    version: int = 1,
) -> bool:
    """Insert or update a playbook template."""
    try:
        with lock:
            conn.execute(
                "INSERT OR REPLACE INTO playbook_templates "
                "(id, name, description, category, config, version) "
                "VALUES (?,?,?,?,?,?)",
                (template_id, name, description, category,
                 json.dumps(config), version),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error("_upsert_playbook_template failed: %s", e)
        return False


def _seed_default_playbooks(
    conn: sqlite3.Connection,
    lock: threading.Lock,
) -> None:
    """Seed 4 default playbook templates using INSERT OR IGNORE."""
    templates = [
        {
            "id": "update-all-agents",
            "name": "Update All Agents",
            "description": "Check for updates on all agents, wait, verify versions, and report results.",
            "category": "maintenance",
            "config": {
                "nodes": [
                    {"id": "n1", "type": "agent_command",
                     "params": {"cmd_type": "update", "broadcast": True},
                     "label": "Check Updates"},
                    {"id": "n2", "type": "delay",
                     "params": {"seconds": 60},
                     "label": "Wait 60s"},
                    {"id": "n3", "type": "agent_command",
                     "params": {"cmd_type": "version_check", "broadcast": True},
                     "label": "Verify Versions"},
                    {"id": "n4", "type": "notify",
                     "params": {"level": "info", "title": "Agent Updates Complete",
                                "message": "All agents updated and verified."},
                     "label": "Report"},
                ],
                "edges": [
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "n3"},
                    {"from": "n3", "to": "n4"},
                ],
                "entry": "n1",
            },
            "version": 1,
        },
        {
            "id": "rolling-dns-restart",
            "name": "Rolling DNS Restart",
            "description": "Restart the primary DNS server, wait for propagation, verify DNS health, and notify.",
            "category": "maintenance",
            "config": {
                "nodes": [
                    {"id": "n1", "type": "service",
                     "params": {"service": "named.service", "action": "restart"},
                     "label": "Restart Primary DNS"},
                    {"id": "n2", "type": "delay",
                     "params": {"seconds": 30},
                     "label": "Wait 30s"},
                    {"id": "n3", "type": "condition",
                     "params": {"metric": "dns_ok", "operator": "==", "threshold": 1},
                     "label": "DNS OK?"},
                    {"id": "n4", "type": "notify",
                     "params": {"level": "info", "title": "DNS Restart Successful",
                                "message": "Primary DNS restarted and healthy."},
                     "label": "Success Notification"},
                    {"id": "n5", "type": "notify",
                     "params": {"level": "error", "title": "DNS Restart Failed",
                                "message": "Primary DNS did not recover after restart."},
                     "label": "Failure Notification"},
                ],
                "edges": [
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "n3"},
                    {"from": "n3", "to": "n4", "condition": True},
                    {"from": "n3", "to": "n5", "condition": False},
                ],
                "entry": "n1",
            },
            "version": 1,
        },
        {
            "id": "backup-verification",
            "name": "Backup Verification",
            "description": "Trigger a backup job, wait for completion, then report the result.",
            "category": "backup",
            "config": {
                "nodes": [
                    {"id": "n1", "type": "script",
                     "params": {"script": "backup", "args": "--verify"},
                     "label": "Trigger Backup"},
                    {"id": "n2", "type": "delay",
                     "params": {"seconds": 300},
                     "label": "Wait 5 Min"},
                    {"id": "n3", "type": "notify",
                     "params": {"level": "info", "title": "Backup Verification Complete",
                                "message": "Backup triggered and verification window passed."},
                     "label": "Report"},
                ],
                "edges": [
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "n3"},
                ],
                "entry": "n1",
            },
            "version": 1,
        },
        {
            "id": "disk-cleanup",
            "name": "Disk Cleanup",
            "description": "Check disk usage; if above 85%, find large files, require approval, then run cleanup.",
            "category": "maintenance",
            "config": {
                "nodes": [
                    {"id": "n1", "type": "condition",
                     "params": {"metric": "disk_percent", "operator": ">", "threshold": 85},
                     "label": "Disk > 85%?"},
                    {"id": "n2", "type": "script",
                     "params": {"script": "diskcheck", "args": "--find-large"},
                     "label": "Find Large Files"},
                    {"id": "n3", "type": "approval_gate",
                     "params": {"message": "Approve disk cleanup?", "timeout_s": 3600},
                     "label": "Approval Gate"},
                    {"id": "n4", "type": "script",
                     "params": {"script": "diskcheck", "args": "--cleanup"},
                     "label": "Execute Cleanup"},
                    {"id": "n5", "type": "notify",
                     "params": {"level": "info", "title": "Disk Cleanup Complete",
                                "message": "Disk cleanup executed successfully."},
                     "label": "Report"},
                    {"id": "n6", "type": "notify",
                     "params": {"level": "info", "title": "Disk OK",
                                "message": "Disk usage is below threshold. No action needed."},
                     "label": "No Action"},
                ],
                "edges": [
                    {"from": "n1", "to": "n2", "condition": True},
                    {"from": "n1", "to": "n6", "condition": False},
                    {"from": "n2", "to": "n3"},
                    {"from": "n3", "to": "n4"},
                    {"from": "n4", "to": "n5"},
                ],
                "entry": "n1",
            },
            "version": 1,
        },
    ]
    try:
        with lock:
            for t in templates:
                conn.execute(
                    "INSERT OR IGNORE INTO playbook_templates "
                    "(id, name, description, category, config, version) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        t["id"], t["name"], t["description"], t["category"],
                        json.dumps(t["config"]), t["version"],
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.error("_seed_default_playbooks failed: %s", e)
