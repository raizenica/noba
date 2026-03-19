"""Noba – Home Assistant event bridge and service proxy."""
from __future__ import annotations

import json
import logging
import threading

import httpx

logger = logging.getLogger("noba")


class HAEventBridge:
    """Subscribe to Home Assistant event stream and trigger automations on matching events."""

    def __init__(self) -> None:
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._triggers: list[dict] = []

    def start(self, hass_url: str, hass_token: str, triggers: list[dict]) -> None:
        """Start listening for HA events.

        triggers: list of {"event_type": str, "automation_id": str}
        """
        if not hass_url or not hass_token or not triggers:
            return
        self._triggers = triggers
        self._shutdown.clear()
        self._thread = threading.Thread(
            target=self._listen, args=(hass_url, hass_token),
            daemon=True, name="ha-event-bridge",
        )
        self._thread.start()
        logger.info("HA event bridge started with %d triggers", len(triggers))

    def stop(self) -> None:
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _listen(self, hass_url: str, hass_token: str) -> None:
        base = hass_url.rstrip("/")
        headers = {"Authorization": f"Bearer {hass_token}"}
        while not self._shutdown.is_set():
            try:
                with httpx.stream("GET", f"{base}/api/stream",
                                  headers=headers, timeout=None) as response:
                    for line in response.iter_lines():
                        if self._shutdown.is_set():
                            break
                        if not line.startswith("data:"):
                            continue
                        try:
                            data = json.loads(line[5:].strip())
                            event_type = data.get("event_type", "")
                            self._handle_event(event_type, data)
                        except (json.JSONDecodeError, AttributeError):
                            continue
            except Exception as e:
                logger.debug("HA event bridge connection error: %s", e)
                if not self._shutdown.is_set():
                    self._shutdown.wait(30)  # Reconnect delay

    def _handle_event(self, event_type: str, data: dict) -> None:
        for trigger in self._triggers:
            if trigger.get("event_type") == event_type:
                auto_id = trigger.get("automation_id", "")
                if auto_id:
                    self._trigger_automation(auto_id, event_type)

    def _trigger_automation(self, auto_id: str, event_type: str) -> None:
        try:
            from .db import db
            from .runner import job_runner
            from .app import _AUTO_BUILDERS, _run_workflow, _run_parallel_workflow

            auto = db.get_automation(auto_id)
            if not auto:
                return
            if auto["type"] == "workflow":
                steps = auto["config"].get("steps", [])
                if steps:
                    mode = auto["config"].get("mode", "sequential")
                    if mode == "parallel":
                        _run_parallel_workflow(auto["id"], steps, f"ha-event:{event_type}")
                    else:
                        _run_workflow(auto["id"], steps, f"ha-event:{event_type}")
                return
            builder = _AUTO_BUILDERS.get(auto["type"])
            if not builder:
                return
            config = auto["config"]

            def make_process(_run_id: int):
                return builder(config)

            job_runner.submit(
                make_process, automation_id=auto_id,
                trigger=f"ha-event:{event_type}",
                triggered_by="ha-event-bridge",
            )
            logger.info("HA event '%s' triggered automation '%s'", event_type, auto["name"])
        except Exception as e:
            logger.error("HA event trigger failed: %s", e)


def call_hass_service(hass_url: str, hass_token: str,
                      domain: str, service: str,
                      entity_id: str = "", data: dict | None = None) -> dict:
    """Call a Home Assistant service."""
    base = hass_url.rstrip("/")
    payload: dict = data or {}
    if entity_id:
        payload["entity_id"] = entity_id
    try:
        r = httpx.post(
            f"{base}/api/services/{domain}/{service}",
            json=payload,
            headers={"Authorization": f"Bearer {hass_token}"},
            timeout=10,
        )
        r.raise_for_status()
        return {"success": True, "status_code": r.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}


# Singleton
ha_bridge = HAEventBridge()
