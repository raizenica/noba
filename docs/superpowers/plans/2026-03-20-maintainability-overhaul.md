# NOBA Maintainability Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose oversized Python/JS modules into focused, testable files while preserving all behavior and existing test compatibility.

**Architecture:** Extract shared state and helpers first (deps.py, agent_store.py, workflow_engine.py), then split route handlers into FastAPI APIRouter modules, then split db/integrations/metrics into domain packages. Frontend follows the same pattern. Each phase ends with a full test checkpoint.

**Tech Stack:** FastAPI APIRouter, httpx, SQLite, Alpine.js, Chart.js — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-03-20-maintainability-overhaul-design.md`

**Branch:** `refactor/maintainability-overhaul`

---

## Phase 1: Backend Module Splitting

The riskiest phase — 4 files totaling ~7,700 lines get reorganized. Order matters: extract shared state first, then routes, then packages.

---

### Task 1: Extract shared dependencies (`deps.py`)

**Files:**
- Create: `share/noba-web/server/deps.py`
- Modify: `share/noba-web/server/app.py`

This is the foundation — all route modules will import from here.

- [ ] **Step 1: Create `deps.py` with helper functions and auth dependencies**

Extract from `app.py`:
- `_read_body()` (lines 4311-4318) — async JSON body reader with size check
- `_client_ip()` (lines 206-211) — extract client IP with X-Forwarded-For support
- `_run_cmd()` (lines 4321-4326) — subprocess execution helper
- `_safe_int()` (lines 58-63) — safe integer conversion
- `_int_param()` (lines 609-614) — extract integer query parameter
- Auth dependency re-exports: `_get_auth`, `_get_auth_sse`, `_require_operator`, `_require_admin`, `_require_permission` (lines 160-203)
- Re-export `db` from `.db` and `bg_collector` reference (set during lifespan)

The file should start with:
```python
from __future__ import annotations

import logging
import subprocess
from fastapi import HTTPException, Request

from .auth import (
    authenticate, rate_limiter, token_store, users,
)
from .config import MAX_BODY_BYTES, TRUST_PROXY, VALID_ROLES
from .db import db

logger = logging.getLogger("noba")
bg_collector = None  # Set by app.py lifespan
```

Then include all helper functions and auth dependency factories exactly as they appear in `app.py`.

- [ ] **Step 2: Update `app.py` — replace extracted functions with imports from `deps`**

At the top of `app.py`, add:
```python
from .deps import (
    _client_ip, _get_auth, _get_auth_sse, _int_param,
    _read_body, _require_admin, _require_operator,
    _require_permission, _run_cmd, _safe_int,
    db,
)
```

Remove the original function definitions (lines 58-63, 160-211, 609-614, 4311-4326).

Update the lifespan function to set `deps.bg_collector`:
```python
import . deps as _deps_mod
_deps_mod.bg_collector = bg_collector
```

- [ ] **Step 3: Verify**

Run: `ruff check share/noba-web/server/deps.py share/noba-web/server/app.py`
Run: `pytest tests/ -x -q`
Expected: All tests pass, no lint errors.

- [ ] **Step 4: Commit**

```
git add share/noba-web/server/deps.py share/noba-web/server/app.py
git commit -m "refactor: extract shared dependencies to deps.py"
```

---

### Task 2: Extract agent data store (`agent_store.py`)

**Files:**
- Create: `share/noba-web/server/agent_store.py`
- Modify: `share/noba-web/server/app.py`
- Modify: `share/noba-web/server/collector.py` (line 349: `from .app import _agent_data, _agent_data_lock, _AGENT_MAX_AGE`)

- [ ] **Step 1: Create `agent_store.py`**

Move from `app.py` lines 45-51:
```python
from __future__ import annotations

import threading

_agent_data: dict[str, dict] = {}
_agent_data_lock = threading.Lock()
_AGENT_MAX_AGE = 120

