<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useHealingStore } from '../../stores/healing'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'
import { LEDGER_TIMELINE_LIMIT } from '../../constants'

const store = useHealingStore()
const authStore = useAuthStore()
const notifStore = useNotificationsStore()

const filterRule = ref('')
const filterTarget = ref('')
const filterResult = ref('')
const expanded = ref(null)

const uniqueRules = computed(() => {
  const rules = store.ledger.map(e => e.rule_id).filter(Boolean)
  return [...new Set(rules)].sort()
})

const uniqueTargets = computed(() => {
  const targets = store.ledger.map(e => e.target).filter(Boolean)
  return [...new Set(targets)].sort()
})

const filtered = computed(() => {
  return store.ledger.filter(entry => {
    if (filterRule.value && entry.rule_id !== filterRule.value) return false
    if (filterTarget.value && entry.target !== filterTarget.value) return false
    if (filterResult.value) {
      const label = resultLabel(entry).toLowerCase()
      if (label !== filterResult.value) return false
    }
    return true
  })
})

function toggle(id) {
  expanded.value = expanded.value === id ? null : id
}

function dotClass(entry) {
  const v = entry.verification_result || entry.action_success
  if (v === true || v === 'verified') return 'dot-ok'
  if (v === false || v === 'failed') return 'dot-fail'
  if (entry.action_type === 'notify') return 'dot-muted'
  return 'dot-warn'
}

function resultBadge(entry) {
  const label = resultLabel(entry)
  if (label === 'Verified') return 'bs'
  if (label === 'Failed') return 'bd'
  if (label === 'Notify') return 'ba'
  return 'bw'
}

function resultLabel(entry) {
  const v = entry.verification_result || entry.action_success
  if (v === true || v === 'verified') return 'Verified'
  if (v === false || v === 'failed') return 'Failed'
  if (entry.action_type === 'notify') return 'Notify'
  return 'Pending'
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const now = Date.now()
  const diff = now - d.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return d.toLocaleString()
}

function exportData() {
  const blob = new Blob([JSON.stringify(filtered.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `healing-ledger-${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function canRollback(entry) {
  return !!entry.snapshot_id || !!entry.rollback_available
}

async function doRollback(id) {
  try {
    await store.rollbackAction(id)
    notifStore.addToast('Rollback initiated successfully', 'success')
    await store.fetchLedger({ limit: LEDGER_TIMELINE_LIMIT })
  } catch (e) {
    notifStore.addToast('Rollback failed: ' + (e?.message || 'unknown error'), 'error')
  }
}
</script>

<template>
  <div class="ledger-timeline">
    <!-- Filter bar -->
    <div class="ledger-filters">
      <select v-model="filterRule" class="form-select">
        <option value="">All Rules</option>
        <option v-for="r in uniqueRules" :key="r" :value="r">{{ r }}</option>
      </select>
      <select v-model="filterTarget" class="form-select">
        <option value="">All Targets</option>
        <option v-for="t in uniqueTargets" :key="t" :value="t">{{ t }}</option>
      </select>
      <select v-model="filterResult" class="form-select">
        <option value="">All Results</option>
        <option value="verified">Verified</option>
        <option value="failed">Failed</option>
        <option value="pending">Pending</option>
      </select>
      <button class="btn btn-xs" @click="exportData">Export</button>
    </div>

    <!-- Timeline -->
    <div v-if="!filtered.length" class="empty-msg">No healing events match filters.</div>
    <div
      v-for="entry in filtered"
      :key="entry.id"
      class="timeline-entry"
      @click="toggle(entry.id)"
    >
      <div class="timeline-dot" :class="dotClass(entry)" />
      <div class="timeline-content">
        <div class="timeline-header">
          <span class="timeline-time">{{ formatTime(entry.created_at) }}</span>
          <span :class="['badge', resultBadge(entry)]">{{ resultLabel(entry) }}</span>
          <span class="badge ba">{{ entry.action_type }}</span>
          <span class="timeline-target">{{ entry.target }}</span>
          <span v-if="entry.duration_s" class="text-muted">{{ entry.duration_s }}s</span>
        </div>
        <!-- Expandable detail -->
        <div v-if="expanded === entry.id" class="timeline-detail">
          <div class="row"><span class="row-label">Rule</span><span class="row-val">{{ entry.rule_id }}</span></div>
          <div class="row"><span class="row-label">Condition</span><span class="row-val">{{ entry.condition }}</span></div>
          <div class="row"><span class="row-label">Trust</span><span class="row-val badge ba">{{ entry.trust_level }}</span></div>
          <div class="row"><span class="row-label">Escalation</span><span class="row-val">Step {{ (entry.escalation_step || 0) + 1 }}</span></div>
          <div class="row"><span class="row-label">Source</span><span class="row-val">{{ entry.source }}</span></div>
          <div v-if="entry.risk_level" class="row"><span class="row-label">Risk</span><span class="row-val">{{ entry.risk_level }}</span></div>
          <div v-if="entry.rollback_status" class="row"><span class="row-label">Rollback</span><span class="row-val">{{ entry.rollback_status }}</span></div>
          <div v-if="entry.dependency_root" class="row"><span class="row-label">Root Cause</span><span class="row-val">{{ entry.dependency_root }}</span></div>
          <div v-if="entry.verification_detail" class="row"><span class="row-label">Detail</span><span class="row-val">{{ entry.verification_detail }}</span></div>
          <div v-if="authStore.isAdmin && canRollback(entry)" class="timeline-actions">
            <button class="btn btn-xs btn-danger" @click.stop="doRollback(entry.id)">Rollback</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ledger-filters { display: flex; gap: .5rem; margin-bottom: 1rem; flex-wrap: wrap; }
.ledger-filters .form-select { max-width: 180px; }
.timeline-entry { display: flex; gap: .75rem; padding: .5rem 0; border-bottom: 1px solid var(--border); cursor: pointer; }
.timeline-entry:hover { background: var(--surface-2); }
.timeline-dot { width: 12px; height: 12px; border-radius: 50%; margin-top: 6px; flex-shrink: 0; }
.dot-ok { background: var(--success); }
.dot-fail { background: var(--danger); }
.dot-warn { background: var(--warning); }
.dot-muted { background: var(--text-muted); }
.timeline-content { flex: 1; min-width: 0; }
.timeline-header { display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; }
.timeline-time { font-family: var(--font-data); font-size: .8rem; color: var(--text-muted); min-width: 80px; }
.timeline-target { font-weight: 600; }
.timeline-detail { margin-top: .5rem; padding: .75rem; background: var(--surface-2); border-radius: 6px; }
.timeline-detail .row { display: flex; gap: .75rem; padding: .2rem 0; font-size: .85rem; }
.row-label { color: var(--text-muted); min-width: 90px; flex-shrink: 0; }
.row-val { color: var(--text); word-break: break-word; }
.timeline-actions { margin-top: .5rem; }
.empty-msg { color: var(--text-muted); padding: 1.5rem 0; text-align: center; font-size: .9rem; }
.text-muted { color: var(--text-muted); font-size: .8rem; }
</style>
