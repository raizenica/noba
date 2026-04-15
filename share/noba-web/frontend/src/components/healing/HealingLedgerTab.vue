<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useHealingStore } from '../../stores/healing'
import { LEDGER_TIMELINE_LIMIT } from '../../constants'

const store = useHealingStore()

// ── Ledger filters ────────────────────────────────────────────────────────────
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
</script>

<template>
  <div>
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
</template>