_agent_commands: dict[str, list] = {}
_agent_cmd_results: dict[str, list] = {}
_agent_cmd_lock = threading.Lock()
```

- [ ] **Step 2: Update imports in `app.py` and `collector.py`**

In `app.py`, replace the globals with:
```python
from .agent_store import (
    _agent_data, _agent_data_lock, _AGENT_MAX_AGE,
    _agent_commands, _agent_cmd_results, _agent_cmd_lock,
)
```

In `collector.py`, update the import (line ~349):
```python
from .agent_store import _agent_data, _agent_data_lock, _AGENT_MAX_AGE
```

- [ ] **Step 3: Verify**

Run: `ruff check share/noba-web/server/agent_store.py share/noba-web/server/app.py share/noba-web/server/collector.py`
Run: `pytest tests/ -x -q`

- [ ] **Step 4: Commit**

```
git add share/noba-web/server/agent_store.py share/noba-web/server/app.py share/noba-web/server/collector.py
git commit -m "refactor: extract agent data store to agent_store.py"
```

---

### Task 3: Extract workflow engine (`workflow_engine.py`)

**Files:**
- Create: `share/noba-web/server/workflow_engine.py`
- Modify: `share/noba-web/server/app.py`
- Modify: `share/noba-web/server/scheduler.py` (lines 110, 198, 300)
- Modify: `share/noba-web/server/alerts.py` (line 165)
- Modify: `share/noba-web/server/hass_bridge.py` (line 76)

- [ ] **Step 1: Create `workflow_engine.py`**

Move from `app.py`:
- `_validate_auto_config()` (lines 1421-1450)
- `_build_auto_script_process()` (lines 1453-1470)
- `_build_auto_webhook_process()` (lines 1473-1487)
- `_build_auto_service_process()` (lines 1490-1500)
- `_build_auto_delay_process()` (lines 1503-1506)
- `_build_auto_http_process()` (lines 1509-1527)
- `_build_auto_notify_process()` (lines 1530-1549)
- `_build_auto_condition_process()` (lines 1552-1574)
- `_AUTO_BUILDERS` dict (lines 1577-1582)
- `_run_workflow()` (lines 1586-1635)
- `_run_parallel_workflow()` (lines 1986-2010)

Include necessary imports at top (subprocess, shlex, threading, logging, etc.) and imports from `.config`, `.db`, `.deps`, `.runner`, `.alerts`.

- [ ] **Step 2: Update deferred imports in consuming modules**

In `scheduler.py`, replace all `from .app import _run_workflow, _AUTO_BUILDERS` (and similar deferred imports at lines 110, 198, 300) with top-level:
```python
from .workflow_engine import _run_workflow, _AUTO_BUILDERS
```

In `alerts.py` (line 165), replace deferred import with:
```python
from .workflow_engine import _run_workflow
```

In `hass_bridge.py` (line 76), replace deferred import with:
```python
from .workflow_engine import _run_workflow
```

In `app.py`, add import and remove the extracted function definitions:
```python
from .workflow_engine import (
    _AUTO_BUILDERS, _run_workflow, _run_parallel_workflow,
    _validate_auto_config,
)
```

- [ ] **Step 3: Verify no deferred imports remain for workflow functions**

Run: `grep -rn "from .app import.*_run_workflow\|from .app import.*_AUTO_BUILDERS" share/noba-web/server/`
Expected: No matches.

- [ ] **Step 4: Verify**

Run: `ruff check share/noba-web/server/workflow_engine.py share/noba-web/server/app.py share/noba-web/server/scheduler.py share/noba-web/server/alerts.py share/noba-web/server/hass_bridge.py`
Run: `pytest tests/ -x -q`

- [ ] **Step 5: Commit**

```
git add share/noba-web/server/workflow_engine.py share/noba-web/server/app.py share/noba-web/server/scheduler.py share/noba-web/server/alerts.py share/noba-web/server/hass_bridge.py
git commit -m "refactor: extract workflow engine from app.py"
```

---

### Task 4: Create router modules (`routers/`)

**Files:**
- Create: `share/noba-web/server/routers/__init__.py`
- Create: `share/noba-web/server/routers/stats.py`
- Create: `share/noba-web/server/routers/auth.py`
- Create: `share/noba-web/server/routers/admin.py`
- Create: `share/noba-web/server/routers/automations.py`
- Create: `share/noba-web/server/routers/integrations.py`
- Create: `share/noba-web/server/routers/system.py`
- Modify: `share/noba-web/server/app.py`

This is the largest task. Each router module follows this pattern:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from ..deps import (
    _client_ip, _get_auth, _get_auth_sse, _read_body,
    _require_admin, _require_operator, db,
)

router = APIRouter()

# Route handlers moved here...
```

- [ ] **Step 1: Create `routers/__init__.py`**

```python
from __future__ import annotations

from fastapi import APIRouter

from .admin import router as admin_router
from .auth import router as auth_router
from .automations import router as automations_router
from .integrations import router as integrations_router
from .stats import router as stats_router
from .system import router as system_router

api_router = APIRouter()
api_router.include_router(stats_router)
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(automations_router)
api_router.include_router(integrations_router)
api_router.include_router(system_router)
```

- [ ] **Step 2: Create `routers/stats.py`**

Move these route handlers from `app.py`:
- `/api/health` (line 246)
- `/api/me` (line 252)
- `/api/permissions` (line 259)
- `/api/plugins` (line 267)
- `/api/stats` (line 273)
- `/api/stream` SSE (line 284)
- `/api/history/*` routes (lines 618-695)
- `/api/metrics/available` (line 677)
- `/api/metrics/prometheus` (line 3050)
- `/api/metrics/correlate` (line 4296)
- `/api/sla/*` routes (lines 2907, 3985)
- `/api/alert-history` (line 2898)
- `/api/notifications/*` routes (lines 3012-3028)
- `/api/dashboard` routes (lines 3035-3041)

- [ ] **Step 3: Create `routers/auth.py`**

Move from `app.py`:
- `/api/login` (line 2238)
- `/api/logout` (line 2296)
- `/api/auth/totp/*` routes (lines 2310-2332)
- `/api/auth/oidc/*` routes (lines 2343-2362)
- `/api/profile/*` routes (lines 2410-2452)
- `/api/admin/users` routes (lines 2058-2063)
- `/api/admin/sessions` routes (lines 2112-2117)
- `/api/admin/api-keys` routes (lines 2131-2157)
- `/api/admin/ssh-keys` routes (lines 2167-2207)

- [ ] **Step 4: Create `routers/admin.py`**

Move from `app.py`:
- `/api/settings` GET/POST (lines 313-318)
- `/api/notifications/test` (line 344)
- `/api/config/*` routes (lines 361, 811, 826)
- `/api/audit` (line 794)
- `/api/backup/*` routes (lines 873-1343) — includes helper functions `_read_state_file`, `_get_backup_dest`, `_safe_snapshot_path`, `_SNAP_RE`
- `/api/log-viewer` (line 1344)
- `/api/action-log` (line 1361)
- `/api/reports/*` routes (lines 3070-3156)
- `/api/plugins/available`, `/api/plugins/install` (lines 3192-3199)
- `/api/runbooks` routes (lines 4268-4280)
- `/api/graylog/search` (line 4253)

