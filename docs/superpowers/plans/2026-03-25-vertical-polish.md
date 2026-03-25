# NOBA Vertical Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish NOBA across showcase, operations, and architecture via 4 vertical slices.

**Architecture:** Each slice is independently shippable. Implementation order: Dashboard → Healing → Agents → n8n. Each slice commits separately with full test verification.

**Tech Stack:** Python 3.11+ (FastAPI, SQLite), Vue 3 (Composition API, Pinia), VitePress docs

**Spec:** `docs/superpowers/specs/2026-03-25-vertical-polish-design.md`

---

## Slice 1: Dashboard Experience

### Task 1.1: Fix docs site hero image

The VitePress hero image references `/images/dashboard.png` which resolves to `docs/public/images/dashboard.png`, but images live in `docs/images/`. VitePress serves static assets from `docs/public/`.

**Files:**
- Modify: `docs/public/` — create `images/` symlink or copy

- [ ] **Step 1:** Create the public images directory and symlink

```bash
cd docs/public && ln -s ../images images
```

- [ ] **Step 2:** Verify locally

```bash
cd docs && npx vitepress dev --port 5173
```

Open `http://localhost:5173/noba/` — hero image should render.

- [ ] **Step 3:** Commit

```bash
git add docs/public/images
git commit -m "fix: docs site hero image — symlink public/images to docs/images"
```

---

### Task 1.2: Data freshness indicator on Health Score

Add "Updated Xs ago" below the health score gauge, driven by `live.timestamp`.

**Files:**
- Modify: `share/noba-web/frontend/src/components/dashboard/HealthScoreGauge.vue`

- [ ] **Step 1:** Read the current HealthScoreGauge component to understand its structure

```bash
cat share/noba-web/frontend/src/components/dashboard/HealthScoreGauge.vue
```

- [ ] **Step 2:** Add a `lastUpdated` computed that formats the SSE timestamp as relative time

Import `useDashboardStore` (if not already), compute `secondsAgo` from `dashboardStore.live.timestamp`, format as "Xs ago" / "Xm ago". Add a `<div>` below the score displaying this value, styled with `color: var(--text-muted); font-size: .7rem`.

- [ ] **Step 3:** Add the status summary line

Below the timestamp, add: `{{ agentCount }} agents · {{ endpointCount }} endpoints`. Pull `agentCount` from `dashboardStore.live.agents.length`. For endpoints, fetch count from `/api/endpoints` on mount (lightweight — just `.length`).

- [ ] **Step 4:** Build and verify visually

```bash
cd share/noba-web/frontend && npm run build
```

Hard-reload the dashboard in the browser. Confirm "Updated Xs ago" and "5 agents · 13 endpoints" appear below the health gauge.

- [ ] **Step 5:** Commit

```bash
git add share/noba-web/frontend/src/components/dashboard/HealthScoreGauge.vue share/noba-web/static/dist/
git commit -m "feat(dashboard): add data freshness indicator and status summary to health gauge"
```

---

### Task 1.3: Dismissible anomaly banner

The HealthBar anomaly alert should be dismissible per-session.

**Files:**
- Modify: `share/noba-web/frontend/src/components/dashboard/HealthBar.vue`

- [ ] **Step 1:** Read the HealthBar component

```bash
cat share/noba-web/frontend/src/components/dashboard/HealthBar.vue
```

- [ ] **Step 2:** Add a `dismissedAlerts` ref backed by sessionStorage

```javascript
const dismissedAlerts = ref(new Set(JSON.parse(sessionStorage.getItem('noba:dismissed-alerts') || '[]')))

function dismissAlert(alertKey) {
  dismissedAlerts.value.add(alertKey)
  sessionStorage.setItem('noba:dismissed-alerts', JSON.stringify([...dismissedAlerts.value]))
}
```

Filter displayed alerts to exclude dismissed keys. Add a small `×` button to each alert row calling `dismissAlert(alert.key || alert.message)`.

- [ ] **Step 3:** Build and verify

```bash
cd share/noba-web/frontend && npm run build
```

Hard-reload dashboard. Dismiss an alert. Verify it stays dismissed on page navigation but reappears after closing and reopening the browser tab.

- [ ] **Step 4:** Commit

```bash
git add share/noba-web/frontend/src/components/dashboard/HealthBar.vue share/noba-web/static/dist/
git commit -m "feat(dashboard): dismissible anomaly alerts with session persistence"
```

---

