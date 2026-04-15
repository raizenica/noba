<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, onMounted } from 'vue'
import { useHealingStore } from '../../stores/healing'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'
import { useApi } from '../../composables/useApi'

const store = useHealingStore()
const authStore = useAuthStore()
const notifStore = useNotificationsStore()
const { post } = useApi()

const expandedEvidence = ref(new Set())

onMounted(async () => {
  if (!store.suggestions.length) await store.fetchSuggestions()
})

const suggestionCount = computed(() => store.suggestions.length)

function categoryBadge(category) {
  const map = {
    dependency: 'ba',
    reliability: 'bw',
    performance: 'bs',
    security: 'bd',
    config: 'bw',
  }
  return map[(category || '').toLowerCase()] || 'bw'
}

function severityBadge(severity) {
  const s = (severity || '').toLowerCase()
  if (s === 'critical' || s === 'high') return 'bd'
  if (s === 'medium') return 'bw'
  return 'bs'
}

function isDependencyCandidate(suggestion) {
  return (suggestion.category || '').toLowerCase() === 'dependency'
    || (suggestion.suggested_action || '').toLowerCase().includes('depend')
}

function toggleEvidence(id) {
  if (expandedEvidence.value.has(id)) {
    expandedEvidence.value.delete(id)
  } else {
    expandedEvidence.value.add(id)
  }
}

function hasEvidence(suggestion) {
  if (!suggestion.evidence) return false
  if (typeof suggestion.evidence === 'string') {
    try { return Object.keys(JSON.parse(suggestion.evidence)).length > 0 } catch { return false }
  }
  return Object.keys(suggestion.evidence).length > 0
}

function parsedEvidence(suggestion) {
  if (!suggestion.evidence) return {}
  if (typeof suggestion.evidence === 'string') {
    try { return JSON.parse(suggestion.evidence) } catch { return { raw: suggestion.evidence } }
  }
  return suggestion.evidence
}

function formatEvidence(evidence) {
  try { return JSON.stringify(evidence, null, 2) } catch { return String(evidence) }
}

