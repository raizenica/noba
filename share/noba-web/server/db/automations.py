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
