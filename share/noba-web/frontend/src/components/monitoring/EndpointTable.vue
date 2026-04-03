<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'
import { useModalsStore } from '../../stores/modals'
import { useDashboardStore } from '../../stores/dashboard'
import AppModal from '../ui/AppModal.vue'

const { get, post, put, del } = useApi()
const authStore      = useAuthStore()
const notif          = useNotificationsStore()
const dashboardStore = useDashboardStore()
const modals         = useModalsStore()

const endpoints     = ref([])
const loading       = ref(false)
const showModal     = ref(false)
const editId        = ref(null)

const defaultForm = () => ({
  name:             '',
  url:              '',
  method:           'GET',
  expected_status:  200,
  check_interval:   300,
  timeout:          10,
  agent_hostname:   '',
  enabled:          true,
  notify_cert_days: 14,
})

const form = ref(defaultForm())

const agents = () => (dashboardStore.live.agents || []).filter(a => a.online)

async function fetchEndpoints() {
  loading.value = true
  try {
    const data = await get('/api/endpoints')
    endpoints.value = Array.isArray(data) ? data : []
  } catch { /* silent */ }
  finally { loading.value = false }
}

function openAdd() {
  editId.value = null
  form.value   = defaultForm()
  showModal.value = true
}

function openEdit(ep) {
  editId.value = ep.id
  form.value = {
    name:             ep.name,
    url:              ep.url,
    method:           ep.method || 'GET',
    expected_status:  ep.expected_status || 200,
    check_interval:   ep.check_interval || 300,
    timeout:          ep.timeout || 10,
    agent_hostname:   ep.agent_hostname || '',
    enabled:          ep.enabled,
    notify_cert_days: ep.notify_cert_days || 14,
  }
  showModal.value = true
}

async function saveEndpoint() {
  const isEdit = !!editId.value
  const url    = isEdit ? `/api/endpoints/${editId.value}` : '/api/endpoints'
  try {
    if (isEdit) {
      await put(url, { ...form.value })
    } else {
      await post(url, { ...form.value })
    }
    notif.addToast(isEdit ? 'Monitor updated' : 'Monitor created', 'success')
    showModal.value = false
    await fetchEndpoints()
  } catch (e) {
    notif.addToast('Error: ' + (e.message || 'Failed to save'), 'error')
  }
}

async function deleteEndpoint(id, name) {
  if (!await modals.confirm(`Delete monitor "${name}"?`)) return
  try {
    await del(`/api/endpoints/${id}`)
    notif.addToast('Deleted', 'success')
    await fetchEndpoints()
  } catch (e) {
    notif.addToast('Error: ' + e.message, 'error')
  }
}

async function checkNow(id) {
  try {
    const data = await post(`/api/endpoints/${id}/check`)
    notif.addToast('Check complete: ' + (data && data.last_status ? data.last_status : 'done'), 'success')
    await fetchEndpoints()
  } catch (e) {
    notif.addToast('Check failed: ' + e.message, 'error')
  }
}

function statusClass(status) {
  if (status === 'up')       return 'bs'
  if (status === 'degraded') return 'bw'
  return 'bd'
}

function certExpiryStyle(days) {
  if (days == null) return 'color:var(--text-muted)'
  if (days <= 7)    return 'color:var(--danger);font-weight:700'
  if (days <= 14)   return 'color:var(--warning);font-weight:600'
  return 'color:var(--success)'
}

onMounted(() => fetchEndpoints())
</script>

