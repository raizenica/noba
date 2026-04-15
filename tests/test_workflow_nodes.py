# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for plugin workflow node registration and execution bridge."""
from __future__ import annotations




def test_register_plugin_builder_adds_to_registry():
    import server.workflow_engine as we
    we._PLUGIN_BUILDERS.clear()
    fn = lambda cfg: None
    we.register_plugin_builder("my_plugin_type", fn)
    assert "my_plugin_type" in we._PLUGIN_BUILDERS
    assert we._PLUGIN_BUILDERS["my_plugin_type"] is fn
    we._PLUGIN_BUILDERS.clear()


def test_register_plugin_builder_skips_builtin_conflict(caplog):
    import server.workflow_engine as we
    import logging
    we._PLUGIN_BUILDERS.clear()
    fn = lambda cfg: None
    with caplog.at_level(logging.WARNING, logger="noba"):
        we.register_plugin_builder("service", fn)  # "service" is a builtin
    assert "service" not in we._PLUGIN_BUILDERS
    assert "conflicts with a built-in" in caplog.text
    we._PLUGIN_BUILDERS.clear()


def test_register_plugin_builder_warns_on_duplicate(caplog):
    import server.workflow_engine as we
    import logging
    we._PLUGIN_BUILDERS.clear()
    fn1 = lambda cfg: None
    fn2 = lambda cfg: None
    we.register_plugin_builder("my_type", fn1)
    with caplog.at_level(logging.WARNING, logger="noba"):
        we.register_plugin_builder("my_type", fn2)
    assert we._PLUGIN_BUILDERS["my_type"] is fn2  # last write wins
    assert "already registered" in caplog.text
    we._PLUGIN_BUILDERS.clear()


