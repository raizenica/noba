# Codebase Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split seven over-grown files into well-bounded units without changing any external API, caller signature, or WebSocket protocol.

**Architecture:** Pure structural refactor — move code to co-located modules, introduce one shared decorator, convert agent.py single-file to zipapp package. No new features. Zero API changes.

**Tech Stack:** Python 3.11 + FastAPI, Vue 3 + Vite, SQLite, Python zipapp (stdlib)

---

## Pre-flight

### Task 0: Create branch and record baseline

**Files:**
- No file changes

- [ ] **Step 1: Create branch**

```bash
git checkout main && git pull
git checkout -b refactor/codebase-split
```

- [ ] **Step 2: Record baseline test count**

```bash
cd /home/raizen/noba && pytest tests/ -v --tb=short 2>&1 | tail -5
```

Expected: all tests passing. Note the exact count — every subsequent task must end with the same count, same result.

- [ ] **Step 3: Record baseline build**

```bash
cd share/noba-web/frontend && npm run build 2>&1 | tail -3
```

Expected: `✓ built in X.XXs`

---

## Task 1: Router error handling decorator

**Files:**
- Modify: `share/noba-web/server/deps.py`
- Modify: all 19 routers in `share/noba-web/server/routers/` (remove try/except blocks, add `@handle_errors`)
- Test: `tests/test_handle_errors.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/test_handle_errors.py`:

```python
"""Tests for the handle_errors decorator in deps."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from share.noba_web.server.deps import handle_errors


def test_handle_errors_passes_through_http_exception():
    app = FastAPI()

    @app.get("/test")
    @handle_errors
    def route():
        raise HTTPException(status_code=404, detail="not found")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/test")
    assert r.status_code == 404
    assert r.json()["detail"] == "not found"


def test_handle_errors_converts_unhandled_to_500():
    app = FastAPI()

    @app.get("/boom")
    @handle_errors
    def route():
        raise ValueError("something went wrong")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 500
    assert "something went wrong" in r.json()["detail"]


def test_handle_errors_async_route():
    app = FastAPI()

    @app.get("/async-boom")
    @handle_errors
    async def route():
        raise RuntimeError("async failure")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/async-boom")
    assert r.status_code == 500
    assert "async failure" in r.json()["detail"]


def test_handle_errors_happy_path():
    app = FastAPI()

    @app.get("/ok")
    @handle_errors
    def route():
        return {"status": "ok"}

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/ok")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/raizen/noba && pytest tests/test_handle_errors.py -v
```

Expected: `ImportError` or `AttributeError` — `handle_errors` doesn't exist yet.

- [ ] **Step 3: Add `handle_errors` to `deps.py`**

Add at the top of `share/noba-web/server/deps.py`, after the existing imports:

```python
import asyncio
import functools
import logging

_log = logging.getLogger("noba")
```

Then add the decorator after all existing helpers (before the `# ── Auth dependencies` section):

```python
# ── Route error handler ───────────────────────────────────────────────────────

def handle_errors(func):
    """Catch unhandled exceptions in route handlers and return HTTP 500.

    HTTPException passes through unchanged.
    Do NOT apply to @router.websocket routes or routes returning StreamingResponse —
    those connections are already upgraded; wrapping them corrupts the protocol.
    """
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

- [ ] **Step 4: Run tests to verify decorator works**

```bash
cd /home/raizen/noba && pytest tests/test_handle_errors.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Apply `@handle_errors` across all 19 routers**

For each router file in `share/noba-web/server/routers/`, for each `@router.get/post/put/delete/patch` route handler:

1. Add `@handle_errors` decorator directly below the `@router.*` line
2. Remove the inner `try:/except HTTPException:/raise/except Exception as e:/raise HTTPException(status_code=500, detail=str(e))` block, keeping only the body

