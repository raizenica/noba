<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useHealingStore } from '../stores/healing'
import { useNotificationsStore } from '../stores/notifications'
import { useIntervals } from '../composables/useIntervals'
import { useModalsStore } from '../stores/modals'
import AppTabBar from '../components/ui/AppTabBar.vue'
import HealOverviewBar from '../components/healing/HealOverviewBar.vue'
import { HEALING_FETCH_ALL_INTERVAL_MS, LEDGER_TIMELINE_LIMIT } from '../constants'

const authStore = useAuthStore()
const store = useHealingStore()
const notify = useNotificationsStore()
const modals = useModalsStore()
const { addInterval, clearAll } = useIntervals()

// ── Tab state ─────────────────────────────────────────────────────────────────
const activeTab = ref('overview')

const tabs = computed(() => [
  { key: 'overview',     label: 'Overview',     icon: 'fa-chart-line', badge: store.suggestionCount },
  { key: 'ledger',       label: 'Ledger',       icon: 'fa-list-alt' },
  { key: 'dependencies', label: 'Dependencies', icon: 'fa-project-diagram' },
  { key: 'trust',        label: 'Trust',        icon: 'fa-shield-alt' },
  { key: 'approvals',    label: 'Approvals',    icon: 'fa-check-circle', badge: store.pendingApprovals.length },
  { key: 'maintenance',  label: 'Maintenance',  icon: 'fa-wrench',       badge: store.activeMaintenance.length },
])

// ── Ledger filters (local to view) ────────────────────────────────────────────
const ledgerFilterRule = ref('')
const ledgerFilterTarget = ref('')
const ledgerLoading = ref(false)

const ledgerRuleOptions = computed(() => {
  const ids = [...new Set(store.ledger.map(r => r.rule_id).filter(Boolean))]
  return ids.sort()
})

const ledgerTargetOptions = computed(() => {
  const targets = [...new Set(store.ledger.map(r => r.target).filter(Boolean))]
  return targets.sort()
})

const filteredLedger = computed(() => {
  return store.ledger.filter(r => {
    if (ledgerFilterRule.value && r.rule_id !== ledgerFilterRule.value) return false
    if (ledgerFilterTarget.value && r.target !== ledgerFilterTarget.value) return false
    return true
  })
})

async function refetchLedger() {
  ledgerLoading.value = true
  try {
    const params = { limit: LEDGER_TIMELINE_LIMIT }
    if (ledgerFilterRule.value) params.rule_id = ledgerFilterRule.value
    if (ledgerFilterTarget.value) params.target = ledgerFilterTarget.value
    await store.fetchLedger(params)
  } finally {
    ledgerLoading.value = false
  }
}

// ── Trust actions ─────────────────────────────────────────────────────────────
const promoteLoading = ref(false)

async function confirmPromote(ruleId) {
  const ok = await modals.confirm(`Promote trust level for rule "${ruleId}"?`)
  if (!ok) return
  
  promoteLoading.value = true
  try {
    const res = await store.promoteTrust(ruleId)
    if (res && res.success) {
      notify.addToast(`Rule ${ruleId} promoted to ${res.new_level}`, 'success')
    }
  } catch {
    notify.addToast('Failed to promote trust level', 'error')
  } finally {
    promoteLoading.value = false
  }
}

// ── Suggestion actions ────────────────────────────────────────────────────────
const dismissingId = ref(null)

async function dismissSuggestion(id) {
  dismissingId.value = id
  try {
    const res = await store.dismissSuggestion(id)
    if (res && res.success) {
      notify.addToast('Suggestion dismissed', 'success')
    }
  } catch {
    notify.addToast('Failed to dismiss suggestion', 'error')
  } finally {
    dismissingId.value = null
  }
}

// ── Maintenance actions ───────────────────────────────────────────────────────
const endingMaintId = ref(null)

