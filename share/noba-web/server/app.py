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
    plugin_manager.discover()
    plugin_manager.start()
    from .scheduler import scheduler
    scheduler.start()
    from .scheduler import fs_watcher
    fs_watcher.start()
    from .scheduler import rss_watcher
    rss_watcher.start()
    db.catchup_rollups()
    logger.info("Noba v%s started (%d plugins)", VERSION, plugin_manager.count)
    yield
    rss_watcher.stop()
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
    try:
        os.unlink(PID_FILE)
    except Exception:
        pass


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Noba Command Center", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)

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
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers[k] = v
    return response


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

# ── Include API routers ───────────────────────────────────────────────────────
from .routers import api_router  # noqa: E402
app.include_router(api_router)