**Import to add in each router** (add to each router's existing `from ..deps import ...` line):

```python
from ..deps import (
    ..., handle_errors,  # add handle_errors here
)
```

**DO NOT** apply `@handle_errors` to:
- `@router.websocket` routes: `agent_websocket` (agents.py), `agent_terminal_ws` (agent_terminal.py), `agent_rdp_ws` (agent_rdp.py), `ws_terminal` (infrastructure.py)
- Routes containing `StreamingResponse`: the SSE route in `stats.py` line ~126

Pattern being removed per route (approximately 5 lines):

```python
# BEFORE
@router.get("/api/something")
def my_route(auth=Depends(_get_auth)):
    try:
        return do_work()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# AFTER
@router.get("/api/something")
@handle_errors
def my_route(auth=Depends(_get_auth)):
    return do_work()
```

Work through all 19 router files:
`admin.py`, `agent_commands.py`, `agent_deploy.py`, `agent_rdp.py` (non-WS routes only),
`agents.py` (non-WS routes only), `agent_terminal.py` (non-WS routes only),
`auth.py`, `automations.py`, `containers.py`, `dashboards.py`,
`healing.py`, `infrastructure.py` (non-WS routes only),
`integration_instances.py`, `integrations.py`, `intelligence.py`,
`monitoring.py`, `operations.py`, `security.py`, `stats.py` (non-SSE routes only)

- [ ] **Step 6: Run ruff check**

```bash
cd /home/raizen/noba && ruff check share/noba-web/server/ --fix
```

Expected: no errors.

- [ ] **Step 7: Run full test suite**

```bash
cd /home/raizen/noba && pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: same pass count as baseline, 0 failures.

- [ ] **Step 8: Commit**

```bash
git add share/noba-web/server/deps.py share/noba-web/server/routers/ tests/test_handle_errors.py
git commit -m "refactor: add handle_errors decorator, remove 135 try/except blocks from routers"
```

---

## Task 2: `db/core.py` mixin split

**Files:**
- Modify: `share/noba-web/server/db/metrics.py` — add `init_schema()` + `_MetricsMixin`
- Modify: `share/noba-web/server/db/audit.py` — add `init_schema()` + `_AuditMixin`
- Modify: `share/noba-web/server/db/automations.py` — add `init_schema()` + `_AutomationsMixin` + `_ApprovalsMixin`
- Modify: `share/noba-web/server/db/alerts.py` — add `init_schema()` + `_AlertsMixin`
- Modify: `share/noba-web/server/db/api_keys.py` — add `init_schema()` + `_ApiKeysMixin`
- Modify: `share/noba-web/server/db/tokens.py` — add `init_schema()` + `_TokensMixin`
- Modify: `share/noba-web/server/db/notifications.py` — add `init_schema()` + `_NotificationsMixin`
- Modify: `share/noba-web/server/db/user_dashboards.py` — add `init_schema()` + `_UserDashboardsMixin`
- Modify: `share/noba-web/server/db/user_preferences.py` — add `init_schema()` + `_UserPreferencesMixin`
- Modify: `share/noba-web/server/db/agents.py` — add `init_schema()` + `_AgentsMixin`
- Modify: `share/noba-web/server/db/endpoints.py` — add `init_schema()` + `_EndpointsMixin`
- Modify: `share/noba-web/server/db/dashboards.py` — add `init_schema()` + `_DashboardsMixin`
- Modify: `share/noba-web/server/db/status_page.py` — add `init_schema()` + `_StatusPageMixin`
- Modify: `share/noba-web/server/db/security.py` — add `init_schema()` + `_SecurityMixin`
- Modify: `share/noba-web/server/db/dependencies.py` — add `init_schema()` + `_DependenciesMixin`
- Modify: `share/noba-web/server/db/baselines.py` — add `init_schema()` + `_BaselinesMixin`
- Modify: `share/noba-web/server/db/network.py` — add `init_schema()` only (no mixin)
- Modify: `share/noba-web/server/db/webhooks.py` — add `init_schema()` + `_WebhooksMixin`
- Modify: `share/noba-web/server/db/backup_verify.py` — add `init_schema()` + `_BackupVerifyMixin`
- Modify: `share/noba-web/server/db/healing.py` — add `init_schema()` + `_HealingMixin`
- Modify: `share/noba-web/server/db/integrations.py` — add `init_schema()` + `_IntegrationsMixin`
- Modify: `share/noba-web/server/db/linked_providers.py` — add `init_schema()` + `_LinkedProvidersMixin`
- Modify: `share/noba-web/server/db/core.py` — rewrite to ~150 lines

**Note:** `db/migrations.py` is excluded — it manages schema migrations separately.

- [ ] **Step 1: Run baseline tests**

```bash
cd /home/raizen/noba && pytest tests/ -v --tb=short 2>&1 | tail -5
```

Note the exact pass count. This is the target for after the refactor.

- [ ] **Step 2: Extract DDL from `core.py` into domain modules**

Open `share/noba-web/server/db/core.py` and find `_init_schema`. It contains `CREATE TABLE IF NOT EXISTS` blocks for every table. For each domain module:

1. Locate the DDL blocks for that module's tables in `core.py`
2. Add `init_schema(conn: sqlite3.Connection) -> None` at the bottom of the domain file, wrapping the DDL in `conn.executescript("""...""")`

Example for `db/metrics.py`:

```python
# Add at the bottom of db/metrics.py

import sqlite3 as _sqlite3

def init_schema(conn: _sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY,
            host TEXT,
            metric TEXT,
            value REAL,
            timestamp INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_metric_time ON metrics(metric, timestamp);
        CREATE INDEX IF NOT EXISTS idx_metric_host ON metrics(host, metric, timestamp);
        CREATE TABLE IF NOT EXISTS metrics_1m (
            host TEXT, metric TEXT, bucket INTEGER,
            avg REAL, min REAL, max REAL,
            PRIMARY KEY (host, metric, bucket)
        );
        CREATE TABLE IF NOT EXISTS metrics_1h (
            host TEXT, metric TEXT, bucket INTEGER,
            avg REAL, min REAL, max REAL,
            PRIMARY KEY (host, metric, bucket)
        );
    """)
```

Repeat for all 22 modules — extract the DDL that belongs to each module's tables.

**Special case for `automations.py`:** It owns DDL for `automations`, `job_runs`, `approval_queue`, and `maintenance_windows` tables. Include all four in its `init_schema`.

**Special case for `network.py`:** Add `init_schema` only — no mixin needed (no wrapper methods exist for it in core.py).

- [ ] **Step 3: Add `_XMixin` classes to each domain module (21 modules)**

For each of the 21 domain modules that have wrapper methods in `core.py`, add the mixin at the bottom of the file, AFTER `init_schema`.

The mixin wraps each public function from that module. Use `self._get_conn()` for writes and `self._get_read_conn()` for reads. Use `self._lock` and `self._read_lock` for threading.

Example template for `db/metrics.py`:

```python
class _MetricsMixin:
    def insert_metrics(self, metrics: list[tuple]) -> None:
        insert_metrics(self._get_conn(), self._lock, metrics)

    def get_history(self, metric: str, range_hours: int = 24,
                    host: str | None = None, aggregate: bool = False) -> list[dict]:
        return get_history(self._get_read_conn(), self._read_lock,
                           metric, range_hours, host, aggregate)

    def rollup_to_1m(self) -> None:
        rollup_to_1m(self._get_conn(), self._lock)

    def rollup_to_1h(self) -> None:
        rollup_to_1h(self._get_conn(), self._lock)

    def prune_rollups(self) -> None:
        prune_rollups(self._get_conn(), self._lock)

    def catchup_rollups(self) -> None:
        catchup_rollups(self._get_conn(), self._lock)
```

For each module, check `core.py` for the exact set of wrapper methods that begin with `def ` and delegate to that module's imported functions. Copy each wrapper into the mixin, replacing the `_prefixed_import` call with the local function name.

- [ ] **Step 4: Rewrite `core.py`**

Replace the entire contents of `share/noba-web/server/db/core.py` with:

```python
"""Noba – Thread-safe SQLite database layer (core)."""
from __future__ import annotations

import logging
import sqlite3
import threading

from ..config import HISTORY_DB
from . import (
    metrics, audit, automations, alerts, api_keys, tokens,
    notifications, user_dashboards, user_preferences, agents,
    endpoints, dashboards, status_page, security, dependencies,
    baselines, network, webhooks, backup_verify, healing,
    integrations, linked_providers,
)
from .metrics import _MetricsMixin
from .audit import _AuditMixin
from .automations import _AutomationsMixin, _ApprovalsMixin
from .alerts import _AlertsMixin
from .api_keys import _ApiKeysMixin
from .tokens import _TokensMixin
from .notifications import _NotificationsMixin
from .user_dashboards import _UserDashboardsMixin
from .user_preferences import _UserPreferencesMixin
from .agents import _AgentsMixin
from .endpoints import _EndpointsMixin
from .dashboards import _DashboardsMixin
from .status_page import _StatusPageMixin
from .security import _SecurityMixin
from .dependencies import _DependenciesMixin
from .baselines import _BaselinesMixin
from .webhooks import _WebhooksMixin
from .backup_verify import _BackupVerifyMixin
from .healing import _HealingMixin
from .integrations import _IntegrationsMixin
from .linked_providers import _LinkedProvidersMixin

logger = logging.getLogger("noba")

_SCHEMA_MODULES = [
    metrics, audit, automations, alerts, api_keys, tokens,
    notifications, user_dashboards, user_preferences, agents,
    endpoints, dashboards, status_page, security, dependencies,
    baselines, network, webhooks, backup_verify, healing,
    integrations, linked_providers,
]
# 22 modules: all own tables. network.py gets init_schema only (no mixin).
# automations.py owns approval_queue DDL (workflow_context is a column).


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


class DatabaseBase:
    """Connection management, schema init, and WAL checkpoint. No domain logic."""

    def __init__(self, path: str = HISTORY_DB) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._read_lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._read_conn: sqlite3.Connection | None = None
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._path, check_same_thread=False, timeout=30,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _get_read_conn(self) -> sqlite3.Connection:
        if self._read_conn is None:
            self._read_conn = sqlite3.connect(
                self._path, check_same_thread=False, timeout=30,
            )
            self._read_conn.row_factory = sqlite3.Row
            self._read_conn.execute("PRAGMA journal_mode=WAL")
        return self._read_conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._get_conn()
            for mod in _SCHEMA_MODULES:
                mod.init_schema(conn)
            _run_alter_migrations(conn)
            conn.commit()

    def wal_checkpoint(self) -> None:
        with self._lock:
            self._get_conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")


class Database(
    DatabaseBase,
    _MetricsMixin, _AuditMixin, _AutomationsMixin, _AlertsMixin,
    _ApiKeysMixin, _TokensMixin, _NotificationsMixin, _UserDashboardsMixin,
    _UserPreferencesMixin, _AgentsMixin, _EndpointsMixin,
    _DashboardsMixin, _StatusPageMixin, _SecurityMixin, _DependenciesMixin,
    _BaselinesMixin, _WebhooksMixin, _BackupVerifyMixin, _ApprovalsMixin,
    _HealingMixin, _IntegrationsMixin, _LinkedProvidersMixin,
):
    """Thread-safe SQLite database with all domain methods via mixins."""
    pass
```

- [ ] **Step 5: Run ruff check**

```bash
cd /home/raizen/noba && ruff check share/noba-web/server/ --fix
```

Expected: no errors (there may be some unused-import warnings to clean up).

- [ ] **Step 6: Run full test suite**

```bash
cd /home/raizen/noba && pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: same pass count as baseline. If failures appear, the most likely cause is a method signature mismatch between the mixin wrapper and the domain function — compare against the old core.py wrapper carefully.

- [ ] **Step 7: Verify core.py line count**

```bash
wc -l share/noba-web/server/db/core.py
```

Expected: ≤ 200 lines.

- [ ] **Step 8: Commit**

```bash
git add share/noba-web/server/db/
git commit -m "refactor: split db/core.py into co-located mixins, core reduces to ~150 lines"
```

---

## Task 3: `integrations/simple.py` category split

**Files:**
- Create: `share/noba-web/server/integrations/simple_media.py`
- Create: `share/noba-web/server/integrations/simple_network.py`
- Create: `share/noba-web/server/integrations/simple_infra.py`
- Create: `share/noba-web/server/integrations/simple_monitoring.py`
- Create: `share/noba-web/server/integrations/simple_iot.py`
- Create: `share/noba-web/server/integrations/simple_comms.py`
- Modify: `share/noba-web/server/integrations/simple.py` — thin re-exporter (~50 lines)

- [ ] **Step 1: Run baseline tests**

```bash
cd /home/raizen/noba && pytest tests/ -v --tb=short 2>&1 | tail -5
```

- [ ] **Step 2: Create the six category files**

Each new file needs this header:

```python
"""Noba – [Category] integrations."""
from __future__ import annotations

import logging
# ... relevant imports from simple.py header

from .base import ConfigError, TransientError, _client, _http_get

logger = logging.getLogger("noba")
```

**Function distribution:**

`simple_media.py` — `get_plex`, `get_jellyfin`, `get_tautulli`, `get_overseerr`, `get_prowlarr`, `get_servarr`, `get_servarr_extended`, `get_servarr_calendar`, `get_nextcloud`

`simple_network.py` — `get_adguard`, `get_traefik`, `get_npm`, `get_cloudflare`

`simple_infra.py` — `get_truenas`, `get_omv`, `get_xcpng`, `get_k8s`, `get_gitea`, `get_gitlab`, `get_github`, `get_paperless`, `get_vaultwarden`

`simple_monitoring.py` — `get_kuma`, `get_scrutiny`, `get_scrutiny_intelligence`, `get_speedtest`, `get_frigate`, `get_graylog`, `query_influxdb`, `get_weather`, `get_energy_shelly`

`simple_iot.py` — `get_homebridge`, `get_z2m`, `get_esphome`, `get_pikvm`

`simple_comms.py` — `get_authentik`

**Note:** `get_hass`, `get_unifi_protect`, and `get_n8n` are NOT in `simple.py` — they live in other integration files or are not yet implemented. Do not create stubs for them here.

Move each function (with all its imports) verbatim — no logic changes.

- [ ] **Step 3: Rewrite `simple.py` as thin re-exporter**

```python
"""Noba – Simple integrations (re-exports from category modules)."""
from __future__ import annotations

from .simple_media import (
    get_jellyfin, get_nextcloud, get_overseerr, get_plex, get_prowlarr,
    get_servarr, get_servarr_calendar, get_servarr_extended, get_tautulli,
)
from .simple_network import get_adguard, get_cloudflare, get_npm, get_traefik
from .simple_infra import (
    get_gitea, get_github, get_gitlab, get_k8s, get_omv,
    get_paperless, get_truenas, get_vaultwarden, get_xcpng,
)
from .simple_monitoring import (
    get_energy_shelly, get_frigate, get_graylog, get_kuma, get_scrutiny,
    get_scrutiny_intelligence, get_speedtest, get_weather, query_influxdb,
)
from .simple_iot import get_esphome, get_homebridge, get_pikvm, get_z2m
from .simple_comms import get_authentik

__all__ = [
    "get_plex", "get_jellyfin", "get_tautulli", "get_overseerr", "get_prowlarr",
    "get_servarr", "get_servarr_extended", "get_servarr_calendar", "get_nextcloud",
    "get_adguard", "get_cloudflare", "get_npm", "get_traefik",
    "get_truenas", "get_omv", "get_xcpng", "get_k8s",
    "get_gitea", "get_gitlab", "get_github", "get_paperless", "get_vaultwarden",
    "get_kuma", "get_scrutiny", "get_scrutiny_intelligence", "get_speedtest",
    "get_frigate", "get_graylog", "query_influxdb", "get_weather", "get_energy_shelly",
    "get_homebridge", "get_z2m", "get_esphome", "get_pikvm",
    "get_authentik",
]
```

- [ ] **Step 4: Run ruff check**

```bash
cd /home/raizen/noba && ruff check share/noba-web/server/ --fix
```

Expected: no errors.

- [ ] **Step 5: Run full test suite**

```bash
cd /home/raizen/noba && pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: same pass count as baseline.

- [ ] **Step 6: Verify simple.py line count**

```bash
wc -l share/noba-web/server/integrations/simple.py
```

Expected: ≤ 60 lines.

- [ ] **Step 7: Commit**

```bash
git add share/noba-web/server/integrations/
git commit -m "refactor: split integrations/simple.py into 6 category files"
```

---

## Task 4: `IntegrationsTab.vue` decomposition

**Files:**
- Create: `share/noba-web/frontend/src/components/settings/integrations/IntegrationCategoryList.vue`
- Create: `share/noba-web/frontend/src/components/settings/integrations/IntegrationInstanceCard.vue`
- Create: `share/noba-web/frontend/src/components/settings/integrations/IntegrationSearchFilter.vue`
- Create: `share/noba-web/frontend/src/components/settings/integrations/IntegrationEmptyState.vue`
- Modify: `share/noba-web/frontend/src/components/settings/IntegrationsTab.vue` — coordinator ~150 lines

- [ ] **Step 1: Baseline build**

```bash
cd /home/raizen/noba/share/noba-web/frontend && npm run build 2>&1 | tail -3
```

Expected: `✓ built in X.XXs`

- [ ] **Step 2: Extract `IntegrationSearchFilter.vue`**

Find the search input and category filter bar in `IntegrationsTab.vue`. Extract into:

```vue
<!-- IntegrationSearchFilter.vue -->
<script setup>
const props = defineProps({
  modelValue: String,          // search query
  selectedCategory: String,    // active category filter
  categories: Array,           // list of category names
})
const emit = defineEmits(['update:modelValue', 'update:selectedCategory'])
</script>
<template>
  <!-- search input + category filter bar from original component -->
</template>
```

- [ ] **Step 3: Extract `IntegrationEmptyState.vue`**

Find the empty/onboarding state block (shown when no integrations configured). Extract into a presentational component with no props needed or a single `hasSearch: Boolean` prop.

- [ ] **Step 4: Extract `IntegrationInstanceCard.vue`**

Find the single integration instance row template (rendered in v-for). Extract:

```vue
<!-- IntegrationInstanceCard.vue -->
<script setup>
const props = defineProps({
  instance: Object,      // { id, name, category, status, health, ... }
})
const emit = defineEmits(['edit', 'delete'])
</script>
<template>
  <!-- single instance row: status badge, health indicator, edit/delete buttons -->
</template>
```

- [ ] **Step 5: Extract `IntegrationCategoryList.vue`**

Find the category grouping logic (v-for over categories, rendering instances per category). Extract:

```vue
<!-- IntegrationCategoryList.vue -->
<script setup>
import IntegrationInstanceCard from './IntegrationInstanceCard.vue'
const props = defineProps({
  groupedInstances: Object,    // { categoryName: [instance, ...] }
})
const emit = defineEmits(['edit', 'delete'])
</script>
<template>
  <!-- grouped list, using IntegrationInstanceCard for each item -->
</template>
```

- [ ] **Step 6: Reduce `IntegrationsTab.vue` to coordinator**

`IntegrationsTab.vue` retains:
- `instances` state, `searchQuery`, `selectedCategory` reactive state
- All API calls (fetch, add, edit, delete)
- Computed `filteredGrouped` grouping/filtering logic
- Template: imports and wires the four new sub-components

```vue
<template>
  <div class="integrations-tab">
    <IntegrationSearchFilter
      v-model="searchQuery"
      v-model:selectedCategory="selectedCategory"
      :categories="categories"
    />
    <IntegrationEmptyState v-if="instances.length === 0" />
    <IntegrationCategoryList
      v-else
      :groupedInstances="filteredGrouped"
      @edit="openEdit"
      @delete="confirmDelete"
    />
    <!-- IntegrationSetup modal (unchanged) -->
  </div>
</template>
```

- [ ] **Step 7: Verify build and line count**

```bash
cd /home/raizen/noba/share/noba-web/frontend && npm run build 2>&1 | tail -3
wc -l src/components/settings/IntegrationsTab.vue
```

Expected: build succeeds, IntegrationsTab.vue ≤ 200 lines.

- [ ] **Step 8: Commit**

```bash
git add share/noba-web/frontend/src/components/settings/
git commit -m "refactor: decompose IntegrationsTab.vue into 4 sub-components"
```

---

## Task 5: `AutomationListTab.vue` decomposition

**Files:**
- Create: `share/noba-web/frontend/src/components/automations/AutomationRow.vue`
- Create: `share/noba-web/frontend/src/components/automations/AutomationRunHistory.vue`
- Create: `share/noba-web/frontend/src/components/automations/AutomationStatusBadge.vue`
- Modify: `share/noba-web/frontend/src/components/automations/AutomationListTab.vue` — coordinator ~150 lines

- [ ] **Step 1: Extract `AutomationStatusBadge.vue`**

Find the status chip template (queued/running/done/failed with color-coded styling). Extract:

```vue
<!-- AutomationStatusBadge.vue -->
<script setup>
const props = defineProps({
  status: String,    // 'queued' | 'running' | 'done' | 'failed' | 'disabled'
})
</script>
<template>
  <!-- status chip with appropriate CSS class and label -->
</template>
```

This is reusable across the app — it can be imported by `AutomationRow`, `AutomationRunHistory`, etc.

- [ ] **Step 2: Extract `AutomationRunHistory.vue`**

Find the run history table/list in `AutomationListTab.vue`. Extract:

```vue
<!-- AutomationRunHistory.vue -->
<script setup>
import AutomationStatusBadge from './AutomationStatusBadge.vue'
const props = defineProps({
  runs: Array,     // list of run history objects
})
</script>
<template>
  <!-- run history table: timestamp, status badge, output/logs -->
</template>
```

- [ ] **Step 3: Extract `AutomationRow.vue`**

Find the single automation row (rendered in v-for). Extract:

```vue
<!-- AutomationRow.vue -->
<script setup>
import AutomationStatusBadge from './AutomationStatusBadge.vue'
import AutomationRunHistory from './AutomationRunHistory.vue'
const props = defineProps({
  automation: Object,      // automation data object
  runHistory: Array,       // last N runs for this automation
  expanded: Boolean,       // whether detail drawer is open
})
const emit = defineEmits(['run', 'disable', 'delete', 'toggle-expand'])
</script>
<template>
  <!-- row: name, type badge, schedule, status badge, action buttons -->
  <!-- collapsible run history when expanded -->
</template>
```

- [ ] **Step 4: Reduce `AutomationListTab.vue` to coordinator**

Retain: automations list state, API calls, computed filters, template that uses `AutomationRow` in v-for.

- [ ] **Step 5: Verify build and line count**

```bash
cd /home/raizen/noba/share/noba-web/frontend && npm run build 2>&1 | tail -3
wc -l src/components/automations/AutomationListTab.vue
```

Expected: build succeeds, AutomationListTab.vue ≤ 200 lines.

- [ ] **Step 6: Commit**

```bash
git add share/noba-web/frontend/src/components/automations/
git commit -m "refactor: decompose AutomationListTab.vue into AutomationRow, RunHistory, StatusBadge"
```

---

## Task 6: `WorkflowBuilder.vue` decomposition

**Files:**
- Create: `share/noba-web/frontend/src/components/automations/workflow/WorkflowNodePalette.vue`
- Create: `share/noba-web/frontend/src/components/automations/workflow/WorkflowNodeConfig.vue`
- Modify: `share/noba-web/frontend/src/components/automations/WorkflowBuilder.vue` — coordinator + canvas ~200 lines

**Note:** `WorkflowNode.vue` (302 lines) stays unchanged.

- [ ] **Step 1: Create `workflow/` subdirectory and extract `WorkflowNodePalette.vue`**

Find the left sidebar with draggable node type tiles in `WorkflowBuilder.vue`. Extract:

```vue
<!-- workflow/WorkflowNodePalette.vue -->
<script setup>
const props = defineProps({
  nodeTypes: Array,    // list of available node type definitions
})
const emit = defineEmits(['add-node'])
// Drag start handler: sets dataTransfer with node type
</script>
<template>
  <!-- left sidebar: node type tiles, draggable -->
</template>
```

- [ ] **Step 2: Extract `WorkflowNodeConfig.vue`**

Find the right panel configuration form (rendered when a node is selected). Extract:

```vue
<!-- workflow/WorkflowNodeConfig.vue -->
<script setup>
const props = defineProps({
  node: Object,           // selected node data (null = nothing selected)
  stepTypes: Array,       // available step type definitions
})
const emit = defineEmits(['update', 'close'])
</script>
<template>
  <!-- right panel: step type select, params fields, condition editor -->
  <!-- shown only when node is not null -->
</template>
```

- [ ] **Step 3: Reduce `WorkflowBuilder.vue` to coordinator + canvas**

Retain in `WorkflowBuilder.vue`:
- All canvas state: `nodes`, `connections`, `dragging`, `selectedNode`
- Drag-and-drop canvas event handlers (`onDrop`, `onDragOver`, `onNodeDrag`)
- SVG connection rendering (tightly coupled to drag state — do not extract)
- Template: mounts `WorkflowNodePalette` (left), canvas with `WorkflowNode` components, `WorkflowNodeConfig` (right)

- [ ] **Step 4: Verify build and line count**

```bash
cd /home/raizen/noba/share/noba-web/frontend && npm run build 2>&1 | tail -3
wc -l src/components/automations/WorkflowBuilder.vue
```

Expected: build succeeds, WorkflowBuilder.vue ≤ 250 lines.

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/frontend/src/components/automations/
git commit -m "refactor: decompose WorkflowBuilder.vue into NodePalette and NodeConfig sub-components"
```

---

## Task 7: Agent zipapp

**Files:**
- Create: `share/noba-agent/__main__.py` (~300 lines)
- Create: `share/noba-agent/websocket.py` (~250 lines)
- Create: `share/noba-agent/metrics.py` (~400 lines)
- Create: `share/noba-agent/commands.py` (~800 lines)
- Create: `share/noba-agent/terminal.py` (~250 lines)
- Create: `share/noba-agent/healing.py` (~300 lines)
- Create: `share/noba-agent/rdp.py` (~600 lines)
- Create: `share/noba-agent/rdp_session.py` (~200 lines, extracted from embedded string)
- Create: `share/noba-agent/utils.py` (~200 lines)
- Create: `scripts/build-agent.sh`
- Modify: `share/noba-web/server/routers/agents.py` — VERSION read via zipfile
- Modify: `share/noba-web/server/routers/agent_deploy.py` — 5 `.py` → `.pyz` references
- Modify: `install.sh` — install `agent.pyz` instead of `agent.py`
- Delete: `share/noba-agent/agent.py` (after all modules extracted and verified)

- [ ] **Step 1: Read and map `agent.py` sections**

Open `share/noba-agent/agent.py` and identify the line boundaries for each module:

- **`websocket.py`**: `class _WebSocketClient` and all WebSocket helper code (line ~149–~550)
- **`metrics.py`**: all `_collect_*` functions and `collect_all_metrics()` (approx lines ~550–~900)
- **`commands.py`**: all `_cmd_*` functions + `execute_commands()` (lines ~673–~3310)
- **`terminal.py`**: all `_pty_*` functions (lines ~3311–~3440 area, check grep output)
- **`healing.py`**: `class HealRuntime` + `_heal_eval_*` condition engine (search for `class HealRuntime`)
- **`rdp.py`**: `_rdp_*` + `_capture_*` functions + `_rdp_capture_loop` (lines ~2600–end)
- **`rdp_session.py`**: the `_MUTTER_SESSION_SCRIPT` string content (extract verbatim)
- **`utils.py`**: path validation, subprocess safety, platform detection helpers
- **`__main__.py`**: `VERSION`, `main()`, `_ws_thread()`, argparse, top-level constants

Run to confirm section boundaries:

```bash
grep -n "^VERSION\|^def main\|^def _ws_thread\|^class _WebSocket\|^class HealRuntime\|^def _collect\|^def _cmd_\|^def _pty\|^def _rdp\|^def _capture\|_MUTTER_SESSION_SCRIPT" share/noba-agent/agent.py | head -30
```

- [ ] **Step 2: Create `scripts/build-agent.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
python3 -m zipapp share/noba-agent \
    -o share/noba-agent.pyz \
    -p "/usr/bin/env python3"
echo "Built share/noba-agent.pyz ($(du -sh share/noba-agent.pyz | cut -f1))"
```

```bash
chmod +x scripts/build-agent.sh
```

- [ ] **Step 3: Extract `rdp_session.py` from the embedded string**

In `agent.py`, find `_MUTTER_SESSION_SCRIPT = """..."""`. Extract the string content to `share/noba-agent/rdp_session.py` as a real Python file (remove the outer triple-quote wrapper).

Verify it's valid Python:

```bash
python3 -m py_compile share/noba-agent/rdp_session.py && echo "OK"
```

- [ ] **Step 4: Create `share/noba-agent/rdp.py`**

Extract all `_rdp_*`, `_capture_*` functions and `_rdp_capture_loop` from `agent.py`.

Add the `_load_mutter_script()` loader at the top of the module, replacing the embedded string:

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

All other RDP functions reference `_MUTTER_SESSION_SCRIPT` as before.

- [ ] **Step 5: Extract remaining modules**

Extract each section to its target file. Each file needs:
- `from __future__ import annotations` at the top
- Only the imports needed for that module's functions
- No circular imports (if `commands.py` calls healing functions, import from `healing`)

For `commands.py`, find and fix the self-update path:

```python
# In _cmd_update_agent — replace __file__ reference with sys.argv[0]:
agent_path = os.path.abspath(sys.argv[0])   # resolves to agent.pyz
```

Check `_cmd_uninstall_agent` for the same pattern and fix it too.

- [ ] **Step 6: Create `share/noba-agent/__main__.py`**

```python
"""Noba Agent – entry point."""
from __future__ import annotations

VERSION = "3.0.0"

import argparse
import sys

# Import from co-located modules (flat zipapp: all on sys.path)
from websocket import _WebSocketClient
from metrics import collect_all_metrics
from commands import execute_commands
# ... etc.

def main() -> None:
    # argparse + _ws_thread + main loop (extracted from agent.py)
    ...

if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Build the zipapp**

```bash
cd /home/raizen/noba && bash scripts/build-agent.sh
```

Expected: `Built share/noba-agent.pyz (XXX K)`

- [ ] **Step 8: Smoke test the zipapp**

```bash
python3 share/noba-agent.pyz --help
```

Expected: prints usage/help without errors.

- [ ] **Step 9: Update `routers/agents.py` VERSION check**

Find the section that reads `agent.py` to compare VERSION. Replace with zipfile inspection:

```python
import re
import zipfile

# In the version-check function:
with zipfile.ZipFile(agent_pyz_path) as zf:
    src = zf.read("__main__.py").decode()
_VER_RE = re.compile(r'^VERSION\s*=\s*["\']([^"\']+)["\']', re.M)
m = _VER_RE.search(src)
server_version = m.group(1) if m else "unknown"
```

Update `agent_pyz_path` to point to `~/.local/libexec/noba/noba-agent.pyz`.

- [ ] **Step 10: Update `routers/agent_deploy.py`** — five `.py` → `.pyz` path references

Find and update lines ~115, 138, 213, 221, 237 (the hardcoded path references). Update the runtime-generated install script to deploy `agent.pyz` and write the systemd unit to call `python3 agent.pyz`.

- [ ] **Step 11: Update `install.sh`**

Find the agent install section. Change:
```bash
# From:
install -m 755 share/noba-agent/agent.py "$AGENT_DIR/agent.py"

# To:
bash scripts/build-agent.sh
install -m 755 share/noba-agent.pyz "$AGENT_DIR/noba-agent.pyz"
```

Update the systemd unit template in `install.sh` to use `python3 noba-agent.pyz`.

- [ ] **Step 12: Run ruff check on server changes**

```bash
cd /home/raizen/noba && ruff check share/noba-web/server/ --fix
```

- [ ] **Step 13: Run full test suite**

```bash
cd /home/raizen/noba && pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: same pass count as Task 1 baseline.

- [ ] **Step 14: Run build**

```bash
cd share/noba-web/frontend && npm run build 2>&1 | tail -3
```

- [ ] **Step 15: Commit (before live test)**

```bash
git add share/noba-agent/ scripts/build-agent.sh share/noba-web/server/routers/agents.py share/noba-web/server/routers/agent_deploy.py install.sh
git commit -m "refactor: convert agent.py monolith to zipapp package (v3.0.0)"
```

- [ ] **Step 16: Live test on PVE nodes**

Rsync the new `.pyz` to the installed path and trigger auto-update:

```bash
bash scripts/build-agent.sh
rsync -a share/noba-agent.pyz ~/.local/libexec/noba/noba-agent.pyz
```

Verify agents on pve01 and pve02 auto-update within one report interval (~30s). Check:
- Agent connects and reports metrics
- Terminal access works
- RDP works on host-a

---

## Post-refactor: Final verification

- [ ] **Run full test suite one last time**

```bash
cd /home/raizen/noba && pytest tests/ -v 2>&1 | tail -10
```

Expected: same count as original baseline, zero failures.

- [ ] **Verify all line count targets**

```bash
wc -l share/noba-web/server/db/core.py
wc -l share/noba-web/server/integrations/simple.py
wc -l share/noba-web/frontend/src/components/settings/IntegrationsTab.vue
wc -l share/noba-web/frontend/src/components/automations/AutomationListTab.vue
wc -l share/noba-web/frontend/src/components/automations/WorkflowBuilder.vue
```

- [ ] **Run final ruff check**

```bash
ruff check share/noba-web/server/
```

Expected: clean.

- [ ] **Update CHANGELOG.md**

Add `[Unreleased]` entry listing all 7 refactor targets.

- [ ] **Final commit**

```bash
git add CHANGELOG.md
git commit -m "docs: update changelog for codebase refactor"
```
