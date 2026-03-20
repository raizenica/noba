# NOBA Maintainability Overhaul — Design Spec

**Date:** 2026-03-20
**Branch:** `refactor/maintainability-overhaul`
**Goal:** Decompose oversized modules, standardize patterns, add validation and caching, improve test coverage — preparing the codebase for round 4 feature work.

---

## Motivation

The NOBA codebase has grown organically to ~183 files. Several core modules have crossed maintainability thresholds:

- `app.py` — 4,326 lines, 211 route handlers + automation engine + shared state
- `actions-mixin.js` — 2,751 lines, mixed concerns
- `integrations.py` — 1,394 lines, 40+ integration functions with repetitive patterns
- `db.py` — 1,002 lines, all database operations in one class
- `metrics.py` — 997 lines, scattered metric collection logic

Before adding round 4 features, the codebase needs to be easier to navigate, test, and extend.

---

## Phase 1: Backend Module Splitting

### 1a. Route Decomposition (`app.py` → `routers/`)

**Note:** An empty `routers/` directory already exists — we use that (FastAPI convention), not `routes/`.

Split `app.py` into focused FastAPI APIRouter modules:

| Module | Responsibility | Key Routes |
|--------|---------------|------------|
| `routers/__init__.py` | Router registration | Imports and includes all routers |
| `routers/stats.py` | Live data + history | `/api/stats`, `/api/stream`, `/api/history/*` |
| `routers/auth.py` | Auth flows + user mgmt | `/api/login`, `/api/logout`, `/api/oidc/*`, `/api/users/*` |
| `routers/admin.py` | Config + audit | `/api/settings`, `/api/audit`, `/api/config/*`, `/api/backup/*` |
| `routers/automations.py` | Automation routes only | `/api/automations/*`, `/api/jobs/*`, `/api/workflows/*` |
| `routers/integrations.py` | Service-specific | `/api/cameras/*`, `/api/services/*`, `/api/recovery/*` |
| `routers/system.py` | Infrastructure | `/api/disks/*`, `/api/tailscale/*`, `/api/docker/*`, `/api/sites/*` |

`app.py` becomes a thin shell (~100 lines): creates `FastAPI()`, mounts static files, includes routers, starts background tasks. Entry points `server.app:app` and `server.main:app` remain functional.

### 1a-ii. Shared Dependencies (`deps.py`)

Extract from `app.py` into a new `deps.py`:

- **Helpers:** `_read_body()`, `_client_ip()` (~30+ call sites each across route modules)
- **Auth dependencies:** `_get_auth`, `_require_operator`, `_require_admin`, `_get_auth_sse` (re-exported from `auth.py`)
- **Background collector reference:** global `bg_collector` instance
- **Database singleton:** `db` reference

All route modules import from `deps.py`, never from each other.

### 1a-iii. Automation Engine Extraction (`workflow_engine.py`)

`app.py` contains ~430 lines of non-route automation logic that `scheduler.py`, `alerts.py`, and `hass_bridge.py` import via deferred imports:

- `_AUTO_BUILDERS` (dispatch table for automation types)
- `_run_workflow()` / `_run_parallel_workflow()`
- Seven `_build_auto_*_process()` builder functions

These move to a new `workflow_engine.py` module. The deferred imports in `scheduler.py` (lines 110, 198, 300), `alerts.py` (line 165), and `hass_bridge.py` (line 76) update to import from `workflow_engine` instead.

### 1a-iv. Agent Data Store (`agent_store.py`)

`app.py` lines 46-51 define mutable globals:
- `_agent_data`, `_agent_data_lock`
- `_agent_commands`, `_agent_commands_lock`
- `_agent_cmd_results`, `_agent_cmd_results_lock`
- `_AGENT_MAX_AGE`

These are accessed by `collector.py` (line 349). They move to `agent_store.py` — a small module with only the stores and their locks. Both route modules and `collector.py` import from there.

### 1b. Database Decomposition (`db.py` → `db/`)

| Module | Responsibility |
|--------|---------------|
| `db/__init__.py` | Re-exports `NoboDB` + `db` singleton for backward compat |
| `db/core.py` | Connection, WAL setup, migrations, single `_lock` + `_conn` |
| `db/metrics.py` | `insert_metrics()`, `get_history()`, aggregation queries |
| `db/audit.py` | `log_audit()`, `get_audit()`, changelog |
| `db/automations.py` | Automation CRUD, job history, workflow state |
| `db/alerts.py` | Alert state, incident tracking |

The `NoboDB` class remains as the public API but delegates to domain modules internally. The **single lock and single connection remain in `db/core.py`** and are passed to domain modules — no per-domain connections. All existing call sites (`from .db import db`) continue to work via `db/__init__.py`.

### 1c. Integration Framework (`integrations.py` → `integrations/`)