### Task 1.4: Forecast confidence tooltip

Add a hover tooltip to the "Confidence: Low" badge in PredictionCard.

**Files:**
- Modify: `share/noba-web/frontend/src/components/cards/PredictionCard.vue`

- [ ] **Step 1:** Read PredictionCard to find where confidence is rendered

```bash
cat share/noba-web/frontend/src/components/cards/PredictionCard.vue
```

- [ ] **Step 2:** Add a computed `confidenceReason` based on the prediction data

```javascript
const confidenceReason = computed(() => {
  const d = prediction.value
  if (!d) return ''
  const r2 = d.r_squared ?? d.combined?.r_squared ?? 0
  const points = d.data_points ?? 0
  if (points < 14) return `Only ${points} data points (need 14+ for reliable projection)`
  if (r2 < 0.5) return `Low correlation (R²=${r2.toFixed(2)}) — usage pattern is irregular`
  return 'Sufficient data for projection'
})
```

- [ ] **Step 3:** Add a `title` attribute to the confidence badge element

```html
<span class="badge" :class="..." :title="confidenceReason">{{ confidence }}</span>
```

- [ ] **Step 4:** Build, verify hover tooltip appears, commit

```bash
cd share/noba-web/frontend && npm run build
git add share/noba-web/frontend/src/components/cards/PredictionCard.vue share/noba-web/static/dist/
git commit -m "feat(dashboard): forecast confidence tooltip explaining projection quality"
```

---

### Task 1.5: Slice 1 verification

- [ ] **Step 1:** Run all tests

```bash
cd /home/raizen/noba && python -m pytest tests/ -x -q
cd share/noba-web/frontend && npm test
```

Expected: 3143+ backend, 91+ frontend — all pass.

- [ ] **Step 2:** Run ruff

```bash
ruff check share/noba-web/server/
```

Expected: All checks passed.

- [ ] **Step 3:** Visual verification via browser — dashboard shows freshness indicator, summary line, dismissible alerts, confidence tooltip.

---

## Slice 3: Healing Pipeline

### Task 3.1: Extract HealingOverviewTab component

**Files:**
- Create: `share/noba-web/frontend/src/components/healing/HealingOverviewTab.vue`
- Modify: `share/noba-web/frontend/src/views/HealingView.vue`

- [ ] **Step 1:** Read HealingView.vue and identify the Overview tab content (lines within `v-if="activeTab === 'overview'"`)

- [ ] **Step 2:** Create `HealingOverviewTab.vue` — extract the Effectiveness Summary card and Suggestions card into a new `<script setup>` component. Accept `store`, `authStore`, `dismissingId`, `dismissSuggestion`, `severityClass` as props or use stores directly.

- [ ] **Step 3:** In HealingView.vue, replace the overview tab content with `<HealingOverviewTab />`. Import the new component.

- [ ] **Step 4:** Build and verify the Overview tab renders identically

