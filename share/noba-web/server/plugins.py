"""Noba – Lightweight plugin/widget system.

Plugins are Python scripts placed in ~/.config/noba-web/plugins/.
Each plugin is a .py file that defines:
  - PLUGIN_ID   (str)   — unique card identifier
  - PLUGIN_NAME (str)   — display name shown in card header
  - PLUGIN_ICON (str)   — FontAwesome class, e.g. "fa-rocket"
  - collect()           — returns dict of data for the card
  - render()            — returns HTML string for the card body

Optional:
  - PLUGIN_INTERVAL (int) — collection interval in seconds (default: 10)
  - REQUIRED_API_VERSION (int) — minimum API version required (default: 1)
  - setup()              — called once at startup
  - teardown()           — called on shutdown
"""
from __future__ import annotations

import importlib.util
import logging
import os
import threading
from pathlib import Path

from .config import PLUGIN_API_VERSION

logger = logging.getLogger("noba")

PLUGIN_DIR = Path(os.environ.get(
    "NOBA_PLUGIN_DIR",
    os.path.expanduser("~/.config/noba-web/plugins"),
))


class Plugin:
    """Wrapper around a loaded plugin module."""

    def __init__(self, mod, path: str) -> None:
        self.mod = mod
        self.path = path
        self.id: str = getattr(mod, "PLUGIN_ID", Path(path).stem)
        self.name: str = getattr(mod, "PLUGIN_NAME", self.id)
        self.icon: str = getattr(mod, "PLUGIN_ICON", "fa-puzzle-piece")
        self.interval: int = getattr(mod, "PLUGIN_INTERVAL", 10)
        self.data: dict = {}
        self.html: str = ""
        self.error: str = ""

    def collect(self) -> None:
        try:
            if hasattr(self.mod, "collect"):
                self.data = self.mod.collect() or {}
            if hasattr(self.mod, "render"):
                self.html = self.mod.render(self.data)
            self.error = ""
        except Exception as e:
            logger.error("Plugin %s collect error: %s", self.id, e)
            self.error = str(e)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "data": self.data,
            "html": self.html,
            "error": self.error,
        }


class PluginManager:
    """Discovers, loads, and periodically collects data from plugins."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._plugins: list[Plugin] = []
        self._threads: list[threading.Thread] = []
        self._shutdown = threading.Event()

    def discover(self) -> None:
        if not PLUGIN_DIR.is_dir():
            return
        for f in sorted(PLUGIN_DIR.glob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"noba_plugin_{f.stem}", str(f))
                if not spec or not spec.loader:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                required = getattr(mod, "REQUIRED_API_VERSION", 1)
                if required > PLUGIN_API_VERSION:
                    logger.warning("Plugin %s requires API v%d but server has v%d — skipping",
                                   f.name, required, PLUGIN_API_VERSION)
                    continue
                plugin = Plugin(mod, str(f))
                if hasattr(mod, "setup"):
                    mod.setup()
                with self._lock:
                    self._plugins.append(plugin)
                logger.info("Loaded plugin: %s (%s)", plugin.id, f.name)
            except Exception as e:
                logger.error("Failed to load plugin %s: %s", f.name, e)

    def start(self) -> None:
        """Start background collection threads for each plugin."""
        for plugin in self._plugins:
            t = threading.Thread(
                target=self._collect_loop,
                args=(plugin,),
                daemon=True,
                name=f"plugin-{plugin.id}",
            )
            t.start()
            self._threads.append(t)

    def _collect_loop(self, plugin: Plugin) -> None:
        plugin.collect()  # initial collection
        while not self._shutdown.wait(plugin.interval):
            plugin.collect()

    def stop(self) -> None:
        self._shutdown.set()
        for plugin in self._plugins:
            if hasattr(plugin.mod, "teardown"):
                try:
                    plugin.mod.teardown()
                except Exception as e:
                    logger.error("Plugin %s teardown error: %s", plugin.id, e)

    def get_all(self) -> list[dict]:
        with self._lock:
            return [p.to_dict() for p in self._plugins]

    def get_ids(self) -> list[str]:
        with self._lock:
            return [p.id for p in self._plugins]

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._plugins)

    def get_available(self, catalog_url: str = "") -> list[dict]:
        """Fetch available plugins from a remote catalog."""
        if not catalog_url:
            return []
        try:
            import httpx
            r = httpx.get(catalog_url, timeout=10)
            r.raise_for_status()
            plugins = r.json()
            if isinstance(plugins, list):
                return plugins
        except Exception as e:
            logger.error("Plugin catalog fetch failed: %s", e)
        return []

    def install_plugin(self, url: str, filename: str) -> bool:
        """Download a plugin file from URL to the plugin directory."""
        import re as _re
        if not _re.match(r'^[a-zA-Z0-9_-]+\.py$', filename):
            return False
        try:
            import httpx
            r = httpx.get(url, timeout=30)
            r.raise_for_status()
            dest = PLUGIN_DIR / filename
            PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
            dest.write_text(r.text, encoding="utf-8")
            logger.info("Installed plugin: %s", filename)
            return True
        except Exception as e:
            logger.error("Plugin install failed: %s", e)
            return False


# Singleton
plugin_manager = PluginManager()