```
integrations/
    __init__.py      — re-exports all get_* functions AND _client (backward compat)
    base.py          — BaseIntegration class
    unifi.py         — dedicated httpx client (cookie auth)
    qbittorrent.py   — dedicated httpx client (cookie session)
    pihole.py        — session manager with 5-min TTL, v6/v5 fallback
    proxmox.py       — token-based auth
    hass.py          — Home Assistant (entity/service loading)
    simple.py        — all simple HTTP integrations (Frigate, Scrutiny, Plex, Sonarr, etc.)
```

**`BaseIntegration` provides:**
- Configurable retries (default 2) with exponential backoff
- Error categorization: `TransientError` (timeout, 5xx) vs `ConfigError` (401, bad URL) vs unexpected
- Response normalization: consistent `{"online": bool, "data": {...}}` shape
- Optional TTL cache: skip re-fetch if data is < N seconds old
- URL validation: reject non-HTTP schemes at construction time

**Connection pool strategy:** A module-level shared `httpx.Client` (like today's `_client`) lives in `base.py`. Simple integrations use this shared pool. Complex integrations (UniFi, qBittorrent, Pi-hole) create dedicated clients as they do today. This preserves the current pooling behavior.

**Auth pattern coverage (6 patterns identified):**
1. No auth — base class, no headers
2. Header token (X-Plex-Token, X-Api-Key, Bearer) — base class with `headers` param
3. Basic auth — base class with `auth` param
4. Session/cookie with dedicated client — subclass (UniFi, qBittorrent, Homebridge, OMV, UniFi Protect)
5. Custom session cache — subclass (Pi-hole v6 with TTL)
6. External API with non-standard auth — base class with custom headers

~20 of 37 integrations use patterns 1-3 and fit `BaseIntegration` directly.

**`__init__.py`** re-exports all `get_*` functions AND `_client` (used by `app.py` lifespan for cleanup) so `collector.py` and `app.py` import paths don't change.

### 1d. Metrics Decomposition (`metrics.py` → `metrics/`)

`metrics.py` at 997 lines exceeds the 600-line target. Contains 5 conceptual groups:

| Module | Responsibility |
|--------|---------------|
| `metrics/__init__.py` | Re-exports for backward compat |
| `metrics/system.py` | CPU, memory, swap, load, uptime |
| `metrics/hardware.py` | Temperature sensors, SMART data, GPU |
| `metrics/network.py` | Network interfaces, connections, listening ports |
| `metrics/storage.py` | Disk usage, mounts, ZFS |
| `metrics/services.py` | Containers, processes, game servers, WoL |

---

## Phase 2: Frontend Cleanup

### 2a. Actions Mixin Split (`actions-mixin.js` → 4 files)

| File | Responsibility | Est. Lines |
|------|---------------|------------|
| `actions-mixin.js` | Core action dispatch, shared modal logic | ~400 |
| `integration-actions.js` | Service controls, integration modals | ~800 |
| `automation-actions.js` | Workflow builder, job management, cron | ~800 |
| `system-actions.js` | Docker, backup, recovery, disk ops | ~750 |

Loaded via spread: `...integrationActionsMixin()`, etc. in `dashboard()`.

**HTML loading:** `index.html` gets 3 additional `<script>` tags before `app.js`, in dependency order:
1. `integration-actions.js`
2. `automation-actions.js`
3. `system-actions.js`
4. `actions-mixin.js` (base, after the others since it may reference them)
5. `auth-mixin.js`
6. `app.js`

Alpine.js component initialization (`dashboard()`) spreads all mixins — order of spread does not affect Alpine.js, only script loading order matters.

### 2b. Interval Lifecycle Management

**Problem:** 8 intervals set across app.js and mixins. Only 3 cleared on logout.

**Solution:** Central interval registry in `app.js`:

```javascript
_registerInterval(name, fn, ms) {
    if (this._intervals[name]) clearInterval(this._intervals[name]);
    this._intervals[name] = setInterval(fn, ms);
},
_clearAllIntervals() {
    Object.keys(this._intervals).forEach(k => {
        clearInterval(this._intervals[k]);
        delete this._intervals[k];
    });
}
```

Called from `logout()` and component teardown.

### 2c. Request Deduplication

```javascript
_deduplicatedFetch(url, opts) {
    if (this._pending[url]) return this._pending[url];
    this._pending[url] = fetch(url, opts).finally(() => delete this._pending[url]);
    return this._pending[url];
}
```

Applied to `refreshStats()`, `loadHistory()`, and other frequently-called endpoints.

---

## Phase 3: Input Validation & Caching

### 3a. Settings Validation

Add a Pydantic model for the settings schema. Applied on `POST /api/settings`:
- Type-check all fields
- Reject unknown keys
- Validate integration URLs: must be `http://` or `https://` scheme
- Broader secret detection for audit masking: check if any segment of the key matches secret patterns

### 3b. YAML Settings Cache Enhancement

**Existing state:** `yaml_config.py` already implements a 2-second TTL cache (line 22: `_SETTINGS_CACHE_TTL = 2.0`).

**Changes:** The existing cache is already functional. We keep the 2s TTL (sufficient for the 5s collection interval). The only addition is ensuring `write_yaml_settings()` properly invalidates the cache (verify this path).

### 3c. Integration URL Validation

At settings write time (not just read time):
- Require `http://` or `https://` scheme
- Reject `file://`, `ftp://`, `gopher://`, etc.
- Validate URL is parseable

Phase 3 is largely independent of Phase 1 — it touches `yaml_config.py` (standalone) and the settings route handler. Can begin in parallel.

---

## Phase 4: Pre-aggregated Metrics

### New Tables

```sql
CREATE TABLE IF NOT EXISTS metrics_1m (
    ts INTEGER NOT NULL,       -- unix timestamp, rounded to minute
    key TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (ts, key)
);

CREATE TABLE IF NOT EXISTS metrics_1h (
    ts INTEGER NOT NULL,       -- unix timestamp, rounded to hour
    key TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (ts, key)
);
```

### Aggregation

After each raw metric insert, a background task:
1. Rolls up the last minute into `metrics_1m` (AVG per key)
2. Every hour, rolls up `metrics_1m` into `metrics_1h`

**Catch-up on restart:** On startup, check for gaps between last rollup timestamp and current time. Run catch-up aggregation for any missed intervals before resuming normal schedule.

### Retention

- Raw metrics: 24 hours (existing)
- `metrics_1m`: 7 days
- `metrics_1h`: 90 days

### Query Changes

History API (`/api/history`) queries:
- Last 1 hour: raw data
- Last 24 hours: `metrics_1m`
- Last 7 days: `metrics_1h`

This eliminates the expensive `GROUP BY` with division on raw data.

---

## Phase 5: Test Coverage

### New Test Files (matching new modules)

| Test File | Covers |
|-----------|--------|
| `tests/test_routes_stats.py` | Stats, stream, history endpoints |
| `tests/test_routes_auth.py` | Login, logout, OIDC, user management |
| `tests/test_routes_admin.py` | Settings, audit, backup |
| `tests/test_integration_base.py` | BaseIntegration retry, timeout, caching, error categorization |
| `tests/test_db_metrics.py` | Metric insert, aggregation, rollup queries |
| `tests/test_db_concurrent.py` | Concurrent writes with threading |
| `tests/test_settings_validation.py` | Pydantic model validation, URL scheme rejection |
| `tests/test_workflow_engine.py` | Workflow execution, auto builders, parallel workflows |

### Existing Tests

Existing test files remain and must continue passing. Existing test **imports** (`from server.db import Database`, `from server.integrations import ...`) must not change — the re-export strategy guarantees this.

---

## Import Dependency Rules

After the split, the following import directions are allowed:

```
routers/*  →  deps.py, db/, integrations/, metrics/, workflow_engine.py, agent_store.py
deps.py    →  auth.py, db/, collector.py
workflow_engine.py  →  db/, integrations/, deps.py
collector.py  →  integrations/, metrics/, agent_store.py, db/
scheduler.py  →  workflow_engine.py, db/
alerts.py     →  workflow_engine.py, db/
```

**Forbidden:** No route module imports from another route module. No `workflow_engine.py` → `routers/` import. No `integrations/` → `routers/` import. Deferred imports are eliminated — all imports are top-level.

---

## Constraints

- **Zero behavior changes** from the user's perspective — all existing API responses, SSE streams, and UI behavior remain identical
- **Backward-compatible imports** — `__init__.py` re-exports preserve existing import paths and existing test imports
- **Existing tests must pass** at every phase boundary
- **No new dependencies** — only stdlib + existing packages (FastAPI, httpx, psutil, pyyaml)
- **Incremental commits** — one commit per logical unit, squash-merge at the end per project convention

---

## Validation Strategy

Each sub-phase has a checkpoint:
1. After each route module extraction: `pytest tests/ -v` + `ruff check`
2. After `db/` split: `pytest tests/test_db.py tests/test_new_db.py -v`
3. After `integrations/` split: `pytest tests/test_integrations.py -v`
4. After frontend split: `node -c` on all JS files + manual smoke test
5. After each phase: full `pytest tests/ -v`

If a checkpoint fails, the last commit is the unit of rollback.

---

## Phase Dependencies

```
Phase 1 (Backend Splitting)
    ├── Phase 2 (Frontend Cleanup)     [independent — can start immediately]
    ├── Phase 3 (Validation/Caching)   [mostly independent — yaml_config.py standalone]
    ├── Phase 4 (Metrics Aggregation)  [needs db/ split from 1b]
    └── Phase 5 (Tests)                [needs all modules split]
```

Phase 1 is the largest and highest-risk phase. Phases 2-3 can proceed in parallel with or after Phase 1. Phase 4 needs Phase 1b. Phase 5 runs last.

---

## Success Criteria

- No file exceeds 600 lines
- All existing tests pass
- New tests cover the split modules
- `ruff check` clean
- `node -c` clean on all JS files
- Integration response shapes are consistent
- Settings endpoint validates input
- History queries use rollup tables
- No deferred imports remain — all imports are top-level
- Import dependency rules are respected (no cycles)