```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 5:** Commit

```bash
git add share/noba-web/frontend/src/components/healing/HealingOverviewTab.vue share/noba-web/frontend/src/views/HealingView.vue share/noba-web/static/dist/
git commit -m "refactor(healing): extract HealingOverviewTab component"
```

---

### Task 3.2: Extract HealingLedgerTab component

**Files:**
- Create: `share/noba-web/frontend/src/components/healing/HealingLedgerTab.vue`
- Modify: `share/noba-web/frontend/src/views/HealingView.vue`

- [ ] **Step 1:** Extract the Ledger tab content (filters + table within `v-if="activeTab === 'ledger'"`) including `ledgerFilterRule`, `ledgerFilterTarget`, `filteredLedger`, `refetchLedger`, and related computed properties.

- [ ] **Step 2:** Move the ledger-specific state (`ledgerFilterRule`, `ledgerFilterTarget`, `ledgerLoading`) and computed properties into the new component.

- [ ] **Step 3:** Replace in HealingView.vue with `<HealingLedgerTab />`.

- [ ] **Step 4:** Build and verify, commit

```bash
git commit -m "refactor(healing): extract HealingLedgerTab component"
```

---

### Task 3.3: Extract HealingApprovalTab component

**Files:**
- Create: `share/noba-web/frontend/src/components/healing/HealingApprovalTab.vue`
- Modify: `share/noba-web/frontend/src/views/HealingView.vue`

- [ ] **Step 1:** Extract the Approvals tab content (the table within `v-if="activeTab === 'approvals'"`) including the `fmtTs` formatter.

- [ ] **Step 2:** Replace in HealingView.vue with `<HealingApprovalTab />`.

- [ ] **Step 3:** Build, verify, commit

```bash
git commit -m "refactor(healing): extract HealingApprovalTab component"
```

---

### Task 3.4: Effectiveness zero-state

**Files:**
- Modify: `share/noba-web/frontend/src/components/healing/HealingOverviewTab.vue` (or HealingView.vue if not yet extracted)

- [ ] **Step 1:** In the Effectiveness Summary table, check if all entries have zero totals. If so, show an empty state message instead of the zero-filled table:

```html
<p v-if="allZero" class="empty-msg">No healing actions have run yet — metrics appear once the pipeline processes its first event.</p>
```

Where `allZero` is:
```javascript
const allZero = computed(() => effectivenessEntries.value.every(e => (e.total || e.count || 0) === 0))
```

- [ ] **Step 2:** Build, verify, commit

```bash
git commit -m "feat(healing): show meaningful empty state instead of zero-filled table"
```

---

### Task 3.5: Pipeline uptime counter

**Files:**
- Modify: `share/noba-web/frontend/src/components/healing/HealOverviewBar.vue`

- [ ] **Step 1:** Read HealOverviewBar.vue

- [ ] **Step 2:** Add a reactive timer that shows pipeline uptime. Use the NOBA server uptime from `/api/health` (already available) or `dashboardStore.live.uptime` as a proxy for pipeline uptime.

```javascript
const pipelineUptime = computed(() => dashboardStore.live.uptime || '--')
```

Add next to the "PIPELINE ACTIVE" badge:
```html
<span style="font-size:.7rem;color:var(--text-muted);margin-left:.5rem">up {{ pipelineUptime }}</span>
```

- [ ] **Step 3:** Build, verify, commit

```bash
git commit -m "feat(healing): show pipeline uptime counter in overview bar"
```

---

### Task 3.6: Empty chart placeholder in EffectivenessPanel

**Files:**
- Modify: `share/noba-web/frontend/src/components/healing/EffectivenessPanel.vue`

- [ ] **Step 1:** Read EffectivenessPanel.vue — the charts (doughnut, bar, rule bar) are invisible when data is zero because Chart.js renders nothing for all-zero datasets.

- [ ] **Step 2:** Add a check before each chart: if data is all zeros, show a "No data yet" overlay instead of rendering the chart.

```html
<div v-if="hasData" class="eff-card">
  <h4>Success Rate</h4>
  <canvas ref="successChart" />
</div>
<div v-else class="eff-card" style="display:flex;align-items:center;justify-content:center;min-height:150px">
  <span style="color:var(--text-muted);font-size:.8rem">No healing data yet</span>
</div>
```

Where `hasData` checks `store.effectiveness` and `store.ledger` for non-zero entries.

- [ ] **Step 3:** Build, verify, commit

```bash
git commit -m "feat(healing): show placeholder instead of invisible charts when no data"
```

---

### Task 3.7: Test data purge endpoint + button

**Files:**
- Modify: `share/noba-web/server/routers/admin.py` — add purge endpoint
- Modify: `share/noba-web/frontend/src/components/healing/MaintenancePanel.vue` — add purge button

- [ ] **Step 1:** Add `POST /api/admin/purge-test-data` endpoint in `routers/admin.py`

```python
@router.post("/api/admin/purge-test-data")
async def api_purge_test_data(request: Request, auth=Depends(_require_admin)):
    """Purge stale test data from healing pipeline."""
    username, _ = auth
    count = 0
    # Clear test approvals (rule_ids containing 'test' or 'deny')
    count += db.purge_test_approvals()
    # Clear resolved test incidents older than 7 days
    count += db.purge_old_test_incidents(max_age_days=7)
    db.audit_log("purge_test_data", username, f"Purged {count} test records", _client_ip(request))
    return {"purged": count}
