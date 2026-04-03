# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""MQTT Listener -- Subscribe to MQTT topics and display live values.

Connects to an MQTT broker and subscribes to configurable topics.
Collected values are shown on a dashboard card with optional sparklines.
"""
from __future__ import annotations

import json
import threading
import time

PLUGIN_ID = "mqtt_listener"
PLUGIN_NAME = "MQTT Listener"
PLUGIN_VERSION = "1.0.0"
PLUGIN_ICON = "fa-broadcast-tower"
PLUGIN_DESCRIPTION = "Subscribe to MQTT topics and display live sensor values on the dashboard."
PLUGIN_INTERVAL = 5

PLUGIN_CONFIG_SCHEMA = {
    "broker_url": {
        "type": "string",
        "label": "Broker URL",
        "default": "localhost",
        "placeholder": "mqtt.example.com",
        "required": True,
    },
    "broker_port": {
        "type": "number",
        "label": "Broker Port",
        "default": 1883,
        "min": 1,
        "max": 65535,
    },
    "username": {
        "type": "string",
        "label": "Username",
        "default": "",
        "placeholder": "Optional",
    },
    "password": {
        "type": "string",
        "label": "Password",
        "default": "",
        "secret": True,
    },
    "topics": {
        "type": "list",
        "label": "Topics to subscribe",
        "default": ["home/sensors/#"],
    },
    "show_sparkline": {
        "type": "boolean",
        "label": "Show sparkline charts",
        "default": True,
    },
    "max_history": {
        "type": "number",
        "label": "Max history points per topic",
        "default": 50,
        "min": 10,
        "max": 500,
    },
}

_lock = threading.Lock()
_latest: dict[str, dict] = {}
_history: dict[str, list] = {}
_client = None
_ctx = None


def _on_message(topic: str, payload: bytes) -> None:
    """Handle incoming MQTT message."""
    try:
        value = payload.decode("utf-8", errors="replace")
        # Try to parse as JSON for structured payloads
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass

        with _lock:
            cfg = _ctx.get_config() if _ctx else {}
            max_hist = int(cfg.get("max_history", 50))
            _latest[topic] = {"value": value, "ts": time.time()}
            if topic not in _history:
                _history[topic] = []
            # Store numeric values for sparkline
            num_val = None
            if isinstance(value, (int, float)):
                num_val = value
            elif isinstance(value, str):
                try:
                    num_val = float(value)
                except ValueError:
                    pass
            if num_val is not None:
                _history[topic].append(num_val)
                if len(_history[topic]) > max_hist:
                    _history[topic] = _history[topic][-max_hist:]
    except Exception:
        pass


def _mqtt_thread(cfg: dict) -> None:
    """Background thread that connects to MQTT and listens."""
    try:
        import paho.mqtt.client as mqtt  # noqa: PLC0415
    except ImportError:
        with _lock:
            _latest["_error"] = {
                "value": "paho-mqtt not installed. Run: pip install paho-mqtt",
                "ts": time.time(),
            }
        return

    broker = cfg.get("broker_url", "localhost")
    port = int(cfg.get("broker_port", 1883))
    topics = cfg.get("topics", ["home/sensors/#"])
    username = cfg.get("username", "")
    password = cfg.get("password", "")

    client = mqtt.Client(client_id="noba-mqtt-listener", protocol=mqtt.MQTTv311)
    if username:
        client.username_pw_set(username, password)

    def on_connect(_c, _ud, _flags, rc):
        if rc == 0:
            for t in topics:
                client.subscribe(t)

    def on_message(_c, _ud, msg):
        _on_message(msg.topic, msg.payload)

    client.on_connect = on_connect
    client.on_message = on_message

    global _client  # noqa: PLW0603
    _client = client

    try:
        client.connect(broker, port, keepalive=60)
        client.loop_forever()
    except Exception as e:
        with _lock:
            _latest["_error"] = {"value": str(e), "ts": time.time()}


def register(ctx) -> None:
    """Start MQTT listener in background thread."""
    global _ctx  # noqa: PLW0603
    _ctx = ctx
    cfg = ctx.get_config()
    if not cfg.get("broker_url"):
        return
    t = threading.Thread(target=_mqtt_thread, args=(cfg,), daemon=True, name="mqtt-listener")
    t.start()


def collect() -> dict:
    """Return latest values for all subscribed topics."""
    with _lock:
        return {
            "topics": {
                k: v for k, v in _latest.items() if not k.startswith("_")
            },
            "history": dict(_history) if _history else {},
            "error": _latest.get("_error", {}).get("value", ""),
            "topic_count": len([k for k in _latest if not k.startswith("_")]),
        }


def render(data: dict) -> str:
    """Render dashboard card HTML."""
    error = data.get("error", "")
    if error:
        return f'<div style="color:var(--danger);font-size:.8rem">{error}</div>'
    topics = data.get("topics", {})
    if not topics:
        return '<div style="color:var(--text-muted);font-size:.8rem">No messages received yet. Check broker config.</div>'
    rows = []
    for topic, info in sorted(topics.items()):
        val = info.get("value", "")
        if isinstance(val, dict):
            val = json.dumps(val, indent=1)
        display = str(val)[:60]
        rows.append(
            f'<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:.78rem">'
            f'<span style="color:var(--text-muted);overflow:hidden;text-overflow:ellipsis">{topic}</span>'
            f'<span style="font-weight:600;margin-left:.5rem">{display}</span></div>'
        )
    return "\n".join(rows)


def teardown() -> None:
    """Disconnect MQTT client."""
    global _client  # noqa: PLW0603
    if _client:
        try:
            _client.disconnect()
        except Exception:
            pass
        _client = None


# ── Workflow node declaration ─────────────────────────────────────────────

WORKFLOW_NODE = {
    "type": "mqtt_publish",
    "label": "MQTT Publish",
    "icon": "fa-broadcast-tower",
    "description": "Publish a message to an MQTT topic via the configured broker",
    "fields": [
        {"key": "topic",   "type": "string",  "label": "Topic",   "required": True,  "default": "noba/events"},
        {"key": "payload", "type": "string",  "label": "Payload", "required": False, "default": "triggered"},
        {"key": "qos",     "type": "select",  "label": "QoS",     "options": ["0", "1", "2"], "default": "0"},
        {"key": "retain",  "type": "boolean", "label": "Retain",  "default": False},
    ],
}


def workflow_node_run(config: dict) -> None:
    """Publish an MQTT message. Requires paho-mqtt to be installed."""
    try:
        import paho.mqtt.publish as publish  # type: ignore
    except ImportError:
        raise RuntimeError("paho-mqtt is not installed. Run: pip install paho-mqtt")

    # In a real plugin use ctx.get_config(); here we fall back to environment vars
    import os
    broker = os.environ.get("MQTT_BROKER", "localhost")
    port   = int(os.environ.get("MQTT_PORT", "1883"))

    publish.single(
        topic    = config.get("topic",   "noba/events"),
        payload  = config.get("payload", "triggered"),
        qos      = int(config.get("qos", 0)),
        retain   = bool(config.get("retain", False)),
        hostname = broker,
        port     = port,
    )