<template>
  <div>
    <!-- Header row -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
      <span style="font-size:.8rem;color:var(--text-muted)">
        {{ endpoints.length }} monitor(s)
      </span>
      <div style="display:flex;gap:.4rem">
        <button
          class="btn btn-xs"
          :disabled="loading"
          @click="fetchEndpoints"
        >
          <i class="fas" :class="loading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i>
        </button>
        <button
          v-if="authStore.isOperator"
          class="btn btn-primary btn-sm"
          @click="openAdd"
        >
          <i class="fas fa-plus"></i> Add Monitor
        </button>
      </div>
    </div>

    <div v-if="loading" class="empty-msg">Loading...</div>
    <div v-else-if="endpoints.length === 0" class="empty-msg">No endpoint monitors configured.</div>

    <div v-else style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:.8rem">
        <thead>
          <tr style="border-bottom:2px solid var(--border);text-align:left">
            <th style="padding:.4rem .5rem">Name</th>
            <th style="padding:.4rem .5rem">URL</th>
            <th style="padding:.4rem .5rem">Agent</th>
            <th style="padding:.4rem .5rem">Status</th>
            <th style="padding:.4rem .5rem">Response</th>
            <th style="padding:.4rem .5rem">Cert Expiry</th>
            <th style="padding:.4rem .5rem">Last Checked</th>
            <th style="padding:.4rem .5rem">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="ep in endpoints"
            :key="ep.id"
            style="border-bottom:1px solid var(--border)"
          >
            <td style="padding:.4rem .5rem;font-weight:600">{{ ep.name }}</td>
            <td
              style="padding:.4rem .5rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
              :title="ep.url"
            >{{ ep.url }}</td>
            <td style="padding:.4rem .5rem">{{ ep.agent_hostname || 'Server' }}</td>
            <td style="padding:.4rem .5rem">
              <span class="badge" :class="statusClass(ep.last_status)" style="font-size:.65rem">
                {{ ep.last_status || 'pending' }}
              </span>
            </td>
            <td style="padding:.4rem .5rem;font-family:var(--font-data)">
              {{ ep.last_response_ms != null ? ep.last_response_ms + 'ms' : '--' }}
            </td>
            <td style="padding:.4rem .5rem">
              <span v-if="ep.cert_expiry_days != null" :style="certExpiryStyle(ep.cert_expiry_days)">
                {{ ep.cert_expiry_days }}d
              </span>
              <span v-else style="color:var(--text-muted)">--</span>
            </td>
            <td style="padding:.4rem .5rem;font-size:.7rem;color:var(--text-muted)">
              {{ ep.last_checked ? new Date(ep.last_checked * 1000).toLocaleString() : 'Never' }}
            </td>
            <td style="padding:.4rem .5rem;white-space:nowrap">
              <button class="btn btn-xs" title="Check Now" aria-label="Check now" @click="checkNow(ep.id)">
                <i class="fas fa-play"></i>
              </button>
              <button
                v-if="authStore.isAdmin"
                class="btn btn-xs"
                title="Edit"
                @click="openEdit(ep)"
              >
                <i class="fas fa-edit"></i>
              </button>
              <button
                v-if="authStore.isAdmin"
                class="btn btn-xs"
                title="Delete"
                @click="deleteEndpoint(ep.id, ep.name)"
              >
                <i class="fas fa-trash"></i>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Add / Edit modal -->
    <AppModal
      :show="showModal"
      :title="editId ? 'Edit Monitor' : 'Add Endpoint Monitor'"
      width="480px"
      @close="showModal = false"
    >
      <div style="padding:1rem;display:grid;gap:.6rem">
        <label style="font-size:.75rem;font-weight:600">Name
          <input
            v-model="form.name"
            class="field-input"
            placeholder="My Service"
            style="margin-top:.2rem"
          >
        </label>

        <label style="font-size:.75rem;font-weight:600">URL
          <input
            v-model="form.url"
            class="field-input"
            placeholder="https://example.com/health"
            style="margin-top:.2rem"
          >
        </label>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
          <label style="font-size:.75rem;font-weight:600">Method
            <select v-model="form.method" class="field-select" style="margin-top:.2rem">
              <option value="GET">GET</option>
              <option value="HEAD">HEAD</option>
            </select>
          </label>
          <label style="font-size:.75rem;font-weight:600">Expected Status
            <input
              v-model.number="form.expected_status"
              type="number"
              class="field-input"
              style="margin-top:.2rem"
            >
          </label>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
          <label style="font-size:.75rem;font-weight:600">Interval (sec)
            <input
              v-model.number="form.check_interval"
              type="number"
              class="field-input"
              style="margin-top:.2rem"
            >
          </label>
          <label style="font-size:.75rem;font-weight:600">Timeout (sec)
            <input
              v-model.number="form.timeout"
              type="number"
              class="field-input"
              style="margin-top:.2rem"
            >
          </label>
        </div>

        <label style="font-size:.75rem;font-weight:600">Agent (blank = server)
          <select v-model="form.agent_hostname" class="field-select" style="margin-top:.2rem">
            <option value="">Server (local)</option>
            <option
              v-for="a in agents()"
              :key="a.hostname"
              :value="a.hostname"
            >{{ a.hostname }}</option>
          </select>
        </label>

        <label style="font-size:.75rem;font-weight:600">Cert expiry alert (days)
          <input
            v-model.number="form.notify_cert_days"
            type="number"
            class="field-input"
            style="margin-top:.2rem"
          >
        </label>

        <label style="font-size:.75rem;display:flex;align-items:center;gap:.4rem">
          <input v-model="form.enabled" type="checkbox"> Enabled
        </label>
      </div>

      <template #footer>
        <button class="btn" @click="showModal = false">Cancel</button>
        <button class="btn btn-primary" @click="saveEndpoint">
          {{ editId ? 'Save' : 'Create' }}
        </button>
      </template>
    </AppModal>
  </div>
</template>
