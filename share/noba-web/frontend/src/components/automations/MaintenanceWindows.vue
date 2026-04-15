<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useApi }                from '../../composables/useApi'
import { useAuthStore }          from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'
import AppModal                  from '../ui/AppModal.vue'

import { useModalsStore } from '../../stores/modals'

const { get, post, put, del } = useApi()
const authStore = useAuthStore()
const notify    = useNotificationsStore()
const modals    = useModalsStore()

// ── Data ───────────────────────────────────────────────────────────────────
const windows         = ref([])
const activeWindowIds = ref(new Set())
const loading         = ref(false)

async function fetchWindows() {
  loading.value = true
  try {
    const data = await get('/api/maintenance-windows')
    windows.value = Array.isArray(data) ? data : []
  } catch (e) {
    notify.addToast('Failed to load maintenance windows: ' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

async function fetchActive() {
  try {
    const data = await get('/api/maintenance-windows/active')
    const ids = Array.isArray(data) ? data.map(w => w.id) : []
    activeWindowIds.value = new Set(ids)
  } catch { /* silent */ }
}

function isActive(w) {
  return activeWindowIds.value.has(w.id)
}

// ── Toggle enabled ──────────────────────────────────────────────────────────
async function toggleEnabled(w) {
  if (!authStore.isAdmin) return
  try {
    await put(`/api/maintenance-windows/${w.id}`, { ...w, enabled: !w.enabled })
    w.enabled = !w.enabled
  } catch (e) {
    notify.addToast('Update failed: ' + e.message, 'error')
  }
}

// ── Form modal ─────────────────────────────────────────────────────────────
const showModal  = ref(false)
const formMode   = ref('create')
const formId     = ref(null)

const formName            = ref('')
const formType            = ref('recurring')
const formSchedule        = ref('')
const formDuration        = ref(60)
const formStart           = ref('')
const formEnd             = ref('')
const formSuppressAlerts  = ref(true)
const formOverrideAutonomy = ref('none')
const formAutoClose       = ref(false)

const formTitle = computed(() => formMode.value === 'create' ? 'New Maintenance Window' : 'Edit Maintenance Window')

function openCreate() {
  formMode.value            = 'create'
  formId.value              = null
  formName.value            = ''
  formType.value            = 'recurring'
  formSchedule.value        = ''
  formDuration.value        = 60
  formStart.value           = ''
  formEnd.value             = ''
  formSuppressAlerts.value  = true
  formOverrideAutonomy.value = 'none'
  formAutoClose.value       = false
  showModal.value           = true
}

function openEdit(w) {
  formMode.value             = 'edit'
  formId.value               = w.id
  formName.value             = w.name || ''
  formType.value             = w.type || 'recurring'
  formSchedule.value         = w.schedule || ''
  formDuration.value         = w.duration_minutes ?? 60
  // Convert unix timestamps to local datetime-local string
  formStart.value            = w.start_ts  ? tsToDatetimeLocal(w.start_ts)  : ''
  formEnd.value              = w.end_ts    ? tsToDatetimeLocal(w.end_ts)    : ''
  formSuppressAlerts.value   = w.suppress_alerts  !== false
  formOverrideAutonomy.value = w.override_autonomy || 'none'
  formAutoClose.value        = !!w.auto_close_alerts
  showModal.value            = true
}

function tsToDatetimeLocal(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  // Pad to YYYY-MM-DDTHH:MM format
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function datetimeLocalToTs(str) {
  if (!str) return null
  return Math.floor(new Date(str).getTime() / 1000)
}

async function saveWindow() {
  if (!formName.value.trim()) {
    notify.addToast('Name is required', 'error')
    return
  }
  if (formType.value === 'recurring' && !formSchedule.value.trim()) {
    notify.addToast('Schedule (cron) is required for recurring windows', 'error')
    return
  }
  if (formType.value === 'one_off' && (!formStart.value || !formEnd.value)) {
    notify.addToast('Start and end datetime are required for one-off windows', 'error')
    return
  }

  const payload = {
    name:              formName.value.trim(),
    type:              formType.value,
    schedule:          formType.value === 'recurring' ? formSchedule.value.trim() : null,
    duration_minutes:  formType.value === 'recurring' ? Number(formDuration.value) : null,
    start_ts:          formType.value === 'one_off' ? datetimeLocalToTs(formStart.value) : null,
    end_ts:            formType.value === 'one_off' ? datetimeLocalToTs(formEnd.value)   : null,
    suppress_alerts:   formSuppressAlerts.value,
    override_autonomy: formOverrideAutonomy.value,
    auto_close_alerts: formAutoClose.value,
    enabled:           true,
  }

  try {
    if (formMode.value === 'create') {
      await post('/api/maintenance-windows', payload)
      notify.addToast('Maintenance window created', 'success')
    } else {
      await put(`/api/maintenance-windows/${formId.value}`, payload)
      notify.addToast('Maintenance window updated', 'success')
    }
    showModal.value = false
    await fetchWindows()
    await fetchActive()
  } catch (e) {
    notify.addToast('Save failed: ' + e.message, 'error')
  }
}

// ── Delete ──────────────────────────────────────────────────────────────────
async function deleteWindow(w) {
  const ok = await modals.confirm(`Delete maintenance window "${w.name}"?`)
  if (!ok) return
  try {
    await del(`/api/maintenance-windows/${w.id}`)
    notify.addToast('Maintenance window deleted', 'success')
    await fetchWindows()
    await fetchActive()
  } catch (e) {
    notify.addToast('Delete failed: ' + e.message, 'error')
  }
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function scheduleLabel(w) {
  if (w.type === 'recurring') return w.schedule || '—'
  const fmt = ts => ts ? new Date(ts * 1000).toLocaleString() : '—'
  return `${fmt(w.start_ts)} → ${fmt(w.end_ts)}`
}

function autonomyLabel(val) {
  switch (val) {
    case 'execute': return 'Execute'
    case 'approve': return 'Approve'
    case 'notify':  return 'Notify'
    default:        return 'None'
  }
}

function autonomyClass(val) {
  switch (val) {
    case 'execute': return 'bs'
    case 'approve': return 'ba'
    case 'notify':  return 'bn'
    default:        return 'bw'
  }
}

// ── Lifecycle ───────────────────────────────────────────────────────────────
let _pollInterval = null

onMounted(async () => {
  await fetchWindows()
  await fetchActive()
  _pollInterval = setInterval(fetchActive, 60_000)
})

onUnmounted(() => {
  clearInterval(_pollInterval)
})
</script>

<template>
  <div>
    <!-- Header row -->
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.8rem">
      <span style="font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted)">
        <i class="fas fa-wrench" style="margin-right:.3rem"></i>
        Maintenance Windows
      </span>
      <div style="display:flex;gap:.4rem">
        <button v-if="authStore.isAdmin" class="btn btn-sm btn-primary" @click="openCreate">
          <i class="fas fa-plus" style="margin-right:.3rem"></i>New
        </button>
        <button class="btn btn-sm" :disabled="loading" @click="fetchWindows(); fetchActive()">
          <i class="fas" :class="loading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i>
        </button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="empty-msg">Loading...</div>

    <!-- Empty state -->
    <div v-else-if="windows.length === 0" class="empty-msg">
      No maintenance windows configured.
    </div>

    <!-- Table -->
    <div v-else style="overflow-x:auto">
      <table style="width:100%;font-size:.78rem;border-collapse:collapse">
        <thead>
          <tr style="border-bottom:1px solid var(--border)">
            <th style="padding:.4rem .6rem;text-align:left">Name</th>
            <th style="padding:.4rem .6rem;text-align:left">Type</th>
            <th style="padding:.4rem .6rem;text-align:left">Schedule / Range</th>
            <th style="padding:.4rem .6rem;text-align:center">Duration</th>
            <th style="padding:.4rem .6rem;text-align:center">Behaviors</th>
            <th style="padding:.4rem .6rem;text-align:center">Enabled</th>
            <th v-if="authStore.isAdmin" style="padding:.4rem .6rem;text-align:center">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="w in windows"
            :key="w.id"
            style="border-bottom:1px solid var(--border)"
          >
            <!-- Name + Active badge -->
            <td style="padding:.4rem .6rem;font-weight:500">
              {{ w.name }}
              <span
                v-if="isActive(w)"
                class="badge ba"
                style="font-size:.55rem;margin-left:.4rem"
                title="Currently active"
              >Active Now</span>
            </td>

            <!-- Type -->
            <td style="padding:.4rem .6rem">
              <span class="badge bn" style="font-size:.6rem">
                {{ w.type === 'recurring' ? 'Recurring' : 'One-off' }}
              </span>
            </td>

            <!-- Schedule / date range -->
            <td style="padding:.4rem .6rem;font-size:.72rem;font-family:monospace;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
              {{ scheduleLabel(w) }}
            </td>

            <!-- Duration (recurring only) -->
            <td style="padding:.4rem .6rem;text-align:center;font-size:.75rem">
              {{ w.type === 'recurring' && w.duration_minutes ? w.duration_minutes + 'm' : '—' }}
            </td>

            <!-- Behaviors: suppress, override autonomy, auto-close -->
            <td style="padding:.4rem .6rem;text-align:center">
              <div style="display:flex;gap:.3rem;justify-content:center;align-items:center;flex-wrap:wrap">
                <i
                  class="fas fa-bell-slash"
                  :style="w.suppress_alerts !== false ? 'color:var(--warning)' : 'color:var(--text-muted);opacity:.35'"
                  :title="w.suppress_alerts !== false ? 'Suppress alerts' : 'Alerts not suppressed'"
                ></i>
                <span
                  v-if="w.override_autonomy && w.override_autonomy !== 'none'"
                  class="badge"
                  :class="autonomyClass(w.override_autonomy)"
                  style="font-size:.55rem"
                  :title="'Override autonomy: ' + autonomyLabel(w.override_autonomy)"
                >{{ autonomyLabel(w.override_autonomy) }}</span>
                <i
                  class="fas fa-times-circle"
                  :style="w.auto_close_alerts ? 'color:var(--info,#4ea8de)' : 'color:var(--text-muted);opacity:.35'"
                  :title="w.auto_close_alerts ? 'Auto-close alerts' : 'Auto-close off'"
                ></i>
              </div>
            </td>

            <!-- Enabled toggle -->
            <td style="padding:.4rem .6rem;text-align:center">
              <button
                class="btn btn-xs"
                :class="w.enabled ? 'btn-primary' : ''"
                :disabled="!authStore.isAdmin"
                :title="w.enabled ? 'Click to disable' : 'Click to enable'"
                @click="toggleEnabled(w)"
              >
                <span class="badge" :class="w.enabled ? 'bs' : 'bw'" style="font-size:.55rem">
                  {{ w.enabled ? 'On' : 'Off' }}
                </span>
              </button>
            </td>

            <!-- Actions -->
            <td v-if="authStore.isAdmin" style="padding:.4rem .6rem;text-align:center">
              <div style="display:flex;gap:.3rem;justify-content:center">
                <button class="btn btn-xs" title="Edit" @click="openEdit(w)">
                  <i class="fas fa-pen"></i>
                </button>
                <button class="btn btn-xs btn-danger" title="Delete" @click="deleteWindow(w)">
                  <i class="fas fa-trash"></i>
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ── Create / Edit modal ─────────────────────────────────────────── -->
    <AppModal
      :show="showModal"
      :title="formTitle"
      width="560px"
      @close="showModal = false"
    >
      <div style="padding:1rem;display:flex;flex-direction:column;gap:.7rem">

        <!-- Name -->
        <div>
          <label class="field-label">Name</label>
          <input
            v-model="formName"
            type="text"
            class="field-input"
            placeholder="e.g. Nightly patching"
            style="width:100%"
          />
        </div>

        <!-- Type toggle -->
        <div>
          <label class="field-label">Type</label>
          <div style="display:flex;gap:.3rem">
            <button
              class="btn btn-xs"
              :class="formType === 'recurring' ? 'btn-primary' : ''"
              @click="formType = 'recurring'"
            >
              <i class="fas fa-redo" style="margin-right:.25rem"></i>Recurring
            </button>
            <button
              class="btn btn-xs"
              :class="formType === 'one_off' ? 'btn-primary' : ''"
              @click="formType = 'one_off'"
            >
              <i class="fas fa-calendar-alt" style="margin-right:.25rem"></i>One-off
            </button>
          </div>
        </div>

        <!-- Recurring fields -->
        <template v-if="formType === 'recurring'">
          <div>
            <label class="field-label">
              Schedule <span style="font-weight:400;color:var(--text-muted)">(cron expression)</span>
            </label>
            <input
              v-model="formSchedule"
              type="text"
              class="field-input"
              placeholder="e.g. 0 2 * * 0  (Sundays at 02:00)"
              style="width:100%;font-family:monospace"
            />
          </div>
          <div>
            <label class="field-label">Duration (minutes)</label>
            <input
              v-model.number="formDuration"
              type="number"
              min="1"
              class="field-input"
              style="width:120px"
            />
          </div>
        </template>

        <!-- One-off fields -->
        <template v-if="formType === 'one_off'">
          <div>
            <label class="field-label">Start</label>
            <input
              v-model="formStart"
              type="datetime-local"
              class="field-input"
            />
          </div>
          <div>
            <label class="field-label">End</label>
            <input
              v-model="formEnd"
              type="datetime-local"
              class="field-input"
            />
          </div>
        </template>

        <!-- Suppress alerts -->
        <label style="display:flex;align-items:center;gap:.5rem;font-size:.82rem;cursor:pointer">
          <input v-model="formSuppressAlerts" type="checkbox" style="accent-color:var(--accent)" />
          <span>Suppress alerts during window</span>
        </label>

        <!-- Override autonomy -->
        <div>
          <label class="field-label">Override Autonomy</label>
          <select
            v-model="formOverrideAutonomy"
            class="field-select"
            style="width:auto"
          >
            <option value="none">None (use default)</option>
            <option value="execute">Execute (auto-run)</option>
            <option value="approve">Approve (require approval)</option>
            <option value="notify">Notify only</option>
          </select>
        </div>

        <!-- Auto-close alerts -->
        <label style="display:flex;align-items:center;gap:.5rem;font-size:.82rem;cursor:pointer">
          <input v-model="formAutoClose" type="checkbox" style="accent-color:var(--accent)" />
          <span>Auto-close alerts when window ends</span>
        </label>

      </div>

      <template #footer>
        <button class="btn" @click="showModal = false">Cancel</button>
        <button class="btn btn-primary" @click="saveWindow">
          {{ formMode === 'create' ? 'Create' : 'Save' }}
        </button>
      </template>
    </AppModal>
  </div>
</template>
