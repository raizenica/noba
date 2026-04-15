# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Plugin workflow node bridge.

Scans loaded plugins for ``WORKFLOW_NODE`` declarations and registers their
builders into the workflow engine.  Also exposes a descriptor list for the
frontend palette / config UI.
"""
from __future__ import annotations

import logging

from . import workflow_engine

logger = logging.getLogger("noba")

# ── Built-in action type descriptors (metadata only — execution in workflow_engine) ──

_BUILTIN_DESCRIPTORS: list[dict] = [
    {"type": "service",       "label": "Service",      "icon": "fa-cog",
     "description": "Start/stop/restart a systemd service",   "category": "builtin", "fields": []},
    {"type": "script",        "label": "Script",       "icon": "fa-terminal",
     "description": "Run a built-in or custom script",        "category": "builtin", "fields": []},
    {"type": "webhook",       "label": "Webhook",      "icon": "fa-link",
     "description": "Fire an outbound HTTP webhook",           "category": "builtin", "fields": []},
    {"type": "http",          "label": "HTTP",         "icon": "fa-globe",
     "description": "Generic HTTP request with auth support",  "category": "builtin", "fields": []},
    {"type": "agent_command", "label": "Agent Cmd",    "icon": "fa-satellite-dish",
     "description": "Run a command on a remote agent",         "category": "builtin", "fields": []},
    {"type": "remediation",   "label": "Remediation",  "icon": "fa-medkit",
     "description": "Execute a healing/remediation action",    "category": "builtin", "fields": []},
]

_plugin_descriptors: list[dict] = []


def scan(plugin_manager) -> None:
    """Scan all enabled plugins and register workflow node builders.

    Called once from ``app.py`` after plugins are loaded.
    Safe to call multiple times (re-scans on each call).
    """
    global _plugin_descriptors
    _plugin_descriptors = []

    for plugin in plugin_manager._plugins:
        if not plugin.enabled:
            continue
        node_meta: dict | None = plugin.workflow_node
        node_fn = plugin.workflow_node_run

        if node_meta is None:
            continue

        if node_fn is None:
            logger.warning(
                "Plugin '%s' declares WORKFLOW_NODE but has no workflow_node_run — skipping",
                plugin.id,
            )
            continue

        type_key: str = node_meta.get("type", "")
        if not type_key:
            logger.warning("Plugin '%s' WORKFLOW_NODE missing 'type' key — skipping", plugin.id)
            continue

        # Wrap the synchronous run function in the builder contract.
        # Built-in builders return subprocess.Popen | None; plugins return None.
        def _make_builder(fn):
            def _builder(config: dict):
                fn(config)
                return None
            return _builder

        workflow_engine.register_plugin_builder(type_key, _make_builder(node_fn))

        _plugin_descriptors.append({
            "type":        type_key,
            "label":       node_meta.get("label", type_key),
            "icon":        node_meta.get("icon", "fa-puzzle-piece"),
            "description": node_meta.get("description", ""),
            "category":    "plugin",
            "fields":      node_meta.get("fields", []),
        })
        logger.info("Registered plugin workflow node: %s (%s)", node_meta.get("label", type_key), type_key)


def get_node_descriptors() -> list[dict]:
    """Return all workflow node descriptors: built-in types first, then plugins."""
    return _BUILTIN_DESCRIPTORS + _plugin_descriptors
