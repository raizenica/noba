<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useApprovalsStore } from '../../stores/approvals'
import { useHealingStore } from '../../stores/healing'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'
import { APPROVAL_QUEUE_LIMIT } from '../../constants'

const approvalsStore = useApprovalsStore()
const healingStore = useHealingStore()
const authStore = useAuthStore()
const notifStore = useNotificationsStore()

const historyExpanded = ref(false)
const now = ref(Date.now())

let clockInterval = null

onMounted(async () => {
  await approvalsStore.fetchPending()
  if (!healingStore.ledger.length) await healingStore.fetchLedger({ limit: APPROVAL_QUEUE_LIMIT })
  clockInterval = setInterval(() => { now.value = Date.now() }, 1000)
})

onBeforeUnmount(() => {
  if (clockInterval) clearInterval(clockInterval)
})

// Healing ledger entries that have been decided (action_success not null) for history
const decidedHistory = computed(() =>
  healingStore.ledger
    .filter(e => e.action_success !== null && e.trust_level === 'approve')
    .slice(0, 20)
)

function riskClass(level) {
  if (!level) return 'bw'
  const l = level.toLowerCase()
  if (l === 'critical' || l === 'high') return 'bd'
  if (l === 'medium') return 'bw'
  return 'bs'
}

function escalationClass(step) {
  return (step || 0) > 0 ? 'bd' : 'bw'
}

