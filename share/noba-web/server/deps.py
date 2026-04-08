# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Shared dependencies for route modules."""
from __future__ import annotations

import functools
import inspect
import json
import logging
import subprocess

from fastapi import HTTPException, Request

from .auth import (  # noqa: F401
    authenticate,
    has_permission,
    token_store,
    ws_token_store,
)
from .config import MAX_BODY_BYTES, TRUST_PROXY
from .db import db  # noqa: F401  -- re-exported for route modules

_log = logging.getLogger("noba")

# ── bg_collector reference (set during lifespan) ─────────────────────────────
bg_collector: object | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_int(value: object, default: int) -> int:
    """Convert *value* to int, returning *default* on bad input."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return default


def _int_param(request: Request, name: str, default: int, lo: int, hi: int) -> int:
    """Extract and validate an integer query parameter clamped to [lo, hi]."""
    try:
        v = int(request.query_params.get(name, str(default)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"Invalid {name} parameter") from None
    return max(lo, min(hi, v))


def check_ws_origin(origin: str, request_host: str | None = None) -> bool:
    """Return True if a WebSocket Origin header is allowed.

    CSWSH protection for all websocket endpoints. Rules:

    1. Empty Origin → reject. Browsers always send Origin on WebSocket
       upgrades; a missing header is either a non-browser client that
       bypasses CORS anyway (use the REST API or a proxy) or an attempt
       to evade the check.
    2. Origin in the explicit ``NOBA_CORS_ORIGINS`` allowlist → allow.
    3. Origin's hostname matches the request Host → allow (same-origin).
    4. Otherwise → reject.

    The allowlist is read lazily from ``server.app._cors_origins`` so that
    tests and future config reloads don't need to bounce the process.
    """
    if not origin:
        return False

    # Lazy import to avoid a circular dep on app.py at module load time.
    try:
        from .app import _cors_origins as _allow
    except Exception:
        _allow = []

    if _allow and origin in _allow:
        return True

    # Same-origin match on hostname.
    try:
        from urllib.parse import urlparse
        origin_host = urlparse(origin).hostname or ""
    except Exception:
        return False

    if not request_host:
        return False
    # Normalise: request_host may include a port (e.g. "noba.local:8000").
    req_host = request_host.split(":", 1)[0]
    return origin_host == req_host


def _client_ip(request: Request) -> str:
    """Extract client IP, supporting X-Forwarded-For when TRUST_PROXY is set."""
    if TRUST_PROXY:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _read_body(request: Request) -> dict:
    """Read JSON request body with MAX_BODY_BYTES size check."""
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(413, "Request body too large") from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON") from None


def _run_cmd(cmd: list, timeout: float = 3) -> str:
    """Run a subprocess with timeout, returning stdout or empty string on failure."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return r.stdout.strip()
    except Exception:
        return ""


# ── Route error handler ───────────────────────────────────────────────────────

def handle_errors(func):
    """Catch unhandled exceptions in route handlers and return HTTP 500.

    HTTPException passes through unchanged.
    Do NOT apply to @router.websocket routes or routes returning StreamingResponse —
    those connections are already upgraded; wrapping them corrupts the protocol.
    """
    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def _async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception:
                _log.exception("Unhandled error in %s", func.__name__)
                raise HTTPException(status_code=500, detail="Internal server error") from None
        return _async_wrapper
    else:
        @functools.wraps(func)
        def _sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception:
                _log.exception("Unhandled error in %s", func.__name__)
                raise HTTPException(status_code=500, detail="Internal server error") from None
        return _sync_wrapper


# ── Auth dependencies ────────────────────────────────────────────────────────

def _get_auth(request: Request) -> tuple[str, str]:
    """Validate Authorization header and return (username, role)."""
    auth = request.headers.get("Authorization", "")
    username, role = authenticate(auth)
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return username, role


def _get_auth_sse(request: Request) -> tuple[str, str]:
    """Auth for SSE -- also accepts token query param since EventSource can't set headers."""
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
    """Require admin or operator role."""
    username, role = _get_auth(request)
    if role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return username, role


def _require_admin(request: Request) -> tuple[str, str]:
    """Require admin role."""
    username, role = _get_auth(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    return username, role


def _require_permission(permission: str):
    """Create a dependency that checks a specific permission."""
    def checker(request: Request) -> tuple[str, str]:
        username, role = _get_auth(request)
        if not has_permission(role, permission):
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")
        return username, role
    return checker