- [ ] **Step 5: Create `routers/automations.py`**

Move from `app.py`:
- `/api/automations/*` routes (lines 1638-2053)
- `/api/run-status` (line 1367)
- `/api/runs/*` routes (lines 1380-1408)
- `/api/run` POST (line 2704) — script execution
- `/api/webhook` (line 2649)

Import `_AUTO_BUILDERS`, `_run_workflow`, `_run_parallel_workflow`, `_validate_auto_config` from `workflow_engine`.
Import `_build_command` helper (move to this file or to `deps.py`).

- [ ] **Step 6: Create `routers/integrations.py`**

Move from `app.py`:
- `/api/cameras/snapshot/{cam}` (line 380)
- `/api/tailscale/status` (line 399)
- `/api/disks/intelligence` (line 406)
- `/api/services/dependencies/blast-radius` (line 418)
- `/api/hass/*` routes (lines 2914-2991)
- `/api/pihole/toggle` (line 3366)
- `/api/game-servers` (line 3425)
- `/api/cameras` (line 3447)
- `/api/wol` (line 3215)
- `/api/cloud-remotes/*` routes (lines 562-607)
- `/api/cloud-test` (line 2746)
- `/api/influxdb/query` (line 507)

- [ ] **Step 7: Create `routers/system.py`**

Move from `app.py`:
- `/api/recovery/*` routes (lines 455-527)
- `/api/sites/sync-status` (line 530)
- `/api/smart` (line 556)
- `/api/container-control` (line 2461)
- `/api/containers/*` routes (lines 2489-2585)
- `/api/compose/*` routes (lines 3394-3406)
- `/api/truenas/vm` (line 2615)
- `/api/service-control` (line 2777)
- `/api/network/*` routes (lines 2809-2821)
- `/api/services/map` (line 2844)
- `/api/disks/prediction` (line 3700)
- `/api/uptime` (line 3719)
- `/api/journal/*` routes (lines 3761-3794)
- `/api/system/*` routes (lines 3228-3246, 3813)
- `/api/k8s/*` routes (lines 3459-3572)
- `/api/proxmox/*` routes (lines 3608-3697) — includes `_pmx_headers` helper
- `/api/terminal` WebSocket (line 3850)
- `/api/agent/*` routes (lines 3862-4094)
- `/api/incidents/*` routes (lines 4200-4206)
- `/status` and `/api/status/public` (lines 4215-4221)
- `/api/system/cpu-governor` (line 3228)
- `/api/processes/*` routes (lines 3336-3343)

- [ ] **Step 8: Slim `app.py` to thin shell**

After all routes are extracted, `app.py` should contain only:
- Imports
- `_cleanup_loop()` (background task, lines 70-94)
- `lifespan()` (lines 97-133)
- `app = FastAPI(...)` creation (line 136)
- CORS + security headers middleware (lines 139-156)
- Static file mount + `_CachedStaticFiles` class (lines 214-241)
- Frontend routes: `/`, `/manifest.json`, `/service-worker.js` (lines 216-226)
- `app.include_router(api_router)` — one line

Target: ~150 lines.

- [ ] **Step 9: Verify**

Run: `ruff check share/noba-web/server/`
Run: `pytest tests/ -v`
Expected: All existing tests pass. Entry points `server.app:app` and `server.main:app` still work.

- [ ] **Step 10: Commit**

```
git add share/noba-web/server/routers/ share/noba-web/server/app.py
git commit -m "refactor: split app.py routes into routers/ package"
```

---

### Task 5: Split `db.py` into `db/` package

**Files:**
- Create: `share/noba-web/server/db/__init__.py`
- Create: `share/noba-web/server/db/core.py`
- Create: `share/noba-web/server/db/metrics.py`
- Create: `share/noba-web/server/db/audit.py`
- Create: `share/noba-web/server/db/automations.py`
- Create: `share/noba-web/server/db/alerts.py`
- Remove: `share/noba-web/server/db.py` (replaced by package)

- [ ] **Step 1: Create `db/core.py`**

Move from `db.py`:
- `Database.__init__()` (lines 41-45)
- `Database._get_conn()` (lines 48-55)
- `Database._init_schema()` (lines 57-159)
- The single `_lock` and `_conn` — these stay here
- All imports

Expose `Database` base class with the core methods.

- [ ] **Step 2: Create domain modules**

Each module adds methods to `Database` via mixin pattern or receives `self` (the Database instance):

**`db/metrics.py`** — Move: `insert_metrics` (162-175), `get_history` (177-213), `prune_history` (215-236), `get_trend` (318-361)

**`db/audit.py`** — Move: `audit_log` (255-267), `get_audit` (269-300), `get_login_history` (302-316), `prune_audit` (238-252)

**`db/automations.py`** — Move: all automation CRUD (364-473), job runs (476-646), API keys (747-817), notifications (820-908), dashboards (911-955)

**`db/alerts.py`** — Move: alert history (649-710), SLA (712-744), incidents (959-998)

Implementation approach: Keep `Database` as a single class in `core.py`. Domain modules contain standalone functions that accept `(conn, lock)` as parameters. The `Database` class methods delegate to these functions:

