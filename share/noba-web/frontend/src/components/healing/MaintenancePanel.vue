<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, onMounted } from 'vue'
import { useHealingStore } from '../../stores/healing'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'

const store = useHealingStore()
const authStore = useAuthStore()
const notify = useNotificationsStore()

const newTarget = ref('')
const newDuration = ref('1h')
const newReason = ref('')
const newAction = ref('suppress')
const creating = ref(false)

const active = computed(() =>
  store.maintenance.filter(w => w.active && !w.cron_expr && !isExpired(w))
)

const scheduled = computed(() =>
  store.maintenance.filter(w => w.cron_expr)
)

function isExpired(w) {
  if (!w.expires_at) return false
  return new Date(w.expires_at) < new Date()
}

function formatCountdown(expiresAt) {
  const diff = new Date(expiresAt) - Date.now()
  if (diff <= 0) return 'expired'
  const totalSecs = Math.floor(diff / 1000)
  const h = Math.floor(totalSecs / 3600)
  const m = Math.floor((totalSecs % 3600) / 60)
  const s = totalSecs % 60
  if (h > 0) return `${h}h ${m}m remaining`
  if (m > 0) return `${m}m ${s}s remaining`
  return `${s}s remaining`
}

function formatTime(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString()
}

async function create() {
  if (!newTarget.value || !newReason.value) return
  creating.value = true
  try {
    const result = await store.createMaintenanceWindow({
      target: newTarget.value,
      duration: newDuration.value,
      reason: newReason.value,
      action: newAction.value,
    })
    if (result) {
      notify.addToast('Maintenance window created', 'success')
      newTarget.value = ''
      newReason.value = ''
      newDuration.value = '1h'
      newAction.value = 'suppress'
    } else {
      notify.addToast('Failed to create maintenance window', 'error')
    }
  } catch {
    notify.addToast('Error creating maintenance window', 'error')
  } finally {
    creating.value = false
  }
}

async function endWindow(id) {
  try {
    const result = await store.endMaintenanceWindow(id)
    if (result) {
      notify.addToast('Maintenance window ended', 'success')
    } else {
      notify.addToast('Failed to end maintenance window', 'error')
    }
  } catch {
    notify.addToast('Error ending maintenance window', 'error')
  }
}

onMounted(async () => {
  if (!store.maintenance.length) {
    await store.fetchMaintenance()
  }
})
</script>

<template>
  <div class="maintenance-panel">
    <!-- Quick-create form -->
    <div v-if="authStore.isOperator" class="maint-create">
      <h4>Enter Maintenance</h4>
      <div class="maint-form">
        <div>
          <label class="field-label">Target</label>
          <input v-model="newTarget" class="field-input" placeholder="all or specific target" />
        </div>
        <div>
          <label class="field-label">Duration</label>
          <select v-model="newDuration" class="form-select">
            <option value="15m">15 minutes</option>
            <option value="30m">30 minutes</option>
            <option value="1h">1 hour</option>
            <option value="2h">2 hours</option>
            <option value="4h">4 hours</option>
            <option value="8h">8 hours</option>
            <option value="24h">24 hours</option>
          </select>
        </div>
        <div>
          <label class="field-label">Reason</label>
          <input v-model="newReason" class="field-input" placeholder="e.g., deploying update" />
        </div>
        <div>
          <label class="field-label">Action</label>
          <select v-model="newAction" class="form-select">
            <option value="suppress">Suppress healing</option>
            <option value="suppress_all">Suppress all (global)</option>
            <option value="queue">Queue events</option>
            <option value="notify_only">Notify only</option>
          </select>
        </div>
        <button
          class="btn btn-primary"
          @click="create"
          :disabled="!newTarget || !newReason || creating"
        >
          {{ creating ? 'Creating...' : 'Create Window' }}
        </button>
      </div>
    </div>

    <!-- Active windows -->
    <h4>
      Active Windows
      <span v-if="active.length" class="badge ba">{{ active.length }}</span>
    </h4>
    <div v-if="!active.length" class="empty-msg">No active maintenance windows.</div>
    <div v-for="w in active" :key="w.id" class="maint-window">
      <div class="maint-header">
        <span class="badge bw">{{ w.target }}</span>
        <span class="badge ba">{{ w.action }}</span>
        <span class="text-muted">{{ w.reason }}</span>
        <span v-if="w.expires_at" class="maint-countdown">
          {{ formatCountdown(w.expires_at) }}
        </span>
      </div>
      <div class="maint-meta">
        Created by {{ w.created_by || 'system' }} · {{ formatTime(w.created_at) }}
      </div>
      <button v-if="authStore.isOperator" class="btn btn-xs btn-danger" @click="endWindow(w.id)">
        End Early
      </button>
    </div>

    <!-- Scheduled windows -->
    <h4>Scheduled</h4>
    <div v-if="!scheduled.length" class="empty-msg">No scheduled maintenance windows.</div>
    <div v-for="w in scheduled" :key="'s' + w.id" class="maint-window">
      <span class="badge ba">{{ w.target }}</span>
      <span class="text-muted">{{ w.cron_expr }}</span>
      <span class="text-muted">{{ w.reason }}</span>
    </div>
  </div>
</template>

<style scoped>
.maintenance-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.maintenance-panel h4 {
  margin: 0 0 .5rem;
  font-size: .9rem;
  color: var(--text-muted);
  text-transform: uppercase;
  display: flex;
  align-items: center;
  gap: .5rem;
}

.maint-create {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem;
}

.maint-create h4 {
  margin-bottom: .75rem;
}

.maint-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: .75rem;
}

.maint-form > div {
  display: flex;
  flex-direction: column;
  gap: .25rem;
}

.maint-form .btn {
  grid-column: 1 / -1;
  justify-self: start;
}

.maint-window {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: .75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: .4rem;
}

.maint-header {
  display: flex;
  align-items: center;
  gap: .5rem;
  flex-wrap: wrap;
}

.maint-meta {
  font-size: .8rem;
  color: var(--text-muted);
}

.maint-countdown {
  font-size: .8rem;
  color: var(--warning);
  margin-left: auto;
}
</style>
