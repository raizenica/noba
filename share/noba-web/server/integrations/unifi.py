# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""UniFi Controller and UniFi Protect integrations (dedicated httpx clients)."""
from __future__ import annotations

import httpx


# ── UniFi Controller ─────────────────────────────────────────────────────────
def get_unifi(url: str, user: str, password: str, site: str = "default", *, verify_ssl=True):
    if not url or not user:
        return None
    try:
        base = url.rstrip("/")
        site = site or "default"
        # Login — use a separate client to avoid cookie jar contamination
        with httpx.Client(timeout=4, verify=verify_ssl) as uclient:
            login_r = uclient.post(f"{base}/api/login", json={"username": user, "password": password}, headers={"Referer": base})
            if login_r.status_code != 200:
                return None
            cookies = login_r.cookies
            # Devices
            dev_r = uclient.get(f"{base}/api/s/{site}/stat/device", cookies=cookies)
            devices = dev_r.json().get("data", []) if dev_r.status_code == 200 else []
            # Clients
            sta_r = uclient.get(f"{base}/api/s/{site}/stat/sta", cookies=cookies)
            clients = sta_r.json().get("data", []) if sta_r.status_code == 200 else []
            adopted = sum(1 for d in devices if d.get("adopted"))
            # Logout — release the session on the controller
            try:
                uclient.post(f"{base}/api/logout", cookies=cookies)
            except Exception:
                pass
        return {
            "devices": len(devices), "adopted": adopted,
            "clients": len(clients), "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# ── UniFi Protect ────────────────────────────────────────────────────────────
def get_unifi_protect(url: str, user: str, password: str, *, verify_ssl=True) -> dict | None:
    if not url or not user:
        return None
    try:
        base = url.rstrip("/")
        with httpx.Client(timeout=6, verify=verify_ssl, follow_redirects=False) as up_client:
            login_r = up_client.post(
                f"{base}/api/auth/login",
                json={"username": user, "password": password},
            )
            login_r.raise_for_status()
            cam_r = up_client.get(f"{base}/proxy/protect/api/cameras")
            cam_r.raise_for_status()
            cameras = cam_r.json()

        cam_list = cameras if isinstance(cameras, list) else []
        recording = sum(
            1 for c in cam_list
            if c.get("isRecording") or c.get("recordingSettings", {}).get("mode") != "never"
        )
        return {
            "cameras": len(cam_list),
            "recording": recording,
            "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None
