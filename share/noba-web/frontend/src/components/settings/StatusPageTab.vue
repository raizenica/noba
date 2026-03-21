<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, post, put } = useApi()

const spComponents = ref([])
const spIncidents = ref([])

const spNewComp = ref({ name: '', group_name: '', service_key: '', display_order: 0 })
const spNewIncident = ref({ title: '', severity: 'minor', message: '' })

const loading = ref(false)

onMounted(() => {
  if (authStore.isAdmin) {
    fetchComponents()
    fetchIncidents()
  }
})

async function fetchComponents() {
  try {
    const d = await get('/api/status/components')
    spComponents.value = Array.isArray(d) ? d : (d.components || [])
  } catch { /* silent */ }
}

async function fetchIncidents() {
  try {
    const d = await get('/api/status/incidents')
    spIncidents.value = Array.isArray(d) ? d : (d.incidents || [])
  } catch { /* silent */ }
}

async function createStatusComponent() {
  if (!spNewComp.value.name.trim()) return
  try {
    await post('/api/status/components', { ...spNewComp.value })
    spNewComp.value = { name: '', group_name: '', service_key: '', display_order: 0 }
    await fetchComponents()
  } catch { /* silent */ }
}

async function deleteStatusComponent(id) {
  if (!confirm('Delete this component?')) return
  try {
    await fetch(`/api/status/components/${id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${authStore.token}` },
    })
    await fetchComponents()
  } catch { /* silent */ }
}

async function createStatusIncident() {
  if (!spNewIncident.value.title.trim()) return
  try {
    await post('/api/status/incidents', { ...spNewIncident.value })
    spNewIncident.value = { title: '', severity: 'minor', message: '' }
    await fetchIncidents()
  } catch { /* silent */ }
}

async function addStatusUpdate(incId) {
  const msgEl = document.getElementById('sp-upd-' + incId)
  const statusEl = document.getElementById('sp-upd-status-' + incId)
  const message = msgEl?.value?.trim() || ''
  const status = statusEl?.value || 'investigating'
  if (!message) return
  try {
    await put(`/api/status/incidents/${incId}`, { message, status })
    if (msgEl) msgEl.value = ''
    await fetchIncidents()
  } catch { /* silent */ }
}

async function resolveStatusIncident(incId) {
  if (!confirm('Mark this incident as resolved?')) return
  try {
    await put(`/api/status/incidents/${incId}`, { status: 'resolved', resolved: true })
    await fetchIncidents()
  } catch { /* silent */ }
}
</script>

