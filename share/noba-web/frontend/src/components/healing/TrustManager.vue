<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { onMounted } from 'vue'
import { useHealingStore } from '../../stores/healing'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'
import { useApi } from '../../composables/useApi'

const store = useHealingStore()
const authStore = useAuthStore()
const notifStore = useNotificationsStore()

const LEVELS = ['notify', 'approve', 'execute']

onMounted(async () => {
  if (!store.trust.length) await store.fetchTrust()
})

function levelIndex(level) {
  return LEVELS.indexOf(level)
}

function currentLevelBadge(level) {
  if (level === 'execute') return 'bs'
  if (level === 'approve') return 'ba'
  return 'bw'
}

function ceilingBadge(level) {
  if (level === 'execute') return 'bs'
  if (level === 'approve') return 'ba'
  return 'bd'
}

function isCircuitBroken(state) {
  return state.current_level === 'notify' && (state.demotion_count || 0) > 0
}

function canPromote(state) {
  const curIdx = levelIndex(state.current_level)
  const ceilIdx = levelIndex(state.ceiling)
  return curIdx < ceilIdx
}

function canDemote(state) {
  return levelIndex(state.current_level) > 0
}

function formatTs(ts) {
  if (!ts) return '—'
  const d = new Date(typeof ts === 'number' ? ts * 1000 : ts)
  const now = Date.now()
  const diff = now - d.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return d.toLocaleDateString()
}

async function promote(state) {
  try {
    await store.promoteTrust(state.rule_id)
    notifStore.addToast(`Promoted trust for ${state.rule_id}`, 'success')
  } catch (e) {
    notifStore.addToast('Promote failed: ' + (e?.message || 'unknown'), 'error')
  }
}

const { post } = useApi()

async function demote(state) {
  const curIdx = levelIndex(state.current_level)
  if (curIdx <= 0) return
  const targetLevel = LEVELS[curIdx - 1]
  try {
    await post(`/api/healing/trust/${encodeURIComponent(state.rule_id)}/demote`)
    await store.fetchTrust()
    notifStore.addToast(`Trust for ${state.rule_id} demoted to ${targetLevel}`, 'success')
  } catch (e) {
    notifStore.addToast('Demote failed: ' + (e?.message || 'unknown'), 'error')
  }
}
</script>

<template>
  <div class="trust-manager">
    <!-- Empty state -->
    <div v-if="!store.trust.length" class="empty-msg">No trust states configured</div>

    <!-- Card grid -->
    <div v-else class="trust-grid">
      <div
        v-for="state in store.trust"
        :key="state.rule_id"
        class="trust-card"
        :class="{ 'trust-card-broken': isCircuitBroken(state) }"
      >
        <!-- Card header -->
        <div class="trust-card-header">
          <span class="trust-rule-id" :title="state.rule_id">{{ state.rule_id }}</span>
          <span v-if="isCircuitBroken(state)" class="badge bd trust-circuit-badge">Circuit Open</span>
        </div>

        <!-- Trust progression bar -->
        <div class="trust-bar">
          <span
            :class="['trust-step', { active: state.current_level === 'notify', past: levelIndex(state.current_level) > 0, ceiling: state.ceiling === 'notify' && state.current_level !== 'notify' }]"
          >notify</span>
          <span class="trust-arrow">→</span>
          <span
            :class="['trust-step', { active: state.current_level === 'approve', past: levelIndex(state.current_level) > 1, ceiling: state.ceiling === 'approve' && state.current_level !== 'approve' }]"
          >approve</span>
          <span class="trust-arrow">→</span>
          <span
            :class="['trust-step', { active: state.current_level === 'execute', ceiling: state.ceiling === 'execute' && state.current_level !== 'execute' }]"
          >execute</span>
        </div>

        <!-- Badges row -->
        <div class="trust-badges">
          <div class="trust-badge-group">
            <span class="trust-badge-label">Level</span>
            <span :class="['badge', currentLevelBadge(state.current_level)]">{{ state.current_level }}</span>
          </div>
          <div class="trust-badge-group">
            <span class="trust-badge-label">Ceiling</span>
            <span :class="['badge', ceilingBadge(state.ceiling)]">{{ state.ceiling }}</span>
          </div>
        </div>

        <!-- Stats -->
        <div class="trust-stats">
          <div class="row">
            <span class="row-label">Promotions</span>
            <span class="row-val">{{ state.promotion_count || 0 }}</span>
          </div>
          <div class="row">
            <span class="row-label">Demotions</span>
            <span class="row-val" :class="{ 'val-danger': (state.demotion_count || 0) > 0 }">
              {{ state.demotion_count || 0 }}
            </span>
          </div>
          <div v-if="state.promoted_at" class="row">
            <span class="row-label">Promoted</span>
            <span class="row-val">{{ formatTs(state.promoted_at) }}</span>
          </div>
          <div v-if="state.demoted_at" class="row">
            <span class="row-label">Demoted</span>
            <span class="row-val">{{ formatTs(state.demoted_at) }}</span>
          </div>
          <div v-if="state.last_evaluated" class="row">
            <span class="row-label">Evaluated</span>
            <span class="row-val">{{ formatTs(state.last_evaluated) }}</span>
          </div>
        </div>

        <!-- Circuit breaker warning -->
        <div v-if="isCircuitBroken(state)" class="trust-circuit-warn">
          Circuit breaker open — rule was demoted {{ state.demotion_count }} time(s).
          Manual promotion required to restore higher trust.
        </div>

        <!-- Admin actions -->
        <div v-if="authStore.isAdmin" class="trust-actions">
          <button
            class="btn btn-xs btn-success"
            :disabled="!canPromote(state)"
            @click="promote(state)"
          >Promote</button>
          <button
            class="btn btn-xs btn-danger"
            :disabled="!canDemote(state)"
            @click="demote(state)"
          >Demote</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.trust-manager { display: flex; flex-direction: column; }

