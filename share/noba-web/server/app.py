"""Noba Command Center – FastAPI application v1.15.0"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .auth import authenticate, load_legacy_user, pbkdf2_hash, rate_limiter, token_store, \
    users, valid_username, verify_password, check_password_strength
from .collector import bg_collector, collect_stats, get_shutdown_flag
from .config import (
    ACTION_LOG, ALLOWED_ACTIONS, HISTORY_METRICS, LOG_DIR, MAX_BODY_BYTES,
    NOBA_YAML, PID_FILE, SCRIPT_DIR, SCRIPT_MAP, SECURITY_HEADERS, TRUST_PROXY,
    VALID_ROLES, VERSION,
)
from .db import db
from .metrics import (
    _read_file, bust_container_cache, collect_smart,
    get_rclone_remotes, strip_ansi, validate_service_name,
)
from .alerts import dispatch_notifications
from .plugins import plugin_manager
from .runner import job_runner
from .yaml_config import read_yaml_settings, write_yaml_settings

logger = logging.getLogger("noba")
_server_start_time = time.time()

# ── Static files directory ────────────────────────────────────────────────────
_WEB_DIR = Path(__file__).parent.parent   # share/noba-web/

# ── Cleanup loop ──────────────────────────────────────────────────────────────
_prune_counter = 0


def _cleanup_loop() -> None:
    global _prune_counter
    shutdown = get_shutdown_flag()
    while not shutdown.wait(300):
        token_store.cleanup()
        rate_limiter.cleanup()
        _prune_counter += 1
        if _prune_counter >= 12:
            _prune_counter = 0
            db.prune_history()
            db.prune_audit()
            db.prune_job_runs()


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.mark_stale_jobs()
    db.audit_log("system_start", "system", f"Noba v{VERSION} starting (FastAPI)")
    bg_collector.start()
    threading.Thread(target=_cleanup_loop, daemon=True, name="token-cleanup").start()
    # warm up psutil CPU measurement
    import psutil
    psutil.cpu_percent(interval=None)
    plugin_manager.discover()
    plugin_manager.start()
    from .scheduler import scheduler
    scheduler.start()
    logger.info("Noba v%s started (%d plugins)", VERSION, plugin_manager.count)
    yield
    scheduler.stop()
    job_runner.shutdown()
    plugin_manager.stop()
    get_shutdown_flag().set()
    db.audit_log("system_stop", "system", "Server stopping")
    try:
        from .integrations import _client as _http_client
        _http_client.close()
    except Exception:
        pass
    try:
        os.unlink(PID_FILE)
    except Exception:
        pass


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Noba Command Center", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)

# ── CORS – restrict to same-origin; override via NOBA_CORS_ORIGINS env var ──
_cors_origins = os.environ.get("NOBA_CORS_ORIGINS", "").split(",")
_cors_origins = [o.strip() for o in _cors_origins if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or [],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── Security headers middleware ───────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers[k] = v
    return response


# ── Auth dependency ───────────────────────────────────────────────────────────
def _get_auth(request: Request) -> tuple[str, str]:
    auth = request.headers.get("Authorization", "")
    username, role = authenticate(auth)
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return username, role


def _get_auth_sse(request: Request) -> tuple[str, str]:
    """Auth for SSE — also accepts token query param since EventSource can't set headers."""
    auth = request.headers.get("Authorization", "")
    username, role = authenticate(auth)
    if not username:
        tok = request.query_params.get("token", "")
        if tok:
            username, role = token_store.validate(tok)
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return username, role


def _require_operator(request: Request) -> tuple[str, str]:
    username, role = _get_auth(request)
    if role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return username, role


