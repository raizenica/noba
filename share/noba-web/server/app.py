"""Noba Command Center – FastAPI application v1.12.0"""
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

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .auth import authenticate, load_legacy_user, pbkdf2_hash, rate_limiter, token_store, \
    users, valid_username, verify_password, check_password_strength, VALID_ROLES
from .collector import bg_collector, collect_stats, get_shutdown_flag
from .config import (
    ACTION_LOG, ALLOWED_ACTIONS, HISTORY_METRICS, LOG_DIR, MAX_BODY_BYTES,
    NOBA_YAML, PID_FILE, SCRIPT_DIR, SCRIPT_MAP, SECURITY_HEADERS, VERSION,
)
from .db import db
from .metrics import (
    _cache, _read_file, bust_container_cache, collect_smart,
    get_rclone_remotes, get_service_status, strip_ansi, validate_service_name,
)
from .alerts import dispatch_notifications
from .yaml_config import read_yaml_settings, write_yaml_settings

logger = logging.getLogger("noba")
_server_start_time = time.time()

# ── Job state (thread-safe) ───────────────────────────────────────────────────
_active_job: dict | None = None
_job_lock = threading.Lock()

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


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    db._init_schema()
    db.audit_log("system_start", "system", f"Noba v{VERSION} starting (FastAPI)")
    bg_collector.start()
    threading.Thread(target=_cleanup_loop, daemon=True, name="token-cleanup").start()
    # warm up psutil CPU measurement
    import psutil
    psutil.cpu_percent(interval=None)
    logger.info("Noba v%s started", VERSION)
    yield
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
    allow_methods=["GET", "POST"],
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


def _require_admin(request: Request) -> tuple[str, str]:
    username, role = _get_auth(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    return username, role


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    return (forwarded.split(",")[0].strip() if forwarded
            else (request.client.host if request.client else "0.0.0.0"))


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
                headers = dict(msg.get("headers", []))
                headers[b"cache-control"] = b"public, max-age=3600"
                msg["headers"] = list(headers.items())
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
async def api_stream(request: Request, auth=Depends(_get_auth)):
    qs = {k: [v] for k, v in request.query_params.items()}
    bg_collector.update_qs(qs)
    shutdown = get_shutdown_flag()

    async def generate():
        loop = asyncio.get_event_loop()
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
    db.audit_log("settings_update", username, "Updated web settings", _client_ip(request))
    if not ok:
        raise HTTPException(500, "Failed to write settings")
    return {"status": "ok"}


# ── /api/notifications/test ───────────────────────────────────────────────────
@app.get("/api/notifications/test")
def api_notif_test(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    cfg = read_yaml_settings()
    notif_cfg = cfg.get("notifications", {})
    if notif_cfg:
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


# ── /api/audit ────────────────────────────────────────────────────────────────
@app.get("/api/audit")
def api_audit(request: Request, auth=Depends(_require_admin)):
    limit = _int_param(request, "limit", 100, 1, 1000)
    return db.get_audit(limit)


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
    content_length = int(request.headers.get("Content-Length", 0))
    if content_length > 512 * 1024:
        raise HTTPException(413, "Upload too large (max 512 KB)")
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "Empty body")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "Invalid file encoding (expected UTF-8 YAML)")
    os.makedirs(os.path.dirname(NOBA_YAML), exist_ok=True)
    tmp = NOBA_YAML + ".restore-tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, NOBA_YAML)
    db.audit_log("config_restore", username, "Restored config from upload", _client_ip(request))
    return {"status": "ok"}


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


# ── /api/run-status ───────────────────────────────────────────────────────────
@app.get("/api/run-status")
def api_run_status(auth=Depends(_get_auth)):
    with _job_lock:
        return dict(_active_job) if _active_job else {"status": "idle"}


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


# ── /api/login ────────────────────────────────────────────────────────────────
@app.post("/api/login")
async def api_login(request: Request):
    ip = _client_ip(request)
    if rate_limiter.is_locked(ip):
        raise HTTPException(429, "Too many failed attempts. Try again shortly.")
    body     = await _read_body(request)
    username = body.get("username", "")
    password = body.get("password", "")

    # Legacy auth.conf check
    legacy = load_legacy_user()
    if legacy and username == legacy[0] and verify_password(legacy[1], password):
        rate_limiter.reset(ip)
        token = token_store.generate(username, "admin")
        db.audit_log("login", username, "success", ip)
        return {"token": token}

    # User DB check
    user_data = users.get(username)
    if user_data and verify_password(user_data[0], password):
        rate_limiter.reset(ip)
        token = token_store.generate(username, user_data[1])
        db.audit_log("login", username, "success", ip)
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
async def api_container_control(request: Request, auth=Depends(_require_admin)):
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
            db.audit_log("container_control", username, f"{ct_action} {ct_name} error: {e}", ip)
            raise HTTPException(500, f"Container control error: {e}")
    raise HTTPException(404, "No container runtime found")