```python
# db/metrics.py
def insert_metrics(conn, lock, ts, flat):
    with lock:
        conn.executemany(...)

# db/core.py (Database class)
from .metrics import insert_metrics as _insert_metrics

class Database:
    def insert_metrics(self, ts, flat):
        _insert_metrics(self._conn, self._lock, ts, flat)
```

- [ ] **Step 3: Create `db/__init__.py`**

```python
from __future__ import annotations

from .core import Database

db = Database()

__all__ = ["Database", "db"]
```

This preserves `from .db import db` in all existing code.

- [ ] **Step 4: Remove old `db.py`**

Delete `share/noba-web/server/db.py` — the `db/` package replaces it.

- [ ] **Step 5: Verify**

Run: `pytest tests/test_db.py tests/test_new_db.py -v`
Run: `pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```
git add share/noba-web/server/db/ && git rm share/noba-web/server/db.py
git commit -m "refactor: split db.py into db/ package with domain modules"
```

---

### Task 6: Split `integrations.py` into `integrations/` package

**Files:**
- Create: `share/noba-web/server/integrations/__init__.py`
- Create: `share/noba-web/server/integrations/base.py`
- Create: `share/noba-web/server/integrations/simple.py`
- Create: `share/noba-web/server/integrations/unifi.py`
- Create: `share/noba-web/server/integrations/qbittorrent.py`
- Create: `share/noba-web/server/integrations/pihole.py`
- Create: `share/noba-web/server/integrations/proxmox.py`
- Create: `share/noba-web/server/integrations/hass.py`
- Remove: `share/noba-web/server/integrations.py`

- [ ] **Step 1: Create `integrations/base.py`**

Contains:
- Shared `_client` (httpx.Client with connection pooling — moved from line 19-27)
- `_http_get()` helper (lines 30-33)
- `BaseIntegration` class:

```python
from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("noba")

_client = httpx.Client(
    timeout=httpx.Timeout(4.0, connect=3.0),
    limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
    follow_redirects=True,
)


class TransientError(Exception):
    """Retryable error (timeout, 5xx)."""

class ConfigError(Exception):
    """Non-retryable error (401, bad URL)."""


class BaseIntegration:
    def __init__(self, url, *, headers=None, auth=None,
                 timeout=4, retries=2, cache_ttl=0, client=None):
        if url and not urlparse(url).scheme in ("http", "https"):
            raise ConfigError(f"Invalid URL scheme: {url}")
        self.url = (url or "").rstrip("/")
        self.headers = headers or {}
        self.auth = auth
        self.timeout = timeout
        self.retries = retries
        self.cache_ttl = cache_ttl
        self._client = client or _client
        self._cache = {}

    def get(self, endpoint, **kwargs):
        cache_key = f"{self.url}{endpoint}"
        if self.cache_ttl:
            cached = self._cache.get(cache_key)
            if cached and time.time() - cached["t"] < self.cache_ttl:
                return cached["data"]

        last_err = None
        for attempt in range(self.retries + 1):
            try:
                r = self._client.get(
                    f"{self.url}{endpoint}",
                    headers=self.headers,
                    auth=self.auth,
                    timeout=self.timeout,
                    **kwargs,
                )
                if r.status_code in (401, 403):
                    raise ConfigError(f"Auth failed: {r.status_code}")
                r.raise_for_status()
                data = r.json()
                if self.cache_ttl:
                    self._cache[cache_key] = {"t": time.time(), "data": data}
                return data
            except ConfigError:
                raise
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                last_err = e
                if attempt < self.retries:
                    time.sleep(0.5 * (2 ** attempt))
            except Exception as e:
                last_err = e
                break
        logger.debug("Integration %s failed: %s", self.url, last_err)
        return None
```

- [ ] **Step 2: Create per-service modules**

**`integrations/simple.py`** — All ~20 simple `get_*` functions that use patterns 1-3 (no auth, header token, basic auth) with the shared `_client`. Move them as-is from `integrations.py`, importing `_client` and `_http_get` from `.base`.

**`integrations/unifi.py`** — `get_unifi()` (lines 431-460), `get_unifi_protect()` (lines 927-953). These create dedicated httpx clients.

**`integrations/qbittorrent.py`** — `get_qbit()` (lines 205-238). Creates dedicated client for cookie auth.

**`integrations/pihole.py`** — `get_pihole()` (lines 63-119), `_pihole_v6_auth()` (lines 44-59), session state (lines 40-41). Most complex integration.

**`integrations/proxmox.py`** — `get_proxmox()` (lines 242-281). Token-based auth with custom header format.

**`integrations/hass.py`** — `get_hass()` (lines 328-350), `get_hass_entities()` (lines 353-402), `get_hass_services()` (lines 405-427). Bearer token pattern.

- [ ] **Step 3: Create `integrations/__init__.py`**

Re-export ALL `get_*` functions AND `_client`:

```python
from .base import _client, BaseIntegration, TransientError, ConfigError
from .simple import (
    get_adguard, get_authentik, get_cloudflare, get_energy_shelly,
    get_esphome, get_frigate, get_gitea, get_github, get_gitlab,
    get_graylog, get_homebridge, get_jellyfin, get_k8s, get_kuma,
    get_nextcloud, get_npm, get_omv, get_overseerr, get_paperless,
    get_pikvm, get_plex, get_prowlarr, get_scrutiny,
    get_scrutiny_intelligence, get_servarr, get_servarr_calendar,
    get_servarr_extended, get_speedtest, get_tautulli, get_traefik,
    get_truenas, get_vaultwarden, get_weather, get_xcpng, get_z2m,
    query_influxdb,
)
from .unifi import get_unifi, get_unifi_protect
from .qbittorrent import get_qbit
from .pihole import get_pihole
from .proxmox import get_proxmox
from .hass import get_hass, get_hass_entities, get_hass_services