def _require_admin(request: Request) -> tuple[str, str]:
    username, role = _get_auth(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    return username, role


def _client_ip(request: Request) -> str:
    if TRUST_PROXY:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


# ── Static / frontend ─────────────────────────────────────────────────────────
@app.get("/")
async def index():
    return FileResponse(_WEB_DIR / "index.html")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(_WEB_DIR / "manifest.json", media_type="application/json")


@app.get("/service-worker.js")
async def service_worker():
    return FileResponse(_WEB_DIR / "service-worker.js", media_type="application/javascript")


class _CachedStaticFiles(StaticFiles):
    """StaticFiles subclass that adds Cache-Control headers."""
    async def __call__(self, scope, receive, send):
        async def _send_with_cache(msg):
            if msg["type"] == "http.response.start":
                headers = [(k, v) for k, v in msg.get("headers", []) if k != b"cache-control"]
                headers.append((b"cache-control", b"public, max-age=3600"))
                msg["headers"] = headers
            await send(msg)
        await super().__call__(scope, receive, _send_with_cache)

app.mount("/static", _CachedStaticFiles(directory=str(_WEB_DIR / "static")), name="static")


# ── /api/health ───────────────────────────────────────────────────────────────
@app.get("/api/health")
def api_health():
    return {"status": "ok", "version": VERSION, "uptime_s": round(time.time() - _server_start_time)}


# ── /api/me ───────────────────────────────────────────────────────────────────
@app.get("/api/me")
def api_me(auth=Depends(_get_auth)):
    username, role = auth
    return {"username": username, "role": role}


# ── /api/plugins ─────────────────────────────────────────────────────────────
@app.get("/api/plugins")
def api_plugins(auth=Depends(_get_auth)):
    return plugin_manager.get_all()


# ── /api/stats ────────────────────────────────────────────────────────────────
@app.get("/api/stats")
def api_stats(request: Request, auth=Depends(_get_auth)):
    qs = dict(request.query_params)
    # Wrap scalar values into lists to match the old parse_qs format
    qs_lists = {k: [v] for k, v in qs.items()}
    bg_collector.update_qs(qs_lists)
    data = bg_collector.get() or collect_stats(qs_lists)
    return JSONResponse(data)


# ── /api/stream (SSE) ────────────────────────────────────────────────────────
@app.get("/api/stream")
async def api_stream(request: Request, auth=Depends(_get_auth_sse)):
    qs = {k: [v] for k, v in request.query_params.items()}
    bg_collector.update_qs(qs)
    shutdown = get_shutdown_flag()

    async def generate():
        loop = asyncio.get_running_loop()
        first = await loop.run_in_executor(None, lambda: bg_collector.get() or collect_stats(qs))
        yield f"data: {json.dumps(first)}\n\n"
        last_hb = time.time()
        while not shutdown.is_set():
            if await request.is_disconnected():
                break
            await asyncio.sleep(5)
            if shutdown.is_set():
                break
            data = bg_collector.get()
            if data:
                yield f"data: {json.dumps(data)}\n\n"
            if time.time() - last_hb >= 15:
                yield ": ping\n\n"
                last_hb = time.time()

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


# ── /api/settings ─────────────────────────────────────────────────────────────
@app.get("/api/settings")
def api_settings_get(auth=Depends(_get_auth)):
    return read_yaml_settings()


@app.post("/api/settings")
async def api_settings_post(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    body = await _read_body(request)
    ok = write_yaml_settings(body)
    if not ok:
        db.audit_log("settings_update", username, "Settings update failed", _client_ip(request))
        raise HTTPException(500, "Failed to write settings")
    db.audit_log("settings_update", username, "Updated web settings", _client_ip(request))
    return {"status": "ok"}


# ── /api/notifications/test ───────────────────────────────────────────────────
@app.get("/api/notifications/test")
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


# ── /api/smart ────────────────────────────────────────────────────────────────
@app.get("/api/smart")
def api_smart(auth=Depends(_get_auth)):
    return collect_smart()


# ── /api/cloud-remotes ────────────────────────────────────────────────────────
@app.get("/api/cloud-remotes")
def api_cloud_remotes(auth=Depends(_get_auth)):
    return get_rclone_remotes()


# ── /api/history/{metric} ─────────────────────────────────────────────────────
def _int_param(request: Request, name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(request.query_params.get(name, str(default)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"Invalid {name} parameter")
    return max(lo, min(hi, v))


@app.get("/api/history/{metric}")
def api_history(metric: str, request: Request, auth=Depends(_get_auth)):
    if metric not in HISTORY_METRICS:
        raise HTTPException(400, "Unknown metric")
    range_h    = _int_param(request, "range", 24, 1, 8760)
    resolution = _int_param(request, "resolution", 60, 1, 3600)
    anomaly    = request.query_params.get("anomaly", "0") == "1"
    return db.get_history(metric, range_h, resolution, anomaly)


@app.get("/api/history/{metric}/export")
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


# ── /api/history/{metric}/trend ──────────────────────────────────────────────
@app.get("/api/history/{metric}/trend")
def api_history_trend(metric: str, request: Request, auth=Depends(_get_auth)):
    if metric not in HISTORY_METRICS:
        raise HTTPException(400, "Unknown metric")
    range_h = _int_param(request, "range", 168, 1, 8760)
    project_h = _int_param(request, "project", 168, 1, 8760)
    return db.get_trend(metric, range_hours=range_h, projection_hours=project_h)


# ── /api/audit ────────────────────────────────────────────────────────────────
@app.get("/api/audit")
def api_audit(request: Request, auth=Depends(_require_admin)):
    limit = _int_param(request, "limit", 100, 1, 1000)
    user_filter = request.query_params.get("user", "")
    action_filter = request.query_params.get("action", "")
    try:
        from_ts = int(request.query_params.get("from", 0))
    except (ValueError, TypeError):
        from_ts = 0
    try:
        to_ts = int(request.query_params.get("to", 0))
    except (ValueError, TypeError):
        to_ts = 0
    return db.get_audit(limit=limit, username_filter=user_filter, action_filter=action_filter, from_ts=from_ts, to_ts=to_ts)


# ── /api/config/backup ────────────────────────────────────────────────────────
@app.get("/api/config/backup")
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


@app.post("/api/config/restore")
async def api_config_restore(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    raw = await request.body()
    if len(raw) > 512 * 1024:
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


# ── /api/backup/status ───────────────────────────────────────────────────────
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


@app.get("/api/backup/status")
def api_backup_status(auth=Depends(_get_auth)):
    from .config import BACKUP_STATE_FILE, CLOUD_STATE_FILE

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


# ── Backup explorer helpers ──────────────────────────────────────────────────
_SNAP_RE = re.compile(r"^\d{8}-\d{6}$")


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


# ── /api/backup/history ──────────────────────────────────────────────────────
@app.get("/api/backup/history")
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
            # Parse timestamp from dir name YYYYMMDD-HHMMSS
            try:
                ts = datetime.strptime(entry.name, "%Y%m%d-%H%M%S")
                iso = ts.isoformat()
            except ValueError:
                iso = entry.name
            info: dict = {"name": entry.name, "timestamp": iso}
            # Quick stat — avoid expensive du
            try:
                st = entry.stat(follow_symlinks=False)
                info["mtime"] = int(st.st_mtime)
            except OSError:
                info["mtime"] = 0
            snapshots.append(info)
    except OSError as e:
        logger.warning("backup/history scan error: %s", e)
    return {"snapshots": snapshots[:200], "dest": dest}


# ── /api/backup/snapshots/{name}/browse ──────────────────────────────────────
@app.get("/api/backup/snapshots/{name}/browse")
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
    return {"type": "dir", "path": subpath or "/", "entries": entries[:2000]}


# ── /api/backup/snapshots/diff ───────────────────────────────────────────────
@app.get("/api/backup/snapshots/diff")
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
    for name in all_names[:5000]:
        sa = files_a.get(name)
        sb = files_b.get(name)
        if sa and not sb:
            removed.append(name)
        elif sb and not sa:
            added.append(name)
        elif sa and sb:
            # Same device + inode = hardlinked = unchanged
            if sa.st_dev == sb.st_dev and sa.st_ino == sb.st_ino:
                unchanged.append(name)
            elif sa.st_size != sb.st_size or int(sa.st_mtime) != int(sb.st_mtime):
                changed.append(name)
            else:
                unchanged.append(name)
    return {"a": snap_a, "b": snap_b, "path": subpath or "/",
            "added": added, "removed": removed, "changed": changed,
            "unchanged_count": len(unchanged)}


# ── /api/backup/restore ──────────────────────────────────────────────────────
@app.post("/api/backup/restore")
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

    # Determine original path from the backup structure
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
        raise HTTPException(400, "Cannot determine original path — provide 'dest' in request body")

    # Safety: don't overwrite protected paths
    restore_real = os.path.realpath(restore_to)
    for forbidden in ("/etc", "/usr", "/bin", "/sbin", "/boot", "/proc", "/sys"):
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
@app.get("/api/backup/config-history")
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
    # Also include the current config
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


@app.get("/api/backup/config-history/{filename}")
def api_config_history_download(filename: str, auth=Depends(_require_admin)):
    # Only allow config.yaml or config.yaml.bak.<digits>
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


# ── /api/log-viewer ───────────────────────────────────────────────────────────
@app.get("/api/log-viewer")
def api_log_viewer(request: Request, auth=Depends(_get_auth)):
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
@app.get("/api/action-log")
def api_action_log(auth=Depends(_get_auth)):
    return PlainTextResponse(strip_ansi(_read_file(ACTION_LOG, "Waiting for output…")))


# ── /api/run-status (legacy compat) ──────────────────────────────────────────
@app.get("/api/run-status")
def api_run_status(auth=Depends(_get_auth)):
    active = job_runner.get_active_ids()
    if not active:
        return {"status": "idle"}
    run = db.get_job_run(active[0])
    if run:
        return {"status": run["status"], "run_id": run["id"],
                "trigger": run["trigger"], "started": run["started_at"]}
    return {"status": "running", "run_ids": active}


# ── /api/runs — job run history & details ────────────────────────────────────
@app.get("/api/runs")
def api_runs(request: Request, auth=Depends(_get_auth)):
    limit = _int_param(request, "limit", 50, 1, 500)
    status = request.query_params.get("status")
    auto_id = request.query_params.get("automation_id")
    trigger_prefix = request.query_params.get("trigger_prefix")
    return db.get_job_runs(automation_id=auto_id, limit=limit, status=status,
                           trigger_prefix=trigger_prefix)


@app.get("/api/runs/{run_id}")
def api_run_detail(run_id: int, auth=Depends(_get_auth)):
    run = db.get_job_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@app.post("/api/runs/{run_id}/cancel")
def api_run_cancel(run_id: int, request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    if not job_runner.cancel(run_id):
        raise HTTPException(404, "Run not active")
    db.audit_log("job_cancel", username, f"Cancelled run {run_id}", _client_ip(request))
    return {"success": True}


# ── /api/automations — CRUD + manual trigger ─────────────────────────────────
def _validate_auto_config(atype: str, config: dict) -> None:
    if atype == "script":
        if not config.get("command") and not config.get("script"):
            raise HTTPException(400, "Script automation requires 'command' or 'script' in config")
    elif atype == "webhook":
        url = config.get("url", "")
        if not url or not url.startswith(("http://", "https://")):
            raise HTTPException(400, "Webhook requires a valid 'url' in config")
    elif atype == "service":
        if not config.get("service"):
            raise HTTPException(400, "Service automation requires 'service' in config")
        if config.get("action", "restart") not in ("start", "stop", "restart"):
            raise HTTPException(400, "Service action must be start, stop, or restart")
    elif atype == "workflow":
        steps = config.get("steps", [])
        if not isinstance(steps, list) or len(steps) < 1:
            raise HTTPException(400, "Workflow requires 'steps' list with at least one automation ID")


def _build_auto_script_process(config: dict) -> subprocess.Popen | None:
    script_key = config.get("script", "")
    command = config.get("command", "")
    args = config.get("args", "")
    if script_key and script_key in SCRIPT_MAP:
        sfile = os.path.join(SCRIPT_DIR, SCRIPT_MAP[script_key])
        if not os.path.isfile(sfile):
            return None
        cmd = [sfile, "--verbose"]
        if args:
            cmd += shlex.split(args) if isinstance(args, str) else [str(a) for a in args]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True, cwd=SCRIPT_DIR)
    if command:
        return subprocess.Popen(["bash", "-c", command],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True)
    return None


def _build_auto_webhook_process(config: dict) -> subprocess.Popen | None:
    url = config.get("url", "")
    method = config.get("method", "POST").upper()
    body = config.get("body")
    cmd = ["curl", "-sS", "-w", "\n--- HTTP %{http_code} (%{time_total}s) ---", "-X", method]
    for k, v in config.get("headers", {}).items():
        cmd += ["-H", f"{k}: {v}"]
    if body:
        if isinstance(body, (dict, list)):
            cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
        elif isinstance(body, str):
            cmd += ["-d", body]
    cmd.append(url)
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)


def _build_auto_service_process(config: dict) -> subprocess.Popen | None:
    svc = config.get("service", "")
    action = config.get("action", "restart")
    if not svc or not validate_service_name(svc) or action not in ("start", "stop", "restart"):
        return None
    if config.get("is_user"):
        cmd = ["systemctl", "--user", action, svc]
    else:
        cmd = ["sudo", "-n", "systemctl", action, svc]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)


_AUTO_BUILDERS = {"script": _build_auto_script_process, "webhook": _build_auto_webhook_process,
                  "service": _build_auto_service_process}
_AUTO_TYPES = frozenset(list(_AUTO_BUILDERS) + ["workflow"])


def _run_workflow(auto_id: str, steps: list[str], triggered_by: str,
                  step_idx: int = 0, retries: int = 0, attempt: int = 0) -> None:
    """Chain-execute workflow steps sequentially via on_complete callbacks.

    ``retries`` is the max retry count per step (0 = no retries).
    ``attempt`` tracks the current attempt for the active step.
    """
    if step_idx >= len(steps):
        return
    step_auto_id = steps[step_idx]
    step_auto = db.get_automation(step_auto_id)
    if not step_auto:
        logger.warning("Workflow %s: step %d auto '%s' not found, skipping", auto_id, step_idx, step_auto_id)
        _run_workflow(auto_id, steps, triggered_by, step_idx + 1, retries)
        return

    builder = _AUTO_BUILDERS.get(step_auto["type"])
    if not builder:
        logger.warning("Workflow %s: step %d has unsupported type '%s'", auto_id, step_idx, step_auto["type"])
        _run_workflow(auto_id, steps, triggered_by, step_idx + 1, retries)
        return

    config = step_auto["config"]

    def make_process(_run_id: int) -> subprocess.Popen | None:
        return builder(config)

    def on_step_complete(_run_id: int, status: str) -> None:
        if status == "done":
            _run_workflow(auto_id, steps, triggered_by, step_idx + 1, retries)
        elif retries > 0 and attempt < retries:
            logger.info("Workflow %s: step %d ('%s') %s — retry %d/%d",
                        auto_id, step_idx, step_auto["name"], status, attempt + 1, retries)
            _run_workflow(auto_id, steps, triggered_by, step_idx, retries, attempt + 1)
        else:
            logger.info("Workflow %s: step %d ('%s') %s — stopping chain",
                        auto_id, step_idx, step_auto["name"], status)

    trigger_suffix = f":step{step_idx}" if attempt == 0 else f":step{step_idx}:retry{attempt}"
    try:
        job_runner.submit(
            make_process,
            automation_id=step_auto_id,
            trigger=f"workflow:{auto_id}{trigger_suffix}",
            triggered_by=triggered_by,
            on_complete=on_step_complete,
        )
    except RuntimeError as exc:
        logger.warning("Workflow %s: step %d submit failed: %s", auto_id, step_idx, exc)


@app.get("/api/automations")
def api_automations_list(request: Request, auth=Depends(_get_auth)):
    type_filter = request.query_params.get("type")
    return db.list_automations(type_filter=type_filter)


@app.post("/api/automations")
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


@app.put("/api/automations/{auto_id}")
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


@app.delete("/api/automations/{auto_id}")
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


@app.post("/api/automations/{auto_id}/run")
def api_automations_run(auto_id: str, request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip = _client_ip(request)
    auto = db.get_automation(auto_id)
    if not auto:
        raise HTTPException(404, "Automation not found")
    config = auto["config"]

    # Workflow: chain execution of steps
    if auto["type"] == "workflow":
        steps = config.get("steps", [])
        if not steps:
            raise HTTPException(400, "Workflow has no steps")
        wf_retries = int(config.get("retries", 0))
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


# ── /api/automations/templates — built-in presets ─────────────────────────────
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
        "description": "Backup → Verify → Cloud sync as a sequential workflow",
        "type": "workflow",
        "config": {"steps": [], "retries": 1},
        "schedule": "0 2 * * *",
    },
]


@app.get("/api/automations/templates")
def api_automation_templates(auth=Depends(_get_auth)):
    return _AUTOMATION_TEMPLATES


# ── /api/automations/stats — aggregated run statistics ────────────────────────
@app.get("/api/automations/stats")
def api_automation_stats(auth=Depends(_get_auth)):
    return db.get_automation_stats()


# ── /api/automations/export — YAML export ────────────────────────────────────
@app.get("/api/automations/export")
def api_automations_export(auth=Depends(_require_operator)):
    import yaml
    autos = db.list_automations()
    body = yaml.dump({"automations": autos}, default_flow_style=False, sort_keys=False)
    return Response(
        content=body,
        media_type="application/x-yaml",
        headers={"Content-Disposition": 'attachment; filename="noba-automations.yaml"'},
    )


# ── /api/automations/import — YAML import ────────────────────────────────────
@app.post("/api/automations/import")
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
    mode = request.query_params.get("mode", "skip")  # skip or overwrite
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


# ── /api/automations/{auto_id}/trigger — external API trigger ────────────────
@app.post("/api/automations/{auto_id}/trigger")
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
    # Check key from header or query param
    provided = (request.headers.get("X-Trigger-Key", "")
                or request.query_params.get("key", ""))
    if not provided or provided != trigger_key:
        # Fall back to Bearer auth
        auth_header = request.headers.get("Authorization", "")
        username, role = authenticate(auth_header)
        if not username or role not in ("admin", "operator"):
            raise HTTPException(401, "Invalid trigger key or credentials")
        triggered_by = username
    else:
        triggered_by = "api-trigger"

    if auto["type"] == "workflow":
        steps = config.get("steps", [])
        if not steps:
            raise HTTPException(400, "Workflow has no steps")
        wf_retries = int(config.get("retries", 0))
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


# ── Parallel workflow execution ───────────────────────────────────────────────
def _run_parallel_workflow(auto_id: str, steps: list[str], triggered_by: str) -> None:
    """Submit all workflow steps concurrently (fan-out)."""
    for idx, step_auto_id in enumerate(steps):
        step_auto = db.get_automation(step_auto_id)
        if not step_auto:
            logger.warning("Parallel workflow %s: step %d auto '%s' not found", auto_id, idx, step_auto_id)
            continue
        builder = _AUTO_BUILDERS.get(step_auto["type"])
        if not builder:
            logger.warning("Parallel workflow %s: step %d unsupported type '%s'", auto_id, idx, step_auto["type"])
            continue
        config = step_auto["config"]

        def make_process(_run_id: int, _b=builder, _c=config) -> subprocess.Popen | None:
            return _b(_c)

        try:
            job_runner.submit(
                make_process,
                automation_id=step_auto_id,
                trigger=f"workflow:{auto_id}:parallel{idx}",
                triggered_by=triggered_by,
            )
        except RuntimeError as exc:
            logger.warning("Parallel workflow %s: step %d submit failed: %s", auto_id, idx, exc)


# ── /api/admin/users ──────────────────────────────────────────────────────────
@app.get("/api/admin/users")
def api_users_get(auth=Depends(_require_admin)):
    return users.list_users()


@app.post("/api/admin/users")
async def api_users_post(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    action = body.get("action")

    if action == "add":
        new_u  = body.get("username", "").strip()
        pw     = body.get("password", "")
        role   = body.get("role", VALID_ROLES[0])
        if not new_u or not pw:
            raise HTTPException(400, "Missing username or password")
        if not valid_username(new_u) or role not in VALID_ROLES:
            raise HTTPException(400, "Invalid username or role")
        pw_err = check_password_strength(pw)
        if pw_err:
            raise HTTPException(400, pw_err)
        if users.exists(new_u):
            raise HTTPException(409, "User already exists")
        users.add(new_u, pbkdf2_hash(pw), role)
        db.audit_log("user_add", username, f"Added {new_u} with role {role}", ip)
        return {"status": "ok"}

    if action == "remove":
        target = body.get("username", "").strip()
        if not users.remove(target):
            raise HTTPException(404, "User not found")
        db.audit_log("user_remove", username, f"Removed {target}", ip)
        return {"status": "ok"}

    if action == "change_password":
        target = body.get("username", "").strip()
        pw     = body.get("password", "")
        pw_err = check_password_strength(pw)
        if pw_err:
            raise HTTPException(400, pw_err)
        if not users.update_password(target, pbkdf2_hash(pw)):
            raise HTTPException(404, "User not found")
        db.audit_log("user_password_change", username, f"Changed password for {target}", ip)
        return {"status": "ok"}

    if action == "list":
        return users.list_users()

    raise HTTPException(400, "Invalid action")


# ── /api/admin/sessions ──────────────────────────────────────────────────────
@app.get("/api/admin/sessions")
def api_sessions_list(auth=Depends(_require_admin)):
    return token_store.list_sessions()


@app.post("/api/admin/sessions/revoke")
async def api_sessions_revoke(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    body = await _read_body(request)
    prefix = body.get("prefix", "").replace("\u2026", "")
    if not prefix or len(prefix) < 8:
        raise HTTPException(400, "Invalid token prefix")
    ok = token_store.revoke_by_prefix(prefix)
    if ok:
        db.audit_log("session_revoke", username, f"Revoked session {prefix}\u2026", _client_ip(request))
    return {"success": ok}


# ── /api/login ────────────────────────────────────────────────────────────────
@app.post("/api/login")
async def api_login(request: Request):
    ip = _client_ip(request)
    if rate_limiter.is_locked(ip):
        raise HTTPException(429, "Too many failed attempts. Try again shortly.")
    body     = await _read_body(request)
    username = body.get("username", "")
    password = body.get("password", "")

    # User DB check (preferred — has up-to-date passwords and roles)
    user_data = users.get(username)
    if user_data and verify_password(user_data[0], password):
        rate_limiter.reset(ip)
        token = token_store.generate(username, user_data[1])
        db.audit_log("login", username, "success", ip)
        return {"token": token}

    # Legacy auth.conf fallback (only when user not in DB)
    if not user_data:
        legacy = load_legacy_user()
        if legacy and username == legacy[0] and verify_password(legacy[1], password):
            rate_limiter.reset(ip)
            token = token_store.generate(username, "admin")
            db.audit_log("login", username, "success (legacy)", ip)
            return {"token": token}

    locked = rate_limiter.record_failure(ip)
    logger.warning("Failed login for '%s' from %s", username, ip)
    db.audit_log("login_failed", username or "unknown", f"Failed from {ip}", ip)
    raise HTTPException(401, "Too many failed attempts." if locked else "Invalid credentials")


# ── /api/logout ───────────────────────────────────────────────────────────────
@app.post("/api/logout")
async def api_logout(request: Request):
    ip   = _client_ip(request)
    auth = request.headers.get("Authorization", "")
    tok  = auth[7:] if auth.startswith("Bearer ") else ""
    if tok:
        uname, _ = token_store.validate(tok)
        if uname:
            db.audit_log("logout", uname, "", ip)
        token_store.revoke(tok)
    return {"status": "ok"}


# ── /api/container-control ────────────────────────────────────────────────────
@app.post("/api/container-control")
async def api_container_control(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    ct_name   = body.get("name",   "").strip()
    ct_action = body.get("action", "").strip()
    if ct_action not in ("start", "stop", "restart"):
        raise HTTPException(400, "Invalid action")
    if not ct_name or not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$", ct_name):
        raise HTTPException(400, "Invalid container name")
    for runtime in ("docker", "podman"):
        try:
            r = subprocess.run([runtime, ct_action, ct_name], capture_output=True, timeout=15)
            if r.returncode == 0:
                bust_container_cache()
                db.audit_log("container_control", username, f"{ct_action} {ct_name} via {runtime}", ip)
                return {"success": True, "runtime": runtime}
        except FileNotFoundError:
            continue
        except Exception as e:
            logger.error("Container control error: %s", e)
            db.audit_log("container_control", username, f"{ct_action} {ct_name} error: {e}", ip)
            raise HTTPException(500, "Container control error")
    raise HTTPException(404, "No container runtime found")


# ── /api/truenas/vm ───────────────────────────────────────────────────────────
@app.post("/api/truenas/vm")
async def api_truenas_vm(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    vm_id  = body.get("id")
    action = body.get("action")
    try:
        vm_id = int(vm_id)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid VM ID")
    if vm_id < 0 or action not in ALLOWED_ACTIONS:
        raise HTTPException(400, "Invalid request")
    cfg = read_yaml_settings()
    if not cfg.get("truenasUrl") or not cfg.get("truenasKey"):
        raise HTTPException(400, "TrueNAS API not configured")
    import urllib.request as _ur
    try:
        url = f"{cfg['truenasUrl'].rstrip('/')}/api/v2.0/vm/id/{vm_id}/{action}"
        req = _ur.Request(url, data=b"{}", headers={
            "Authorization": f"Bearer {cfg['truenasKey']}",
            "Content-Type":  "application/json",
        }, method="POST")
        with _ur.urlopen(req, timeout=5) as r:
            success = r.getcode() == 200
        db.audit_log("vm_action", username, f"VM {vm_id} {action} {success}", ip)
        return {"success": success}
    except Exception as e:
        logger.error("VM action failed: %s", e)
        db.audit_log("vm_action", username, f"VM {vm_id} {action} failed: {e}", ip)
        raise HTTPException(502, "VM action failed")


# ── /api/webhook ──────────────────────────────────────────────────────────────
@app.post("/api/webhook")
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
            # All noba scripts accept --verbose
            return [sfile, "--verbose"] + safe_args
    return None


@app.post("/api/run")
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


# ── /api/cloud-test ───────────────────────────────────────────────────────────
@app.post("/api/cloud-test")
async def api_cloud_test(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    remote = body.get("remote", "").strip()
    if not remote or not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9 ._-]{0,63}$", remote):
        raise HTTPException(400, "Invalid remote name")
    try:
        r = subprocess.run(["rclone", "lsd", remote + ":", "--max-depth", "1"],
                           capture_output=True, text=True, timeout=15)
        err_line = next(
            (line for line in r.stderr.strip().splitlines() if line.strip() and not line.startswith("NOTICE")),
            r.stderr.strip()[:120],
        )
        success = r.returncode == 0
        db.audit_log("cloud_test", username, f"Remote {remote} -> {success}", ip)
        if not success:
            raise HTTPException(422, err_line or "Remote connection failed")
        return {"success": True}
    except subprocess.TimeoutExpired:
        db.audit_log("cloud_test", username, f"Remote {remote} timeout", ip)
        raise HTTPException(504, "Connection timed out (15s)")
    except FileNotFoundError:
        raise HTTPException(424, "rclone not found on this system")
    except Exception as e:
        logger.error("Cloud test error: %s", e)
        raise HTTPException(500, "Cloud test error")


# ── /api/service-control ──────────────────────────────────────────────────────
@app.post("/api/service-control")
async def api_service_control(request: Request, auth=Depends(_require_operator)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    svc        = body.get("service", "").strip()
    action     = body.get("action",  "").strip()
    is_user_v  = body.get("is_user", False)
    is_user    = is_user_v is True or str(is_user_v).lower() in ("true", "1", "yes", "t", "y")
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(400, f'Action "{action}" not allowed')
    if not svc or not validate_service_name(svc):
        raise HTTPException(400, "Invalid service name")
    cmd = (["systemctl", "--user", action, svc] if is_user
           else ["sudo", "-n", "systemctl", action, svc])
    try:
        r = subprocess.run(cmd, timeout=10, capture_output=True)
        success = r.returncode == 0
        db.audit_log("service_control", username, f"{action} {svc} (user={is_user}) -> {success}", ip)
        if not success:
            stderr = strip_ansi(r.stderr.decode().strip())
            raise HTTPException(422, stderr or f"systemctl {action} {svc} failed")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Service control error: %s", e)
        db.audit_log("service_control", username, f"{action} {svc} failed: {e}", ip)
        raise HTTPException(500, "Service control error")


# ── Helpers ───────────────────────────────────────────────────────────────────
async def _read_body(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(413, "Request body too large")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")


def _run_cmd(cmd: list, timeout: float = 3) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return r.stdout.strip()
    except Exception:
        return ""