async function endMaintenance(id) {
  endingMaintId.value = id
  try {
    const res = await store.endMaintenanceWindow(id)
    if (res) {
      notify.addToast('Maintenance window ended', 'success')
    }
  } catch {
    notify.addToast('Failed to end maintenance window', 'error')
  } finally {
    endingMaintId.value = null
  }
}

// ── Formatters ────────────────────────────────────────────────────────────────
function fmtBool(val) {
  if (val === true) return '\u2713'
  if (val === false) return '\u2717'
  return '\u2013'
}

function fmtTs(ts) {
  if (!ts) return '\u2013'
  return new Date(ts * 1000).toLocaleString()
}

function ledgerRowStyle(row) {
  if (row.verified === true) return { borderLeft: '3px solid var(--success)' }
  if (row.action_success === false) return { borderLeft: '3px solid var(--danger)' }
  if (row.verified === false) return { borderLeft: '3px solid var(--warning)' }
  return {}
}

function trustLevelClass(level) {
  if (level === 'execute') return 'bs'
  if (level === 'approve') return 'bw'
  return 'ba'
}

function severityClass(severity) {
  if (severity === 'high') return 'bd'
  if (severity === 'medium') return 'bw'
  return 'bs'
}

// ── Tab badge counts ──────────────────────────────────────────────────────────
const approvalBadge = computed(() => store.pendingApprovals.length || 0)
const maintenanceBadge = computed(() => store.activeMaintenance.length || 0)

// ── Effectiveness summary ─────────────────────────────────────────────────────
const effectivenessEntries = computed(() => {
  const eff = store.effectiveness
  if (!eff || typeof eff !== 'object') return []
  if (Array.isArray(eff)) return eff
  return Object.entries(eff).map(([rule_id, stats]) => ({ rule_id, ...stats }))
})

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  store.fetchAll()
  addInterval(() => store.fetchAll(), HEALING_FETCH_ALL_INTERVAL_MS)
})

onUnmounted(() => {
  clearAll()
})
</script>