```

- [ ] **Step 2:** Add `purge_test_approvals()` and `purge_old_test_incidents()` methods to `db/core.py` — simple DELETE queries with pattern matching on rule_id/automation_id.

- [ ] **Step 3:** Add "Purge Test Data" button to MaintenancePanel.vue — admin-only, with confirmation modal.

- [ ] **Step 4:** Write backend test for the purge endpoint.

- [ ] **Step 5:** Run all tests, lint, build, verify, commit

```bash
git commit -m "feat(healing): add admin purge-test-data endpoint and maintenance button"
```

---

### Task 3.8: Slice 3 verification

- [ ] **Step 1:** Run all backend + frontend tests
- [ ] **Step 2:** Ruff check
- [ ] **Step 3:** Visual verification — Healing page shows extracted components rendering correctly, zero-state works, pipeline uptime visible, chart placeholder visible

---

## Slice 2: Agent Operations

### Task 2.1: Split agents.py — extract agent_commands.py

**Files:**
- Create: `share/noba-web/server/routers/agent_commands.py`
- Modify: `share/noba-web/server/routers/agents.py`
- Modify: `share/noba-web/server/routers/__init__.py`

- [ ] **Step 1:** Read agents.py and identify the command dispatch functions: `api_agent_command`, `api_agent_results`, `api_agent_history`, `api_agent_network_stats`, `api_agent_stream` (stream logs), `api_agent_stop_stream`, `api_agent_active_streams`, `api_sla_summary`.

- [ ] **Step 2:** Create `agent_commands.py` with its own `APIRouter(tags=["agent-commands"])`. Move the identified functions and their helper functions. Keep all shared imports from `agent_store`, `deps`, `db`.

- [ ] **Step 3:** Update `__init__.py` to register the new router.

- [ ] **Step 4:** Run the full backend test suite — all 3143 tests must pass with zero changes to tests.

```bash
python -m pytest tests/ -x -q
```

- [ ] **Step 5:** Commit

```bash
git commit -m "refactor(agents): extract agent_commands.py — command dispatch and results"
```

---

### Task 2.2: Split agents.py — extract agent_deploy.py

**Files:**
- Create: `share/noba-web/server/routers/agent_deploy.py`
- Modify: `share/noba-web/server/routers/agents.py`
- Modify: `share/noba-web/server/routers/__init__.py`

- [ ] **Step 1:** Identify deploy functions: `api_agent_deploy`, `api_agent_update`, `api_agent_install_script`, `api_agent_file_upload`, `api_agent_file_download`, `api_agent_transfer`, `api_agent_uninstall`.

- [ ] **Step 2:** Create `agent_deploy.py`, move functions, register router.

- [ ] **Step 3:** Run full test suite, verify all pass.

- [ ] **Step 4:** Commit

```bash
git commit -m "refactor(agents): extract agent_deploy.py — SSH deploy and file transfer"
```

---

### Task 2.3: Split agents.py — extract agent_terminal.py

**Files:**
- Create: `share/noba-web/server/routers/agent_terminal.py`
- Modify: `share/noba-web/server/routers/agents.py`
- Modify: `share/noba-web/server/routers/__init__.py`

- [ ] **Step 1:** Identify terminal functions: the WebSocket terminal handler (`ws_agent_terminal`), PTY forwarding helpers (`_forward_pty_to_agent`, `_dispatch_terminal_command`), and terminal-specific state.

- [ ] **Step 2:** Create `agent_terminal.py`, move functions, register router.

- [ ] **Step 3:** Run full test suite, verify all pass.

- [ ] **Step 4:** Commit

```bash
git commit -m "refactor(agents): extract agent_terminal.py — remote terminal WebSocket"
```

---

### Task 2.4: Stale command timeout

**Files:**
- Modify: `share/noba-web/server/collector.py` or `share/noba-web/server/scheduler.py`

- [ ] **Step 1:** In the collector's agent processing loop (or as a scheduler task), add a check: for each command in `_agent_commands` or `_agent_cmd_results` with status QUEUED and `queued_at` older than 300 seconds, transition to TIMEOUT status.

- [ ] **Step 2:** Write a test verifying that a command queued > 5 minutes ago gets marked as TIMEOUT.

- [ ] **Step 3:** Run tests, commit

```bash
git commit -m "feat(agents): auto-timeout stale QUEUED commands after 5 minutes"
```

---

### Task 2.5: Agent version badge and command palette count

**Files:**
- Modify: `share/noba-web/frontend/src/views/AgentsView.vue`
- Modify: `share/noba-web/frontend/src/components/agents/CommandPalette.vue`

- [ ] **Step 1:** In AgentsView.vue agent cards, add a version badge:

```html
<span v-if="a.agent_version" class="badge bn" style="font-size:.6rem">v{{ a.agent_version }}</span>
```

- [ ] **Step 2:** In CommandPalette.vue, add a count line showing total command types and categories:

```javascript
const cmdCount = computed(() => Object.values(COMMAND_CATEGORIES).flat().length)
const catCount = computed(() => Object.keys(COMMAND_CATEGORIES).length)
```

Display as subtle text: `{{ cmdCount }} commands · {{ catCount }} categories`

- [ ] **Step 3:** Build, verify visually, commit

```bash
git commit -m "feat(agents): add version badge to agent cards and command palette discovery count"
```

---

### Task 2.6: Slice 2 verification

- [ ] **Step 1:** Run all backend + frontend tests
- [ ] **Step 2:** Ruff check
- [ ] **Step 3:** Verify agents.py went from ~1359 lines to ~300 lines with 3 new files
- [ ] **Step 4:** Visual verification — agent cards show version badges, command palette shows count

---

## Slice 4: n8n Integration

### Task 4.1: n8n integration module

**Files:**
- Create: `share/noba-web/server/integrations/n8n.py`

- [ ] **Step 1:** Create the integration module that fetches workflow and execution data from n8n's REST API:

```python
"""n8n workflow automation integration."""
from __future__ import annotations
import logging
from .util import _http_get

