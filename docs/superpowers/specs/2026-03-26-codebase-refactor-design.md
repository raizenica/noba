# NOBA Codebase Refactor Design

**Date:** 2026-03-26
**Branch:** `refactor/codebase-split`
**Status:** Approved for implementation

## Overview

NOBA has grown substantially across several major feature rounds. This sprint addresses
seven concrete structural problems: one god-class database facade, one mixed-concern
integration file, two oversized frontend components, one oversized automation component,
one oversized workflow builder component, a cross-cutting error handling duplication
pattern, and a monolithic agent file constrained by its single-file distribution model.

No new features are added. External APIs, caller signatures, and WebSocket protocols
are unchanged unless explicitly noted.

---

## Target 1: `db/core.py` — Mixin co-location

### Problem

`db/core.py` is 1,681 lines split across three concerns:
- ~220 lines: import block re-importing from 22 already-split domain modules
- ~570 lines: `_init_schema()` — raw DDL SQL for every table in one method, including
  three inline `ALTER TABLE` migration blocks for additive column migrations
- ~900 lines: 184 delegation wrapper methods, each forwarding to a domain function

The domain logic is already correctly split. The bulk comes from centralised DDL
and mechanical boilerplate wrappers.

### Design

**DDL extraction:** Each of the 22 domain modules that owns tables gains a
`def init_schema(conn: sqlite3.Connection) -> None` function at the bottom of the
file containing the `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`
statements for its tables. The `executescript()` call is used inside each function.

`db/migrations.py` is not given an `init_schema` — it manages schema migrations
separately and is excluded from the mixin plan.

`db/network.py` already has its table DDL but has no wrapper methods in the current
`Database` class (it is not imported in `core.py`). It gets `init_schema()` only;
no `_NetworkMixin` is created. Wrapping `network.py` functions is out of scope for
this refactor.

**Inline ALTER TABLE migrations:** The three `ALTER TABLE` blocks currently in
`_init_schema` (adding `assigned_to` to `status_incidents`, `workflow_context` to
`approval_queue`, `verify_ssl`/`ca_bundle` to `integration_instances`, and audit
trail columns) **remain in `DatabaseBase._init_schema`**, executed after all
`mod.init_schema()` calls. They are idempotent (swallow `OperationalError` on
duplicate column) and must not be lost.

```python
def _run_alter_migrations(conn: sqlite3.Connection) -> None:
    """Idempotent additive column migrations. Swallows OperationalError
    ('duplicate column name') so they are safe to run on every startup."""
    migrations = [
        "ALTER TABLE status_incidents ADD COLUMN assigned_to TEXT",
        "ALTER TABLE approval_queue ADD COLUMN workflow_context TEXT",
        "ALTER TABLE integration_instances ADD COLUMN verify_ssl INTEGER DEFAULT 1",
        "ALTER TABLE integration_instances ADD COLUMN ca_bundle TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN risk_level TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN snapshot_id INTEGER",
        "ALTER TABLE heal_ledger ADD COLUMN rollback_status TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN dependency_root TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN suppressed_by TEXT",
        "ALTER TABLE heal_ledger ADD COLUMN maintenance_window_id INTEGER",
        "ALTER TABLE heal_ledger ADD COLUMN instance_id TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists

def _init_schema(self):
    with self._lock:
        conn = self._get_conn()
        for mod in _SCHEMA_MODULES:
            mod.init_schema(conn)
        # Inline additive migrations (idempotent ALTER TABLE blocks)
        _run_alter_migrations(conn)
        conn.commit()
```

**`_SCHEMA_MODULES`** is a module-level list defined explicitly in `core.py`.
`automations.py` owns the DDL for both the `automations`/`job_runs` tables and the
`approval_queue`/`workflow_approval_context` tables — there is no separate `approvals.py`
module. Both groups of wrapper methods (`_AutomationsMixin` and `_ApprovalsMixin`)
are therefore defined at the bottom of `automations.py`.

