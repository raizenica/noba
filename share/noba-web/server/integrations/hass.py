# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Home Assistant integrations (Bearer token auth)."""
from __future__ import annotations

import httpx

from .base import _http_get


# ── Home Assistant ───────────────────────────────────────────────────────────
def get_hass(url: str, token: str):
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Bearer {token}"}
        states = _http_get(f"{base}/api/states", hdrs, category="smart_home")
        if not isinstance(states, list):
            return None
        domains = {}
        for e in states:
            d = e.get("entity_id", "").split(".")[0]
            domains[d] = domains.get(d, 0) + 1
        lights_on = sum(1 for e in states if e.get("entity_id", "").startswith("light.") and e.get("state") == "on")
        switches_on = sum(1 for e in states if e.get("entity_id", "").startswith("switch.") and e.get("state") == "on")
        automations = domains.get("automation", 0)
        return {
            "entities": len(states), "automations": automations,
            "lights_on": lights_on, "switches_on": switches_on,
            "domains": domains, "status": "online",
        }
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def get_hass_entities(url: str, token: str, entity_filter: str = "") -> dict | None:
    """Fetch detailed Home Assistant entity states with optional domain filter."""
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Bearer {token}"}
        states = _http_get(f"{base}/api/states", hdrs, category="smart_home")
        if not isinstance(states, list):
            return None
        entities = []
        for e in states:
            eid = e.get("entity_id", "")
            domain = eid.split(".")[0] if "." in eid else ""
            if entity_filter and domain != entity_filter:
                continue
            state = e.get("state", "unknown")
            attrs = e.get("attributes", {})
            entity = {
                "entity_id": eid,
                "domain": domain,
                "state": state,
                "name": attrs.get("friendly_name", eid),
                "icon": attrs.get("icon", ""),
            }
            # Add domain-specific attributes
            if domain == "sensor":
                entity["unit"] = attrs.get("unit_of_measurement", "")
                entity["device_class"] = attrs.get("device_class", "")
            elif domain == "light":
                entity["brightness"] = attrs.get("brightness")
                entity["color_temp"] = attrs.get("color_temp")
                entity["rgb_color"] = attrs.get("rgb_color")
            elif domain == "climate":
                entity["temperature"] = attrs.get("temperature")
                entity["current_temperature"] = attrs.get("current_temperature")
                entity["hvac_action"] = attrs.get("hvac_action", "")
            elif domain == "media_player":
                entity["media_title"] = attrs.get("media_title", "")
                entity["source"] = attrs.get("source", "")
            elif domain in ("binary_sensor", "switch", "input_boolean"):
                entity["device_class"] = attrs.get("device_class", "")
            elif domain == "cover":
                entity["current_position"] = attrs.get("current_position")
            if "battery_level" in attrs:
                entity["battery"] = attrs.get("battery_level")
            entities.append(entity)
        return {"entities": entities[:500], "total": len(states)}
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def get_hass_services(url: str, token: str) -> list | None:
    """Fetch available Home Assistant services."""
    if not url or not token:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"Authorization": f"Bearer {token}"}
        services = _http_get(f"{base}/api/services", hdrs, category="smart_home")
        if not isinstance(services, list):
            return None
        result = []
        for svc in services:
            domain = svc.get("domain", "")
            for name, info in svc.get("services", {}).items():
                result.append({
                    "domain": domain,
                    "service": name,
                    "name": info.get("name", name),
                    "description": info.get("description", "")[:100],
                })
        return result
    except (httpx.HTTPError, KeyError, ValueError):
        return None