.trust-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem;
}

.trust-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: .65rem;
}
.trust-card-broken { border-color: var(--danger); }

.trust-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .5rem;
}
.trust-rule-id {
  font-weight: 600;
  font-size: .88rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  color: var(--text);
}
.trust-circuit-badge { font-size: .65rem; flex-shrink: 0; }

/* Trust progression bar */
.trust-bar {
  display: flex;
  align-items: center;
  gap: .3rem;
  padding: .4rem .5rem;
  background: var(--surface-2);
  border-radius: 5px;
  flex-wrap: nowrap;
  overflow: hidden;
}
.trust-step {
  font-size: .72rem;
  padding: .2rem .45rem;
  border-radius: 4px;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid transparent;
  white-space: nowrap;
  transition: background .15s, color .15s;
}
.trust-step.past {
  color: var(--text-muted);
  border-color: var(--border);
}
.trust-step.active {
  background: var(--accent, #2196f3);
  color: #fff;
  border-color: var(--accent, #2196f3);
  font-weight: 700;
}
.trust-step.ceiling {
  border-color: var(--warning, #f0a500);
  color: var(--warning, #f0a500);
}
.trust-arrow { font-size: .7rem; color: var(--text-muted); flex-shrink: 0; }

.trust-badges {
  display: flex;
  gap: .75rem;
}
.trust-badge-group {
  display: flex;
  align-items: center;
  gap: .3rem;
}
.trust-badge-label {
  font-size: .72rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: .04em;
}

.trust-stats { display: flex; flex-direction: column; gap: .15rem; }
.trust-stats .row { display: flex; gap: .75rem; align-items: baseline; font-size: .82rem; }
.row-label { color: var(--text-muted); min-width: 80px; flex-shrink: 0; }
.row-val { color: var(--text); }
.val-danger { color: var(--danger); font-weight: 600; }

.trust-circuit-warn {
  font-size: .78rem;
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
  border-radius: 4px;
  padding: .4rem .6rem;
}

.trust-actions { display: flex; gap: .4rem; margin-top: .1rem; }
.btn-success { background: var(--success); border-color: var(--success); color: #fff; }
.btn-success:hover:not(:disabled) { filter: brightness(1.1); }
.btn-success:disabled, .btn-danger:disabled { opacity: .4; cursor: not-allowed; }

.empty-msg { color: var(--text-muted); padding: 1.5rem 0; text-align: center; font-size: .9rem; }
</style>
