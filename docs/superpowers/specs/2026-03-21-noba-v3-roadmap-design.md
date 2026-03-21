# NOBA v3.0 Roadmap — Design Spec

**Goal:** Refactor NOBA's backend and frontend for long-term maintainability, then build advanced automation and intelligence features on the clean foundation.

**Architecture:** 5-phase plan — 3 structural phases (backend decomposition, Vue.js migration, test coverage) followed by 2 feature phases (advanced automation engine, predictive intelligence). Each phase produces a working, deployable system.

**Approach:** Clean branch, clean slate. No backward-compatibility constraints — agents can be redeployed, configs can change format.

---

## Phase 1: Backend Decomposition

### Problem

`routers/system.py` is 3190 lines with 122 functions spanning 13+ domains. Every backend change requires navigating a god file, and unrelated domains are tangled in one module.

### Solution

Extract `system.py` into 8 focused router files, one per domain. Delete `system.py` entirely.

### New Router Files

| File | Domain | Routes | Source |
|------|--------|--------|--------|
| `routers/agents.py` | Agent CRUD, commands, WebSocket, deploy, streams | ~21 | Lines ~800-1600 of system.py |
| `routers/containers.py` | Docker containers, compose, TrueNAS VM control | ~11 | Lines ~134-340 |
| `routers/monitoring.py` | Endpoint monitors, uptime, SLA, health score | ~8 | Lines ~470-730 |
| `routers/infrastructure.py` | Network, K8s, Proxmox, services map, disks | ~11 | Lines ~384-470, 762-920 |
| `routers/security.py` | Security scans, findings, scoring | ~6 | Lines ~2955-3080 |
| `routers/intelligence.py` | AI ops, drift/baselines, incidents | ~17 | Lines ~2543-2960 |
| `routers/operations.py` | Recovery, journal, processes, system info, backups | ~12 | Lines ~52-130, 528-620, 3081-3175 |
| `routers/dashboards.py` | Custom dashboard CRUD, export/IaC | ~7 | Lines ~2457-2540 |

### Existing Files (unchanged)

| File | Domain | Lines |
|------|--------|-------|
| `routers/admin.py` | User management, audit, settings | 880 |
| `routers/auth.py` | Login, OIDC, tokens | 458 |
| `routers/automations.py` | Automation CRUD, trigger, workflow | 684 |
| `routers/integrations.py` | Cloud remotes, InfluxDB, integration configs | 366 |
| `routers/stats.py` | SSE, metrics history, trends | 360 |

### Shared Modules (unchanged)

- `agent_store.py` — agent data stores and locks (already clean)
- `db/` — database layer (already modular)
- `deps.py` — auth dependencies
- `config.py`, `yaml_config.py` — configuration
- `collector.py` — metric collection
- `scheduler.py` — cron, endpoint checker, drift checker
- `integrations/` — per-integration modules
- `metrics/` — per-domain metric collection

### Rules

- Every route URL stays identical — no API changes
- Each new router file uses `APIRouter(tags=["domain"])` for OpenAPI grouping
- Shared imports (db, deps, agent_store) imported at top of each file
- `routers/__init__.py` consolidates all routers for `app.py`
- `system.py` is deleted, not left as a stub

---

## Phase 2: Vue.js Migration + Mobile Responsive

### Problem

`index.html` is 6945 lines with 852 Alpine.js directives, all sharing one global `x-data` scope via 6 JS mixin files. No lazy loading — the entire UI ships on every page load. Mobile layout is broken in portrait mode.

### Solution

Migrate the frontend to Vue.js (Vue 3 + Vite + Vue Router + Pinia). Each page becomes a self-contained `.vue` component with its own template, logic, and scoped styles. Add responsive CSS for mobile.

### Why Vue

- Alpine.js was modeled after Vue — same reactive model, similar template syntax (`x-show` → `v-show`, `x-for` → `v-for`)
- True component encapsulation — each page owns its state, no global namespace pollution
- Lazy loading via Vue Router — mobile users only download the page they visit
- Scales indefinitely — 100+ features, each in its own component file

### Frontend Structure

