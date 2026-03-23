# Self-Healing Interface Implementation Plan (Phase 5 of 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full healing dashboard UI, configuration tabs, and template-driven integration cards. Make the self-healing system visible, manageable, and user-friendly.

**Architecture:** Extends the existing Vue 3 frontend. New components follow the established `DashboardCard` wrapper pattern, Pinia stores, and `useApi` composable. A new `useHealing` composable centralizes all healing API calls. The HealingView is rebuilt with 10 panels. New settings tabs for healing config and maintenance windows. Template-driven `IntegrationCard` component auto-renders cards for any configured integration instance.

**Tech Stack:** Vue 3 + Vite, Pinia, Chart.js, CSS variables (6 themes)

**Spec:** `docs/superpowers/specs/2026-03-22-full-self-healing-design.md` (Sections 12, 14, 16)

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `frontend/src/composables/useHealing.js` | Centralized healing API composable |
| `frontend/src/stores/healing.js` | Pinia store for healing state (ledger, trust, suggestions, dependencies, maintenance) |
| `frontend/src/components/healing/HealOverviewBar.vue` | Pipeline status bar (active/paused/degraded, pending approvals, circuit breakers) |
| `frontend/src/components/healing/EffectivenessPanel.vue` | Chart.js charts for success rate, MTTR, per-rule breakdown |
| `frontend/src/components/healing/LedgerTimeline.vue` | Vertical timeline with expandable entries, filters, export |
| `frontend/src/components/healing/DependencyGraph.vue` | Interactive SVG dependency visualization |
| `frontend/src/components/healing/TrustManager.vue` | Enhanced trust cards with history timeline |
| `frontend/src/components/healing/ApprovalQueue.vue` | Pending approvals with context cards and approve/deny/defer |
| `frontend/src/components/healing/MaintenancePanel.vue` | Active/scheduled windows with calendar and quick-create |
| `frontend/src/components/healing/SuggestionsPanel.vue` | Enhanced suggestions with accept/dismiss/snooze |
| `frontend/src/components/healing/CapabilityMatrix.vue` | Per-agent capability manifest view |
| `frontend/src/components/cards/IntegrationCard.vue` | Template-driven card for any integration instance |
| `frontend/src/components/settings/HealingTab.vue` | Healing settings (pipeline, risk, approval, prediction) |
| `frontend/src/components/settings/MaintenanceTab.vue` | Maintenance window management |

### Modified files
| File | Change |
|------|--------|
| `frontend/src/views/HealingView.vue` | Complete rebuild with 10-panel layout |
| `frontend/src/views/DashboardView.vue` | Add IntegrationCard rendering for configured instances |
| `frontend/src/views/SettingsView.vue` | Register new settings tabs |
| `frontend/src/router/index.js` | No changes needed (healing route exists) |

---

## Task 1: Healing Store + Composable

**Files:**
- Create: `share/noba-web/frontend/src/stores/healing.js`
- Create: `share/noba-web/frontend/src/composables/useHealing.js`

The healing store centralizes all self-healing state. The composable wraps API calls.

### useHealing.js
```javascript
import { useApi } from './useApi'

export function useHealing() {
  const { get, post, del } = useApi()

  return {
    // Ledger
    fetchLedger: (params = {}) => {
      const qs = new URLSearchParams(params).toString()
      return get(`/api/healing/ledger${qs ? '?' + qs : ''}`)
    },

    // Effectiveness
    fetchEffectiveness: () => get('/api/healing/effectiveness'),

    // Trust
    fetchTrust: () => get('/api/healing/trust'),
    promoteTrust: (ruleId) => post(`/api/healing/trust/${ruleId}/promote`),

    // Suggestions
    fetchSuggestions: () => get('/api/healing/suggestions'),
    dismissSuggestion: (id) => post(`/api/healing/suggestions/${id}/dismiss`),

    // Dependencies
    fetchDependencies: () => get('/api/healing/dependencies'),
    validateDependencies: (config) => post('/api/healing/dependencies/validate', config),

    // Maintenance
    fetchMaintenance: () => get('/api/healing/maintenance'),
    createMaintenance: (data) => post('/api/healing/maintenance', data),
    endMaintenance: (id) => del(`/api/healing/maintenance/${id}`),

    // Capabilities
    fetchCapabilities: (hostname) => get(`/api/healing/capabilities/${hostname}`),
    refreshCapabilities: (hostname) => post(`/api/healing/capabilities/${hostname}/refresh`),

    // Rollback
    rollback: (ledgerId) => post(`/api/healing/rollback/${ledgerId}`),

    // Pipeline health
    fetchHealth: () => get('/api/healing/health'),
  }
}
```