function relTime(ts) {
  if (!ts) return ''
  const sec = typeof ts === 'number' ? ts : Math.floor(new Date(ts).getTime() / 1000)
  const diff = Math.floor(Date.now() / 1000 - sec)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

async function accept(suggestion) {
  // Accept = mark dependency candidate as confirmed via dismiss with accepted note
  try {
    await post(`/api/healing/suggestions/${suggestion.id}/dismiss`, { reason: 'accepted' })
    await store.fetchSuggestions()
    notifStore.addToast(`Accepted: ${suggestion.rule_id || suggestion.category}`, 'success')
  } catch (e) {
    notifStore.addToast('Accept failed: ' + (e?.message || 'unknown'), 'error')
  }
}

async function dismiss(suggestion) {
  try {
    await store.dismissSuggestion(suggestion.id)
    notifStore.addToast('Suggestion dismissed', 'success')
  } catch (e) {
    notifStore.addToast('Dismiss failed: ' + (e?.message || 'unknown'), 'error')
  }
}

async function snooze(suggestion) {
  // Snooze = dismiss with a 30-day re-evaluation note
  try {
    await post(`/api/healing/suggestions/${suggestion.id}/dismiss`, {
      reason: 'snoozed_30d',
      note: 'Re-evaluate in 30 days',
    })
    await store.fetchSuggestions()
    notifStore.addToast('Suggestion snoozed for 30 days', 'success')
  } catch (e) {
    // Fallback: use standard dismiss if custom body not accepted
    try {
      await store.dismissSuggestion(suggestion.id)
      notifStore.addToast('Suggestion snoozed (dismissed)', 'success')
    } catch {
      notifStore.addToast('Snooze failed: ' + (e?.message || 'unknown'), 'error')
    }
  }
}
</script>

<template>
  <div class="suggestions-panel">
    <!-- Header with badge counter -->
    <div class="sp-header">
      <span class="sp-title">
        Suggestions
        <span v-if="suggestionCount > 0" :class="['badge', suggestionCount > 5 ? 'bd' : 'ba', 'sp-count']">
          {{ suggestionCount }}
        </span>
      </span>
      <button class="btn btn-xs" @click="store.fetchSuggestions()">Refresh</button>
    </div>

    <!-- Empty state -->
    <div v-if="!store.suggestions.length" class="empty-msg">
      No suggestions — system is healthy
    </div>

    <!-- Suggestion cards -->
    <div v-else class="sp-list">
      <div
        v-for="s in store.suggestions"
        :key="s.id"
        class="sp-card"
      >
        <!-- Card header -->
        <div class="sp-card-head">
          <div class="sp-card-badges">
            <span :class="['badge', categoryBadge(s.category)]">{{ s.category || 'general' }}</span>
            <span :class="['badge', severityBadge(s.severity)]">{{ s.severity || 'info' }}</span>
            <span v-if="s.rule_id" class="sp-rule-id">{{ s.rule_id }}</span>
          </div>
          <span v-if="s.created_at" class="sp-time">{{ relTime(s.created_at) }}</span>
        </div>

        <!-- Message -->
        <p class="sp-message">{{ s.message }}</p>

        <!-- Suggested action -->
        <div v-if="s.suggested_action" class="sp-action-hint">
          Suggested: {{ s.suggested_action }}
        </div>

        <!-- Evidence (collapsed / expandable) -->
        <div v-if="hasEvidence(s)" class="sp-evidence">
          <button
            class="btn btn-xs sp-evidence-toggle"
            @click="toggleEvidence(s.id)"
          >
            {{ expandedEvidence.has(s.id) ? 'Hide Evidence' : 'Show Evidence' }}
          </button>
          <pre v-if="expandedEvidence.has(s.id)" class="sp-evidence-pre">{{ formatEvidence(parsedEvidence(s)) }}</pre>
        </div>

        <!-- Actions -->
        <div v-if="authStore.isOperator" class="sp-actions">
          <button
            v-if="isDependencyCandidate(s)"
            class="btn btn-xs btn-success"
            @click="accept(s)"
          >Accept</button>
          <button class="btn btn-xs" @click="dismiss(s)">Dismiss</button>
          <button class="btn btn-xs" @click="snooze(s)" title="Dismiss with 30-day re-evaluation">
            Snooze 30d
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.suggestions-panel { display: flex; flex-direction: column; gap: .75rem; }

.sp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sp-title {
  font-size: .8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: .4rem;
}
.sp-count { font-size: .65rem; }

.sp-list { display: flex; flex-direction: column; gap: .75rem; }

.sp-card {
  padding: .85rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-2);
  display: flex;
  flex-direction: column;
  gap: .5rem;
}

.sp-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .5rem;
  flex-wrap: wrap;
}
.sp-card-badges { display: flex; align-items: center; gap: .35rem; flex-wrap: wrap; }
.sp-rule-id {
  font-family: var(--font-data);
  font-size: .75rem;
  color: var(--text-muted);
  padding: .1rem .3rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
}
.sp-time { font-size: .72rem; color: var(--text-muted); flex-shrink: 0; }

.sp-message {
  margin: 0;
  font-size: .85rem;
  color: var(--text);
  line-height: 1.5;
}

.sp-action-hint {
  font-size: .78rem;
  color: var(--text-muted);
  font-style: italic;
  padding: .2rem .4rem;
  border-left: 2px solid var(--border);
}

.sp-evidence { display: flex; flex-direction: column; gap: .3rem; }
.sp-evidence-toggle { font-size: .75rem; align-self: flex-start; }
.sp-evidence-pre {
  font-family: var(--font-data);
  font-size: .75rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: .6rem;
  overflow-x: auto;
  margin: 0;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
}

.sp-actions { display: flex; gap: .4rem; flex-wrap: wrap; }
.btn-success { background: var(--success); border-color: var(--success); color: #fff; }
.btn-success:hover { filter: brightness(1.1); }

.empty-msg { color: var(--text-muted); padding: 1.5rem 0; text-align: center; font-size: .9rem; }
</style>