<template>
  <div class="view-root">
    <div class="view-header">
      <h1 class="view-title"><i class="fas fa-heartbeat" style="margin-right:8px"></i>Self-Healing</h1>
      <p class="view-subtitle">Monitor heal outcomes, trust levels, and pipeline suggestions</p>
    </div>

    <!-- Overview Bar -->
    <HealOverviewBar />

    <!-- Tab nav -->
    <AppTabBar :tabs="tabs" :active="activeTab" @change="(key) => activeTab = key" />

    <!-- ── Overview Tab ──────────────────────────────────────────────────── -->
    <div v-if="activeTab === 'overview'">
      <!-- Effectiveness Summary -->
      <div class="card" style="margin-bottom:16px">
        <div class="card-header">
          <h3 class="card-title"><i class="fas fa-chart-bar mr-6"></i>Effectiveness Summary</h3>
        </div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <div v-if="store.loading && effectivenessEntries.length === 0" style="padding:24px;text-align:center;color:var(--text-muted)">
            <i class="fas fa-spinner fa-spin"></i> Loading...
          </div>
          <p v-else-if="effectivenessEntries.length === 0" class="empty-msg">No effectiveness data yet — metrics appear once healing actions have run.</p>
          <table v-else style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="background:var(--surface2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px">
                <th class="th-left">Rule</th>
                <th class="th-center">Total</th>
                <th class="th-center">Success</th>
                <th class="th-center">Failed</th>
                <th class="th-center">Rate</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in effectivenessEntries" :key="entry.rule_id" class="border-b table-row-hover">
                <td class="td-body" style="font-family:monospace;font-size:12px">{{ entry.rule_id || '\u2013' }}</td>
                <td class="td-body-center">{{ entry.total || entry.count || 0 }}</td>
                <td class="td-body-center" style="color:var(--success);font-weight:600">{{ entry.successes || entry.success || 0 }}</td>
                <td class="td-body-center" style="color:var(--danger);font-weight:600">{{ entry.failures || entry.failed || 0 }}</td>
                <td class="td-body-center">
                  <span class="badge" :class="(entry.rate || entry.success_rate || 0) >= 0.8 ? 'bs' : (entry.rate || entry.success_rate || 0) >= 0.5 ? 'bw' : 'bd'">
                    {{ ((entry.rate || entry.success_rate || 0) * 100).toFixed(0) }}%
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Suggestions -->
      <div class="card">
        <div class="card-header">
          <h3 class="card-title"><i class="fas fa-lightbulb mr-6"></i>Suggestions</h3>
        </div>
        <div class="card-body">
          <div v-if="store.loading && store.suggestions.length === 0" style="padding:24px;text-align:center;color:var(--text-muted)">
            <i class="fas fa-spinner fa-spin"></i> Loading...
          </div>
          <p v-else-if="store.suggestions.length === 0" class="empty-msg" style="margin:0">No suggestions at this time. The pipeline is running smoothly.</p>
          <div v-else style="display:flex;flex-direction:column;gap:12px">
            <div v-for="sug in store.suggestions" :key="sug.id" class="border-b" style="display:flex;align-items:flex-start;gap:14px;padding:10px 0">
              <div style="flex:1">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap">
                  <span class="badge ba">{{ sug.category || 'general' }}</span>
                  <span class="badge" :class="severityClass(sug.severity)">{{ sug.severity || 'low' }}</span>
                  <span v-if="sug.rule_id" style="font-family:monospace;font-size:11px;color:var(--text-muted)">{{ sug.rule_id }}</span>
                </div>
                <p style="margin:0;font-size:13px;line-height:1.5">{{ sug.message }}</p>
              </div>
              <div v-if="authStore.isOperator" style="flex-shrink:0">
                <button class="btn btn-xs" :disabled="dismissingId === sug.id" @click="dismissSuggestion(sug.id)">
                  <i v-if="dismissingId === sug.id" class="fas fa-spinner fa-spin"></i>
                  <i v-else class="fas fa-times"></i>
                  Dismiss
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Ledger Tab ────────────────────────────────────────────────────── -->
    <div v-if="activeTab === 'ledger'">
      <!-- Filters -->
      <div style="display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;align-items:center">
        <select v-model="ledgerFilterRule" class="form-select" style="width:auto" @change="refetchLedger">
          <option value="">All rules</option>
          <option v-for="r in ledgerRuleOptions" :key="r" :value="r">{{ r }}</option>
        </select>
        <select v-model="ledgerFilterTarget" class="form-select" style="width:auto" @change="refetchLedger">
          <option value="">All targets</option>
          <option v-for="t in ledgerTargetOptions" :key="t" :value="t">{{ t }}</option>
        </select>
        <button class="btn btn-xs" @click="refetchLedger" :disabled="ledgerLoading">
          <i class="fas fa-sync-alt" :class="{ 'fa-spin': ledgerLoading }"></i>
          Refresh
        </button>
        <span style="color:var(--text-muted);font-size:12px">Auto-refreshes every 30s</span>
      </div>

      <!-- Table -->
      <div class="card">
        <div class="card-body" style="padding:0;overflow-x:auto">
          <div v-if="store.loading && filteredLedger.length === 0" style="padding:32px;text-align:center;color:var(--text-muted)">
            <i class="fas fa-spinner fa-spin"></i> Loading...
          </div>
          <div v-else-if="filteredLedger.length === 0" class="empty-msg" style="padding:3rem;text-align:center">
            <i class="fas fa-history" style="font-size:2.5rem;opacity:.2;display:block;margin-bottom:1rem;margin-inline:auto"></i>
            No heal events recorded yet.
            <br><small style="opacity:.6;max-width:400px;display:inline-block">The pipeline will automatically log events here as it detects and resolves system anomalies across your agents.</small>
          </div>
          <table v-else style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="background:var(--surface2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px">
                <th class="th-left">Timestamp</th>
                <th class="th-left">Rule ID</th>
                <th class="th-left">Target</th>
                <th class="th-left">Action</th>
                <th class="th-center">Step</th>
                <th class="th-left">Trust</th>
                <th class="th-center">Success</th>
                <th class="th-center">Verified</th>
                <th class="th-right">Duration</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in filteredLedger"
                :key="row.id || (row.rule_id + row.ts)"
                :style="ledgerRowStyle(row)"
                class="border-b table-row-hover" style="transition:background .15s"
              >
                <td class="td-body" style="color:var(--text-muted);white-space:nowrap">{{ fmtTs(row.ts) }}</td>
                <td class="td-body" style="font-family:monospace;font-size:12px">{{ row.rule_id || '\u2013' }}</td>
                <td class="td-body" style="font-family:monospace;font-size:12px">{{ row.target || '\u2013' }}</td>
                <td class="td-body">
                  <span class="badge ba">{{ row.action_type || '\u2013' }}</span>
                </td>
                <td class="td-body-center">{{ row.escalation_step ||0 }}</td>
                <td class="td-body">
                  <span v-if="row.trust_level" class="badge" :class="trustLevelClass(row.trust_level)">{{ row.trust_level }}</span>
                  <span v-else style="color:var(--text-muted)">\u2013</span>
                </td>
                <td class="td-body-center" style="font-weight:600"
                    :style="{ color: row.action_success === true ? 'var(--success)' : row.action_success === false ? 'var(--danger)' : 'var(--text-muted)' }">
                  {{ fmtBool(row.action_success) }}
                </td>
                <td class="td-body-center" style="font-weight:600"
                    :style="{ color: row.verified === true ? 'var(--success)' : row.verified === false ? 'var(--warning)' : 'var(--text-muted)' }">
                  {{ fmtBool(row.verified) }}
                </td>
                <td class="td-body-right" style="color:var(--text-muted)">
                  {{ row.duration_s != null ? (row.duration_s ||0).toFixed(1) + 's' : '\u2013' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ── Dependencies Tab ──────────────────────────────────────────────── -->
    <div v-if="activeTab === 'dependencies'">
      <div class="card">
        <div class="card-header">
          <h3 class="card-title"><i class="fas fa-project-diagram mr-6"></i>Service Dependencies</h3>
        </div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <div v-if="store.loading && store.dependencies.length === 0" style="padding:24px;text-align:center;color:var(--text-muted)">
            <i class="fas fa-spinner fa-spin"></i> Loading...
          </div>
          <p v-else-if="store.dependencies.length === 0" class="empty-msg">No dependencies configured.</p>
          <table v-else style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="background:var(--surface2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px">
                <th class="th-left">Service</th>
                <th class="th-left">Depends On</th>
                <th class="th-left">Type</th>
                <th class="th-center">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(dep, idx) in store.dependencies" :key="idx" class="border-b table-row-hover">
                <td class="td-body" style="font-family:monospace;font-size:12px">{{ dep.service || dep.from || '\u2013' }}</td>
                <td class="td-body" style="font-family:monospace;font-size:12px">{{ dep.depends_on || dep.to || '\u2013' }}</td>
                <td class="td-body">
                  <span class="badge ba">{{ dep.type || dep.dependency_type || 'hard' }}</span>
                </td>
                <td class="td-body-center">
                  <span class="badge" :class="dep.healthy !== false ? 'bs' : 'bd'">
                    {{ dep.healthy !== false ? 'OK' : 'Down' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ── Trust Tab ─────────────────────────────────────────────────────── -->
    <div v-if="activeTab === 'trust'">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
        <button class="btn btn-xs" @click="store.fetchTrust()" :disabled="store.loading">
          <i class="fas fa-sync-alt" :class="{ 'fa-spin': store.loading }"></i>
          Refresh
        </button>
      </div>

      <div v-if="store.loading && store.trust.length === 0" style="padding:32px;text-align:center;color:var(--text-muted)">
        <i class="fas fa-spinner fa-spin"></i> Loading...
      </div>

      <div v-else-if="store.trust.length === 0" class="empty-msg" style="padding:2rem;text-align:center">
        <i class="fas fa-shield-alt" style="font-size:2rem;opacity:.3;display:block;margin-bottom:.5rem"></i>
        No trust states yet.
        <br><small style="opacity:.6">Trust levels are created automatically when healing rules first execute.</small>
      </div>

      <div v-else style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px">
        <div v-for="state in store.trust" :key="state.rule_id" class="card">
          <div class="card-body">
            <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:12px">
              <div>
                <div style="font-family:monospace;font-size:13px;font-weight:600;margin-bottom:4px">{{ state.rule_id }}</div>
                <span class="badge" :class="trustLevelClass(state.current_level)">{{ state.current_level }}</span>
              </div>
              <div v-if="authStore.isAdmin">
                <button
                  class="btn btn-xs"
                  :disabled="promoteLoading"
                  @click="confirmPromote(state.rule_id)"
                >
                  <i class="fas" :class="promoteLoading ? 'fa-spinner fa-spin' : 'fa-arrow-up'"></i>
                  Promote
                </button>
              </div>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:12px">
              <div style="color:var(--text-muted)">Ceiling</div>
              <div>
                <span class="badge" :class="trustLevelClass(state.ceiling)">{{ state.ceiling || '\u2013' }}</span>
              </div>
              <div style="color:var(--text-muted)">Promotions</div>
              <div style="color:var(--success);font-weight:600">{{ state.promotion_count ||0 }}</div>
              <div style="color:var(--text-muted)">Demotions</div>
              <div style="color:var(--danger);font-weight:600">{{ state.demotion_count ||0 }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Approvals Tab ─────────────────────────────────────────────────── -->
    <div v-if="activeTab === 'approvals'">
      <div class="card">
        <div class="card-header">
          <h3 class="card-title"><i class="fas fa-check-circle mr-6"></i>Pending Approvals</h3>
        </div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <div v-if="store.loading && store.pendingApprovals.length === 0" style="padding:24px;text-align:center;color:var(--text-muted)">
            <i class="fas fa-spinner fa-spin"></i> Loading...
          </div>
          <p v-else-if="store.pendingApprovals.length === 0" class="empty-msg">No pending approvals. All heal actions are autonomous or completed.</p>
          <table v-else style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="background:var(--surface2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px">
                <th class="th-left">Timestamp</th>
                <th class="th-left">Rule ID</th>
                <th class="th-left">Target</th>
                <th class="th-left">Action</th>
                <th class="th-center">Step</th>
                <th class="th-left">Trust</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in store.pendingApprovals"
                :key="row.id || (row.rule_id + row.ts)"
                class="border-b table-row-hover" style="transition:background .15s"
              >
                <td class="td-body" style="color:var(--text-muted);white-space:nowrap">{{ fmtTs(row.ts) }}</td>
                <td class="td-body" style="font-family:monospace;font-size:12px">{{ row.rule_id || '\u2013' }}</td>
                <td class="td-body" style="font-family:monospace;font-size:12px">{{ row.target || '\u2013' }}</td>
                <td class="td-body">
                  <span class="badge ba">{{ row.action_type || '\u2013' }}</span>
                </td>
                <td class="td-body-center">{{ row.escalation_step ||0 }}</td>
                <td class="td-body">
                  <span class="badge bw">{{ row.trust_level }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ── Maintenance Tab ───────────────────────────────────────────────── -->
    <div v-if="activeTab === 'maintenance'">
      <div class="card">
        <div class="card-header">
          <h3 class="card-title"><i class="fas fa-wrench mr-6"></i>Maintenance Windows</h3>
        </div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <div v-if="store.loading && store.maintenance.length === 0" style="padding:24px;text-align:center;color:var(--text-muted)">
            <i class="fas fa-spinner fa-spin"></i> Loading...
          </div>
          <p v-else-if="store.maintenance.length === 0" class="empty-msg">No maintenance windows configured.</p>
          <table v-else style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="background:var(--surface2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px">
                <th class="th-left">Target</th>
                <th class="th-left">Reason</th>
                <th class="th-left">Start</th>
                <th class="th-left">End</th>
                <th class="th-center">Status</th>
                <th v-if="authStore.isOperator" class="th-center">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="mw in store.maintenance"
                :key="mw.id"
                class="border-b table-row-hover" style="transition:background .15s"
              >
                <td class="td-body" style="font-family:monospace;font-size:12px">{{ mw.target || mw.hostname || '\u2013' }}</td>
                <td class="td-body">{{ mw.reason || '\u2013' }}</td>
                <td class="td-body" style="color:var(--text-muted);white-space:nowrap">{{ fmtTs(mw.start_ts || mw.created_at) }}</td>
                <td class="td-body" style="color:var(--text-muted);white-space:nowrap">{{ fmtTs(mw.end_ts) }}</td>
                <td class="td-body-center">
                  <span class="badge" :class="mw.active ? 'bw' : 'bs'">{{ mw.active ? 'Active' : 'Ended' }}</span>
                </td>
                <td v-if="authStore.isOperator" class="td-body-center">
                  <button
                    v-if="mw.active"
                    class="btn btn-xs"
                    :disabled="endingMaintId === mw.id"
                    @click="endMaintenance(mw.id)"
                  >
                    <i v-if="endingMaintId === mw.id" class="fas fa-spinner fa-spin"></i>
                    <i v-else class="fas fa-stop"></i>
                    End
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
    
    <!-- ── Inspect Modal ─────────────────────────────────────────────────── -->
    <AppModal :show="showInspectModal" title="Raw Execution Result" @close="showInspectModal = false" width="600px">
      <div v-if="inspectedRow" style="padding:1rem">
        <div style="margin-bottom:1rem;display:flex;gap:1rem;flex-wrap:wrap">
          <div><span style="font-size:11px;color:var(--text-muted);text-transform:uppercase">Target</span><br><code style="font-size:13px">{{ inspectedRow.target }}</code></div>
          <div><span style="font-size:11px;color:var(--text-muted);text-transform:uppercase">Rule ID</span><br><code style="font-size:13px">{{ inspectedRow.rule_id }}</code></div>
          <div><span style="font-size:11px;color:var(--text-muted);text-transform:uppercase">Action</span><br><span class="badge ba">{{ inspectedRow.action_type }}</span></div>
        </div>
        <div v-if="inspectedRow.error_message" style="margin-bottom:1rem">
          <span style="font-size:11px;color:var(--danger);text-transform:uppercase;font-weight:600">Error Message</span>
          <pre style="margin-top:4px;padding:8px;background:var(--surface);border-left:3px solid var(--danger);font-size:12px;white-space:pre-wrap;word-break:break-all;color:var(--danger)">{{ inspectedRow.error_message }}</pre>
        </div>
        <div style="margin-bottom:1rem">
          <span style="font-size:11px;color:var(--text-muted);text-transform:uppercase">Action Parameters (JSON)</span>
          <pre style="margin-top:4px;padding:8px;background:var(--surface);border:1px solid var(--border);border-radius:4px;font-size:12px;white-space:pre-wrap;word-break:break-all">{{ inspectedRow.action_params || '{}' }}</pre>
        </div>
        <div>
          <span style="font-size:11px;color:var(--text-muted);text-transform:uppercase">Verify Result (JSON)</span>
          <pre style="margin-top:4px;padding:8px;background:var(--surface);border:1px solid var(--border);border-radius:4px;font-size:12px;white-space:pre-wrap;word-break:break-all">{{ inspectedRow.verify_result || '{}' }}</pre>
        </div>
      </div>
    </AppModal>
  </div>
</template>
