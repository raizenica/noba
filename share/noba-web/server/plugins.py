# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Formalized plugin system.

Plugins are Python scripts placed in ~/.config/noba/plugins/ (or the legacy
~/.config/noba-web/plugins/ directory).

Each plugin **must** export:
  - PLUGIN_NAME    (str)   -- human-readable name
  - PLUGIN_VERSION (str)   -- semver string, e.g. "1.0.0"
  - register(app, db)      -- called at load time; may add routes, cards, etc.

Each plugin **may** also export:
  - PLUGIN_ID          (str)  -- unique identifier (defaults to filename stem)
  - PLUGIN_ICON        (str)  -- FontAwesome class (default: "fa-puzzle-piece")
  - PLUGIN_DESCRIPTION (str)  -- short description for the UI
  - PLUGIN_INTERVAL    (int)  -- collection interval in seconds (default: 10)
  - REQUIRED_API_VERSION (int) -- minimum API version (default: 1)
  - collect()          -- returns dict of data for the dashboard card
  - render(data)       -- returns HTML string for the dashboard card body
  - setup()            -- called once at startup
  - teardown()         -- called on shutdown
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import threading
from pathlib import Path

from .config import PLUGIN_API_VERSION

logger = logging.getLogger("noba")


class PluginContext:
    """Limited context passed to new-style plugins instead of raw app + db.

    New plugins should declare ``register(ctx: PluginContext)`` and use this
    interface.  Legacy plugins with ``register(app, db)`` signatures continue
    to work unchanged — the manager calls them with the raw objects.
    """

    def __init__(self, app, db, plugin_id: str = "") -> None:
        self._app = app
        self._db = db
        self._plugin_id = plugin_id

    def add_route(self, path: str, endpoint, methods=None, **kwargs) -> None:
        """Register a new API route."""
        self._app.add_api_route(
            path, endpoint, methods=methods or ["GET"], **kwargs
        )

    def query(self, sql: str, params=None) -> list[dict]:
        """Execute a read-only DB query. Returns list of row dicts."""
        with self._db._read_lock:
            conn = self._db._get_read_conn()
            cur = conn.execute(sql, params or ())
            return [dict(r) for r in cur.fetchall()]

    def get_config(self) -> dict:
        """Return the plugin's current config with defaults filled in."""
        return _read_plugin_config(self._plugin_id) if self._plugin_id else {}

    def log(self, message: str, level: str = "info") -> None:
        """Log a message under the plugin namespace."""
        logging.getLogger("noba.plugin").log(
            getattr(logging, level.upper(), logging.INFO), message
        )

PLUGIN_DIR = Path(os.environ.get(
    "NOBA_PLUGIN_DIR",
    os.path.expanduser("~/.config/noba/plugins"),
))

# Bundled catalog plugins shipped with NOBA
BUNDLED_PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugins" / "catalog"

# Legacy directory -- checked as fallback
_LEGACY_PLUGIN_DIR = Path(os.path.expanduser("~/.config/noba-web/plugins"))

# File that tracks which plugins are disabled
_DISABLED_FILE = PLUGIN_DIR / ".disabled.json"

# Directory for per-plugin config files
_CONFIG_DIR = PLUGIN_DIR / "config"