```python
from . import (
    metrics, audit, automations, alerts, api_keys, tokens,
    notifications, user_dashboards, user_preferences, agents,
    endpoints, dashboards, status_page, security, dependencies,
    baselines, network, webhooks, backup_verify, healing,
    integrations, linked_providers,
)

# Both lists must be kept in sync — _SCHEMA_MODULES immediately follows the imports.
_SCHEMA_MODULES = [
    metrics, audit, automations, alerts, api_keys, tokens,
    notifications, user_dashboards, user_preferences, agents,
    endpoints, dashboards, status_page, security, dependencies,
    baselines, network, webhooks, backup_verify, healing,
    integrations, linked_providers,
]
# 22 modules: all own tables, including network (DDL only, no mixin).
# automations covers approval_queue DDL (workflow_context is a column, not a table).
```

Order follows FK dependencies: `integrations` before `healing` (heal_snapshots
references integration_instances); `status_page` before nothing (self-contained);
`automations` before nothing. `CREATE TABLE IF NOT EXISTS` with FKs does not fail
at DDL time even with forward references, but explicit ordering documents intent.

**Wrapper mixins:** Each of the 21 modules that has wrapper methods in `Database`
gains a `class _XMixin` at the bottom of the file containing those wrappers.
`rollup_to_1m`, `rollup_to_1h`, `prune_rollups`, and `catchup_rollups` move into
`_MetricsMixin` (not `DatabaseBase`), consistent with the architecture goal of
keeping `DatabaseBase` to connection management only.

Example pattern:

```python
# db/metrics.py (bottom section, added during refactor)

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS metrics (...);
        CREATE INDEX IF NOT EXISTS idx_metric_time ON metrics(metric, timestamp);
        CREATE TABLE IF NOT EXISTS metrics_1m (...);
        CREATE TABLE IF NOT EXISTS metrics_1h (...);
    """)

class _MetricsMixin:
    def insert_metrics(self, metrics: list[tuple]) -> None:
        insert_metrics(self._get_conn(), self._lock, metrics)

    def get_history(self, metric: str, range_hours: int = 24, ...) -> list[dict]:
        return get_history(self._get_read_conn(), self._read_lock, metric, ...)

    def rollup_to_1m(self) -> None:
        from .metrics import rollup_to_1m as _r
        _r(self._get_conn(), self._lock)

    def rollup_to_1h(self) -> None:
        from .metrics import rollup_to_1h as _r
        _r(self._get_conn(), self._lock)

    def prune_rollups(self) -> None:
        from .metrics import prune_rollups as _r
        _r(self._get_conn(), self._lock)

    def catchup_rollups(self) -> None:
        from .metrics import catchup_rollups as _r
        _r(self._get_conn(), self._lock)
```

`db/core.py` final structure (~150 lines):

```python
# db/core.py

from . import metrics, audit, ...  # explicit _SCHEMA_MODULES list
from .metrics import _MetricsMixin
from .audit import _AuditMixin
# ... all 21 mixin imports

_SCHEMA_MODULES = [metrics, audit, ...]

class DatabaseBase:
    """Connection management + schema init only."""
    def __init__(self, path): ...
    def _get_conn(self): ...
    def _get_read_conn(self): ...
    def execute_read(self, fn): ...
    def execute_write(self, fn): ...
    def transaction(self, fn): ...
    def _init_schema(self): ...   # calls _SCHEMA_MODULES + ALTER TABLE migrations
    def wal_checkpoint(self): ... # kept here: infrastructure, not domain

class Database(
    DatabaseBase,
    _MetricsMixin, _AuditMixin, _AutomationsMixin, _AlertsMixin,
    _ApiKeysMixin, _TokensMixin, _NotificationsMixin, _UserDashboardsMixin,
    _UserPreferencesMixin, _AgentsMixin, _EndpointsMixin,
    _DashboardsMixin, _StatusPageMixin, _SecurityMixin, _DependenciesMixin,
    _BaselinesMixin, _WebhooksMixin, _BackupVerifyMixin, _ApprovalsMixin,
    _HealingMixin, _IntegrationsMixin, _LinkedProvidersMixin,
):
    pass
```

