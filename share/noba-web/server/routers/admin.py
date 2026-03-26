"""Noba – Admin endpoints (settings, audit, backup, log viewer, reports, plugins, runbooks)."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from ..alerts import dispatch_notifications
from ..config import ACTION_LOG, HISTORY_METRICS, LOG_DIR, NOBA_YAML
from ..constants import (
    CONFIG_UPLOAD_MAX_BYTES,
    DIFF_NAMES_LIMIT,
    DIR_ENTRIES_LIMIT,
    ERROR_TRUNCATE_LEN,
    FILE_VERSIONS_LIMIT,
    HISTORY_RESOLUTION_S,
    SNAPSHOT_LIST_LIMIT,
)
from ..deps import (
    _client_ip, _get_auth, _int_param, _read_body, _require_admin,
    _require_operator, _run_cmd, _safe_int, db,
    handle_errors,
)
from ..metrics import _read_file, strip_ansi
from ..plugins import plugin_manager
from ..runner import job_runner
from ..schemas import is_secret_key, validate_integration_urls
from ..yaml_config import read_yaml_settings, write_yaml_settings

logger = logging.getLogger("noba")

router = APIRouter()


# ── /api/settings ─────────────────────────────────────────────────────────────
@router.get("/api/settings")
@handle_errors
def api_settings_get(auth=Depends(_get_auth)):
    _, role = auth
    settings = read_yaml_settings()
    # Mask secrets for ALL roles including admin — secrets are write-only
    return {k: ("***" if is_secret_key(k) else v) for k, v in settings.items()}


@router.post("/api/settings")
@handle_errors
async def api_settings_post(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    url_errors = validate_integration_urls(body)
    if url_errors:
        raise HTTPException(status_code=400, detail="; ".join(url_errors))
    old_settings = read_yaml_settings()
    changed = []
    for k in body:
        ov = old_settings.get(k)
        nv = body.get(k)
        if ov != nv:
            changed.append({"key": k, "old": "***" if is_secret_key(k) else str(ov)[:80],
                            "new": "***" if is_secret_key(k) else str(nv)[:80]})
    ok = write_yaml_settings(body)
    if not ok:
        db.audit_log("settings_update", username, "Settings update failed", ip)
        raise HTTPException(500, "Failed to write settings")
    if changed:
        db.audit_log("settings_change", username, json.dumps(changed[:20]), ip)
    db.audit_log("settings_update", username, "Updated web settings", ip)
    return {"status": "ok"}


# ── /api/notifications/test ───────────────────────────────────────────────────
@router.post("/api/notifications/test")
@handle_errors
def api_notif_test(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    cfg = read_yaml_settings()
    notif_cfg = cfg.get("notifications", {})
    if not notif_cfg:
        return {"status": "ok", "message": "No notification channels configured"}
    threading.Thread(
        target=dispatch_notifications,
        args=("info", "This is a test notification from NOBA", notif_cfg, None),
        daemon=True,
    ).start()
    db.audit_log("test_notification", username, "Test notification triggered", _client_ip(request))
    return {"status": "ok", "message": "Notification sent"}


# ── /api/config/changelog ────────────────────────────────────────────────────
@router.get("/api/config/changelog")
@handle_errors
def api_config_changelog(auth=Depends(_require_admin)):
    entries = db.get_audit(limit=100, action_filter="settings_change")
    result = []
    for e in entries:
        details = e.get("details", "")
        try:
            changes = json.loads(details)
        except (json.JSONDecodeError, TypeError):
            changes = [{"key": "unknown", "old": "", "new": details}]
        result.append({
            "timestamp": e.get("time", ""),
            "username": e.get("username", ""),
            "changes": changes,
        })
    return result


# ── /api/audit ────────────────────────────────────────────────────────────────
@router.get("/api/audit")
@handle_errors
def api_audit(request: Request, auth=Depends(_require_admin)):
    limit = _int_param(request, "limit", 100, 1, 1000)
    user_filter = request.query_params.get("user", "")
    action_filter = request.query_params.get("action", "")
    from_ts = _safe_int(request.query_params.get("from", 0), 0)
    to_ts = _safe_int(request.query_params.get("to", 0), 0)
    return db.get_audit(limit=limit, username_filter=user_filter, action_filter=action_filter,
                        from_ts=from_ts, to_ts=to_ts)


# ── /api/config/backup & /api/config/restore ─────────────────────────────────
@router.get("/api/config/backup")
@handle_errors
def api_config_backup(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    body = b""
    if os.path.exists(NOBA_YAML):
        with open(NOBA_YAML, "rb") as f:
            body = f.read()
    db.audit_log("config_backup", username, "Downloaded config backup", _client_ip(request))
    return Response(
        content=body,
        media_type="application/x-yaml",
        headers={"Content-Disposition": 'attachment; filename="noba-config-backup.yaml"'},
    )


@router.post("/api/config/restore")
@handle_errors
async def api_config_restore(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    raw = await request.body()
    if len(raw) > CONFIG_UPLOAD_MAX_BYTES:
        raise HTTPException(413, "Upload too large (max 512 KB)")
    if not raw:
        raise HTTPException(400, "Empty body")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "Invalid file encoding (expected UTF-8 YAML)")
    import yaml
    try:
        parsed = yaml.safe_load(text)
        if not isinstance(parsed, dict):
            raise HTTPException(400, "Config must be a YAML mapping")
    except yaml.YAMLError as e:
        raise HTTPException(400, f"Invalid YAML: {e}")
    os.makedirs(os.path.dirname(NOBA_YAML), exist_ok=True)
    tmp = NOBA_YAML + ".restore-tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, NOBA_YAML)
    db.audit_log("config_restore", username, "Restored config from upload", _client_ip(request))
    return {"status": "ok"}


# ── Backup explorer helpers ──────────────────────────────────────────────────
_SNAP_RE = re.compile(r"^\d{8}-\d{6}$")


def _read_state_file(path: str) -> dict:
    """Parse a key=value state file into a dict."""
    result: dict = {}
    if not os.path.exists(path):
        return result
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                result[key.strip()] = val.strip().strip('"').strip("'")
    except Exception:
        pass
    return result


def _get_backup_dest() -> str | None:
    """Return the configured backup destination path, or None."""
    cfg = read_yaml_settings()
    dest = cfg.get("backupDest", "")
    return dest if dest and os.path.isdir(dest) else None


def _safe_snapshot_path(dest: str, name: str, subpath: str = "") -> str | None:
    """Validate and resolve a path inside a snapshot. Returns None on traversal."""
    if not _SNAP_RE.match(name):
        return None
    base = os.path.realpath(os.path.join(dest, name))
    if not base.startswith(os.path.realpath(dest)):
        return None
    if subpath:
        full = os.path.realpath(os.path.join(base, subpath))
        if not full.startswith(base):
            return None
        return full
    return base


# ── /api/backup/status ───────────────────────────────────────────────────────
@router.get("/api/backup/status")
@handle_errors
def api_backup_status(auth=Depends(_get_auth)):
    from ..config import BACKUP_STATE_FILE, CLOUD_STATE_FILE

    nas = _read_state_file(BACKUP_STATE_FILE)
    cloud = _read_state_file(CLOUD_STATE_FILE)

    def _build_nas(state: dict) -> dict | None:
        if not state:
            return None
        exit_code = state.get("exit_code", "")
        dur = state.get("duration", "")
        return {
            "exit_code": int(exit_code) if exit_code.isdigit() else None,
            "snapshot": state.get("snapshot", ""),
            "duration": int(dur) if dur.isdigit() else None,
            "failed_sources": state.get("failed_sources", ""),
            "timestamp": state.get("timestamp", ""),
        }

    def _build_cloud(state: dict) -> dict | None:
        if not state:
            return None
        status = state.get("LAST_STATUS", "")
        return {
            "exit_code": 0 if status.lower() in ("ok", "success", "0") else (1 if status else None),
            "snapshot": "",
            "duration": None,
            "failed_sources": "",
            "timestamp": state.get("LAST_SYNC_TIME", ""),
            "size": state.get("LAST_SIZE", ""),
        }

    return {"nas": _build_nas(nas), "cloud": _build_cloud(cloud)}


@router.post("/api/backup/report")
@handle_errors
def api_backup_report(request: Request, auth=Depends(_require_admin)):
    """Send an email summary of the last backup status."""
    username, _ = auth
    from ..config import BACKUP_STATE_FILE, CLOUD_STATE_FILE
    nas = _read_state_file(BACKUP_STATE_FILE)
    cloud = _read_state_file(CLOUD_STATE_FILE)
    if not nas and not cloud:
        raise HTTPException(404, "No backup state found")
    cfg = read_yaml_settings()
    notif_cfg = cfg.get("notifications", {})
    email_cfg = notif_cfg.get("email", {})
    if not email_cfg.get("enabled"):
        raise HTTPException(400, "Email notifications not configured")

    msg_parts = ["NOBA Backup Report"]
    if nas:
        exit_code = nas.get("exit_code", "?")
        status = "SUCCESS" if exit_code == "0" else "FAILED"
        msg_parts.append(f"\nNAS Backup: {status}")
        msg_parts.append(f"  Snapshot: {nas.get('snapshot', 'N/A')}")
        msg_parts.append(f"  Duration: {nas.get('duration', 'N/A')}s")
        if nas.get("failed_sources"):
            msg_parts.append(f"  Failed: {nas['failed_sources']}")
    if cloud:
        msg_parts.append(f"\nCloud Sync: {cloud.get('LAST_STATUS', 'N/A')}")
        msg_parts.append(f"  Last sync: {cloud.get('LAST_SYNC_TIME', 'N/A')}")

    message = "\n".join(msg_parts)
    threading.Thread(target=dispatch_notifications,
                    args=("info", message, notif_cfg, ["email"]), daemon=True).start()
    db.audit_log("backup_report", username, "Sent backup report email", _client_ip(request))
    return {"status": "ok", "message": "Report sent"}


# ── /api/backup/history ──────────────────────────────────────────────────────
@router.get("/api/backup/history")
@handle_errors
def api_backup_history(auth=Depends(_get_auth)):
    dest = _get_backup_dest()
    if not dest:
        return {"snapshots": [], "dest": ""}
    snapshots = []
    try:
        for entry in sorted(os.scandir(dest), key=lambda e: e.name, reverse=True):
            if not entry.is_dir(follow_symlinks=False):
                continue
            if not _SNAP_RE.match(entry.name):
                continue
            try:
                ts = datetime.strptime(entry.name, "%Y%m%d-%H%M%S")
                iso = ts.isoformat()
            except ValueError:
                iso = entry.name
            info: dict = {"name": entry.name, "timestamp": iso}
            try:
                st = entry.stat(follow_symlinks=False)
                info["mtime"] = int(st.st_mtime)
            except OSError:
                info["mtime"] = 0
            snapshots.append(info)
    except OSError as e:
        logger.warning("backup/history scan error: %s", e)
    return {"snapshots": snapshots[:SNAPSHOT_LIST_LIMIT], "dest": dest}


# ── /api/backup/snapshots ────────────────────────────────────────────────────
@router.get("/api/backup/snapshots/{name}/browse")
@handle_errors
def api_snapshot_browse(name: str, request: Request, auth=Depends(_get_auth)):
    dest = _get_backup_dest()
    if not dest:
        raise HTTPException(404, "Backup destination not configured")
    subpath = request.query_params.get("path", "")
    resolved = _safe_snapshot_path(dest, name, subpath)
    if resolved is None:
        raise HTTPException(400, "Invalid snapshot or path")
    if not os.path.exists(resolved):
        raise HTTPException(404, "Path not found")
    if os.path.isfile(resolved):
        st = os.stat(resolved)
        return {"type": "file", "name": os.path.basename(resolved),
                "size": st.st_size, "mtime": int(st.st_mtime)}
    entries = []
    try:
        for e in sorted(os.scandir(resolved), key=lambda x: (not x.is_dir(), x.name)):
            try:
                st = e.stat(follow_symlinks=False)
                entries.append({
                    "name": e.name,
                    "type": "dir" if e.is_dir(follow_symlinks=False) else "file",
                    "size": st.st_size if e.is_file(follow_symlinks=False) else 0,
                    "mtime": int(st.st_mtime),
                })
            except OSError:
                continue
    except OSError as e:
        raise HTTPException(500, f"Cannot read directory: {e}")
    return {"type": "dir", "path": subpath or "/", "entries": entries[:DIR_ENTRIES_LIMIT]}


@router.get("/api/backup/snapshots/diff")
@handle_errors
def api_snapshot_diff(request: Request, auth=Depends(_get_auth)):
    dest = _get_backup_dest()
    if not dest:
        raise HTTPException(404, "Backup destination not configured")
    snap_a = request.query_params.get("a", "")
    snap_b = request.query_params.get("b", "")
    subpath = request.query_params.get("path", "")
    path_a = _safe_snapshot_path(dest, snap_a, subpath)
    path_b = _safe_snapshot_path(dest, snap_b, subpath)
    if path_a is None or path_b is None:
        raise HTTPException(400, "Invalid snapshot names")
    if not os.path.isdir(path_a) or not os.path.isdir(path_b):
        raise HTTPException(404, "Snapshot path not found")

    added, removed, changed, unchanged = [], [], [], []
    files_a: dict[str, os.stat_result] = {}
    files_b: dict[str, os.stat_result] = {}
    try:
        for e in os.scandir(path_a):
            try:
                files_a[e.name] = e.stat(follow_symlinks=False)
            except OSError:
                pass
        for e in os.scandir(path_b):
            try:
                files_b[e.name] = e.stat(follow_symlinks=False)
            except OSError:
                pass
    except OSError as e:
        raise HTTPException(500, f"Cannot scan snapshots: {e}")

    all_names = sorted(set(files_a) | set(files_b))
    for name in all_names[:DIFF_NAMES_LIMIT]:
        sa = files_a.get(name)
        sb = files_b.get(name)
        if sa and not sb:
            removed.append(name)
        elif sb and not sa:
            added.append(name)
        elif sa and sb:
            if sa.st_dev == sb.st_dev and sa.st_ino == sb.st_ino:
                unchanged.append(name)
            elif sa.st_size != sb.st_size or int(sa.st_mtime) != int(sb.st_mtime):
                changed.append(name)
            else:
                unchanged.append(name)
    return {"a": snap_a, "b": snap_b, "path": subpath or "/",
            "added": added, "removed": removed, "changed": changed,
            "unchanged_count": len(unchanged)}


# ── /api/backup/file-versions ────────────────────────────────────────────────
@router.get("/api/backup/file-versions")
@handle_errors
def api_file_versions(request: Request, auth=Depends(_get_auth)):
    """List all versions of a file across snapshots."""
    dest = _get_backup_dest()
    if not dest:
        raise HTTPException(404, "Backup destination not configured")
    file_path = request.query_params.get("path", "")
    if not file_path:
        raise HTTPException(400, "File path required")
    versions = []
    try:
        for entry in sorted(os.scandir(dest), key=lambda e: e.name, reverse=True):
            if not entry.is_dir() or not _SNAP_RE.match(entry.name):
                continue
            full = _safe_snapshot_path(dest, entry.name, file_path)
            if full and os.path.isfile(full):
                st = os.stat(full)
                versions.append({
                    "snapshot": entry.name,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "inode": st.st_ino,
                })
    except OSError as e:
        raise HTTPException(500, f"Error scanning versions: {e}")
    seen_inodes: set = set()
    for v in versions:
        v["unique"] = v["inode"] not in seen_inodes
        seen_inodes.add(v["inode"])
    return {"path": file_path, "versions": versions[:FILE_VERSIONS_LIMIT]}


# ── /api/backup/restore ──────────────────────────────────────────────────────
@router.post("/api/backup/restore")
@handle_errors
async def api_backup_restore(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    snapshot = body.get("snapshot", "")
    file_path = body.get("path", "")
    dest_override = body.get("dest", "")

    backup_dest = _get_backup_dest()
    if not backup_dest:
        raise HTTPException(404, "Backup destination not configured")

    resolved = _safe_snapshot_path(backup_dest, snapshot, file_path)
    if resolved is None or not os.path.exists(resolved):
        raise HTTPException(400, "Invalid snapshot or file path")
    if not os.path.isfile(resolved):
        raise HTTPException(400, "Can only restore individual files")

    cfg = read_yaml_settings()
    sources = cfg.get("backupSources", [])
    rel = os.path.relpath(resolved, os.path.join(backup_dest, snapshot))
    top_dir = rel.split(os.sep)[0]

    original = ""
    for src in sources:
        base = os.path.basename(src).lstrip(".")
        if base == top_dir:
            rest = os.sep.join(rel.split(os.sep)[1:])
            original = os.path.join(os.path.dirname(src), os.path.basename(src), rest)
            break

    restore_to = dest_override or original
    if not restore_to:
        raise HTTPException(400, "Cannot determine original path -- provide 'dest' in request body")

    restore_real = os.path.realpath(restore_to)
    for forbidden in ("/etc", "/usr", "/bin", "/sbin", "/boot", "/proc", "/sys",
                      "/dev", "/root", "/run", "/var/run", "/lib", "/lib64"):
        if restore_real.startswith(forbidden):
            raise HTTPException(403, f"Cannot restore to {forbidden}")

    try:
        import shutil
        os.makedirs(os.path.dirname(restore_to), exist_ok=True)
        shutil.copy2(resolved, restore_to)
    except Exception as e:
        raise HTTPException(500, f"Restore failed: {e}")

    db.audit_log("backup_restore", username,
                 f"Restored {file_path} from {snapshot} to {restore_to}", ip)
    return {"status": "ok", "restored_to": restore_to}


# ── /api/backup/config-history ───────────────────────────────────────────────
@router.get("/api/backup/config-history")
@handle_errors
def api_config_history(auth=Depends(_require_admin)):
    import glob as glob_mod
    versions = []
    pattern = f"{NOBA_YAML}.bak.*"
    for path in sorted(glob_mod.glob(pattern), reverse=True):
        try:
            ts_str = path.rsplit(".bak.", 1)[-1]
            ts = int(ts_str)
            st = os.stat(path)
            versions.append({
                "timestamp": ts,
                "iso": datetime.fromtimestamp(ts).isoformat(),
                "size": st.st_size,
                "filename": os.path.basename(path),
            })
        except (ValueError, OSError):
            continue
    if os.path.exists(NOBA_YAML):
        try:
            st = os.stat(NOBA_YAML)
            versions.insert(0, {
                "timestamp": int(st.st_mtime),
                "iso": datetime.fromtimestamp(st.st_mtime).isoformat(),
                "size": st.st_size,
                "filename": "config.yaml",
                "current": True,
            })
        except OSError:
            pass
    return {"versions": versions[:50]}


@router.get("/api/backup/config-history/{filename}")
@handle_errors
def api_config_history_download(filename: str, auth=Depends(_require_admin)):
    if filename == "config.yaml":
        path = NOBA_YAML
    elif re.match(r"^config\.yaml\.bak\.\d+$", filename):
        path = os.path.join(os.path.dirname(NOBA_YAML), filename)
    else:
        raise HTTPException(400, "Invalid filename")
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    with open(path, "rb") as f:
        content = f.read()
    return Response(
        content=content,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── /api/backup/restic ───────────────────────────────────────────────────────
@router.get("/api/backup/restic")
@handle_errors
def api_restic_status(auth=Depends(_get_auth)):
    """Check restic repository status if configured."""
    import subprocess
    cfg = read_yaml_settings()
    repo = cfg.get("resticRepo", "")
    if not repo:
        return {"configured": False}
    env = dict(os.environ)
    password = cfg.get("resticPassword", "")
    if password:
        env["RESTIC_PASSWORD"] = password
    try:
        r = subprocess.run(["restic", "-r", repo, "snapshots", "--json", "--latest", "5"],
                          capture_output=True, text=True, timeout=30, env=env)
        if r.returncode != 0:
            return {"configured": True, "error": r.stderr.strip()[:ERROR_TRUNCATE_LEN]}
        snapshots = json.loads(r.stdout)
        return {
            "configured": True,
            "snapshots": [{
                "id": s.get("short_id", ""),
                "time": s.get("time", ""),
                "hostname": s.get("hostname", ""),
                "paths": s.get("paths", []),
            } for s in (snapshots or [])],
        }
    except FileNotFoundError:
        return {"configured": True, "error": "restic not installed"}
    except Exception as e:
        return {"configured": True, "error": str(e)}


# ── /api/backup/schedules ────────────────────────────────────────────────
@router.get("/api/backup/schedules")
@handle_errors
def api_backup_schedules(auth=Depends(_get_auth)):
    """List backup-related automations (scheduled backup jobs)."""
    autos = db.list_automations()
    return [a for a in autos if a.get("type") == "script" and
            a.get("config", {}).get("script") in ("backup", "cloud", "verify")]


@router.post("/api/backup/schedule")
@handle_errors
async def api_backup_schedule_create(request: Request, auth=Depends(_require_admin)):
    """Create a backup schedule with friendly parameters."""
    import uuid
    username, _ = auth
    body = await _read_body(request)
    backup_type = body.get("type", "backup")
    schedule = body.get("schedule", "0 3 * * *")
    name = body.get("name", f"Scheduled {backup_type}")
    if backup_type not in ("backup", "cloud", "verify"):
        raise HTTPException(400, "Type must be backup, cloud, or verify")
    auto_id = uuid.uuid4().hex[:12]
    config = {"script": backup_type, "args": "--verbose"}
    if not db.insert_automation(auto_id, name, "script", config, schedule, True):
        raise HTTPException(500, "Failed to create backup schedule")
    db.audit_log("backup_schedule", username, f"Created {backup_type} schedule: {schedule}", _client_ip(request))
    return {"id": auto_id, "status": "ok"}


# ── /api/backup/progress ────────────────────────────────────────────────
@router.get("/api/backup/progress")
@handle_errors
def api_backup_progress(auth=Depends(_get_auth)):
    """Get progress of currently running backup jobs."""
    active_ids = job_runner.get_active_ids()
    if not active_ids:
        return {"running": False}
    progress = []
    for rid in active_ids:
        run = db.get_job_run(rid)
        if run and run.get("trigger", "").startswith("script:backup"):
            progress.append({
                "run_id": rid,
                "trigger": run.get("trigger", ""),
                "started_at": run.get("started_at"),
                "status": run.get("status"),
            })
    return {"running": len(progress) > 0, "jobs": progress}


# ── /api/backup/health ──────────────────────────────────────────────────
@router.get("/api/backup/health")
@handle_errors
def api_backup_health(auth=Depends(_get_auth)):
    """Check backup destination accessibility and space."""
    cfg = read_yaml_settings()
    dest = cfg.get("backupDest", "")
    if not dest or not os.path.isdir(dest):
        return {"accessible": False, "error": "Destination not configured or not accessible"}
    try:
        import shutil
        total, used, free = shutil.disk_usage(dest)
        snapshot_count = sum(1 for e in os.scandir(dest)
                           if e.is_dir() and re.match(r'^\d{8}-\d{6}$', e.name))
        return {
            "accessible": True,
            "path": dest,
            "total_gb": round(total / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1),
            "percent_used": round(used / total * 100, 1) if total else 0,
            "snapshot_count": snapshot_count,
        }
    except Exception as e:
        return {"accessible": False, "error": str(e)}


# ── /api/log-viewer ───────────────────────────────────────────────────────────
@router.get("/api/log-viewer")
@handle_errors
def api_log_viewer(request: Request, auth=Depends(_require_operator)):
    log_type = request.query_params.get("type", "syserr")
    if log_type == "syserr":
        text = _run_cmd(["journalctl", "-p", "3", "-n", "25", "--no-pager"], timeout=4)
    elif log_type == "action":
        text = strip_ansi(_read_file(ACTION_LOG, "No recent actions."))
    elif log_type in ("backup", "cloud"):
        fname = "backup-to-nas.log" if log_type == "backup" else "cloud-backup.log"
        raw   = _read_file(os.path.join(LOG_DIR, fname), "No log.")
        text  = strip_ansi("\n".join(raw.splitlines()[-30:]))
    else:
        text = "Unknown log type."
    return PlainTextResponse(text or "Empty.")


# ── /api/action-log ───────────────────────────────────────────────────────────
@router.get("/api/action-log")
@handle_errors
def api_action_log(auth=Depends(_require_operator)):
    return PlainTextResponse(strip_ansi(_read_file(ACTION_LOG, "Waiting for output\u2026")))


# ── /api/reports ──────────────────────────────────────────────────────────────
@router.get("/api/reports/bandwidth")
@handle_errors
def api_bandwidth_report(request: Request, auth=Depends(_get_auth)):
    """Bandwidth usage report per interface over configurable period."""
    range_h = _int_param(request, "range", 24, 1, 8760)
    rx_points = db.get_history("net_rx_bytes", range_hours=range_h, resolution=HISTORY_RESOLUTION_S)
    tx_points = db.get_history("net_tx_bytes", range_hours=range_h, resolution=HISTORY_RESOLUTION_S)

    total_rx = sum(p["value"] * HISTORY_RESOLUTION_S for p in rx_points)
    total_tx = sum(p["value"] * HISTORY_RESOLUTION_S for p in tx_points)

    hourly = []
    for rx, tx in zip(rx_points, tx_points):
        hourly.append({
            "time": rx["time"],
            "rx_bps": round(rx["value"]),
            "tx_bps": round(tx["value"]),
        })

    from ..metrics import _fmt_bytes  # noqa: F811
    return {
        "range_hours": range_h,
        "total_rx": _fmt_bytes(total_rx),
        "total_tx": _fmt_bytes(total_tx),
        "total_rx_bytes": round(total_rx),
        "total_tx_bytes": round(total_tx),
        "hourly": hourly,
    }


@router.get("/api/reports/anomalies")
@handle_errors
def api_anomaly_report(request: Request, auth=Depends(_get_auth)):
    """Generate anomaly detection summary for the past week."""
    range_h = _int_param(request, "range", 168, 1, 8760)
    metrics = ["cpu_percent", "mem_percent", "cpu_temp"]
    results = {}
    for metric in metrics:
        points = db.get_history(metric, range_hours=range_h, resolution=HISTORY_RESOLUTION_S, anomaly=True)
        anomalies = [p for p in points if p.get("anomaly")]
        if anomalies:
            results[metric] = {
                "count": len(anomalies),
                "latest": anomalies[-1] if anomalies else None,
                "values": [a["value"] for a in anomalies[-10:]],
            }
    return {
        "range_hours": range_h,
        "anomaly_count": sum(r["count"] for r in results.values()),
        "metrics": results,
    }


@router.post("/api/reports/custom")
@handle_errors
async def api_custom_report(request: Request, auth=Depends(_require_operator)):
    """Generate a custom report from a template definition."""
    body = await _read_body(request)
    metrics = body.get("metrics", ["cpu_percent", "mem_percent"])
    range_h = _safe_int(body.get("range_hours", 24), 24)
    title = body.get("title", "Custom Report")

    report_data = {}
    for metric in metrics:
        if metric not in HISTORY_METRICS:
            continue
        points = db.get_history(metric, range_hours=range_h, resolution=HISTORY_RESOLUTION_S)
        if points:
            values = [p["value"] for p in points]
            report_data[metric] = {
                "avg": round(sum(values) / len(values), 2),
                "max": round(max(values), 2),
                "min": round(min(values), 2),
                "current": round(values[-1], 2) if values else 0,
                "points": len(values),
                "data": [{"time": p["time"], "value": p["value"]} for p in points],
            }

    return {
        "title": title,
        "range_hours": range_h,
        "generated_at": datetime.now().isoformat(),
        "metrics": report_data,
    }


@router.get("/api/grafana/dashboard")
@handle_errors
def api_grafana_template(auth=Depends(_get_auth)):
    """Return a Grafana dashboard JSON template for NOBA metrics."""
    return {
        "dashboard": {
            "title": "NOBA System Metrics",
            "panels": [
                {"title": "CPU Usage", "type": "timeseries",
                 "targets": [{"expr": "noba_cpu_percent", "legendFormat": "CPU %"}],
                 "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8}},
                {"title": "Memory Usage", "type": "timeseries",
                 "targets": [{"expr": "noba_mem_percent", "legendFormat": "Memory %"}],
                 "gridPos": {"x": 12, "y": 0, "w": 12, "h": 8}},
                {"title": "Disk Usage", "type": "bargauge",
                 "targets": [{"expr": "noba_disk_percent", "legendFormat": "{{mount}}"}],
                 "gridPos": {"x": 0, "y": 8, "w": 12, "h": 8}},
                {"title": "Network I/O", "type": "timeseries",
                 "targets": [
                     {"expr": "noba_net_rx_bps", "legendFormat": "RX"},
                     {"expr": "noba_net_tx_bps", "legendFormat": "TX"},
                 ],
                 "gridPos": {"x": 12, "y": 8, "w": 12, "h": 8}},
                {"title": "Service Status", "type": "stat",
                 "targets": [{"expr": "noba_service_up", "legendFormat": "{{name}}"}],
                 "gridPos": {"x": 0, "y": 16, "w": 24, "h": 4}},
            ],
            "time": {"from": "now-24h", "to": "now"},
            "refresh": "30s",
        },
        "datasource": {
            "type": "prometheus",
            "url": "http://YOUR_NOBA_HOST:8080/api/metrics/prometheus",
        },
    }


# ── /api/plugins/available & install ──────────────────────────────────────────
@router.get("/api/plugins/available")
@handle_errors
def api_plugins_available(auth=Depends(_require_admin)):
    cfg = read_yaml_settings()
    catalog_url = cfg.get("pluginCatalogUrl", "")
    return plugin_manager.get_available(catalog_url)


@router.get("/api/plugins/bundled")
@handle_errors
def api_plugins_bundled(auth=Depends(_require_admin)):
    """List bundled catalog plugins shipped with NOBA."""
    return plugin_manager.get_bundled_catalog()


@router.post("/api/plugins/install")
@handle_errors
async def api_plugins_install(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    body = await _read_body(request)
    # Support bundled installs (no url, just filename)
    filename = body.get("filename", "")
    url = body.get("url", "")
    bundled = body.get("bundled", False)
    if not filename:
        raise HTTPException(400, "Filename required")
    if bundled:
        ok = plugin_manager.install_bundled(filename)
    else:
        if not url:
            raise HTTPException(400, "URL required for remote install")
        ok = plugin_manager.install_plugin(url, filename)
    if not ok:
        raise HTTPException(400, "Install failed")
    db.audit_log("plugin_install", username, f"Installed {filename}", _client_ip(request))
    return {"status": "ok"}


# ── /api/plugins/{id}/config ─────────────────────────────────────────────────
@router.get("/api/plugins/{plugin_id}/config")
@handle_errors
def api_plugin_config_get(plugin_id: str, auth=Depends(_require_admin)):
    """Return current config and schema for a plugin."""
    config, schema = plugin_manager.get_plugin_config(plugin_id)
    if not schema:
        raise HTTPException(404, "Plugin has no configurable settings")
    return {"config": config, "schema": schema}


@router.post("/api/plugins/{plugin_id}/config")
@handle_errors
async def api_plugin_config_post(plugin_id: str, request: Request, auth=Depends(_require_admin)):
    """Validate and save plugin config."""
    username, _ = auth
    body = await _read_body(request)
    errors = plugin_manager.set_plugin_config(plugin_id, body)
    if errors:
        raise HTTPException(400, "; ".join(errors))
    db.audit_log("plugin_config", username, f"Updated config for plugin {plugin_id}", _client_ip(request))
    return {"status": "ok"}


# ── /api/plugins (managed list, enable/disable, reload) ──────────────────────
@router.get("/api/plugins/managed")
@handle_errors
def api_plugins_managed(auth=Depends(_get_auth)):
    """List all plugins with management metadata (name, version, enabled)."""
    return plugin_manager.get_managed()


@router.post("/api/plugins/{name}/enable")
@handle_errors
async def api_plugin_enable(name: str, request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    if not plugin_manager.enable_plugin(name):
        raise HTTPException(404, f"Plugin '{name}' not found")
    db.audit_log("plugin_enable", username, f"Enabled plugin {name}", _client_ip(request))
    return {"status": "ok", "plugin": name, "enabled": True}


@router.post("/api/plugins/{name}/disable")
@handle_errors
async def api_plugin_disable(name: str, request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    if not plugin_manager.disable_plugin(name):
        raise HTTPException(404, f"Plugin '{name}' not found")
    db.audit_log("plugin_disable", username, f"Disabled plugin {name}", _client_ip(request))
    return {"status": "ok", "plugin": name, "enabled": False}


@router.post("/api/plugins/reload")
@handle_errors
async def api_plugins_reload(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    plugin_manager.reload()
    db.audit_log("plugin_reload", username, "Reloaded all plugins", _client_ip(request))
    return {"status": "ok", "count": plugin_manager.count}


# ── /api/runbooks ─────────────────────────────────────────────────────────────
@router.get("/api/runbooks")
@handle_errors
def api_runbooks(auth=Depends(_get_auth)):
    cfg = read_yaml_settings()
    runbooks = cfg.get("runbooks", [])
    if isinstance(runbooks, str):
        try:
            runbooks = json.loads(runbooks)
        except (json.JSONDecodeError, TypeError):
            runbooks = []
    return runbooks


@router.get("/api/runbooks/{runbook_id}")
@handle_errors
def api_runbook_detail(runbook_id: str, auth=Depends(_get_auth)):
    cfg = read_yaml_settings()
    runbooks = cfg.get("runbooks", [])
    if isinstance(runbooks, str):
        try:
            runbooks = json.loads(runbooks)
        except (json.JSONDecodeError, TypeError):
            runbooks = []
    for rb in runbooks:
        if rb.get("id") == runbook_id:
            return rb
    raise HTTPException(404, "Runbook not found")


# ── /api/graylog/search ──────────────────────────────────────────────────────
@router.get("/api/graylog/search")
@handle_errors
def api_graylog_search(request: Request, auth=Depends(_require_operator)):
    cfg = read_yaml_settings()
    url = cfg.get("graylogUrl", "")
    token = cfg.get("graylogToken", "")
    # Support user:password auth as fallback when no API token is configured
    if not token:
        user = cfg.get("graylogUser", "")
        password = cfg.get("graylogPassword", "")
        if user and password:
            token = f"{user}:{password}"
    query = request.query_params.get("q", "*")
    hours = _int_param(request, "hours", 1, 1, 168)
    if not url:
        raise HTTPException(404, "Graylog not configured")
    from ..integrations import get_graylog
    result = get_graylog(url, token, query, hours)
    return result or {"messages": [], "total": 0}