__all__ = [...]  # list all exports
```

- [ ] **Step 4: Remove old `integrations.py`**

- [ ] **Step 5: Verify**

Run: `pytest tests/test_integrations.py -v`
Run: `pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```
git add share/noba-web/server/integrations/ && git rm share/noba-web/server/integrations.py
git commit -m "refactor: split integrations.py into integrations/ package with BaseIntegration"
```

---

### Task 7: Split `metrics.py` into `metrics/` package

**Files:**
- Create: `share/noba-web/server/metrics/__init__.py`
- Create: `share/noba-web/server/metrics/system.py`
- Create: `share/noba-web/server/metrics/hardware.py`
- Create: `share/noba-web/server/metrics/network.py`
- Create: `share/noba-web/server/metrics/storage.py`
- Create: `share/noba-web/server/metrics/services.py`
- Create: `share/noba-web/server/metrics/util.py`
- Remove: `share/noba-web/server/metrics.py`

- [ ] **Step 1: Create `metrics/util.py`**

Move shared infrastructure:
- `strip_ansi()` (lines 24-25)
- `_read_file()` (lines 28-33)
- `TTLCache` class (lines 37-62)
- `_cache` singleton (line 65)
- `_run()` subprocess helper (lines 68-83)
- `validate_ip()` (lines 87-92)
- `validate_service_name()` (lines 95-96)
- `_fmt_bytes()` (lines 331-336)

- [ ] **Step 2: Create domain modules**

**`metrics/system.py`** — CPU state + locks (lines 100-101), `get_cpu_percent` (104-108), `get_cpu_history` (111-113), `get_cpu_governor` (699-700), `collect_system` (162-206).

**`metrics/hardware.py`** — `collect_hardware` (210-261), `_collect_battery` (264-290), `collect_smart` (517-610), `get_ipmi_sensors` (781-806).

**`metrics/network.py`** — Net state + locks (117-127), `get_net_io` (130-150), `human_bps` (153-158), `collect_network` (340-385), `collect_per_interface_net` (414-435), `get_network_connections` (809-831), `get_listening_ports` (834-860), `ping_host` (466-475), `check_device_presence` (756-778), `check_cert_expiry` (627-646), `check_domain_expiry` (650-676), `get_vpn_status` (680-695).

**`metrics/storage.py`** — Disk I/O state + locks (122-124), `collect_storage` (294-328), `collect_disk_io` (389-410), `get_rclone_remotes` (614-623).

**`metrics/services.py`** — `get_service_status` (439-462), `get_containers` (479-509), `bust_container_cache` (512-513), `check_docker_updates` (720-749), `send_wol` (704-716), `snapshot_top_processes` (880-900), `get_process_history` (903-906), `probe_game_server` (863-872), `query_source_server` (909-948).

- [ ] **Step 3: Create `metrics/__init__.py`**

Re-export everything used by `collector.py` and `app.py`:

```python
from .util import strip_ansi, _read_file, validate_ip, validate_service_name, _fmt_bytes, TTLCache
from .system import collect_system, get_cpu_percent, get_cpu_history, get_cpu_governor
from .hardware import collect_hardware, collect_smart, get_ipmi_sensors
from .network import (collect_network, collect_per_interface_net, get_net_io, human_bps,
                      get_network_connections, get_listening_ports, ping_host,
                      check_device_presence, check_cert_expiry, check_domain_expiry, get_vpn_status)
from .storage import collect_storage, collect_disk_io, get_rclone_remotes
from .services import (get_service_status, get_containers, bust_container_cache,
                       check_docker_updates, send_wol, snapshot_top_processes,
                       get_process_history, probe_game_server, query_source_server)
```

- [ ] **Step 4: Remove old `metrics.py`, verify**

Run: `pytest tests/test_metrics.py tests/test_metrics_new.py -v`
Run: `pytest tests/ -x -q`

- [ ] **Step 5: Commit**

```
git add share/noba-web/server/metrics/ && git rm share/noba-web/server/metrics.py
git commit -m "refactor: split metrics.py into metrics/ package"
```

---

### Task 8: Phase 1 Checkpoint

- [ ] **Step 1: Full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 2: Lint check**

Run: `ruff check share/noba-web/server/`
Expected: Clean.

- [ ] **Step 3: Verify no file exceeds 600 lines**

Run: `find share/noba-web/server -name '*.py' -exec wc -l {} + | sort -n | tail -20`
Expected: No file over 600 lines.

- [ ] **Step 4: Verify no deferred imports from app remain**

Run: `grep -rn "from .app import" share/noba-web/server/ --include="*.py" | grep -v "from .app import app"`
Expected: No matches (only `from .app import app` in `main.py` is allowed).

- [ ] **Step 5: Commit checkpoint**

```
git commit --allow-empty -m "checkpoint: Phase 1 complete — backend module splitting done"
```

---

## Phase 2: Frontend Cleanup

---

### Task 9: Split `actions-mixin.js` into 4 files

