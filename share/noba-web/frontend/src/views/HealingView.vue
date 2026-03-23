<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useHealingStore } from '../stores/healing'
import { useNotificationsStore } from '../stores/notifications'
import { useIntervals } from '../composables/useIntervals'
import HealOverviewBar from '../components/healing/HealOverviewBar.vue'

const authStore = useAuthStore()
const store = useHealingStore()
const notify = useNotificationsStore()
const { addInterval, clearAll } = useIntervals()

// ── Tab state ─────────────────────────────────────────────────────────────────
const activeTab = ref('overview')

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
    const params = { limit: 100 }
    if (ledgerFilterRule.value) params.rule_id = ledgerFilterRule.value
    if (ledgerFilterTarget.value) params.target = ledgerFilterTarget.value
    await store.fetchLedger(params)
  } finally {
    ledgerLoading.value = false
  }
}

// ── Trust actions ─────────────────────────────────────────────────────────────
const promoteConfirm = ref(null)
const promoteLoading = ref(false)

function openPromote(ruleId) {
  promoteConfirm.value = ruleId
}

function cancelPromote() {
  promoteConfirm.value = null
}

async function confirmPromote(ruleId) {
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
    promoteConfirm.value = null
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
  addInterval(() => store.fetchAll(), 30000)
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
    <div class="tab-nav" style="margin-bottom:20px">
      <button
        class="btn"
        :class="activeTab === 'overview' ? 'btn-primary' : ''"
        @click="activeTab = 'overview'"
      >
        <i class="fas fa-chart-line" style="margin-right:6px"></i>Overview
        <span v-if="store.suggestionCount" class="nav-badge" style="margin-left:6px">{{ store.suggestionCount }}</span>
      </button>
      <button
        class="btn"
        :class="activeTab === 'ledger' ? 'btn-primary' : ''"
        @click="activeTab = 'ledger'"
        style="margin-left:8px"
      >
        <i class="fas fa-list-alt" style="margin-right:6px"></i>Ledger
      </button>
      <button
        class="btn"
        :class="activeTab === 'dependencies' ? 'btn-primary' : ''"
        @click="activeTab = 'dependencies'"
        style="margin-left:8px"
      >
        <i class="fas fa-project-diagram" style="margin-right:6px"></i>Dependencies
      </button>
      <button
        class="btn"
        :class="activeTab === 'trust' ? 'btn-primary' : ''"
        @click="activeTab = 'trust'"
        style="margin-left:8px"
      >
        <i class="fas fa-shield-alt" style="margin-right:6px"></i>Trust
      </button>
      <button
        class="btn"
        :class="activeTab === 'approvals' ? 'btn-primary' : ''"
        @click="activeTab = 'approvals'"
        style="margin-left:8px"
      >
        <i class="fas fa-check-circle" style="margin-right:6px"></i>Approvals
        <span v-if="approvalBadge" class="nav-badge" style="margin-left:6px">{{ approvalBadge }}</span>
      </button>
      <button
        class="btn"
        :class="activeTab === 'maintenance' ? 'btn-primary' : ''"
        @click="activeTab = 'maintenance'"
        style="margin-left:8px"
      >
        <i class="fas fa-wrench" style="margin-right:6px"></i>Maintenance
        <span v-if="maintenanceBadge" class="nav-badge" style="margin-left:6px">{{ maintenanceBadge }}</span>
      </button>
    </div>

    <!-- ── Overview Tab ──────────────────────────────────────────────────── -->
    <div v-if="activeTab === 'overview'">
      <!-- Effectiveness Summary -->
      <div class="card" style="margin-bottom:16px">
        <div class="card-header">
          <h3 class="card-title"><i class="fas fa-chart-bar" style="margin-right:6px"></i>Effectiveness Summary</h3>
        </div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <div v-if="store.loading && effectivenessEntries.length === 0" style="padding:24px;text-align:center;color:var(--text-muted)">
            <i class="fas fa-spinner fa-spin"></i> Loading...
          </div>
          <p v-else-if="effectivenessEntries.length === 0" class="empty-msg">No effectiveness data available yet.</p>
          <table v-else style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="background:var(--surface2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px">
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Rule</th>
                <th style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Total</th>
                <th style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Success</th>
                <th style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Failed</th>
                <th style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Rate</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in effectivenessEntries" :key="entry.rule_id" style="border-bottom:1px solid var(--border)" class="table-row-hover">
                <td style="padding:9px 14px;font-family:monospace;font-size:12px">{{ entry.rule_id || '\u2013' }}</td>
                <td style="padding:9px 14px;text-align:center">{{ entry.total || entry.count || 0 }}</td>
                <td style="padding:9px 14px;text-align:center;color:var(--success);font-weight:600">{{ entry.successes || entry.success || 0 }}</td>
                <td style="padding:9px 14px;text-align:center;color:var(--danger);font-weight:600">{{ entry.failures || entry.failed || 0 }}</td>
                <td style="padding:9px 14px;text-align:center">
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
          <h3 class="card-title"><i class="fas fa-lightbulb" style="margin-right:6px"></i>Suggestions</h3>
        </div>
        <div class="card-body">
          <div v-if="store.loading && store.suggestions.length === 0" style="padding:24px;text-align:center;color:var(--text-muted)">
            <i class="fas fa-spinner fa-spin"></i> Loading...
          </div>
          <p v-else-if="store.suggestions.length === 0" class="empty-msg" style="margin:0">No suggestions at this time. The pipeline is running smoothly.</p>
          <div v-else style="display:flex;flex-direction:column;gap:12px">
            <div v-for="sug in store.suggestions" :key="sug.id" style="display:flex;align-items:flex-start;gap:14px;padding:10px 0;border-bottom:1px solid var(--border)">
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
          <table style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="background:var(--surface2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px">
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Timestamp</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Rule ID</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Target</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Action</th>
                <th style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Step</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Trust</th>
                <th style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Success</th>
                <th style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Verified</th>
                <th style="padding:10px 14px;text-align:right;border-bottom:1px solid var(--border)">Duration</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="store.loading && filteredLedger.length === 0">
                <td colspan="9" style="padding:24px;text-align:center;color:var(--text-muted)">
                  <i class="fas fa-spinner fa-spin"></i> Loading...
                </td>
              </tr>
              <tr v-else-if="filteredLedger.length === 0">
                <td colspan="9" class="empty-msg">No heal outcomes recorded yet.</td>
              </tr>
              <tr
                v-for="row in filteredLedger"
                :key="row.id || (row.rule_id + row.ts)"
                :style="ledgerRowStyle(row)"
                style="border-bottom:1px solid var(--border);transition:background .15s"
                class="table-row-hover"
              >
                <td style="padding:9px 14px;color:var(--text-muted);white-space:nowrap">{{ fmtTs(row.ts) }}</td>
                <td style="padding:9px 14px;font-family:monospace;font-size:12px">{{ row.rule_id || '\u2013' }}</td>
                <td style="padding:9px 14px;font-family:monospace;font-size:12px">{{ row.target || '\u2013' }}</td>
                <td style="padding:9px 14px">
                  <span class="badge ba">{{ row.action_type || '\u2013' }}</span>
                </td>
                <td style="padding:9px 14px;text-align:center">{{ row.escalation_step ||0 }}</td>
                <td style="padding:9px 14px">
                  <span v-if="row.trust_level" class="badge" :class="trustLevelClass(row.trust_level)">{{ row.trust_level }}</span>
                  <span v-else style="color:var(--text-muted)">\u2013</span>
                </td>
                <td style="padding:9px 14px;text-align:center;font-weight:600"
                    :style="{ color: row.action_success === true ? 'var(--success)' : row.action_success === false ? 'var(--danger)' : 'var(--text-muted)' }">
                  {{ fmtBool(row.action_success) }}
                </td>
                <td style="padding:9px 14px;text-align:center;font-weight:600"
                    :style="{ color: row.verified === true ? 'var(--success)' : row.verified === false ? 'var(--warning)' : 'var(--text-muted)' }">
                  {{ fmtBool(row.verified) }}
                </td>
                <td style="padding:9px 14px;text-align:right;color:var(--text-muted)">
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
          <h3 class="card-title"><i class="fas fa-project-diagram" style="margin-right:6px"></i>Service Dependencies</h3>
        </div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <div v-if="store.loading && store.dependencies.length === 0" style="padding:24px;text-align:center;color:var(--text-muted)">
            <i class="fas fa-spinner fa-spin"></i> Loading...
          </div>
          <p v-else-if="store.dependencies.length === 0" class="empty-msg">No dependencies configured.</p>
          <table v-else style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="background:var(--surface2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px">
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Service</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Depends On</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Type</th>
                <th style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(dep, idx) in store.dependencies" :key="idx" style="border-bottom:1px solid var(--border)" class="table-row-hover">
                <td style="padding:9px 14px;font-family:monospace;font-size:12px">{{ dep.service || dep.from || '\u2013' }}</td>
                <td style="padding:9px 14px;font-family:monospace;font-size:12px">{{ dep.depends_on || dep.to || '\u2013' }}</td>
                <td style="padding:9px 14px">
                  <span class="badge ba">{{ dep.type || dep.dependency_type || 'hard' }}</span>
                </td>
                <td style="padding:9px 14px;text-align:center">
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

      <p v-else-if="store.trust.length === 0" class="empty-msg">No trust states found.</p>

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
                  v-if="promoteConfirm !== state.rule_id"
                  class="btn btn-xs"
                  @click="openPromote(state.rule_id)"
                >
                  <i class="fas fa-arrow-up"></i> Promote
                </button>
                <div v-else style="display:flex;gap:6px;align-items:center">
                  <span style="font-size:12px;color:var(--text-muted)">Sure?</span>
                  <button class="btn btn-xs btn-primary" :disabled="promoteLoading" @click="confirmPromote(state.rule_id)">
                    <i v-if="promoteLoading" class="fas fa-spinner fa-spin"></i>
                    <span v-else>Yes</span>
                  </button>
                  <button class="btn btn-xs" @click="cancelPromote">No</button>
                </div>
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
          <h3 class="card-title"><i class="fas fa-check-circle" style="margin-right:6px"></i>Pending Approvals</h3>
        </div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <div v-if="store.loading && store.pendingApprovals.length === 0" style="padding:24px;text-align:center;color:var(--text-muted)">
            <i class="fas fa-spinner fa-spin"></i> Loading...
          </div>
          <p v-else-if="store.pendingApprovals.length === 0" class="empty-msg">No pending approvals. All heal actions are autonomous or completed.</p>
          <table v-else style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="background:var(--surface2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px">
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Timestamp</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Rule ID</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Target</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Action</th>
                <th style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Step</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Trust</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in store.pendingApprovals"
                :key="row.id || (row.rule_id + row.ts)"
                style="border-bottom:1px solid var(--border);transition:background .15s"
                class="table-row-hover"
              >
                <td style="padding:9px 14px;color:var(--text-muted);white-space:nowrap">{{ fmtTs(row.ts) }}</td>
                <td style="padding:9px 14px;font-family:monospace;font-size:12px">{{ row.rule_id || '\u2013' }}</td>
                <td style="padding:9px 14px;font-family:monospace;font-size:12px">{{ row.target || '\u2013' }}</td>
                <td style="padding:9px 14px">
                  <span class="badge ba">{{ row.action_type || '\u2013' }}</span>
                </td>
                <td style="padding:9px 14px;text-align:center">{{ row.escalation_step ||0 }}</td>
                <td style="padding:9px 14px">
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
          <h3 class="card-title"><i class="fas fa-wrench" style="margin-right:6px"></i>Maintenance Windows</h3>
        </div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          <div v-if="store.loading && store.maintenance.length === 0" style="padding:24px;text-align:center;color:var(--text-muted)">
            <i class="fas fa-spinner fa-spin"></i> Loading...
          </div>
          <p v-else-if="store.maintenance.length === 0" class="empty-msg">No maintenance windows configured.</p>
          <table v-else style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="background:var(--surface2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px">
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Target</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Reason</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">Start</th>
                <th style="padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)">End</th>
                <th style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Status</th>
                <th v-if="authStore.isOperator" style="padding:10px 14px;text-align:center;border-bottom:1px solid var(--border)">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="mw in store.maintenance"
                :key="mw.id"
                style="border-bottom:1px solid var(--border);transition:background .15s"
                class="table-row-hover"
              >
                <td style="padding:9px 14px;font-family:monospace;font-size:12px">{{ mw.target || mw.hostname || '\u2013' }}</td>
                <td style="padding:9px 14px">{{ mw.reason || '\u2013' }}</td>
                <td style="padding:9px 14px;color:var(--text-muted);white-space:nowrap">{{ fmtTs(mw.start_ts || mw.created_at) }}</td>
                <td style="padding:9px 14px;color:var(--text-muted);white-space:nowrap">{{ fmtTs(mw.end_ts) }}</td>
                <td style="padding:9px 14px;text-align:center">
                  <span class="badge" :class="mw.active ? 'bw' : 'bs'">{{ mw.active ? 'Active' : 'Ended' }}</span>
                </td>
                <td v-if="authStore.isOperator" style="padding:9px 14px;text-align:center">
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
  </div>
</template>