**Caller impact:** Zero. `from .db import db` and `db.method(...)` are unchanged.

**Result:** `core.py` 1,681 → ~150 lines. Each domain module grows by ~20–60 lines.
Total line count across `db/` is unchanged; distribution is dramatically better.

---

## Target 2: `integrations/simple.py` — Category split

### Problem

`integrations/simple.py` is 1,118 lines mixing integration handlers from six
distinct functional categories with no internal organisation.

### Design

Split into category files. `simple.py` becomes a thin re-exporter:

```
integrations/
  simple_network.py      — pihole, adguard, unifi, cloudflare, traefik, npm (~200 lines)
  simple_media.py        — plex, jellyfin, sonarr, radarr, qbittorrent, tautulli,
                           overseerr, prowlarr, lidarr, readarr, bazarr (~250 lines)
  simple_infra.py        — truenas, proxmox, omv, xcpng, k8s, gitea, gitlab,
                           github, paperless, vaultwarden (~200 lines)
  simple_monitoring.py   — uptime-kuma, scrutiny, speedtest, frigate,
                           graylog, influxdb (~150 lines)
  simple_iot.py          — hass, homebridge, z2m, esphome, pikvm,
                           unifi-protect, n8n (~150 lines)
  simple_comms.py        — gotify, pushover, ntfy, authentik (~100 lines)
  simple.py              — imports and re-exports all of the above (~50 lines)
```

`speedtest` belongs in `simple_monitoring.py` only (removed from `simple_comms.py`).

**Caller impact:** Zero. All external imports of `from .integrations.simple import X`
continue to resolve through `simple.py`'s re-exports.

---

## Target 3: `IntegrationsTab.vue` — Sub-component decomposition

### Problem

`IntegrationsTab.vue` is 1,532 lines handling list rendering, search/filter,
instance management, health display, group management, and action dispatch in a
single component.

### Design

```
frontend/src/components/settings/
  IntegrationsTab.vue                 — coordinator, ~150 lines
  integrations/
    IntegrationCategoryList.vue       — grouped list rendering by category (~200 lines)
    IntegrationInstanceCard.vue       — single instance row: status badge, health
                                        indicator, edit/delete actions (~150 lines)
    IntegrationSearchFilter.vue       — search input + category filter bar (~80 lines)
    IntegrationEmptyState.vue         — empty/onboarding state with call-to-action (~60 lines)
```

`IntegrationSetup.vue` (the setup wizard, 330 lines) is already a separate
component and remains unchanged.

**Data flow:** `IntegrationsTab` owns the instances list and search state.
It passes filtered data down as props. `IntegrationInstanceCard` emits
`edit` and `delete` events up. No Pinia store changes required.

---

## Target 4: `AutomationListTab.vue` — Sub-component decomposition

### Problem

`AutomationListTab.vue` is 967 lines handling list rendering, status badges,
run history display, trigger controls, and the automation detail drawer in one file.

### Design

```
frontend/src/components/automations/
  AutomationListTab.vue               — coordinator, ~150 lines
  AutomationRow.vue                   — single automation row: name, type, schedule,
                                        status badge, run/disable/delete actions (~150 lines)
  AutomationRunHistory.vue            — run history table with status + output (~150 lines)
  AutomationStatusBadge.vue           — reusable status chip (queued/running/done/failed)
                                        (~40 lines, reusable across the app)
```

`AutomationFormModal.vue` (460 lines) is already separate and unchanged.

---

## Target 5: `WorkflowBuilder.vue` — Sub-component decomposition

### Problem

`WorkflowBuilder.vue` is 784 lines combining the canvas drag surface, node palette,
node configuration panel, and connection rendering in one component.

### Design

`WorkflowNode.vue` (302 lines) already exists as a separate component handling
individual node rendering, drag-to-move, and connection port handles. It is kept
as-is — no rename or replacement needed.

