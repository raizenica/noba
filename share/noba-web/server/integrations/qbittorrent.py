"""qBittorrent integration (dedicated httpx client for form login + cookies)."""
from __future__ import annotations

import httpx

from .base import _client


# ── qBittorrent ───────────────────────────────────────────────────────────
def get_qbit(url: str, user: str, password: str) -> dict | None:
    if not url or not user:
        return None
    base   = url.rstrip("/")
    result = {"dl_speed": 0, "up_speed": 0, "active_torrents": 0, "status": "offline"}
    try:
        # Use a separate client to avoid cookie jar contamination on the shared _client
        with httpx.Client(timeout=4) as qclient:
            r1 = qclient.post(
                f"{base}/api/v2/auth/login",
                data={"username": user, "password": password},
            )
        cookie = r1.headers.get("set-cookie")
        if not cookie:
            return result
        r2 = _client.get(
            f"{base}/api/v2/sync/maindata",
            headers={"Cookie": cookie},
            timeout=4,
        )
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
