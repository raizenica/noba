# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – IoT integrations."""
from __future__ import annotations

import logging
import httpx

from .base import ConfigError, TransientError, _http_get


logger = logging.getLogger("noba")



# ── Homebridge ───────────────────────────────────────────────────────────────
def get_homebridge(url: str, user: str, password: str) -> dict | None:
    if not url or not user:
        return None
    try:
        base = url.rstrip("/")
        with httpx.Client(timeout=4, follow_redirects=False) as hb_client:
            login_r = hb_client.post(
                f"{base}/api/auth/login",
                json={"username": user, "password": password},
            )
            login_r.raise_for_status()
            token = login_r.json().get("access_token", "")
            hdrs = {"Authorization": f"Bearer {token}"}
            acc_r = hb_client.get(f"{base}/api/accessories", headers=hdrs)
            acc_r.raise_for_status()
            accessories = acc_r.json()

        acc_list = accessories if isinstance(accessories, list) else []
        battery_devices = []
        for acc in acc_list:
            svc_chars = acc.get("serviceCharacteristics", acc.get("values", {}))
            # Look for battery level in characteristics
            if isinstance(svc_chars, list):
                for ch in svc_chars:
                    if ch.get("type") == "BatteryLevel" or ch.get("description") == "Battery Level":
                        battery_devices.append({
                            "name": acc.get("serviceName", acc.get("name", "?")),
                            "battery": int(ch.get("value", 0)),
                        })
                        break
        return {
            "accessories": len(acc_list),
            "battery_devices": battery_devices,
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





# ── Zigbee2MQTT ──────────────────────────────────────────────────────────────
def get_z2m(url: str) -> dict | None:
    if not url:
        return None
    try:
        base = url.rstrip("/")
        devices = _http_get(f"{base}/api/devices")
        dev_list = devices if isinstance(devices, list) else []
        offline = sum(
            1 for d in dev_list
            if d.get("availability", {}).get("state") == "offline"
            or d.get("interview_completed") is False
        )
        low_battery = []
        for d in dev_list:
            battery = d.get("battery")
            if battery is not None and int(battery) < 20:
                low_battery.append({
                    "name": d.get("friendly_name", d.get("ieee_address", "?")),
                    "battery": int(battery),
                })
        return {
            "devices": len(dev_list),
            "offline": offline,
            "low_battery": low_battery,
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





# ── ESPHome ──────────────────────────────────────────────────────────────────
def get_esphome(url: str) -> dict | None:
    if not url:
        return None
    try:
        base = url.rstrip("/")
        data = _http_get(f"{base}/devices")
        dev_list = data if isinstance(data, list) else []
        online = sum(
            1 for d in dev_list
            if d.get("status") == "ONLINE" or d.get("connected") is True
        )
        return {
            "nodes": len(dev_list),
            "online": online,
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





# ── PiKVM ────────────────────────────────────────────────────────────────────
def get_pikvm(url: str, user: str, password: str) -> dict | None:
    if not url:
        return None
    try:
        import base64
        base = url.rstrip("/")
        cred = base64.b64encode(f"{user}:{password}".encode()).decode()
        hdrs = {"Authorization": f"Basic {cred}"}
        _http_get(f"{base}/api/info", hdrs)
        return {"online": True, "status": "online"}
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}