```
frontend/src/components/automations/
  WorkflowBuilder.vue                 — coordinator + canvas event handling + SVG
                                        connection rendering, ~200 lines
  workflow/
    WorkflowNodePalette.vue           — left sidebar: draggable node type tiles (~150 lines)
    WorkflowNodeConfig.vue            — right panel: selected node configuration form
                                        (step type, params, conditions) (~200 lines)
```

Canvas SVG connection rendering stays in `WorkflowBuilder.vue` — tightly coupled
to drag-and-drop state. `WorkflowNode.vue` stays in its current location unchanged.

---

## Target 6: Router error handling decorator

### Problem

135 try/except blocks across all 19 routers follow an identical pattern:

```python
try:
    ...
except HTTPException:
    raise
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
```

### Design

Add `handle_errors` to `server/deps.py` (already imported by all routers):

```python
import asyncio, functools, logging
_log = logging.getLogger("noba")

def handle_errors(func):
    """Catch unhandled exceptions in route handlers and return HTTP 500.
    HTTPException and WebSocketDisconnect pass through unchanged.
    Do NOT apply to WebSocket routes or routes returning StreamingResponse."""
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def _async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                _log.exception("Unhandled error in %s", func.__name__)
                raise HTTPException(status_code=500, detail=str(e))
        return _async_wrapper
    else:
        @functools.wraps(func)
        def _sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                _log.exception("Unhandled error in %s", func.__name__)
                raise HTTPException(status_code=500, detail=str(e))
        return _sync_wrapper
```

**Exclusions — do NOT apply `@handle_errors` to:**
- `@router.websocket` routes — `WebSocketDisconnect` must not be converted to
  `HTTPException` on an already-upgraded connection
- Routes returning `StreamingResponse` (SSE endpoints) — the outer coroutine
  returns before the stream is consumed; exceptions inside the generator are
  not catchable here

**Rollout:** Apply to all non-WebSocket, non-SSE route handlers in one pass.
Each router's try/except blocks are removed. Net change: ~200 lines removed.

---

## Target 7: `agent.py` → zipapp package

### Problem

`agent.py` is 4,949 lines in a single file. The single-file constraint exists
because the auto-update mechanism distributes one file. The file now contains:
the WebSocket client, metric collection, 42 command handlers, PTY management,
a healing runtime, RDP orchestration for three platforms, and a 200-line Mutter
subprocess script embedded as a Python string.

### Design

#### Package structure

The source is a flat directory (not a subpackage). All modules live at the zip root:

```
share/noba-agent/
  __main__.py          — argparse entry point, main() loop, _ws_thread(),
                         VERSION = "3.0.0" (~300 lines)
  websocket.py         — custom RFC 6455 WebSocket client (~250 lines)
  metrics.py           — CPU/mem/disk/net/temp/process/uptime collection (~400 lines)
  commands.py          — all 42 _cmd_* handlers + execute_commands() (~800 lines)
  terminal.py          — PTY management, _pty_* functions (~250 lines)
  healing.py           — HealRuntime class + _heal_eval* condition engine (~300 lines)
  rdp.py               — RDP capture loop, X11/Windows/macOS inject, orchestration (~600 lines)
  rdp_session.py       — Mutter D-Bus subprocess script (real .py, not embedded string)
  utils.py             — path validation, subprocess safety, platform detection (~200 lines)
```

#### `rdp_session.py` loading

The zipapp adds itself to `sys.path`, so all flat modules are importable.
`rdp.py` loads the session script using `importlib.util.find_spec`, which
resolves correctly from within a flat zipapp:

```python
# rdp.py
import importlib.util as _ilu

def _load_mutter_script() -> str:
    spec = _ilu.find_spec("rdp_session")
    if spec is None:
        raise RuntimeError("rdp_session module not found in agent package")
    return spec.loader.get_data(spec.origin).decode("utf-8")

_MUTTER_SESSION_SCRIPT = _load_mutter_script()
```

This is identical in runtime behaviour to the current embedded string —
the subprocess is still started with `python3 -c <script>` — but the
source is now a real, syntax-highlighted, navigable Python file.

