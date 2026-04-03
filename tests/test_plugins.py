# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the formalized plugin system (plugins.py)."""
from __future__ import annotations

import os
import textwrap

import pytest

from server.plugins import Plugin, PluginManager, _read_disabled


@pytest.fixture()
def plugin_dir(tmp_path):
    """Create a temporary plugin directory and point NOBA_PLUGIN_DIR to it."""
    d = tmp_path / "plugins"
    d.mkdir()
    os.environ["NOBA_PLUGIN_DIR"] = str(d)
    # Patch module-level PLUGIN_DIR and _DISABLED_FILE
    import server.plugins as pm
    pm.PLUGIN_DIR = d
    pm._DISABLED_FILE = d / ".disabled.json"
    yield d
    os.environ.pop("NOBA_PLUGIN_DIR", None)


@pytest.fixture()
def sample_plugin(plugin_dir):
    """Write a minimal valid plugin file."""
    code = textwrap.dedent("""\
        PLUGIN_NAME = "Test Plugin"
        PLUGIN_VERSION = "1.2.3"
        PLUGIN_ID = "test_plug"
        PLUGIN_ICON = "fa-flask"
        PLUGIN_DESCRIPTION = "A test plugin"

        def register(app, db):
            pass

        def collect():
            return {"value": 42}

        def render(data):
            return "<span>42</span>"
    """)
    p = plugin_dir / "test_plug.py"
    p.write_text(code)
    return p


def test_plugin_wrapper(sample_plugin):
    """Plugin class wraps a module correctly."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("test_mod", str(sample_plugin))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = Plugin(mod, str(sample_plugin), enabled=True)
    assert p.id == "test_plug"
    assert p.name == "Test Plugin"
    assert p.version == "1.2.3"
    assert p.icon == "fa-flask"
    assert p.description == "A test plugin"
    assert p.enabled is True


def test_plugin_collect(sample_plugin):
    """Plugin.collect() calls module collect + render."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("test_mod", str(sample_plugin))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = Plugin(mod, str(sample_plugin))
    p.collect()
    assert p.data == {"value": 42}
    assert p.html == "<span>42</span>"
    assert p.error == ""


def test_plugin_collect_disabled(sample_plugin):
    """Plugin.collect() is a no-op when disabled."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("test_mod", str(sample_plugin))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = Plugin(mod, str(sample_plugin), enabled=False)
    p.collect()
    assert p.data == {}


def test_plugin_to_dict(sample_plugin):
    """to_dict returns card data."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("test_mod", str(sample_plugin))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = Plugin(mod, str(sample_plugin))
    d = p.to_dict()
    assert d["id"] == "test_plug"
    assert d["name"] == "Test Plugin"


def test_plugin_to_managed_dict(sample_plugin):
    """to_managed_dict returns admin UI data."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("test_mod", str(sample_plugin))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = Plugin(mod, str(sample_plugin))
    d = p.to_managed_dict()
    assert d["version"] == "1.2.3"
    assert d["description"] == "A test plugin"
    assert d["enabled"] is True


def test_manager_discover(plugin_dir, sample_plugin):
    """PluginManager.discover() finds and loads plugins."""
    mgr = PluginManager()
    mgr.discover()
    assert len(mgr.get_ids()) == 1
    assert "test_plug" in mgr.get_ids()


def test_manager_discover_skips_underscore(plugin_dir):
    """Plugins starting with _ are skipped."""
    (plugin_dir / "_hidden.py").write_text("PLUGIN_NAME='hidden'\nPLUGIN_VERSION='1.0.0'\ndef register(a,b): pass\n")
    mgr = PluginManager()
    mgr.discover()
    assert len(mgr.get_ids()) == 0


def test_manager_get_all_only_enabled(plugin_dir, sample_plugin):
    """get_all returns only enabled plugins."""
    mgr = PluginManager()
    mgr.discover()
    assert len(mgr.get_all()) == 1
    mgr.disable_plugin("test_plug")
    assert len(mgr.get_all()) == 0


def test_manager_get_managed(plugin_dir, sample_plugin):
    """get_managed returns all plugins regardless of enabled state."""
    mgr = PluginManager()
    mgr.discover()
    mgr.disable_plugin("test_plug")
    managed = mgr.get_managed()
    assert len(managed) == 1
    assert managed[0]["enabled"] is False


def test_manager_enable_disable(plugin_dir, sample_plugin):
    """Enable/disable toggles plugin state and persists to disk."""
    mgr = PluginManager()
    mgr.discover()

    assert mgr.disable_plugin("test_plug") is True
    assert mgr.count == 0

    assert mgr.enable_plugin("test_plug") is True
    assert mgr.count == 1

    # Unknown plugin returns False
    assert mgr.enable_plugin("nonexistent") is False
    assert mgr.disable_plugin("nonexistent") is False


def test_disabled_file_persistence(plugin_dir, sample_plugin):
    """Disabled state is written to .disabled.json."""
    mgr = PluginManager()
    mgr.discover()
    mgr.disable_plugin("test_plug")

    disabled = _read_disabled()
    assert "test_plug" in disabled

    mgr.enable_plugin("test_plug")
    disabled = _read_disabled()
    assert "test_plug" not in disabled


def test_manager_reload(plugin_dir, sample_plugin):
    """reload() re-discovers plugins."""
    mgr = PluginManager()
    mgr.discover()
    assert mgr.count == 1

    # Add a second plugin
    code = textwrap.dedent("""\
        PLUGIN_NAME = "Second"
        PLUGIN_VERSION = "0.1.0"
        def register(app, db): pass
    """)
    (plugin_dir / "second.py").write_text(code)

    mgr.reload()
    assert len(mgr.get_ids()) == 2


def test_manager_count_only_enabled(plugin_dir, sample_plugin):
    """count property only counts enabled plugins."""
    mgr = PluginManager()
    mgr.discover()
    assert mgr.count == 1
    mgr.disable_plugin("test_plug")
    assert mgr.count == 0