**Files:**
- Modify: `share/noba-web/static/actions-mixin.js` (slim to ~400 lines)
- Create: `share/noba-web/static/integration-actions.js`
- Create: `share/noba-web/static/automation-actions.js`
- Create: `share/noba-web/static/system-actions.js`
- Modify: `share/noba-web/index.html` (add script tags)

- [ ] **Step 1: Create `integration-actions.js`**

Create function `integrationActionsMixin()` returning object with:
- `svcAction()`, `vmAction()`, `triggerWebhook()` (lines 112-191)
- `containerAction()` (lines 329-358)
- `hassToggle()`, `fetchHassEntities()`, `hassToggleEntity()` (lines 1463-1781)
- Docker deep management (lines 1794-1843)
- Kubernetes methods (lines 1856-1922)
- Proxmox methods (lines 1932-1976)
- Docker Compose methods (lines 1521-1547)
- `sendWol()` (lines 1482-1495)
- `toggleDns()` (lines 1500-1513)
- `setCpuGovernor()` (lines 1589-1603)
- `fetchAlertHistory()` (lines 1556-1566)
- Agent command methods (lines 2518-2645)

- [ ] **Step 2: Create `automation-actions.js`**

Create function `automationActionsMixin()` returning object with:
- Automation CRUD (lines 1103-1201)
- `openRunDetail()` (line 1203)
- Job notification poller (lines 1241-1288)
- Templates & stats (lines 1291-1388)
- `runAutomation()` (lines 1390-1457)
- Workflow trace & validation (lines 2125-2153)
- All automation state properties (`autoForm*`, `autoTemplates`, etc.)

- [ ] **Step 3: Create `system-actions.js`**

Create function `systemActionsMixin()` returning object with:
- History & metrics (lines 362-592)
- Audit log (lines 489-559)
- Config backup/restore (lines 594-771)
- Layout backup/restore (lines 774-821)
- SMART disk health (lines 699-738)
- Backup explorer (lines 825-1024)
- Session management (lines 1027-1077)
- Alert rules (lines 2057-2123)
- System health, network, processes, journal (lines 2258-2412)
- Disk prediction, incidents, runbooks, Graylog (lines 2389-2748)
- Backup scheduling (lines 2196-2247)
- InfluxDB/Blast radius (lines 2469-2515)
- User profile (lines 2155-2193)
- API keys, TOTP (lines 1605-1707)
- All related state properties

- [ ] **Step 4: Slim `actions-mixin.js` to core only**

Keep in `actionsMixin()`:
- `fetchLog()` (lines 61-84)
- `requestConfirm()` / `runConfirmedAction()` (lines 90-103)
- `runScript()` / `cancelActiveRun()` (lines 200-278)
- `openRunHistory()` / `fetchRunHistory()` (lines 287-322)
- `exportChart()` (line 1720)
- `fmtRunTime()`, `runStatusClass()`, `fmtDuration()`, `fmtFileSize()` — shared formatters
- Core state properties (modal, running script, job runner)

- [ ] **Step 5: Update `index.html` — add script tags**

Find the existing script tags section and add before `actions-mixin.js`:
```html
<script src="/static/integration-actions.js"></script>
<script src="/static/automation-actions.js"></script>
<script src="/static/system-actions.js"></script>
```

- [ ] **Step 6: Update `app.js` — spread new mixins in `dashboard()`**

```javascript
return {
    ...authMixin(),
    ...actionsMixin(),
    ...integrationActionsMixin(),
    ...automationActionsMixin(),
    ...systemActionsMixin(),
    // ...rest of dashboard properties
```

- [ ] **Step 7: Verify**

Run: `node -c share/noba-web/static/actions-mixin.js`
Run: `node -c share/noba-web/static/integration-actions.js`
Run: `node -c share/noba-web/static/automation-actions.js`
Run: `node -c share/noba-web/static/system-actions.js`
Run: `node -c share/noba-web/static/app.js`
Expected: All syntax checks pass.

- [ ] **Step 8: Commit**

```
git add share/noba-web/static/ share/noba-web/index.html
git commit -m "refactor: split actions-mixin.js into 4 domain-specific files"
```

---

### Task 10: Add interval registry and request deduplication

**Files:**
- Modify: `share/noba-web/static/app.js`

- [ ] **Step 1: Add interval registry**

In `dashboard()` return object, add state and helper methods:

```javascript
_intervals: {},
_pending: {},

_registerInterval(name, fn, ms) {
    if (this._intervals[name]) clearInterval(this._intervals[name]);
    this._intervals[name] = setInterval(fn, ms);
},
_clearInterval(name) {
    if (this._intervals[name]) {
        clearInterval(this._intervals[name]);
        delete this._intervals[name];
    }
},
_clearAllIntervals() {
    Object.keys(this._intervals).forEach(k => {
        clearInterval(this._intervals[k]);
        delete this._intervals[k];
    });
},
```

- [ ] **Step 2: Replace all raw `setInterval` calls with `_registerInterval`**

In `app.js`:
- `_logTimer` (line 562) → `this._registerInterval('log', () => {...}, 12000)`
- `_cloudTimer` (line 567) → `this._registerInterval('cloud', () => {...}, 300000)`
- `_heartbeatTimer` (line 573) → `this._registerInterval('heartbeat', () => {...}, 5000)`
- `_countdownTimer` (line 818) → `this._registerInterval('countdown', () => {...}, 1000)`
- `_poll` (line 923) → `this._registerInterval('poll', () => {...}, 5000)`