```
share/noba-web/frontend/          # New Vue project root
  src/
    App.vue                       # Root layout — sidebar, header
    router/index.js               # Vue Router — lazy-loaded routes
    stores/                       # Pinia stores (replace mixin state)
      auth.js                     # Login, token, user role
      dashboard.js                # Dashboard data, polling
      agents.js                   # Agent state, commands
      notifications.js            # Toast system
    views/                        # One per page (lazy-loaded)
      DashboardView.vue
      AgentsView.vue
      MonitoringView.vue
      InfrastructureView.vue
      AutomationsView.vue
      LogsView.vue
      SecurityView.vue
      SettingsView.vue
    components/                   # Reusable components
      cards/                      # Dashboard card components
        SystemHealthCard.vue
        PiholeCard.vue
        ...
      modals/                     # Modal dialogs
        HistoryModal.vue
        SmartModal.vue
        ...
      ui/                         # Generic UI components
        Toast.vue
        Badge.vue
        ConfirmDialog.vue
        DataTable.vue
    composables/                  # Shared logic (Vue composition API)
      useApi.js                   # Fetch wrapper with auth
      useSse.js                   # SSE connection management
      useIntervals.js             # Interval registry (replaces _registerInterval)
  vite.config.js
  package.json
```

### Build Integration

- Vite builds to `share/noba-web/static/dist/`
- FastAPI serves `index.html` from the Vite build output
- In development: Vite dev server with proxy to FastAPI backend
- In production: static files served by FastAPI (same as today, just built files instead of raw)

**Deployment strategy:** The built frontend is committed to the repo (in `static/dist/`), so end users never need Node.js installed. Only developers making frontend changes need Node.js + npm. This keeps the install.sh, Docker image, and RPM workflow unchanged — no new runtime dependency. A `Makefile` or `scripts/build-frontend.sh` handles the build step for development.

**No TypeScript** — plain JavaScript throughout. The project has no TS toolchain and adding one isn't justified for this migration.

### Mobile Responsive Strategy

- **Sidebar:** collapsible hamburger overlay on screens < 768px, touch-friendly tap targets (44px minimum)
- **Dashboard grid:** single-column card stack in portrait, 2-column on landscape tablet, current masonry on desktop. CSS grid with responsive breakpoints.
- **Data tables:** horizontal scroll wrapper on mobile
- **Modals:** full-screen on mobile (bottom sheet pattern for quick actions)
- **Charts:** Chart.js responsive mode already works, just needs container sizing

### SSE Auth Compatibility

EventSource cannot set custom headers. The current `_get_auth_sse` fallback (token as query parameter) must be preserved in the Vue migration. The `useSse.js` composable will pass the token as `?token=...` on the EventSource URL, matching the existing pattern.

### Migration Approach

Incremental, one page at a time:
1. Set up Vue project, build pipeline, and App.vue shell
2. Migrate login/auth flow first (smallest, validates the pattern)
3. Dashboard page (largest — validates card component pattern)
4. Remaining pages in any order
5. Remove Alpine.js, old JS files, old index.html

---

## Phase 3: Test Coverage + API Contracts

### Problem

783 tests exist but cover mostly DB, auth, and config. The 8 new router modules and 9 Vue pages have no test coverage. No formal API contract between frontend and backend.

### Solution

Add integration tests for every router, component tests for Vue pages, and generate an OpenAPI schema as the contract.

### Backend Tests

Phase 3 tests are **additive** to the existing 783 tests. The existing suite (DB, auth, config, workflow engine) stays unchanged. New tests cover the refactored router modules.

- **Integration tests** for each new router file — test actual HTTP requests against a test FastAPI app
- One test file per router: `tests/test_router_agents.py`, `tests/test_router_containers.py`, etc.
- Use `httpx.AsyncClient` with the FastAPI test client
- Mock external dependencies (agent_store, subprocess calls) but hit real SQLite

### Frontend Tests

- **Vitest + Vue Test Utils** for component-level testing
- Critical paths: login flow, dashboard data rendering, agent command dispatch, automation CRUD
- Snapshot tests for card components (catch unintended template changes)

### E2E Tests

- **Playwright** smoke tests: login → navigate each page → verify renders
- Run in CI against a test server instance

### API Contract

- FastAPI auto-generates OpenAPI schema — expose at `/api/openapi.json`
- Vue frontend can validate against the schema using JSDoc annotations or runtime checks
- Schema becomes the single source of truth for request/response shapes

---

## Phase 4: Advanced Automation Engine

### Problem

Current automation engine handles cron triggers, webhooks, and sequential/parallel workflows. Missing: automatic remediation, approval workflows, and maintenance windows.

### Solution

Extend the automation engine with remediation actions, per-rule autonomy settings, an approval queue, and maintenance window support.

### Auto-Remediation Actions

New action types for the automation engine:

| Action | Risk | Description |
|--------|------|-------------|
| `restart_container` | low | Docker restart by container name |
| `restart_service` | low | systemd service restart |
| `flush_dns` | low | Clear DNS cache on Pi-hole agents |
| `clear_cache` | low | Purge application caches |
| `trigger_backup` | medium | Initiate backup job |
| `failover_dns` | high | Switch DNS to backup pair |
| `scale_container` | medium | Adjust container resource limits |
| `run_playbook` | high | Execute a maintenance playbook |

Each action type has:
- Typed parameters with validation
- Execution timeout
- Audit logging

**Rollback** is an optional per-action-type behavior, not a general framework. Only actions with a natural reverse get rollback logic:
- `restart_container` / `restart_service` — post-restart health check, if still failing log it as a failed remediation (no reverse action, just escalation)
- `failover_dns` — reverse is fail-back to primary, can be triggered manually or on recovery detection
- Other actions (trigger_backup, clear_cache, etc.) — no rollback, fire-and-forget with result logging

### Per-Rule Autonomy

Every automation rule gets an `autonomy` field:

| Level | Behavior |
|-------|----------|
| `execute` | Runs immediately when triggered, no human in the loop |
| `approve` | Queues the action, sends push notification, waits for approval (with optional auto-approve timeout) |
| `notify` | Only sends a notification, takes no action |
| `disabled` | Rule is saved but inactive |

This is a property of the rule itself, set by whoever creates/edits the rule (operator or admin role required). All users see the same rule behavior — this is not per-user override. The design intent is that the person configuring the automation decides the appropriate autonomy level for that specific action.

### Approval Flow

- Pending actions stored in DB with full context (what triggered, what action, what parameters)
- PWA push notification sent on `approve`-level triggers
- Approve/deny from any device (phone, desktop)
- Configurable auto-approve timeout (e.g., "if no response in 15 minutes, execute anyway")
- Approval history in audit log

### Maintenance Windows

- Named time ranges (e.g., "Tuesday 2am-4am maintenance")
- Cron-like recurrence or one-off
- Per-window behavior:
  - Suppress alerts during window
  - Override automation autonomy (e.g., elevate all rules to `execute` during planned maintenance)
  - Auto-close alerts that resolve during the window
- Active window indicator in the UI header

### Action Audit Trail

Every automated action gets a full audit record:
- Trigger source (which alert/rule/schedule)
- Action taken (type, parameters, target)
- Outcome (success/failure, duration, output)
- Who approved it (or "auto" / "autonomous")
- Rollback result if applicable

---

## Phase 5: Predictive Intelligence + Workflow Orchestration

### Problem

Current capacity planning uses simple linear regression. Workflows are sequential or parallel with no branching. No pre-built maintenance sequences.

### Solution

Smarter predictions, a visual workflow builder, and maintenance playbook templates.

### Enhanced Capacity Planning

- **Multi-metric regression** — combine disk usage + inode count + I/O rate for more accurate disk-full predictions
- **Seasonal decomposition** — detect weekly/monthly patterns in workloads, avoid false "you'll be full in 3 days" alerts caused by cyclical spikes
- **Confidence intervals** — show prediction bands (68%/95%) instead of a single line
- **Per-service health scoring** — weighted composite: uptime (40%) + latency trend (25%) + error rate (20%) + resource headroom (15%)

### Visual Workflow Builder

- Vue-based drag-and-drop workflow editor
- Node types: action, condition, parallel split, approval gate, delay, notification
- Conditional branching: `if disk > 90% → cleanup; else → notify`
- Parallel execution paths with join points
- Approval gates mid-workflow (pause until human approves)
- Import/export workflows as JSON

### Maintenance Playbooks

Pre-built workflow templates:

| Playbook | Steps |
|----------|-------|
| Update all agents | Queue update → rolling restart → verify versions → report |
| Rolling DNS restart | Restart primary → verify resolution → restart secondary → verify |
| Backup verification | Trigger backup → wait → verify checksum → verify restore test → report |
| Disk cleanup | Check thresholds → identify large/old files → notify for approval → delete → verify space |

Users can customize templates or build from scratch.

---

## Non-Goals

- No framework migration beyond Vue (no React, Svelte, etc.)
- No separate mobile app — responsive web covers mobile use cases
- No multi-tenant SaaS features — NOBA remains a self-hosted tool
- No personalized multi-site logic — site awareness is generic and fully configurable
- No Kubernetes operator — NOBA monitors K8s, it doesn't run on it

## Dependencies

- **Vue 3** + **Vite** + **Vue Router** + **Pinia** (frontend)
- **Vitest** + **Vue Test Utils** (frontend testing)
- **Playwright** (E2E testing)
- No new backend dependencies — FastAPI, SQLite, httpx all sufficient
