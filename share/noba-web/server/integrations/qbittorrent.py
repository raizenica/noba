# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""qBittorrent integration (dedicated httpx client for form login + cookies)."""
from __future__ import annotations

import httpx


# ── qBittorrent ───────────────────────────────────────────────────────────
def get_qbit(url: str, user: str, password: str) -> dict | None:
    if not url or not user:
        return None
    base   = url.rstrip("/")
    result = {"dl_speed": 0, "up_speed": 0, "active_torrents": 0, "status": "offline"}
    try:
        # Use a dedicated client for both login and data to avoid cookie leakage
        with httpx.Client(timeout=4) as qclient:
            r1 = qclient.post(
                f"{base}/api/v2/auth/login",
                data={"username": user, "password": password},
            )
            if not r1.headers.get("set-cookie"):
                return result
            r2 = qclient.get(f"{base}/api/v2/sync/maindata")
            d = r2.json()
        state = d.get("server_state", {})
        result.update({
            "dl_speed":       state.get("dl_info_speed", 0),
            "up_speed":       state.get("up_info_speed", 0),
            "active_torrents": sum(
                1 for t in d.get("torrents", {}).values()
                if t.get("state") in ("downloading", "stalledDL", "metaDL")
            ),
            "status": "online",
        })
    except (httpx.HTTPError, KeyError, ValueError):
        pass
    return result
