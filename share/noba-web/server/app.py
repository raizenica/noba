# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba Command Center -- FastAPI application v1.16.0"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .collector import bg_collector, get_shutdown_flag
from .config import NOBA_YAML, PID_FILE, SECURITY_HEADERS, VERSION
from .db import db
from . import deps as _deps
from .plugins import plugin_manager
from .runner import job_runner
from .auth import rate_limiter, token_store

logger = logging.getLogger("noba")
_server_start_time = time.time()

# ── Static files directory ────────────────────────────────────────────────────
_WEB_DIR = Path(__file__).parent.parent   # share/noba-web/

# ── Cleanup loop ──────────────────────────────────────────────────────────────
_prune_counter = 0


def _safe_remove(path: str, allowed_dir: str) -> bool:
    """Remove a file only if it lives inside allowed_dir. Returns True on success."""
    try:
        real = os.path.realpath(path)
        # Ensure allowed_dir is terminated with a separator to prevent sibling dir bypass
        real_allowed = os.path.join(os.path.realpath(allowed_dir), "")
        if not real.startswith(real_allowed):
            logger.warning("Blocked path-traversal delete: %s (outside %s)", real, allowed_dir)
            return False
        if os.path.exists(real):
            os.remove(real)
            return True
    except OSError as e:
        logger.debug("File removal failed: %s — %s", path, e)
    return False


def _sweep_stale_commands() -> None:
    """Remove stale agent commands/delivered entries regardless of agent activity."""
    from .agent_store import (
        _agent_cmd_lock, _agent_commands, _delivered_commands, _COMMAND_DELIVERY_TIMEOUT,
    )
    import time as _t
    now = _t.time()
    with _agent_cmd_lock:
        stale = [h for h, cmds in _agent_commands.items()
                 if cmds and cmds[0].get("queued_at", 0) < now - 600]
        for h in stale:
            del _agent_commands[h]
        stale_d = [h for h, cmds in _delivered_commands.items()
                   if cmds and all(now - c.get("delivered_at", 0) > _COMMAND_DELIVERY_TIMEOUT for c in cmds)]
        for h in stale_d:
            del _delivered_commands[h]
    if stale or stale_d:
        logger.info("Swept %d stale command queues, %d stale delivery queues", len(stale), len(stale_d))


async def _cleanup_loop() -> None:
    """Async cleanup loop — replaces the old thread-based version."""
    import asyncio as _aio
    counter = 0
    _backoff = 0
    try:
        while True:
            try:
                token_store.cleanup()
                rate_limiter.cleanup()
                # Sweep stale agent commands (agents may be offline)
                _sweep_stale_commands()
                _backoff = 0
            except Exception as e:
                logger.warning("Cleanup tick failed: %s", e)
                _backoff = min(_backoff + 5, 60)
            await _aio.sleep(300 + _backoff)
            counter += 1
            if counter >= 12:
                counter = 0
                db.prune_history()
                db.prune_audit()
                db.prune_job_runs()
                db.prune_rollups()
                db.prune_endpoint_check_history()
                try:
                    db.wal_checkpoint()
                except Exception as exc:
                    logger.debug("WAL checkpoint failed: %s", exc)
            if counter == 6:  # Every ~30 minutes
                try:
                    if os.path.exists(NOBA_YAML):
                        import shutil
                        bak = f"{NOBA_YAML}.auto.{int(time.time())}"
                        shutil.copy2(NOBA_YAML, bak)
                        import glob as glob_mod
                        for old in sorted(glob_mod.glob(f"{NOBA_YAML}.auto.*"))[:-10]:
                            os.unlink(old)
                except Exception as e:
                    logger.debug("Auto config backup failed: %s", e)
    except _aio.CancelledError:
        logger.info("Cleanup loop stopped.")
        raise


