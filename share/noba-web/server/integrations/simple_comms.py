# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Communications integrations."""
from __future__ import annotations

import logging

import httpx

from .base import ConfigError, TransientError, _http_get

logger = logging.getLogger("noba")



# ── Authentik ────────────────────────────────────────────────────────────────
def get_authentik(url: str, token: str) -> dict | None:
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Bearer {token}"}
        users_data = _http_get(f"{base}/api/v3/core/users/?page_size=1", hdrs, category="identity_auth")
        user_count = users_data.get("pagination", {}).get("count", 0)
        events_data = _http_get(
            f"{base}/api/v3/events/events/?action=login_failed&ordering=-created&page_size=10",
            hdrs, category="identity_auth",
        )
        failed_logins = events_data.get("pagination", {}).get("count", 0)
        return {
            "users": user_count,
            "failed_logins": failed_logins,
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError):
        return {"status": "offline", "error": "Connection failed"}



