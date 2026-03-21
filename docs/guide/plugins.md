# Plugins

The Plugin system allows extending NOBA with custom integrations, dashboard cards, API routes, and automation types without modifying the core codebase.

## Plugin Catalogue

Navigate to **Settings → Plugins** to browse available plugins.

Each plugin entry shows:
- Name and description
- Author and version
- Required permissions
- Install / Uninstall button

## Installing a Plugin

### From the Catalogue

1. Open **Settings → Plugins → Catalogue**.
2. Find the plugin and click **Install**.
3. NOBA downloads and installs it, then prompts for any required configuration.
4. Restart is not required — plugins are hot-loaded.

### Manual Install

Place the plugin directory in `~/.config/noba/plugins/<plugin-name>/` (bare-metal) or `/app/config/plugins/<plugin-name>/` (Docker).

A valid plugin directory contains:
```
plugin.yaml       # Manifest
main.py           # Python entry point
static/           # Optional: frontend assets (JS, CSS)
```

## Plugin Manifest

```yaml
name: my-plugin
version: 1.0.0
author: you
description: Does something useful
permissions:
  - read_stats
  - write_automations
  - agent_commands
entry: main.py
routes:
  - prefix: /api/plugins/my-plugin
frontend:
  card: static/card.js
  settings: static/settings.js
```

## PluginContext API

Plugins receive a `PluginContext` object that provides safe access to NOBA internals:

```python
from noba.plugins import PluginContext

def register(ctx: PluginContext):
    # Register an API route
    @ctx.router.get("/status")
    async def status():
        return {"ok": True}

    # Read current stats snapshot
    stats = ctx.stats.current()

    # Send a notification
    ctx.notifications.send("telegram", "Plugin event fired")

    # Register a custom automation type
    @ctx.automations.register("my_action")
    async def my_action(params: dict):
        # ... do work
        return {"result": "done"}

    # Access the SQLite database (read-only)
    rows = ctx.db.query("SELECT * FROM metrics LIMIT 10")
```

### Available Context Methods

| Method | Description |
|--------|-------------|
| `ctx.router` | FastAPI router — add GET/POST routes |
| `ctx.stats.current()` | Latest stats snapshot |
| `ctx.stats.history(metric, hours)` | Historical data |
| `ctx.notifications.send(channel, msg)` | Send a notification |
| `ctx.automations.register(type)` | Register a custom automation type |
| `ctx.automations.trigger(id)` | Trigger an existing automation |
| `ctx.db.query(sql, params)` | Read-only database query |
| `ctx.config.get(key)` | Read a config value |
| `ctx.config.set(key, value)` | Write a config value |
| `ctx.agents.list()` | List registered agents |
| `ctx.agents.send_command(agent_id, cmd)` | Send a command to an agent |

## Plugin Permissions

Plugins declare required permissions in the manifest. Users are shown the permission list at install time.

| Permission | Grants |
|-----------|--------|
| `read_stats` | Access to stats and history |
| `write_automations` | Create/trigger automations |
| `agent_commands` | Send commands to agents |
| `read_config` | Read configuration values |
| `write_config` | Write configuration values |
| `db_read` | Raw database read access |
| `notifications` | Send notifications |

## Built-in Plugins

| Plugin | Description |
|--------|-------------|
| `grafana-push` | Push metrics to a Grafana Loki/Prometheus endpoint |
| `ntfy` | Send notifications via ntfy.sh |
| `healthchecks-io` | Report heartbeats to healthchecks.io |
| `wakeonlan` | Add Wake-on-LAN buttons to the dashboard |
| `speedtest` | Run periodic internet speed tests |
