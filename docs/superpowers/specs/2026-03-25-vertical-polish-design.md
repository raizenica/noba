# NOBA Vertical Polish — Design Spec

**Date:** 2026-03-25
**Goal:** Improve NOBA across three dimensions (showcase, operations, architecture) via four targeted vertical slices, each delivering a complete improvement.

**Approach:** Vertical Slices — pick the highest-impact areas and go deep on each one rather than sweeping horizontally. Each slice addresses all three goals simultaneously.

---

## Slice 1: Dashboard Experience

### Architecture
- No structural changes needed — `DashboardView.vue` (339 lines) is well-sized
- Fix broken hero image on GitHub Pages docs site (VitePress image path)

### Operational
- **Data freshness indicator** — add "Last updated: Xs ago" timestamp to the HealthScoreGauge component, driven by `live.timestamp` from the SSE stream
- **Dismissible anomaly banner** — the top-of-page anomaly alert should be dismissible per-session (sessionStorage flag) and link to the source metric
- **Forecast confidence tooltip** — Capacity Forecast "Confidence: Low" badge should have a hover tooltip explaining why (e.g., "< 7 days of data" or "R-squared < 0.5")

### Showcase
- Fix docs site hero image broken path
- **Status summary line** under Health Score gauge: "5 agents · 13 endpoints · 19 apps" using live data from the dashboard store

### Files
- `components/dashboard/HealthScoreGauge.vue` — add timestamp + summary line
- `components/dashboard/HealthBar.vue` — add dismiss button to anomaly alerts
- `components/cards/PredictionCard.vue` — add confidence tooltip
- `docs/.vitepress/` — fix image path in landing page config

---

## Slice 2: Agent Operations

### Architecture
Split `routers/agents.py` (1359 lines) into 4 focused files:

| New File | Domain | Estimated Lines |
|----------|--------|-----------------|
| `routers/agents.py` | CRUD, list, detail, bulk actions | ~300 |
| `routers/agent_commands.py` | Command dispatch, WS relay, results polling | ~400 |
| `routers/agent_deploy.py` | SSH deploy, file transfer, install script | ~350 |
| `routers/agent_terminal.py` | Remote terminal WebSocket, PTY forwarding | ~300 |

**Rules:**
- All route URLs stay identical — no API changes
- Shared imports (agent_store, deps, db) imported in each file
- `routers/__init__.py` updated to include all new routers
- Tests continue to pass without modification (routes unchanged)

### Operational
- **Agent health sparklines** — add a mini 1-hour CPU trend sparkline to agent cards using data already stored via `insert_metrics()`. Render as a tiny inline SVG or CSS-only bar chart
- **Stale command timeout** — commands in QUEUED status > 5 minutes auto-transition to TIMEOUT. Add a periodic check in the collector or scheduler

### Showcase
- **Command palette discovery** — add a subtle count indicator on the Agents page: "42 command types · 9 categories"
- **Agent version badge** — show agent version (e.g., "v2.1") on each agent card for fleet consistency visibility

### Files
- `routers/agents.py` → split into 4 files
- `routers/__init__.py` — register new routers
- `views/AgentsView.vue` — sparkline + version badge on agent cards
- `components/agents/CommandPalette.vue` — command count indicator
- `collector.py` or `scheduler.py` — stale command timeout logic

---

## Slice 3: Healing Pipeline

### Architecture
Split `views/HealingView.vue` (565 lines) into focused tab components:

| New Component | Content | Estimated Lines |
|---------------|---------|-----------------|
| `HealingOverviewTab.vue` | Effectiveness Summary table + Suggestions | ~120 |
| `HealingLedgerTab.vue` | Ledger filters + table | ~80 |
| `HealingApprovalTab.vue` | Pending approvals table | ~50 |
| `HealingView.vue` (shell) | Tab routing, store init, shared formatters | ~150 |

Dependencies/Trust/Maintenance tabs are already extracted — no change needed.

### Operational
- **Test data purge** — admin-only "Purge test data" button on Maintenance tab. Clears approvals, incidents, and trust states matching test patterns (rule_ids containing "test", "deny-test", age > 7 days with no resolution)
- **Suggestion actionability** — suggestions like "uptime degraded (score 3.0/10)" should deep-link to the relevant page (e.g., Monitoring → SLA tab or the specific endpoint)
- **Effectiveness zero-state** — when all counts are 0, show "No healing actions have run yet" message instead of a table of zeros

### Showcase
- **Pipeline uptime counter** — show "running for 14h 22m" next to the "PIPELINE: ACTIVE" badge in the overview bar
- **Charts on empty data** — the doughnut + bar charts in EffectivenessPanel should render with a placeholder state (empty ring with "No data" label) instead of being invisible

### Files
- `views/HealingView.vue` → split into 4 components
- `components/healing/HealOverviewBar.vue` — add pipeline uptime
- `components/healing/EffectivenessPanel.vue` — empty chart state
- `components/healing/MaintenancePanel.vue` — purge test data button
- `routers/admin.py` or `routers/agents.py` — purge API endpoint

---

## Slice 4: n8n Integration

### Architecture
- New integration module: `integrations/n8n.py` — fetches workflow status and execution history from n8n's REST API (`/api/v1/executions`, `/api/v1/workflows`)
- New webhook preset in Automations — "n8n Incoming" template that accepts n8n's webhook payload format

### Operational
- **n8n workflow status card** — new dashboard card showing workflow execution stats (total runs, failure rate, last execution time). Data from n8n's API using the existing n8n API credential
- **Bidirectional webhook** — NOBA automations can call n8n webhook triggers, and n8n can call NOBA's webhook endpoints to trigger heals, create incidents, or update endpoint status
- **Execution history** — show recent n8n executions on the Monitoring or Automations page with status indicators (success/error/running)

### Showcase
- **"n8n Connected" badge** on the Automations page showing sync status and workflow count
- Demonstrates NOBA's extensibility — connects to external automation platforms, not just internal

### Files
- `integrations/n8n.py` — new integration module
- `collector.py` — add n8n data collection if URL configured
- `components/cards/N8nCard.vue` — new dashboard card
- `stores/dashboard.js` — register `n8n` in live reactive object
- `views/DashboardView.vue` — add N8nCard import + visibility gate
- `components/settings/IntegrationSetup.vue` — n8n URL + API key config fields

---

## Implementation Order

1. **Slice 1 (Dashboard)** — quickest, mostly frontend, immediately visible
2. **Slice 3 (Healing)** — component split + operational fixes, medium effort
3. **Slice 2 (Agents)** — biggest refactor (agents.py split), highest risk
4. **Slice 4 (n8n)** — new feature, can be done independently

Each slice is independently shippable. Test suite must pass after each slice.

---

## Success Criteria

- All 3143+ backend tests pass after each slice
- All 91+ frontend tests pass after each slice
- No API URL changes (backward compatible)
- Ruff passes clean
- Each slice verified visually via browser automation
