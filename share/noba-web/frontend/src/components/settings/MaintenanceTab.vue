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
const loading = ref(false)

const scheduled = computed(() =>
  store.maintenance.filter(w => w.cron_expr)
)

const active = computed(() =>
  store.maintenance.filter(w => w.active && !w.cron_expr && !isExpired(w))
)

const history = computed(() =>
  store.maintenance.filter(w => !w.active || isExpired(w))
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

async function refresh() {
  loading.value = true
  try {
    await store.fetchMaintenance()
  } finally {
    loading.value = false
  }
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
  await refresh()
})
</script>

<template>
  <div>
    <!-- Scheduled (cron-based) windows from config -->
    <div class="s-section">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.75rem">
        <span class="s-label" style="margin:0">Scheduled Windows</span>
        <button class="btn btn-xs" @click="refresh" :disabled="loading">
          <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
        </button>
      </div>
      <p style="font-size:.78rem;color:var(--text-muted);margin-bottom:.75rem">
        Recurring maintenance windows defined via cron expressions in the server config.
      </p>
      <div v-if="!scheduled.length" style="text-align:center;color:var(--text-muted);font-size:.8rem;padding:1.25rem 0">
        No scheduled (cron) maintenance windows configured.
      </div>
      <div
        v-for="w in scheduled"
        :key="'sched-' + w.id"
        style="background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:.75rem 1rem;margin-bottom:.5rem"
      >
        <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap">
          <span class="badge bw">{{ w.target }}</span>
          <span class="badge ba">{{ w.action }}</span>
          <code style="font-size:.72rem;color:var(--accent)">{{ w.cron_expr }}</code>
          <span style="font-size:.8rem;color:var(--text-muted)">{{ w.reason }}</span>
        </div>
      </div>
    </div>

    <!-- Quick-create ad-hoc window -->
    <div v-if="authStore.isOperator" class="s-section">
      <span class="s-label">Create Ad-Hoc Window</span>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:.75rem">
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
        <div style="grid-column:1/-1">
          <button
            class="btn btn-primary"
            @click="create"
            :disabled="!newTarget || !newReason || creating"
          >
            <i class="fas" :class="creating ? 'fa-spinner fa-spin' : 'fa-plus'"></i>
            {{ creating ? 'Creating...' : 'Create Window' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Active windows -->
    <div class="s-section">
      <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.75rem">
        <span class="s-label" style="margin:0">Active Windows</span>
        <span v-if="active.length" class="badge ba" style="font-size:.65rem">{{ active.length }}</span>
      </div>
      <div v-if="!active.length" style="text-align:center;color:var(--text-muted);font-size:.8rem;padding:1.25rem 0">
        No active maintenance windows.
      </div>
      <div
        v-for="w in active"
        :key="'active-' + w.id"
        style="background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:.75rem 1rem;margin-bottom:.5rem;display:flex;flex-direction:column;gap:.35rem"
      >
        <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap">
          <span class="badge bw">{{ w.target }}</span>
          <span class="badge ba">{{ w.action }}</span>
          <span style="font-size:.8rem;color:var(--text-muted)">{{ w.reason }}</span>
          <span v-if="w.expires_at" style="font-size:.8rem;color:var(--warning);margin-left:auto">
            {{ formatCountdown(w.expires_at) }}
          </span>
        </div>
        <div style="font-size:.78rem;color:var(--text-muted)">
          Created by {{ w.created_by || 'system' }} &middot; {{ formatTime(w.created_at) }}
        </div>
        <div>
          <button
            v-if="authStore.isOperator"
            class="btn btn-xs btn-danger"
            style="width:auto"
            @click="endWindow(w.id)"
          >
            <i class="fas fa-stop"></i> End Early
          </button>
        </div>
      </div>
    </div>

    <!-- History table -->
    <div class="s-section">
      <span class="s-label">Past Windows</span>
      <div v-if="!history.length" style="text-align:center;color:var(--text-muted);font-size:.8rem;padding:1.25rem 0">
        No maintenance history recorded yet.
      </div>
      <div v-else style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:.78rem">
          <thead>
            <tr style="color:var(--text-muted);text-align:left;border-bottom:1px solid var(--border)">
              <th style="padding:.4rem .6rem">Target</th>
              <th style="padding:.4rem .6rem">Action</th>
              <th style="padding:.4rem .6rem">Reason</th>
              <th style="padding:.4rem .6rem">Created By</th>
              <th style="padding:.4rem .6rem">Started</th>
              <th style="padding:.4rem .6rem">Ended</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="w in history"
              :key="'hist-' + w.id"
              style="border-bottom:1px solid var(--border)"
            >
              <td style="padding:.4rem .6rem">
                <span class="badge bw" style="font-size:.65rem">{{ w.target }}</span>
              </td>
              <td style="padding:.4rem .6rem;color:var(--text-muted)">{{ w.action }}</td>
              <td style="padding:.4rem .6rem;color:var(--text-muted)">{{ w.reason }}</td>
              <td style="padding:.4rem .6rem;color:var(--text-muted)">{{ w.created_by || 'system' }}</td>
              <td style="padding:.4rem .6rem;color:var(--text-muted);font-family:var(--font-data);font-size:.72rem">
                {{ formatTime(w.created_at) }}
              </td>
              <td style="padding:.4rem .6rem;color:var(--text-muted);font-family:var(--font-data);font-size:.72rem">
                {{ w.expires_at ? formatTime(w.expires_at) : '—' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
