<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useHealingStore } from '../../stores/healing'
import { useNotificationsStore } from '../../stores/notifications'

const authStore = useAuthStore()
const store = useHealingStore()
const notify = useNotificationsStore()

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

// ── Formatters ────────────────────────────────────────────────────────────────
function severityClass(severity) {
  if (severity === 'high') return 'bd'
  if (severity === 'medium') return 'bw'
  return 'bs'
}

// ── Effectiveness summary ─────────────────────────────────────────────────────
const RULE_LABELS = {
  total: 'Total',
  verified_count: 'Verified',
  failed_count: 'Failed',
  pending_count: 'Pending',
  success_rate: 'Success Rate',
}

const effectivenessEntries = computed(() => {
  const eff = store.effectiveness
  if (!eff || typeof eff !== 'object') return []
  if (Array.isArray(eff)) return eff
  return Object.entries(eff).map(([rule_id, stats]) => ({
    rule_id,
    display_name: RULE_LABELS[rule_id] || rule_id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
    ...stats,
  }))
})
</script>

<template>
  <div>
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
              <td class="td-body" style="font-family:monospace;font-size:12px">{{ entry.display_name || entry.rule_id || '\u2013' }}</td>
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
</template>
