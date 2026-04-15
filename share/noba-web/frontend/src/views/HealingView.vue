<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useHealingStore } from '../stores/healing'
import { useNotificationsStore } from '../stores/notifications'
import { useIntervals } from '../composables/useIntervals'
import { useModalsStore } from '../stores/modals'
import AppTabBar from '../components/ui/AppTabBar.vue'
import AppModal from '../components/ui/AppModal.vue'
import HealOverviewBar from '../components/healing/HealOverviewBar.vue'
import HealingOverviewTab from '../components/healing/HealingOverviewTab.vue'
import HealingLedgerTab from '../components/healing/HealingLedgerTab.vue'
import HealingApprovalTab from '../components/healing/HealingApprovalTab.vue'
import { HEALING_FETCH_ALL_INTERVAL_MS } from '../constants'

const authStore = useAuthStore()
const store = useHealingStore()
const notify = useNotificationsStore()
const modals = useModalsStore()
const { register, clearAll } = useIntervals()

const showInspectModal = ref(false)
const inspectedRow = ref(null)

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
function fmtTs(ts) {
  if (!ts) return '\u2013'
  return new Date(ts * 1000).toLocaleString()
}

function trustLevelClass(level) {
  if (level === 'execute') return 'bs'
  if (level === 'approve') return 'bw'
  return 'ba'
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  store.fetchAll()
  register('healing-refresh', () => store.fetchAll(), HEALING_FETCH_ALL_INTERVAL_MS)
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
    <HealingOverviewTab v-if="activeTab === 'overview'" />

    <!-- ── Ledger Tab ────────────────────────────────────────────────────── -->
    <HealingLedgerTab v-if="activeTab === 'ledger'" />

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
    <HealingApprovalTab v-if="activeTab === 'approvals'" />

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