### healing.js (Pinia store)
```javascript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useHealing } from '../composables/useHealing'

export const useHealingStore = defineStore('healing', () => {
  const healing = useHealing()

  const ledger = ref([])
  const trust = ref([])
  const suggestions = ref([])
  const dependencies = ref([])
  const maintenance = ref([])
  const effectiveness = ref({})
  const loading = ref(false)

  const pendingApprovals = computed(() =>
    ledger.value.filter(e => e.trust_level === 'approve' && !e.action_success)
  )
  const activeMaintenance = computed(() =>
    maintenance.value.filter(w => w.active)
  )
  const openCircuitBreakers = computed(() =>
    trust.value.filter(t => t.current_level === 'notify' && t.demotion_count > 0)
  )

  async function fetchAll() {
    loading.value = true
    try {
      const [l, t, s, d, m, e] = await Promise.all([
        healing.fetchLedger({ limit: 100 }),
        healing.fetchTrust(),
        healing.fetchSuggestions(),
        healing.fetchDependencies(),
        healing.fetchMaintenance(),
        healing.fetchEffectiveness(),
      ])
      if (l) ledger.value = l
      if (t) trust.value = t
      if (s) suggestions.value = s
      if (d) dependencies.value = d
      if (m) maintenance.value = m
      if (e) effectiveness.value = e
    } finally {
      loading.value = false
    }
  }

  return {
    ledger, trust, suggestions, dependencies, maintenance,
    effectiveness, loading, pendingApprovals, activeMaintenance,
    openCircuitBreakers, fetchAll,
  }
})
```

Commit: `git commit -m "feat(frontend): add healing store and useHealing composable"`

---

## Task 2: Heal Overview Bar + Rebuilt HealingView

**Files:**
- Create: `share/noba-web/frontend/src/components/healing/HealOverviewBar.vue`
- Modify: `share/noba-web/frontend/src/views/HealingView.vue`

### HealOverviewBar.vue
Top-of-page status bar showing:
- Pipeline status badge (Active/Paused/Maintenance/Degraded)
- Active heals count
- Pending approvals count (with urgency badge)
- Circuit breakers open count
- Active maintenance windows count

Uses CSS classes: `.heal-bar`, `.heal-stat`, badge classes from global.css.

### HealingView.vue rebuild
Replace the current 3-tab layout with a richer 6-tab layout:
1. **Overview** — HealOverviewBar + EffectivenessPanel (charts)
2. **Ledger** — LedgerTimeline (enhanced from current table)
3. **Dependencies** — DependencyGraph visualization
4. **Trust** — TrustManager (enhanced from current cards)
5. **Approvals** — ApprovalQueue
6. **Maintenance** — MaintenancePanel

Each tab lazy-loads its component. The overview bar is always visible above tabs.

Commit: `git commit -m "feat(frontend): rebuild HealingView with overview bar and 6-tab layout"`

---

## Task 3: Ledger Timeline

**Files:**
- Create: `share/noba-web/frontend/src/components/healing/LedgerTimeline.vue`

Vertical timeline replacing the flat table. Each entry:
- Timestamp on the left
- Color-coded dot (green=verified, red=failed, yellow=unverified, grey=notify)
- Action type + target as the title
- Expandable detail showing: metrics before/after, approval info, rollback status, duration, escalation step
- Filter bar: by rule, target, risk level, result, date range
- Export button (JSON/CSV)

Uses existing `.badge` classes for status, `.card` for expandable detail.

Commit: `git commit -m "feat(frontend): add ledger timeline with expandable entries and filters"`

---

## Task 4: Effectiveness Charts

**Files:**
- Create: `share/noba-web/frontend/src/components/healing/EffectivenessPanel.vue`

Chart.js charts:
- **Success rate over time** — line chart (7d/30d/90d toggle)
- **MTTR** — line chart showing average time-to-resolution
- **Per-rule breakdown** — horizontal bar chart of success rates
- **Action type donut** — which actions verify most often

Uses Chart.js (already a dependency). Fetches data from `/api/healing/effectiveness`.

Commit: `git commit -m "feat(frontend): add effectiveness charts with success rate, MTTR, and breakdowns"`

---

## Task 5: Dependency Graph Visualization

**Files:**
- Create: `share/noba-web/frontend/src/components/healing/DependencyGraph.vue`

Interactive SVG-based graph:
- Nodes positioned in layers (external → infrastructure → service)
- Color-coded by health status (green=ok, yellow=degraded, red=down, grey=unknown)
- Edges as arrows showing dependency direction
- Click node → shows popover with recent heals, trust state, current alerts
- Connectivity-suspect sites shown with dashed border + grey overlay
- Auto-layout using simple top-down tree positioning (no external graph library needed)

Commit: `git commit -m "feat(frontend): add dependency graph visualization with interactive nodes"`

---

## Task 6: Approval Queue + Trust Manager + Suggestions

**Files:**
- Create: `share/noba-web/frontend/src/components/healing/ApprovalQueue.vue`
- Create: `share/noba-web/frontend/src/components/healing/TrustManager.vue`
- Create: `share/noba-web/frontend/src/components/healing/SuggestionsPanel.vue`