# ── /api/truenas/vm ───────────────────────────────────────────────────────────
@app.post("/api/truenas/vm")
async def api_truenas_vm(request: Request, auth=Depends(_get_auth)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    vm_id  = body.get("id")
    action = body.get("action")
    if not vm_id or action not in ALLOWED_ACTIONS:
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
        db.audit_log("vm_action", username, f"VM {vm_id} {action} failed: {e}", ip)
        raise HTTPException(502, f"VM action failed: {e}")


# ── /api/webhook ──────────────────────────────────────────────────────────────
@app.post("/api/webhook")
async def api_webhook(request: Request, auth=Depends(_get_auth)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    hook_id = body.get("id")
    cfg = read_yaml_settings()
    hook = next((a for a in cfg.get("automations", []) if a.get("id") == hook_id), None)
    if not hook or not hook.get("url"):
        raise HTTPException(404, "Webhook not found in config")
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
        db.audit_log("webhook", username, f"Webhook {hook_id} failed: {e}", ip)
        raise HTTPException(502, f"Webhook failed: {e}")


# ── /api/run ──────────────────────────────────────────────────────────────────
@app.post("/api/run")
async def api_run(request: Request, auth=Depends(_get_auth)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    script   = body.get("script", "")
    args_in  = body.get("args",   "")

    safe_args = []
    if isinstance(args_in, str) and args_in.strip():
        try:
            safe_args = shlex.split(args_in)
        except ValueError:
            safe_args = args_in.split()
    elif isinstance(args_in, list):
        safe_args = [str(a) for a in args_in if str(a).strip()]

    global _active_job
    with _job_lock:
        if _active_job and _active_job.get("status") == "running":
            raise HTTPException(409, "A script is already running")
        _active_job = {"script": script, "status": "running", "started": datetime.now().isoformat()}

    def _run_script():
        global _active_job
        status = "error"
        p = None
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            with open(ACTION_LOG, "w") as f:
                f.write(f">> [{ts}] Initiating: {script} {' '.join(safe_args)}\n\n")

            if script == "custom":
                cfg = read_yaml_settings()
                act = next((a for a in cfg.get("customActions", []) if a.get("id") == args_in), None)
                if act and act.get("command"):
                    with open(ACTION_LOG, "a") as f:
                        p = subprocess.Popen(["bash", "-c", act["command"]], stdout=f, stderr=subprocess.STDOUT)
                else:
                    with open(ACTION_LOG, "a") as f:
                        f.write(f"[ERROR] Custom action not found: {args_in}\n")
                    status = "failed"
            elif script == "speedtest":
                with open(ACTION_LOG, "a") as f:
                    p = subprocess.Popen(["speedtest-cli", "--simple"] + safe_args, stdout=f, stderr=subprocess.STDOUT)
            elif script in SCRIPT_MAP:
                sfile = os.path.join(SCRIPT_DIR, SCRIPT_MAP[script])
                if os.path.isfile(sfile):
                    with open(ACTION_LOG, "a") as f:
                        p = subprocess.Popen([sfile, "--verbose"] + safe_args, stdout=f,
                                             stderr=subprocess.STDOUT, cwd=SCRIPT_DIR)
                else:
                    with open(ACTION_LOG, "a") as f:
                        f.write(f"[ERROR] Script not found: {sfile}\n")
                    status = "failed"
            else:
                with open(ACTION_LOG, "a") as f:
                    f.write(f"[ERROR] Unknown script: {script}\n")
                status = "failed"

            if p:
                try:
                    p.wait(timeout=300)
                    status = "done" if p.returncode == 0 else "failed"
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait()
                    with open(ACTION_LOG, "a") as f:
                        f.write("\n[ERROR] Script timed out after 300s.\n")
                    status = "timeout"
        except Exception as e:
            logger.exception("Script runner error: %s", e)
        finally:
            with open(ACTION_LOG, "a") as f:
                f.write(f"\n>> [{datetime.now().strftime('%H:%M:%S')}] {status.upper()}\n")
            with _job_lock:
                if _active_job and _active_job.get("script") == script:
                    _active_job["status"]   = status
                    _active_job["finished"] = datetime.now().isoformat()
            db.audit_log("script_run", username, f"{script} {args_in} -> {status}", ip)

    threading.Thread(target=_run_script, daemon=True, name=f"run-{script}").start()
    return {"success": True, "status": "running", "script": script}


# ── /api/cloud-test ───────────────────────────────────────────────────────────
@app.post("/api/cloud-test")
async def api_cloud_test(request: Request, auth=Depends(_get_auth)):
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
            (l for l in r.stderr.strip().splitlines() if l.strip() and not l.startswith("NOTICE")),
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
        raise HTTPException(500, f"Cloud test error: {e}")


# ── /api/service-control ──────────────────────────────────────────────────────
@app.post("/api/service-control")
async def api_service_control(request: Request, auth=Depends(_get_auth)):
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
            stderr = r.stderr.decode().strip()
            raise HTTPException(422, stderr or f"systemctl {action} {svc} failed")
        return {"success": True}
    except Exception as e:
        db.audit_log("service_control", username, f"{action} {svc} failed: {e}", ip)
        raise HTTPException(500, f"Service control error: {e}")


# ── Helpers ───────────────────────────────────────────────────────────────────
async def _read_body(request: Request) -> dict:
    content_length = int(request.headers.get("Content-Length", 0))
    if content_length > MAX_BODY_BYTES:
        raise HTTPException(413, "Request body too large")
    raw = await request.body()
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