def test_register_plugin_builder_concurrent_writes() -> None:
    """register_plugin_builder must be safe to call from multiple threads."""
    import threading as _threading
    import server.workflow_engine as we
    we._PLUGIN_BUILDERS.clear()
    fns = {f"plugin_type_{i}": lambda: None for i in range(20)}
    threads = [
        _threading.Thread(target=we.register_plugin_builder, args=(k, v))
        for k, v in fns.items()
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(we._PLUGIN_BUILDERS) == 20
    for k in fns:
        assert k in we._PLUGIN_BUILDERS
    we._PLUGIN_BUILDERS.clear()


def test_plugin_reads_workflow_node_attrs(tmp_path):
    """Plugin.__init__ should pick up WORKFLOW_NODE and workflow_node_run."""
    import types
    from server.plugins import Plugin

    mod = types.ModuleType("test_wf_plugin")
    mod.PLUGIN_NAME = "WF Test"
    mod.PLUGIN_VERSION = "1.0.0"
    mod.WORKFLOW_NODE = {
        "type": "wf_test_action",
        "label": "WF Test Action",
        "icon": "fa-star",
        "description": "A test workflow node",
        "fields": [{"key": "msg", "type": "string", "label": "Message"}],
    }
    mod.workflow_node_run = lambda cfg: None

    plugin = Plugin(mod, "/fake/path.py", enabled=True)

    assert plugin.workflow_node == mod.WORKFLOW_NODE
    assert plugin.workflow_node_run is mod.workflow_node_run


def test_plugin_workflow_node_defaults_to_none(tmp_path):
    """Plugins without WORKFLOW_NODE have None for both attrs."""
    import types
    from server.plugins import Plugin

    mod = types.ModuleType("plain_plugin")
    mod.PLUGIN_NAME = "Plain"
    mod.PLUGIN_VERSION = "1.0.0"

    plugin = Plugin(mod, "/fake/plain.py", enabled=True)

    assert plugin.workflow_node is None
    assert plugin.workflow_node_run is None


def _make_plugin(type_key, label, has_run_fn=True):
    """Helper: create a minimal Plugin with a WORKFLOW_NODE declared."""
    import types
    from server.plugins import Plugin

    mod = types.ModuleType(f"plugin_{type_key}")
    mod.PLUGIN_NAME = label
    mod.PLUGIN_VERSION = "1.0.0"
    mod.WORKFLOW_NODE = {
        "type": type_key,
        "label": label,
        "icon": "fa-star",
        "description": f"{label} description",
        "fields": [{"key": "param", "type": "string", "label": "Param"}],
    }
    if has_run_fn:
        mod.workflow_node_run = lambda cfg: None
    return Plugin(mod, f"/fake/{type_key}.py", enabled=True)


def test_scan_registers_builders(monkeypatch):
    import server.workflow_engine as we
    import server.workflow_nodes as wn

    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()

    class FakePM:
        _plugins = [_make_plugin("slack_notify", "Slack Notify")]

    wn.scan(FakePM())

    assert "slack_notify" in we._PLUGIN_BUILDERS
    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()


def test_scan_skips_plugin_without_run_fn(caplog):
    import logging
    import server.workflow_engine as we
    import server.workflow_nodes as wn

    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()

    class FakePM:
        _plugins = [_make_plugin("no_fn_type", "No Fn", has_run_fn=False)]

    with caplog.at_level(logging.WARNING, logger="noba"):
        wn.scan(FakePM())

    assert "no_fn_type" not in we._PLUGIN_BUILDERS
    assert "no workflow_node_run" in caplog.text
    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()


def test_scan_skips_disabled_plugin():
    import server.workflow_engine as we
    import server.workflow_nodes as wn
    from server.plugins import Plugin
    import types

    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()

    mod = types.ModuleType("disabled_plugin")
    mod.PLUGIN_NAME = "Disabled"
    mod.PLUGIN_VERSION = "1.0.0"
    mod.WORKFLOW_NODE = {"type": "disabled_type", "label": "Disabled", "icon": "fa-ban",
                          "description": "", "fields": []}
    mod.workflow_node_run = lambda cfg: None
    plugin = Plugin(mod, "/fake/disabled.py", enabled=False)

    class FakePM:
        _plugins = [plugin]

    wn.scan(FakePM())

    assert "disabled_type" not in we._PLUGIN_BUILDERS
    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()


def test_get_node_descriptors_includes_builtins_and_plugins():
    import server.workflow_engine as we
    import server.workflow_nodes as wn

    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()

    class FakePM:
        _plugins = [_make_plugin("custom_node", "Custom Node")]

    wn.scan(FakePM())
    descriptors = wn.get_node_descriptors()

    types_found = [d["type"] for d in descriptors]
    assert "service" in types_found        # builtin
    assert "custom_node" in types_found    # plugin

    plugin_desc = next(d for d in descriptors if d["type"] == "custom_node")
    assert plugin_desc["category"] == "plugin"
    assert plugin_desc["label"] == "Custom Node"

    builtin_desc = next(d for d in descriptors if d["type"] == "service")
    assert builtin_desc["category"] == "builtin"

    we._PLUGIN_BUILDERS.clear()
    wn._plugin_descriptors.clear()


def test_workflow_nodes_endpoint_returns_descriptors(tmp_path, monkeypatch):
    """GET /api/workflow-nodes returns builtin + plugin descriptors."""
    import server.workflow_nodes as wn
    # Seed one plugin descriptor directly
    wn._plugin_descriptors = [{
        "type": "test_ep_node", "label": "EP Node", "icon": "fa-star",
        "description": "Endpoint test node", "category": "plugin", "fields": [],
    }]

    from fastapi.testclient import TestClient
    from server.app import app
    from server.deps import _get_auth

    app.dependency_overrides[_get_auth] = lambda: {"username": "admin", "role": "admin"}
    client = TestClient(app)
    resp = client.get("/api/workflow-nodes")
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    types = [d["type"] for d in data]
    assert "service" in types        # builtin
    assert "test_ep_node" in types   # plugin
    wn._plugin_descriptors.clear()
