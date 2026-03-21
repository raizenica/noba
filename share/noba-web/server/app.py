"""Noba Command Center -- FastAPI application v1.16.0"""
from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
            db.prune_rollups()
            db.prune_endpoint_check_history()
            # Checkpoint WAL to prevent unbounded growth on long-running instances
            try:
                with db._lock:
                    db._get_conn().execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception as exc:
                logger.debug("WAL checkpoint failed: %s", exc)
        if _prune_counter == 6:  # Every ~30 minutes
            try:
                if os.path.exists(NOBA_YAML):
                    import shutil
                    bak = f"{NOBA_YAML}.auto.{int(time.time())}"
                    shutil.copy2(NOBA_YAML, bak)
                    # Keep only last 10 auto backups
                    import glob as glob_mod
                    for old in sorted(glob_mod.glob(f"{NOBA_YAML}.auto.*"))[:-10]:
                        os.unlink(old)
            except Exception as e:
                logger.debug("Auto config backup failed: %s", e)


# ── Transfer cleanup (Phase 1c) ──────────────────────────────────────────────
async def _cleanup_transfers() -> None:
    """Remove orphaned file transfers older than 1 hour."""
    import asyncio as _asyncio

    from .agent_store import _TRANSFER_DIR, _TRANSFER_MAX_AGE, _transfer_lock, _transfers

    try:
        while True:
            await _asyncio.sleep(900)  # Every 15 minutes
            now = int(time.time())
            with _transfer_lock:
                expired = [tid for tid, t in _transfers.items()
                           if now - t.get("created_at", 0) > _TRANSFER_MAX_AGE]
                for tid in expired:
                    transfer = _transfers.pop(tid)
                    # Clean up final file
                    final = transfer.get("final_path", "")
                    if final and os.path.exists(final):
                        try:
                            os.remove(final)
                        except OSError:
                            pass
                    # Clean up orphaned chunks
                    try:
                        for fname in os.listdir(_TRANSFER_DIR):
                            if fname.startswith(tid):
                                try:
                                    os.remove(os.path.join(_TRANSFER_DIR, fname))
                                except OSError:
                                    pass
                    except OSError:
                        pass
            if expired:
                logger.info("[cleanup] Removed %d expired transfer(s)", len(expired))
    except _asyncio.CancelledError:
        logger.info("Transfer cleanup task stopped.")
        raise


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.mark_stale_jobs()
    db.audit_log("system_start", "system", f"Noba v{VERSION} starting (FastAPI)")
    bg_collector.start()
    _deps.bg_collector = bg_collector  # expose to route modules via deps
    threading.Thread(target=_cleanup_loop, daemon=True, name="token-cleanup").start()
    # warm up psutil CPU measurement
    import psutil
    psutil.cpu_percent(interval=None)
    plugin_manager.discover(app=app, db=db)
    plugin_manager.start()
    from .scheduler import scheduler
    scheduler.start()
    from .scheduler import fs_watcher
    fs_watcher.start()
    from .scheduler import rss_watcher
    rss_watcher.start()
    from .scheduler import endpoint_checker
    endpoint_checker.start()
    from .scheduler import drift_checker
    drift_checker.start()
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
    except Exception:
        pass
    # Start file transfer cleanup background task (Phase 1c)
    import asyncio as _asyncio
    _transfer_cleanup_task = _asyncio.create_task(_cleanup_transfers())
    logger.info("Noba v%s started (%d plugins)", VERSION, plugin_manager.count)
    yield
    _transfer_cleanup_task.cancel()
    rss_watcher.stop()
    endpoint_checker.stop()
    drift_checker.stop()
    from .scheduler import fs_watcher as _fw
    _fw.stop()
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
    # Close all agent WebSocket connections
    from .agent_store import _agent_websockets, _agent_ws_lock
    with _agent_ws_lock:
        ws_list = list(_agent_websockets.items())
        _agent_websockets.clear()
    for _ws_hostname, ws_conn in ws_list:
        try:
            await ws_conn.close(code=1001, reason="Server shutting down")
        except Exception:
            pass
    try:
        os.unlink(PID_FILE)
    except Exception:
        pass


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Noba Command Center",
    version=VERSION,
    lifespan=lifespan,
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

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
    if not request.url.path.startswith(_DOCS_PATHS):
        for k, v in SECURITY_HEADERS.items():
            response.headers[k] = v
    return response


# ── Static / frontend ─────────────────────────────────────────────────────────
_VUE_DIST = _WEB_DIR / "static" / "dist"


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


# Serve Vite-built assets (hashed filenames = immutable)
if (_VUE_DIST / "assets").exists():
    app.mount("/assets", _CachedStaticFiles(directory=str(_VUE_DIST / "assets")), name="vue-assets")

# Keep /static mount for favicons and other non-Vue static files
app.mount("/static", _CachedStaticFiles(directory=str(_WEB_DIR / "static")), name="static")


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


# ── SPA fallback (must be last) ──────────────────────────────────────────────
@app.get("/{rest:path}")
async def spa_fallback(rest: str = ""):
    return FileResponse(_VUE_DIST / "index.html")