function timeRemaining(expiresAt) {
  if (!expiresAt) return null
  const exp = typeof expiresAt === 'number' ? expiresAt * 1000 : new Date(expiresAt).getTime()
  const diff = Math.floor((exp - now.value) / 1000)
  if (diff <= 0) return 'Expired'
  if (diff < 60) return `${diff}s`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ${diff % 60}s`
  return `${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m`
}

function timerClass(expiresAt) {
  if (!expiresAt) return ''
  const exp = typeof expiresAt === 'number' ? expiresAt * 1000 : new Date(expiresAt).getTime()
  const diff = Math.floor((exp - now.value) / 1000)
  if (diff <= 0 || diff < 60) return 'timer-urgent'
  if (diff < 300) return 'timer-warn'
  return 'timer-ok'
}

function relTime(ts) {
  if (!ts) return '—'
  const sec = typeof ts === 'number' ? ts : Math.floor(new Date(ts).getTime() / 1000)
  const diff = Math.floor(Date.now() / 1000 - sec)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function historyBadge(entry) {
  const v = entry.verification_result ?? entry.action_success
  if (v === true || v === 'verified') return 'bs'
  if (v === false || v === 'failed') return 'bd'
  return 'bw'
}

function historyLabel(entry) {
  const v = entry.verification_result ?? entry.action_success
  if (v === true || v === 'verified') return 'Verified'
  if (v === false || v === 'failed') return 'Failed'
  return 'Unknown'
}

async function approve(item) {
  try {
    await approvalsStore.decide(item.id, 'approved')
    notifStore.addToast(`Approved: ${item.action_type || item.id}`, 'success')
  } catch (e) {
    notifStore.addToast('Approve failed: ' + (e?.message || 'unknown'), 'error')
  }
}

async function deny(item) {
  try {
    await approvalsStore.decide(item.id, 'denied')
    notifStore.addToast(`Denied: ${item.action_type || item.id}`, 'success')
  } catch (e) {
    notifStore.addToast('Deny failed: ' + (e?.message || 'unknown'), 'error')
  }
}

// Defer is frontend-only: adds a local deferred marker and removes from visible list
const deferred = ref(new Set())

function defer(item) {
  deferred.value.add(item.id)
  notifStore.addToast(`Deferred approval ${item.id} — will remain pending`, 'info')
}

const visiblePending = computed(() =>
  approvalsStore.pending.filter(p => !deferred.value.has(p.id))
)
</script>

<template>
  <div class="approval-queue">
    <!-- Header -->
    <div class="aq-header">
      <span class="aq-title">
        Pending Approvals
        <span v-if="approvalsStore.count > 0" class="badge bd aq-count">{{ approvalsStore.count }}</span>
      </span>
      <button class="btn btn-xs" @click="approvalsStore.fetchPending()">Refresh</button>
    </div>

    <!-- Empty state -->
    <div v-if="visiblePending.length === 0" class="empty-msg">No pending approvals</div>

    <!-- Approval cards -->
    <div v-else class="aq-list">
      <div
        v-for="item in visiblePending"
        :key="item.id"
        class="aq-card"
        :class="{ 'aq-card-escalated': (item.escalation_step || 0) > 0 }"
      >
        <!-- Card header row -->
        <div class="aq-card-head">
          <div class="aq-card-title">
            <span class="badge ba">{{ item.action_type || 'action' }}</span>
            <span class="aq-target">{{ item.target || item.target_host || item.target_service || '—' }}</span>
            <span
              v-if="(item.escalation_step || 0) > 0"
              :class="['badge', escalationClass(item.escalation_step)]"
              title="Escalated approval"
            >Escalated (step {{ item.escalation_step }})</span>
          </div>
          <span class="aq-time">{{ relTime(item.requested_at || item.created_at) }}</span>
        </div>

        <!-- Details grid -->
        <div class="aq-details">
          <div v-if="item.risk_level" class="row">
            <span class="row-label">Risk</span>
            <span :class="['badge', riskClass(item.risk_level)]">{{ item.risk_level }}</span>
          </div>
          <div v-if="item.condition || item.trigger_condition" class="row">
            <span class="row-label">Trigger</span>
            <span class="row-val">{{ item.condition || item.trigger_condition }}</span>
          </div>
          <div v-if="item.rule_id" class="row">
            <span class="row-label">Rule</span>
            <span class="row-val">{{ item.rule_id }}</span>
          </div>
          <div v-if="item.reason" class="row">
            <span class="row-label">Reason</span>
            <span class="row-val">{{ item.reason }}</span>
          </div>
          <div v-if="item.source" class="row">
            <span class="row-label">Source</span>
            <span class="row-val">{{ item.source }}</span>
          </div>
        </div>

        <!-- Timer -->
        <div v-if="item.expires_at" class="aq-timer" :class="timerClass(item.expires_at)">
          Expires in: {{ timeRemaining(item.expires_at) }}
        </div>

        <!-- Actions -->
        <div v-if="authStore.isOperator" class="aq-actions">
          <button class="btn btn-xs btn-success" @click="approve(item)">Approve</button>
          <button class="btn btn-xs btn-danger" @click="deny(item)">Deny</button>
          <button class="btn btn-xs" @click="defer(item)">Defer</button>
        </div>
      </div>
    </div>

    <!-- History section (collapsed) -->
    <div v-if="decidedHistory.length > 0" class="aq-history">
      <button class="btn btn-xs aq-history-toggle" aria-label="Toggle history" @click="historyExpanded = !historyExpanded">
        {{ historyExpanded ? 'Hide' : 'Show' }} Recent History ({{ decidedHistory.length }})
      </button>
      <div v-if="historyExpanded" class="aq-history-list">
        <div
          v-for="entry in decidedHistory"
          :key="entry.id"
          class="aq-history-row"
        >
          <span :class="['badge', historyBadge(entry)]">{{ historyLabel(entry) }}</span>
          <span class="badge ba">{{ entry.action_type }}</span>
          <span class="aq-history-target">{{ entry.target }}</span>
          <span class="aq-history-time">{{ relTime(entry.created_at) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.approval-queue { display: flex; flex-direction: column; gap: .75rem; }

.aq-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.aq-title {
  font-size: .8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: .4rem;
}
.aq-count { font-size: .65rem; }

.aq-list { display: flex; flex-direction: column; gap: .75rem; }

.aq-card {
  padding: .85rem;
  border: 1px solid var(--border);
  border-left: 3px solid var(--warning, #f0a500);
  border-radius: 6px;
  background: var(--surface-2);
  display: flex;
  flex-direction: column;
  gap: .5rem;
}
.aq-card-escalated { border-left-color: var(--danger); }

.aq-card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: .5rem;
}
.aq-card-title { display: flex; align-items: center; gap: .4rem; flex-wrap: wrap; }
.aq-target { font-weight: 600; font-size: .9rem; }
.aq-time { font-size: .72rem; color: var(--text-muted); flex-shrink: 0; }

.aq-details { display: flex; flex-direction: column; gap: .15rem; }
.aq-details .row { display: flex; gap: .75rem; align-items: baseline; font-size: .82rem; }
.row-label { color: var(--text-muted); min-width: 70px; flex-shrink: 0; }
.row-val { color: var(--text); word-break: break-word; }

.aq-timer {
  font-size: .78rem;
  font-family: var(--font-data);
  padding: .2rem .4rem;
  border-radius: 4px;
  width: fit-content;
}
.timer-urgent { color: var(--danger); background: color-mix(in srgb, var(--danger) 15%, transparent); }
.timer-warn { color: var(--warning); background: color-mix(in srgb, var(--warning) 15%, transparent); }
.timer-ok { color: var(--text-muted); }

.aq-actions { display: flex; gap: .4rem; }
.btn-success { background: var(--success); border-color: var(--success); color: #fff; }
.btn-success:hover { filter: brightness(1.1); }

.aq-history { margin-top: .25rem; }
.aq-history-toggle { font-size: .75rem; }
.aq-history-list {
  margin-top: .5rem;
  display: flex;
  flex-direction: column;
  gap: .3rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: .5rem;
  background: var(--surface);
}
.aq-history-row {
  display: flex;
  align-items: center;
  gap: .4rem;
  font-size: .8rem;
  flex-wrap: wrap;
}
.aq-history-target { color: var(--text); flex: 1; }
.aq-history-time { color: var(--text-muted); font-size: .72rem; flex-shrink: 0; }

.empty-msg { color: var(--text-muted); padding: 1.5rem 0; text-align: center; font-size: .9rem; }
</style>