<template>
  <div>
    <!-- Admin gate -->
    <div v-if="!authStore.isAdmin" style="text-align:center;padding:3rem;color:var(--text-muted)">
      <i class="fas fa-lock" style="font-size:2rem;margin-bottom:.75rem;display:block;opacity:.4"></i>
      Admin role required to manage the status page.
    </div>

    <template v-else>
      <!-- Component Management -->
      <div class="s-section">
        <span class="s-label">Status Page Components</span>
        <p class="help-text" style="margin-bottom:.6rem">
          Components shown on the public
          <a href="/status" target="_blank" style="color:var(--accent)">/status</a> page.
          Link to service keys for live status.
        </p>
        <div style="margin-bottom:.75rem;display:flex;gap:.4rem;flex-wrap:wrap">
          <input class="field-input" style="flex:1;min-width:120px" type="text"
            v-model="spNewComp.name" placeholder="Component name">
          <input class="field-input" style="width:120px" type="text"
            v-model="spNewComp.group_name" placeholder="Group">
          <input class="field-input" style="width:120px" type="text"
            v-model="spNewComp.service_key" placeholder="Service key">
          <input class="field-input" style="width:60px" type="number"
            v-model.number="spNewComp.display_order" placeholder="#" title="Display order">
          <button class="btn btn-sm btn-primary" @click="createStatusComponent" :disabled="!spNewComp.name.trim()">
            <i class="fas fa-plus"></i> Add
          </button>
        </div>
        <div style="max-height:200px;overflow-y:auto">
          <div
            v-for="comp in spComponents" :key="comp.id"
            style="display:flex;align-items:center;gap:.4rem;padding:.35rem 0;border-bottom:1px solid var(--border)"
          >
            <span style="flex:1;font-size:.8rem">{{ comp.name }}</span>
            <span style="font-size:.7rem;color:var(--text-muted)">{{ comp.group_name }}</span>
            <span style="font-size:.65rem;color:var(--text-dim)">{{ comp.service_key || '--' }}</span>
            <button class="btn btn-sm" style="padding:.15rem .4rem;font-size:.65rem" @click="deleteStatusComponent(comp.id)" title="Delete">
              <i class="fas fa-trash"></i>
            </button>
          </div>
          <div v-if="spComponents.length === 0" style="font-size:.75rem;color:var(--text-muted);padding:.5rem 0">
            No components configured. Add components above.
          </div>
        </div>
      </div>

      <!-- Create Incident -->
      <div class="s-section">
        <span class="s-label">Create Incident</span>
        <div style="display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.5rem">
          <input class="field-input" style="flex:1;min-width:180px" type="text"
            v-model="spNewIncident.title" placeholder="Incident title">
          <select class="field-input field-select" style="width:100px" v-model="spNewIncident.severity">
            <option value="minor">Minor</option>
            <option value="major">Major</option>
            <option value="critical">Critical</option>
          </select>
        </div>
        <div style="display:flex;gap:.4rem;flex-wrap:wrap">
          <input class="field-input" style="flex:1;min-width:200px" type="text"
            v-model="spNewIncident.message" placeholder="Initial message (optional)">
          <button class="btn btn-sm btn-primary" @click="createStatusIncident" :disabled="!spNewIncident.title.trim()">
            <i class="fas fa-exclamation-triangle"></i> Create
          </button>
        </div>
      </div>

      <!-- Active Incidents -->
      <div class="s-section">
        <span class="s-label">Active Incidents</span>
        <div style="max-height:260px;overflow-y:auto">
          <div
            v-for="inc in spIncidents.filter(i => !i.resolved_at)" :key="inc.id"
            style="background:var(--surface);border-radius:6px;padding:.6rem;margin-bottom:.4rem;border-left:3px solid var(--warning)"
          >
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.3rem">
              <span style="font-size:.8rem;font-weight:700">{{ inc.title }}</span>
              <span style="font-size:.6rem;padding:.1rem .4rem;border-radius:3px;background:var(--warning-dim,#ff980022);color:var(--warning);text-transform:uppercase;font-weight:700">
                {{ inc.status }}
              </span>
            </div>
            <div style="font-size:.65rem;color:var(--text-muted);margin-bottom:.4rem">
              {{ new Date((inc.created_at || 0) * 1000).toLocaleString() }}
            </div>
            <div style="display:flex;gap:.3rem;flex-wrap:wrap;align-items:center">
              <input class="field-input" style="flex:1;min-width:150px;font-size:.75rem;padding:.2rem .4rem"
                type="text" :id="'sp-upd-' + inc.id" placeholder="Update message...">
              <select class="field-input field-select" style="width:110px;font-size:.75rem;padding:.2rem .3rem" :id="'sp-upd-status-' + inc.id">
                <option value="investigating">Investigating</option>
                <option value="identified">Identified</option>
                <option value="monitoring">Monitoring</option>
              </select>
              <button class="btn btn-sm" style="font-size:.65rem;padding:.2rem .5rem" @click="addStatusUpdate(inc.id)">
                <i class="fas fa-plus"></i> Update
              </button>
              <button class="btn btn-sm" style="font-size:.65rem;padding:.2rem .5rem;color:var(--success)" @click="resolveStatusIncident(inc.id)">
                <i class="fas fa-check"></i> Resolve
              </button>
            </div>
          </div>
          <div v-if="spIncidents.filter(i => !i.resolved_at).length === 0" style="font-size:.75rem;color:var(--text-muted);padding:.5rem 0">
            No active incidents.
          </div>
        </div>
        <button class="btn btn-sm" style="margin-top:.5rem" @click="fetchIncidents">
          <i class="fas fa-sync"></i> Refresh
        </button>
      </div>
    </template>
  </div>
</template>