logger = logging.getLogger("noba")

def collect_n8n(base_url: str, api_key: str) -> dict | None:
    """Fetch n8n workflow stats and recent executions."""
    if not base_url or not api_key:
        return None
    headers = {"X-N8N-API-KEY": api_key}
    try:
        workflows = _http_get(f"{base_url}/api/v1/workflows", headers, timeout=8)
        executions = _http_get(f"{base_url}/api/v1/executions?limit=20", headers, timeout=8)
        # ... parse and return stats
    except Exception:
        return None
```

- [ ] **Step 2:** Write tests for the integration module (mock httpx responses).

- [ ] **Step 3:** Commit

```bash
git commit -m "feat(n8n): add n8n integration module for workflow and execution data"
```

---

### Task 4.2: Wire n8n into collector and config

**Files:**
- Modify: `share/noba-web/server/collector.py` — add n8n collection call
- Modify: `share/noba-web/server/yaml_config.py` — add n8nUrl, n8nApiKey config keys
- Modify: `share/noba-web/frontend/src/stores/dashboard.js` — register `n8n` in live object

- [ ] **Step 1:** Add `n8nUrl` and `n8nApiKey` to the YAML config schema in `yaml_config.py`.

- [ ] **Step 2:** In collector.py, call `collect_n8n()` when n8nUrl is configured and store result in `stats["n8n"]`.

- [ ] **Step 3:** Register `n8n: null` in the dashboard store's `live` reactive object.

- [ ] **Step 4:** Run tests, commit

```bash
git commit -m "feat(n8n): wire integration into collector, config, and dashboard store"
```

---

### Task 4.3: N8nCard dashboard component

**Files:**
- Create: `share/noba-web/frontend/src/components/cards/N8nCard.vue`
- Modify: `share/noba-web/frontend/src/views/DashboardView.vue`

- [ ] **Step 1:** Create N8nCard showing:
  - Connection status (online/offline badge)
  - Workflow count (total, active)
  - Recent execution stats (total, failed, avg duration)
  - Last execution timestamp

- [ ] **Step 2:** Import and add to DashboardView.vue with visibility gate:

```html
<N8nCard v-if="showCard('n8n') && dashboardStore.live.n8n" data-id="n8n" />
```

- [ ] **Step 3:** Build, verify visually, commit

```bash
git commit -m "feat(n8n): add N8nCard dashboard component"
```

---

### Task 4.4: n8n settings UI

**Files:**
- Modify: `share/noba-web/frontend/src/components/settings/IntegrationSetup.vue`

- [ ] **Step 1:** Add n8n URL and API key fields to the integration settings form, following the existing pattern for other integrations.

- [ ] **Step 2:** Build, verify, commit

```bash
git commit -m "feat(n8n): add n8n URL and API key to integration settings"
```

---

### Task 4.5: Slice 4 verification

- [ ] **Step 1:** Run all backend + frontend tests
- [ ] **Step 2:** Ruff check
- [ ] **Step 3:** Visual verification — n8n card appears on dashboard when configured, settings page has n8n fields

---

## Final Verification

- [ ] All 4 slices committed and pushed
- [ ] Full test suite passes (backend + frontend)
- [ ] Ruff passes clean
- [ ] Visual verification of each slice via browser
- [ ] CHANGELOG.md updated with all improvements