def _read_disabled() -> set[str]:
    """Read the set of disabled plugin IDs from disk."""
    try:
        if _DISABLED_FILE.is_file():
            data = json.loads(_DISABLED_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return set(data)
    except Exception:
        pass
    return set()


def _write_disabled(disabled: set[str]) -> None:
    """Persist the set of disabled plugin IDs to disk."""
    try:
        _DISABLED_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DISABLED_FILE.write_text(
            json.dumps(sorted(disabled), indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error("Failed to write disabled plugins file: %s", e)


def _read_plugin_config(plugin_id: str) -> dict:
    """Read saved config for a plugin from disk."""
    path = _CONFIG_DIR / f"{plugin_id}.json"
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_plugin_config(plugin_id: str, config: dict) -> None:
    """Write config for a plugin to disk."""
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        path = _CONFIG_DIR / f"{plugin_id}.json"
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error("Failed to write config for plugin %s: %s", plugin_id, e)


def _validate_config(schema: dict, values: dict) -> tuple[dict, list[str]]:
    """Validate config values against a schema.

    Returns (validated_config, errors).  Fills in defaults for missing keys.
    """
    result = {}
    errors = []
    for key, field in schema.items():
        ftype = field.get("type", "string")
        default = field.get("default", "" if ftype == "string" else
                            0 if ftype == "number" else
                            False if ftype == "boolean" else [])
        value = values.get(key)

        # Use default if not provided
        if value is None:
            if field.get("required") and default in ("", 0, False, []):
                errors.append(f"{field.get('label', key)} is required")
            result[key] = default
            continue

        # Type coercion + validation
        if ftype == "string":
            result[key] = str(value)
        elif ftype == "number":
            try:
                result[key] = float(value)
                if "min" in field and result[key] < field["min"]:
                    errors.append(f"{field.get('label', key)} must be >= {field['min']}")
                if "max" in field and result[key] > field["max"]:
                    errors.append(f"{field.get('label', key)} must be <= {field['max']}")
            except (ValueError, TypeError):
                errors.append(f"{field.get('label', key)} must be a number")
        elif ftype == "boolean":
            result[key] = bool(value)
        elif ftype == "list":
            if isinstance(value, list):
                result[key] = [str(v) for v in value]
            else:
                errors.append(f"{field.get('label', key)} must be a list")
        else:
            result[key] = value

    return result, errors


class Plugin:
    """Wrapper around a loaded plugin module."""

    def __init__(self, mod, path: str, *, enabled: bool = True) -> None:
        self.mod = mod
        self.path = path
        self.id: str = getattr(mod, "PLUGIN_ID", Path(path).stem)
        self.name: str = getattr(mod, "PLUGIN_NAME", self.id)
        self.version: str = getattr(mod, "PLUGIN_VERSION", "0.0.0")
        self.icon: str = getattr(mod, "PLUGIN_ICON", "fa-puzzle-piece")
        self.description: str = getattr(mod, "PLUGIN_DESCRIPTION", "")
        self.interval: int = getattr(mod, "PLUGIN_INTERVAL", 10)
        self.config_schema: dict = getattr(mod, "PLUGIN_CONFIG_SCHEMA", {})
        self.enabled: bool = enabled
        self.workflow_node: dict | None     = getattr(mod, "WORKFLOW_NODE", None)
        self.workflow_node_run              = getattr(mod, "workflow_node_run", None)
        self.data: dict = {}
        self.html: str = ""
        self.error: str = ""

    def collect(self) -> None:
        if not self.enabled:
            return
        try:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError
            # Use a single-thread executor to run collect() with a timeout.
            # Timeout is clamped between 5s and the plugin's interval.
            timeout = max(5, self.interval)
            with ThreadPoolExecutor(max_workers=1) as executor:
                if hasattr(self.mod, "collect"):
                    future = executor.submit(self.mod.collect)
                    try:
                        self.data = future.result(timeout=timeout) or {}
                    except TimeoutError:
                        logger.error("Plugin %s collect timed out after %ds", self.id, timeout)
                        self.error = f"collect timed out after {timeout}s"
                        return
                if hasattr(self.mod, "render"):
                    future = executor.submit(self.mod.render, self.data)
                    try:
                        self.html = future.result(timeout=timeout)
                    except TimeoutError:
                        logger.error("Plugin %s render timed out after %ds", self.id, timeout)
                        self.error = f"render timed out after {timeout}s"
                        return
            self.error = ""
        except Exception as e:
            logger.error("Plugin %s collect error: %s", self.id, e)
            self.error = "Plugin data collection failed"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "data": self.data,
            "html": self.html,
            "error": self.error,
        }

    def get_config(self) -> dict:
        """Return current config, with defaults filled in from schema."""
        saved = _read_plugin_config(self.id)
        if not self.config_schema:
            return saved
        result = {}
        for key, field in self.config_schema.items():
            ftype = field.get("type", "string")
            default = field.get("default", "" if ftype == "string" else
                                0 if ftype == "number" else
                                False if ftype == "boolean" else [])
            result[key] = saved.get(key, default)
        return result

    def to_managed_dict(self) -> dict:
        """Extended dict for the plugin management UI."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "icon": self.icon,
            "description": self.description,
            "enabled": self.enabled,
            "error": self.error,
            "path": self.path,
            "has_config": bool(self.config_schema),
            "config_schema": self.config_schema if self.config_schema else None,
        }


class PluginManager:
    """Discovers, loads, and periodically collects data from plugins."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._plugins: list[Plugin] = []
        self._threads: list[threading.Thread] = []
        self._shutdown = threading.Event()
        self._app = None
        self._db = None

    def discover(self, app=None, db=None) -> None:
        """Scan plugin directories and load all valid plugins."""
        self._app = app
        self._db = db
        disabled = _read_disabled()

        dirs: list[Path] = []
        if PLUGIN_DIR.is_dir():
            dirs.append(PLUGIN_DIR)
        if _LEGACY_PLUGIN_DIR.is_dir() and _LEGACY_PLUGIN_DIR != PLUGIN_DIR:
            dirs.append(_LEGACY_PLUGIN_DIR)

        for plugin_dir in dirs:
            for f in sorted(plugin_dir.glob("*.py")):
                if f.name.startswith("_"):
                    continue
                self._load_plugin(f, disabled)

    def _load_plugin(self, f: Path, disabled: set[str]) -> None:
        """Load a single plugin file."""
        try:
            spec = importlib.util.spec_from_file_location(
                f"noba_plugin_{f.stem}", str(f),
            )
            if not spec or not spec.loader:
                return
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            required = getattr(mod, "REQUIRED_API_VERSION", 1)
            if required > PLUGIN_API_VERSION:
                logger.warning(
                    "Plugin %s requires API v%d but server has v%d -- skipping",
                    f.name, required, PLUGIN_API_VERSION,
                )
                return

            plugin_id = getattr(mod, "PLUGIN_ID", f.stem)
            enabled = plugin_id not in disabled

            plugin = Plugin(mod, str(f), enabled=enabled)

            # Call setup() if present
            if hasattr(mod, "setup"):
                mod.setup()

            # Call register() if present -- the formalized interface.
            # New-style plugins accept register(ctx: PluginContext).
            # Legacy plugins accept register(app, db) -- both are supported.
            if hasattr(mod, "register") and self._app is not None:
                try:
                    import inspect as _inspect  # noqa: PLC0415
                    sig = _inspect.signature(mod.register)
                    param_count = len(sig.parameters)
                    if param_count == 1:
                        # New-style: register(ctx)
                        mod.register(PluginContext(self._app, self._db, plugin_id))
                    else:
                        # Legacy: register(app, db)
                        mod.register(self._app, self._db)
                except Exception as e:
                    logger.error("Plugin %s register error: %s", plugin_id, e)
                    plugin.error = f"register failed: {e}"

            with self._lock:
                # Avoid duplicates on reload
                self._plugins = [
                    p for p in self._plugins if p.id != plugin.id
                ]
                self._plugins.append(plugin)

            logger.info("Loaded plugin: %s (%s) enabled=%s", plugin.id, f.name, enabled)
        except Exception as e:
            logger.error("Failed to load plugin %s: %s", f.name, e)

    def start(self) -> None:
        """Start background collection threads for each enabled plugin."""
        with self._lock:
            for plugin in self._plugins:
                if not plugin.enabled:
                    continue
                if any(t.name == f"plugin-{plugin.id}" and t.is_alive()
                       for t in self._threads):
                    continue
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
            if not plugin.enabled:
                continue
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
        """Return card data for all enabled plugins (used by collector)."""
        with self._lock:
            return [p.to_dict() for p in self._plugins if p.enabled]

    def get_managed(self) -> list[dict]:
        """Return management data for all plugins (admin UI)."""
        with self._lock:
            return [p.to_managed_dict() for p in self._plugins]

    def get_ids(self) -> list[str]:
        with self._lock:
            return [p.id for p in self._plugins]

    @property
    def count(self) -> int:
        with self._lock:
            return len([p for p in self._plugins if p.enabled])

    def enable_plugin(self, plugin_id: str) -> bool:
        """Enable a plugin by ID. Returns True if found."""
        with self._lock:
            for p in self._plugins:
                if p.id == plugin_id:
                    p.enabled = True
                    disabled = _read_disabled()
                    disabled.discard(plugin_id)
                    _write_disabled(disabled)
                    logger.info("Enabled plugin: %s", plugin_id)
                    return True
        return False

    def disable_plugin(self, plugin_id: str) -> bool:
        """Disable a plugin by ID. Returns True if found."""
        with self._lock:
            for p in self._plugins:
                if p.id == plugin_id:
                    p.enabled = False
                    disabled = _read_disabled()
                    disabled.add(plugin_id)
                    _write_disabled(disabled)
                    logger.info("Disabled plugin: %s", plugin_id)
                    return True
        return False

    def reload(self) -> None:
        """Stop all plugins, clear state, and re-discover."""
        # Stop existing collection threads
        self._shutdown.set()
        for plugin in self._plugins:
            if hasattr(plugin.mod, "teardown"):
                try:
                    plugin.mod.teardown()
                except Exception as e:
                    logger.error("Plugin %s teardown error: %s", plugin.id, e)

        # Reset state
        self._shutdown = threading.Event()
        with self._lock:
            self._plugins = []
        self._threads = []

        # Re-discover and start
        self.discover(app=self._app, db=self._db)
        self.start()
        logger.info("Plugins reloaded")

    def get_plugin_config(self, plugin_id: str) -> tuple[dict, dict]:
        """Return (config_values, config_schema) for a plugin."""
        with self._lock:
            for p in self._plugins:
                if p.id == plugin_id:
                    return p.get_config(), p.config_schema
        return {}, {}

    def set_plugin_config(self, plugin_id: str, values: dict) -> list[str]:
        """Validate and save config for a plugin. Returns list of errors."""
        with self._lock:
            for p in self._plugins:
                if p.id == plugin_id:
                    if not p.config_schema:
                        return ["Plugin has no configurable settings"]
                    validated, errors = _validate_config(p.config_schema, values)
                    if errors:
                        return errors
                    _write_plugin_config(plugin_id, validated)
                    return []
        return ["Plugin not found"]

    def get_bundled_catalog(self) -> list[dict]:
        """Return metadata for bundled catalog plugins."""
        if not BUNDLED_PLUGIN_DIR.is_dir():
            return []
        catalog = []
        for f in sorted(BUNDLED_PLUGIN_DIR.glob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"noba_catalog_{f.stem}", str(f),
                )
                if not spec or not spec.loader:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                catalog.append({
                    "id": getattr(mod, "PLUGIN_ID", f.stem),
                    "name": getattr(mod, "PLUGIN_NAME", f.stem),
                    "version": getattr(mod, "PLUGIN_VERSION", "0.0.0"),
                    "icon": getattr(mod, "PLUGIN_ICON", "fa-puzzle-piece"),
                    "description": getattr(mod, "PLUGIN_DESCRIPTION", ""),
                    "filename": f.name,
                    "bundled": True,
                })
            except Exception as e:
                logger.error("Failed to read bundled plugin %s: %s", f.name, e)
        return catalog

    def install_bundled(self, filename: str) -> bool:
        """Copy a bundled plugin to the user's plugin directory."""
        import re as _re  # noqa: PLC0415
        if not _re.match(r'^[a-zA-Z0-9_-]+\.py$', filename):
            return False
        src = BUNDLED_PLUGIN_DIR / filename
        if not src.is_file():
            return False
        try:
            PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
            dest = PLUGIN_DIR / filename
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            logger.info("Installed bundled plugin: %s", filename)
            return True
        except Exception as e:
            logger.error("Failed to install bundled plugin %s: %s", filename, e)
            return False

    def get_available(self, catalog_url: str = "") -> list[dict]:
        """Fetch available plugins from a remote catalog."""
        if not catalog_url:
            return []
        try:
            import httpx  # noqa: PLC0415
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
        import re as _re  # noqa: PLC0415
        if not _re.match(r'^[a-zA-Z0-9_-]+\.py$', filename):
            logger.warning("Plugin install rejected: invalid filename %r", filename)
            return False
        if not url.startswith("https://"):
            logger.warning("Plugin install rejected: non-HTTPS URL %r", url)
            return False
        try:
            import httpx  # noqa: PLC0415
            logger.info("Installing plugin %r from %s", filename, url)
            r = httpx.get(url, timeout=30)
            r.raise_for_status()
            dest = PLUGIN_DIR / filename
            PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
            dest.write_text(r.text, encoding="utf-8")
            logger.info("Installed plugin: %s from %s", filename, url)
            return True
        except Exception as e:
            logger.error("Plugin install failed: %s", e)
            return False


# Singleton
plugin_manager = PluginManager()