In `actions-mixin.js` and sub-mixins:
- Job polling intervals → `this._registerInterval('job_poll', ...)`
- Automation polling → `this._registerInterval('auto_poll', ...)`
- Job notif poller → `this._registerInterval('job_notif', ...)`

- [ ] **Step 3: Update `logout()` in auth-mixin.js**

Replace individual `clearInterval` calls with:
```javascript
this._clearAllIntervals();
```

- [ ] **Step 4: Add request deduplication**

```javascript
_deduplicatedFetch(url, opts) {
    const key = url + (opts?.method || 'GET');
    if (this._pending[key]) return this._pending[key];
    this._pending[key] = fetch(url, opts).finally(() => delete this._pending[key]);
    return this._pending[key];
},
```

Replace `fetch(` with `this._deduplicatedFetch(` in:
- `refreshStats()` in `app.js`
- `fetchHistory()` in `system-actions.js`
- `fetchAuditLog()` in `system-actions.js`

- [ ] **Step 5: Verify**

Run: `node -c share/noba-web/static/app.js`
Run: `node -c share/noba-web/static/auth-mixin.js`
Run: `node -c share/noba-web/static/actions-mixin.js`

- [ ] **Step 6: Commit**

```
git add share/noba-web/static/
git commit -m "fix: add interval registry and request deduplication to frontend"
```

---

## Phase 3: Input Validation & Caching

---

### Task 11: Settings validation with Pydantic

**Files:**
- Create: `share/noba-web/server/schemas.py`
- Modify: `share/noba-web/server/routers/admin.py` (settings POST handler)

- [ ] **Step 1: Create `schemas.py` with settings model**

```python
from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator


class SettingsUpdate(BaseModel, extra="allow"):
    """Validates settings written via POST /api/settings.
    Uses extra='allow' since settings keys are dynamic,
    but validates URL fields explicitly."""

    @field_validator("*", mode="before")
    @classmethod
    def validate_url_fields(cls, v, info):
        if info.field_name and info.field_name.endswith(("Url", "_url", "URL")):
            if isinstance(v, str) and v.strip():
                parsed = urlparse(v.strip())
                if parsed.scheme not in ("http", "https", ""):
                    raise ValueError(
                        f"Invalid URL scheme '{parsed.scheme}' — must be http or https"
                    )
        return v


_SECRET_PATTERNS = re.compile(
    r"(token|key|pass|secret|password|credential|auth)", re.IGNORECASE
)


def is_secret_key(key: str) -> bool:
    return bool(_SECRET_PATTERNS.search(key))
```

- [ ] **Step 2: Apply validation in settings POST handler**

In `routers/admin.py`, update the `api_settings_post` handler to validate URL fields before writing. Use `is_secret_key()` for audit masking.

- [ ] **Step 3: Verify**

Run: `pytest tests/ -x -q`
Run: `ruff check share/noba-web/server/schemas.py`

- [ ] **Step 4: Commit**

```
git add share/noba-web/server/schemas.py share/noba-web/server/routers/admin.py
git commit -m "feat: add Pydantic settings validation and URL scheme enforcement"
```

---

### Task 12: Verify YAML cache invalidation

**Files:**
- Modify: `share/noba-web/server/yaml_config.py` (if needed)

- [ ] **Step 1: Read `yaml_config.py` and verify cache invalidation path**

Check that `write_yaml_settings()` clears the cache after writing. The 2s TTL cache already exists — verify it works correctly.

- [ ] **Step 2: If invalidation is missing, add it**

After the YAML write in `write_yaml_settings()`:
```python
_settings_cache.clear()  # or whatever the cache variable is named
```

- [ ] **Step 3: Commit if changes were needed**

```
git add share/noba-web/server/yaml_config.py
git commit -m "fix: ensure YAML cache invalidation on settings write"
```

---

## Phase 4: Pre-aggregated Metrics

---

### Task 13: Add rollup tables and aggregation

**Files:**
- Modify: `share/noba-web/server/db/core.py` (add tables to schema)
- Modify: `share/noba-web/server/db/metrics.py` (add rollup functions)
- Modify: `share/noba-web/server/collector.py` (trigger aggregation after insert)

- [ ] **Step 1: Add `metrics_1m` and `metrics_1h` tables to schema**

In `db/core.py` `_init_schema()`, add:
```sql
CREATE TABLE IF NOT EXISTS metrics_1m (
    ts INTEGER NOT NULL,
    key TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (ts, key)
);
CREATE TABLE IF NOT EXISTS metrics_1h (
    ts INTEGER NOT NULL,
    key TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (ts, key)
);
```

- [ ] **Step 2: Add rollup functions in `db/metrics.py`**