# ── Transfer cleanup (Phase 1c) ──────────────────────────────────────────────
async def _cleanup_transfers() -> None:
    """Remove orphaned file transfers older than 1 hour."""
    import asyncio as _asyncio

    from .agent_store import _TRANSFER_DIR, _TRANSFER_MAX_AGE, _transfer_lock, _transfers

    try:
        while True:
            await _asyncio.sleep(900)
            try:
                now = int(time.time())
                async with _transfer_lock:
                    expired = [tid for tid, t in _transfers.items()
                               if now - t.get("created_at", 0) > _TRANSFER_MAX_AGE]
                    for tid in expired:
                        transfer = _transfers.pop(tid)
                        # Clean up final file
                        final = transfer.get("final_path", "")
                        if final:
                            _safe_remove(final, _TRANSFER_DIR)
                # Clean up orphaned chunks outside the lock — single listdir
                if expired:
                    try:
                        all_files = os.listdir(_TRANSFER_DIR)
                    except OSError as e:
                        logger.debug("transfer chunk cleanup listdir: %s", e)
                        all_files = []
                    for fname in all_files:
                        for tid in expired:
                            if fname.startswith(tid):
                                _safe_remove(os.path.join(_TRANSFER_DIR, fname), _TRANSFER_DIR)
                                break
                if expired:
                    logger.info("[cleanup] Removed %d expired transfer(s)", len(expired))
            except Exception as e:
                logger.debug("Transfer cleanup cycle failed: %s", e)
    except _asyncio.CancelledError:
        logger.info("Transfer cleanup task stopped.")
        raise


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Hydrate token store from DB (tokens survive restarts)
    token_store.load_from_db()
    db.mark_stale_jobs()
    import asyncio as _asyncio
    db.audit_log("system_start", "system", f"Noba v{VERSION} starting (FastAPI)")
    bg_collector.start()
    _deps.bg_collector = bg_collector  # expose to route modules via deps
    _cleanup_task = _asyncio.create_task(_cleanup_loop())
    # warm up psutil CPU measurement
    import psutil
    psutil.cpu_percent(interval=None)
    try:
        plugin_manager.discover(app=app, db=db)
        plugin_manager.start()
        from . import workflow_nodes as _wn
        _wn.scan(plugin_manager)
    except Exception:
        logger.exception("Plugin system failed to start")
    from .scheduler import scheduler, fs_watcher, rss_watcher, endpoint_checker, drift_checker
    loop = _asyncio.get_running_loop()
    for name, component in [
        ("scheduler", scheduler), ("fs_watcher", fs_watcher),
        ("rss_watcher", rss_watcher), ("endpoint_checker", endpoint_checker),
    ]:
        try:
            component.start()
        except Exception:
            logger.exception("Failed to start %s", name)
    try:
        drift_checker.start(loop=loop)
    except Exception:
        logger.exception("Failed to start drift_checker")
    db.catchup_rollups()
    # Load persisted agents (show as offline until they report)
    from .agent_store import _agent_data, _agent_data_lock
    try:
        for agent in db.get_all_agents():
            with _agent_data_lock:
                if agent["hostname"] not in _agent_data:
                    _agent_data[agent["hostname"]] = {
                        "_received": agent["last_seen"],
                        "_ip": agent["ip"],
                        "platform": agent["platform"],
                        "arch": agent["arch"],
                        "agent_version": agent["agent_version"],
                        "hostname": agent["hostname"],
                    }
    except Exception as e:
        logger.warning("Failed to load persisted agents: %s", e)
    # Start file transfer cleanup background task (Phase 1c)
    _transfer_cleanup_task = _asyncio.create_task(_cleanup_transfers())
    logger.info("Noba v%s started (%d plugins)", VERSION, plugin_manager.count)
    yield
    # Signal collector threads FIRST to prevent port-bind on restart
    get_shutdown_flag().set()
    # Close HTTP client early
    with suppress(Exception):
        from .integrations import _client as _http_client
        _http_client.close()
    _cleanup_task.cancel()
    _transfer_cleanup_task.cancel()
    for component in [rss_watcher, endpoint_checker, drift_checker, fs_watcher, scheduler]:
        with suppress(Exception):
            component.stop()
    job_runner.shutdown()
    plugin_manager.stop()
    db.audit_log("system_stop", "system", "Server stopping")
    # Close all agent WebSocket connections
    from .agent_store import _agent_websockets, _agent_ws_lock
    with _agent_ws_lock:
        ws_list = list(_agent_websockets.items())
        _agent_websockets.clear()
    for _ws_hostname, ws_conn in ws_list:
        with suppress(Exception):
            await ws_conn.close(code=1001, reason="Server shutting down")
    with suppress(Exception):
        os.unlink(PID_FILE)