**Development fallback:** When running from an unzipped source tree (e.g.
`python3 share/noba-agent/__main__.py`), `find_spec("rdp_session")` still works
because the source directory is on `sys.path`.

#### Self-update path fix

`commands.py` (the `_cmd_update_agent` handler) must resolve the agent path as:

```python
agent_path = os.path.abspath(sys.argv[0])  # resolves to agent.pyz
```

**Not** `os.path.abspath(__file__)`, which inside a zipapp resolves to a path
inside the archive (e.g. `.../agent.pyz/__main__.py`) and cannot be opened for
writing. `sys.argv[0]` always points to the `.pyz` file itself.

The same fix applies to `_cmd_uninstall_agent` if it references `__file__`.

#### Build step

`scripts/build-agent.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
python3 -m zipapp share/noba-agent \
    -o share/noba-agent.pyz \
    -p "/usr/bin/env python3"
echo "Built share/noba-agent.pyz ($(du -sh share/noba-agent.pyz | cut -f1))"
```

The `.pyz` is a standard Python zipapp — `python3 agent.pyz` works on any
Python 3.6+ system with no changes to invocation.

#### VERSION

`__main__.py` contains `VERSION = "3.0.0"`. The server reads it via zipfile
inspection:

```python
# routers/agents.py
import zipfile, re
with zipfile.ZipFile(agent_pyz_path) as zf:
    src = zf.read("__main__.py").decode()
_VER_RE = re.compile(r'^VERSION\s*=\s*["\']([^"\']+)["\']', re.M)
server_version = _VER_RE.search(src).group(1)
```

#### Update mechanism

- Server reads `agent.pyz` as **bytes** and base64-encodes for transport
- Agent's `_cmd_update_agent` writes decoded bytes to `agent.pyz` (`sys.argv[0]`) and restarts
- All five hardcoded `.py` path references in `routers/agent_deploy.py` (lines ~115,
  138, 213, 221, 237) are updated to `.pyz`
- The runtime-generated install script in `agent_deploy.py` is updated to deploy
  `agent.pyz` and write the systemd unit pointing to `python3 agent.pyz`
- `install.sh` installs `agent.pyz` to `~/.local/libexec/noba/noba-agent.pyz`
- The server's version-check path in `routers/agents.py` switches from reading
  `agent.py` text to reading `__main__.py` from inside the zipfile

**Backward compatibility with 2.x agents:** 2.x agents receiving a `.pyz` file
via `update_agent` write it to `agent.py`. Python executes `.pyz` files correctly
regardless of extension (zipapp format detection is by content, not filename).
The shebang satisfies the existing `if not new_code.startswith(b"#!/")` validation.
This transition path works transparently — 2.x agents upgrade to 3.0 in one step.

#### Zero-dependency guarantee

The zipapp contains only stdlib code. No pip packages are bundled.
`Pillow` (used for RDP JPEG encoding) remains an optional host-installed
dependency detected at runtime — unchanged.

#### Test targets

Proxmox VE nodes (pve01, pve02) — full agent functionality including metric
reporting, command execution, and terminal. host-a (Raspberry Pi 5) — RDP
capture and input injection via Mutter D-Bus.

---

## Implementation order

1. Router error handling decorator — cross-cutting, low risk, establishes patterns
2. `db/core.py` mixin split — backend, no frontend impact
3. `integrations/simple.py` category split — isolated, no caller changes
4. `IntegrationsTab.vue` decomposition — largest frontend component
5. `AutomationListTab.vue` decomposition
6. `WorkflowBuilder.vue` decomposition
7. Agent zipapp — most structural change, tested on PVE nodes last

## Success criteria

- `pytest tests/ -v` passes with zero regressions after each step
- `ruff check share/noba-web/server/` passes after Python changes
- `npm run build` succeeds after frontend changes
- Agent zipapp runs on PVE test nodes with full functionality
- `db/core.py` ≤ 200 lines
- `integrations/simple.py` ≤ 60 lines
- All refactored Vue components ≤ 200 lines
- No new files created unless strictly necessary