```python
def rollup_to_1m(conn, lock):
    """Aggregate raw metrics into 1-minute buckets."""
    now = int(time.time())
    minute_ts = now - (now % 60) - 60  # previous complete minute
    with lock:
        conn.execute("""
            INSERT OR REPLACE INTO metrics_1m (ts, key, value)
            SELECT ? , key, AVG(value)
            FROM metrics
            WHERE ts >= ? AND ts < ?
            GROUP BY key
        """, (minute_ts, minute_ts, minute_ts + 60))
        conn.commit()


def rollup_to_1h(conn, lock):
    """Aggregate 1m metrics into 1-hour buckets."""
    now = int(time.time())
    hour_ts = now - (now % 3600) - 3600  # previous complete hour
    with lock:
        conn.execute("""
            INSERT OR REPLACE INTO metrics_1h (ts, key, value)
            SELECT ?, key, AVG(value)
            FROM metrics_1m
            WHERE ts >= ? AND ts < ?
            GROUP BY key
        """, (hour_ts, hour_ts, hour_ts + 3600))
        conn.commit()


def prune_rollups(conn, lock):
    """Enforce retention: 7 days for 1m, 90 days for 1h."""
    now = int(time.time())
    with lock:
        conn.execute("DELETE FROM metrics_1m WHERE ts < ?", (now - 7 * 86400,))
        conn.execute("DELETE FROM metrics_1h WHERE ts < ?", (now - 90 * 86400,))
        conn.commit()


def catchup_rollups(conn, lock):
    """On startup, fill any gaps in rollup tables."""
    now = int(time.time())
    with lock:
        row = conn.execute("SELECT MAX(ts) FROM metrics_1m").fetchone()
        last_1m = row[0] if row and row[0] else now - 3600
        # Roll up each missing minute
        for ts in range(last_1m + 60, now, 60):
            conn.execute("""
                INSERT OR IGNORE INTO metrics_1m (ts, key, value)
                SELECT ?, key, AVG(value)
                FROM metrics WHERE ts >= ? AND ts < ?
                GROUP BY key
            """, (ts, ts, ts + 60))
        conn.commit()
```

- [ ] **Step 3: Update `get_history()` to query appropriate table**

```python
def get_history(conn, lock, metric, hours=24, resolution=60):
    if hours <= 1:
        table = "metrics"
    elif hours <= 168:  # 7 days
        table = "metrics_1m"
    else:
        table = "metrics_1h"
    # Query from selected table...
```

- [ ] **Step 4: Trigger rollup after metric insert in collector**

In `collector.py`, after `db.insert_metrics()`:
```python
if int(time.time()) % 60 < bg_collector.interval:
    db.rollup_to_1m()
if int(time.time()) % 3600 < bg_collector.interval:
    db.rollup_to_1h()
```

Call `db.catchup_rollups()` during lifespan startup.

- [ ] **Step 5: Verify**

Run: `pytest tests/test_db.py -v`
Run: `pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```
git add share/noba-web/server/db/ share/noba-web/server/collector.py share/noba-web/server/app.py
git commit -m "feat: add pre-aggregated metrics tables with 1m/1h rollups"
```

---

## Phase 5: Test Coverage

---

### Task 14: Tests for new modules

**Files:**
- Create: `tests/test_integration_base.py`
- Create: `tests/test_workflow_engine.py`
- Create: `tests/test_db_concurrent.py`
- Create: `tests/test_settings_validation.py`

- [ ] **Step 1: Write `test_integration_base.py`**

Test `BaseIntegration`:
- Retry on timeout (mock httpx to raise TimeoutException first, succeed second)
- ConfigError on 401 (no retry)
- Cache TTL (second call within TTL returns cached data)
- URL scheme validation (reject `file://`)
- `None` return on exhausted retries

- [ ] **Step 2: Write `test_workflow_engine.py`**

Test:
- `_validate_auto_config()` with valid/invalid configs
- `_build_auto_script_process()` returns correct subprocess args
- `_AUTO_BUILDERS` has all expected keys

- [ ] **Step 3: Write `test_db_concurrent.py`**

Test concurrent metric inserts:
```python
import threading

def test_concurrent_inserts(tmp_db):
    threads = []
    for i in range(10):
        t = threading.Thread(target=tmp_db.insert_metrics, args=(time.time() + i, {"cpu": i}))
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    history = tmp_db.get_history("cpu", hours=1)
    assert len(history) == 10
```

- [ ] **Step 4: Write `test_settings_validation.py`**

Test `schemas.py`:
- Valid HTTP URL passes
- `file://` URL raises validation error
- `is_secret_key()` matches token/key/pass/secret variations
- Empty URL passes (integrations are optional)

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -v`
Expected: All tests pass including new ones.

- [ ] **Step 6: Commit**

```
git add tests/
git commit -m "test: add tests for BaseIntegration, workflow engine, concurrent DB, settings validation"
```

---

### Task 15: Final Verification

- [ ] **Step 1: Full test suite**

Run: `pytest tests/ -v`

- [ ] **Step 2: Full lint**

Run: `ruff check share/noba-web/server/`

- [ ] **Step 3: JS syntax check**

Run: `for f in share/noba-web/static/*.js; do node -c "$f"; done`

- [ ] **Step 4: File size check**

Run: `find share/noba-web/server -name '*.py' -exec wc -l {} + | sort -rn | head -20`
Run: `wc -l share/noba-web/static/*.js`
Expected: No file over 600 lines.

- [ ] **Step 5: Import cycle check**

Run: `python3 -c "from server.app import app; print('OK')"` (from `share/noba-web/`)
Expected: No circular import errors.

- [ ] **Step 6: Deferred import check**

Run: `grep -rn "from \.app import\|from \.integrations import\|from \.db import\|from \.metrics import" share/noba-web/server/ --include="*.py" | grep -v __init__ | grep -v "^.*:.*from \.\(app\|db\|integrations\|metrics\) import"` to find unexpected patterns.

- [ ] **Step 7: Final commit**

```
git commit --allow-empty -m "checkpoint: all 5 phases complete — maintainability overhaul done"
```