# ── App ───────────────────────────────────────────────────────────────────────
_dev_mode = os.environ.get("NOBA_DEV", "").strip() in ("1", "true", "yes")
app = FastAPI(
    title="Noba Command Center",
    version=VERSION,
    lifespan=lifespan,
    openapi_url="/api/openapi.json" if _dev_mode else None,
    docs_url="/api/docs" if _dev_mode else None,
    redoc_url="/api/redoc" if _dev_mode else None,
)


@app.exception_handler(500)
async def _handle_500(request: Request, exc: Exception):
    logging.getLogger("noba").error("Unhandled 500: %s %s — %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(422)
async def _handle_422(request: Request, exc: Exception):
    logging.getLogger("noba").warning("Validation error: %s %s — %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=422, content={"detail": "Validation error"})


# ── CORS ──────────────────────────────────────────────────────────────────────
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
_DOCS_PATHS = ("/api/docs", "/api/redoc", "/api/openapi.json")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    # Skip strict CSP for Swagger/ReDoc (they load external CSS/JS)
    if request.url.path not in _DOCS_PATHS:
        for k, v in SECURITY_HEADERS.items():
            response.headers[k] = v
    return response


# ── Static / frontend ─────────────────────────────────────────────────────────
_VUE_DIST = _WEB_DIR / "static" / "dist"


class _CachedStaticFiles(StaticFiles):
    """StaticFiles subclass that adds Cache-Control headers."""
    def __init__(self, *args, max_age: int = 3600, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache_header = f"public, max-age={max_age}".encode()

    async def __call__(self, scope, receive, send):
        cache_val = self._cache_header

        async def _send_with_cache(msg):
            if msg["type"] == "http.response.start":
                headers = [(k, v) for k, v in msg.get("headers", []) if k != b"cache-control"]
                headers.append((b"cache-control", cache_val))
                msg["headers"] = headers
            await send(msg)
        await super().__call__(scope, receive, _send_with_cache)


# Serve Vite-built assets (hashed filenames = immutable, long cache)
if (_VUE_DIST / "assets").exists():
    app.mount("/assets", _CachedStaticFiles(
        directory=str(_VUE_DIST / "assets"), max_age=31536000), name="vue-assets")

# Keep /static mount for favicons and other non-Vue static files (short cache)
app.mount("/static", _CachedStaticFiles(
    directory=str(_WEB_DIR / "static"), max_age=300), name="static")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(_VUE_DIST / "manifest.json", media_type="application/json")


@app.get("/service-worker.js")
async def service_worker():
    return FileResponse(_VUE_DIST / "service-worker.js", media_type="application/javascript")


@app.get("/favicon.svg")
async def favicon_svg():
    return FileResponse(_VUE_DIST / "favicon.svg", media_type="image/svg+xml")


@app.get("/favicon.ico")
async def favicon_ico():
    return FileResponse(_VUE_DIST / "favicon.ico", media_type="image/x-icon")


# ── Include API routers ───────────────────────────────────────────────────────
from .routers import api_router  # noqa: E402
app.include_router(api_router)


# ── Health check endpoint ─────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Health check endpoint for monitoring and load balancers."""
    checks: dict = {"status": "ok", "timestamp": int(time.time())}

    # DB check — exercises connection, lock, and WAL read path
    try:
        db.execute_write(lambda conn: conn.execute("SELECT 1").fetchone())
        checks["db"] = "ok"
    except Exception:
        checks["db"] = "error"
        checks["status"] = "degraded"

    # Uptime
    checks["uptime_s"] = int(time.time() - _server_start_time)

    return checks


# ── SPA fallback (must be last) ──────────────────────────────────────────────
@app.get("/{rest:path}")
async def spa_fallback(rest: str = ""):
    if rest.startswith("api/"):
        raise HTTPException(404, "API route not found")
    # index.html must never be cached: it contains hashed asset URLs and must
    # always be fetched fresh so browsers pick up new deployments immediately.
    return FileResponse(
        _VUE_DIST / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