### ApprovalQueue
- Card per pending approval with full context (action, target, risk, evidence, escalation, rollback info)
- Approve/Deny/Defer buttons (role-gated)
- Timer showing time remaining before auto-deny
- Escalation indicator badge
- Historical section (collapsed by default)

### TrustManager
- Enhanced card per rule showing current level, ceiling, promotion/demotion timeline
- Visual trust progression bar (notify → approve → execute)
- Manual promote/demote buttons (admin only)
- Circuit breaker state indicator

### SuggestionsPanel
- Cards with category badge, severity, message, evidence preview
- Dependency candidate suggestions have "Accept" button (adds to graph)
- Accept/Dismiss/Snooze actions
- Badge counter in tab nav

Commit: `git commit -m "feat(frontend): add approval queue, trust manager, and suggestions panels"`

---

## Task 7: Maintenance Panel

**Files:**
- Create: `share/noba-web/frontend/src/components/healing/MaintenancePanel.vue`

- Active windows list with countdown timer and "End Early" button
- Scheduled windows list (from YAML config)
- "Enter Maintenance" quick-create form: target selector, duration picker, reason, action type
- Queued events during active window (expandable)

Commit: `git commit -m "feat(frontend): add maintenance window management panel"`

---

## Task 8: Capability Matrix

**Files:**
- Create: `share/noba-web/frontend/src/components/healing/CapabilityMatrix.vue`

- Per-agent row showing: hostname, OS, distro, init system
- Capability badges (green=available, yellow=degraded, red=unavailable)
- Last probe timestamp
- "Refresh" button per agent
- Expandable detail showing full manifest

Commit: `git commit -m "feat(frontend): add per-agent capability matrix view"`

---

## Task 9: Template-Driven Integration Cards

**Files:**
- Create: `share/noba-web/frontend/src/components/cards/IntegrationCard.vue`
- Modify: `share/noba-web/frontend/src/views/DashboardView.vue`

### IntegrationCard.vue
Generic card that renders any integration instance based on a template:

```vue
<template>
  <DashboardCard :title="instance.id" :icon="template.icon" :health="health">
    <div class="integration-metrics">
      <div v-for="metric in template.metrics" :key="metric.key" class="row">
        <span class="row-label">{{ metric.label }}</span>
        <span v-if="metric.type === 'status'" class="row-val">
          <span :class="['badge', statusBadgeClass(data[metric.key])]">
            {{ data[metric.key] || 'unknown' }}
          </span>
        </span>
        <span v-else-if="metric.type === 'percent_bar'" class="row-val">
          <div class="prog">
            <div class="prog-track" :style="{ width: (data[metric.key]||0) + '%' }" />
          </div>
          <span class="prog-meta">{{ data[metric.key]||0 }}%</span>
        </span>
        <span v-else class="row-val">{{ data[metric.key] ?? '—' }}</span>
      </div>
    </div>
    <div v-if="instance.site" class="row">
      <span class="row-label">Site</span>
      <span class="row-val badge ba">{{ instance.site }}</span>
    </div>
  </DashboardCard>
</template>
```

Props: `instance` (from integration_instances), `template` (card template definition), `data` (live metrics from collector).

### Dashboard integration
In DashboardView, after existing cards, add a section that renders IntegrationCards for each configured integration instance. Data comes from the dashboard store's live data (integration collectors already report metrics).

Commit: `git commit -m "feat(frontend): add template-driven IntegrationCard for any platform"`

---

## Task 10: Settings Tabs (Healing + Maintenance)

**Files:**
- Create: `share/noba-web/frontend/src/components/settings/HealingTab.vue`
- Create: `share/noba-web/frontend/src/components/settings/MaintenanceTab.vue`
- Modify: `share/noba-web/frontend/src/views/SettingsView.vue`

### HealingTab.vue
Settings sections:
- **General**: Pipeline enable/disable, global heal cooldown
- **Risk Overrides**: Override default risk level per action type
- **Approval Policy**: Timeout per stage, max defers, emergency override toggle
- **Predictive**: Enable/disable, evaluation interval, horizon thresholds
- **Notification Routing**: Channel for heal events, digest settings

### MaintenanceTab.vue
- CRUD for scheduled maintenance windows (cron editor, duration, target, action)
- Active windows overview
- History of past windows

### SettingsView.vue
Register the two new tabs in the tab list.

Commit: `git commit -m "feat(frontend): add healing and maintenance settings tabs"`

---

## Task 11: Build Frontend + Lint + Final Integration

- [ ] **Step 1: Build frontend**
```bash
cd share/noba-web/frontend && npm run build
```

- [ ] **Step 2: Copy built assets to static/dist/**

- [ ] **Step 3: Run all backend tests**
```bash
pytest tests/ -v --tb=short 2>&1 | tail -5
```

- [ ] **Step 4: Update CHANGELOG.md**

- [ ] **Step 5: Commit built assets + CHANGELOG**
```bash
git commit -m "chore: build frontend + update CHANGELOG for heal interface phase"
```
