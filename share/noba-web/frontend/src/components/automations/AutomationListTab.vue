<script setup>
import { ref, computed, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'
import { useModalsStore } from '../../stores/modals'
import AutomationFormModal from './AutomationFormModal.vue'
import RunOutputModal from './RunOutputModal.vue'
import AutomationRow from './AutomationRow.vue'
import AutomationRunHistory from './AutomationRunHistory.vue'
import AutomationWebhooks from './AutomationWebhooks.vue'
import AutomationTraceModal from './AutomationTraceModal.vue'

const authStore = useAuthStore()
const notify    = useNotificationsStore()
const modals    = useModalsStore()
const { get, del, download } = useApi()

// ── Automation list ────────────────────────────────────────────────────────
const autoList        = ref([])
const autoListLoading = ref(false)
const autoFilter      = ref('all')
const autoSearch      = ref('')
const autoStats       = ref({})

const filteredAutoList = computed(() => {
  let list = autoList.value
  if (autoFilter.value !== 'all') list = list.filter(a => a.type === autoFilter.value)
  if (autoSearch.value) {
    const q = autoSearch.value.toLowerCase()
    list = list.filter(a => a.name.toLowerCase().includes(q))
  }
  return list
})

async function fetchAutomations() {
  autoListLoading.value = true
  try { const data = await get('/api/automations'); autoList.value = Array.isArray(data) ? data : [] }
  catch (e) { notify.addToast('Failed to load automations: ' + e.message, 'error') }
  finally { autoListLoading.value = false }
}
async function fetchAutoStats() {
  try { const data = await get('/api/automations/stats'); if (data && typeof data === 'object') autoStats.value = data }
  catch { /* silent */ }
}

// ── Selection & Bulk ───────────────────────────────────────────────────────
const selectedAutos = ref(new Set())

function toggleSelectAuto(id) {
  if (selectedAutos.value.has(id)) { selectedAutos.value.delete(id) } else { selectedAutos.value.add(id) }
}
function selectAllAutos() {
  if (selectedAutos.value.size === filteredAutoList.value.length) { selectedAutos.value.clear() }
  else { selectedAutos.value = new Set(filteredAutoList.value.map(a => a.id)) }
}
async function bulkToggleAutomations(enabled) {
  const targets = Array.from(selectedAutos.value); if (!targets.length) return
  const label = enabled ? 'enable' : 'disable'
  if (!await modals.confirm(`Bulk ${label} ${targets.length} automations?`)) return
  let success = 0, fail = 0
  for (const id of targets) { try { const { put } = useApi(); await put(`/api/automations/${id}`, { enabled }); success++ } catch { fail++ } }
  if (success) notify.addToast(`${success} automations ${label}d`, 'success')
  if (fail) notify.addToast(`${fail} automations failed to ${label}`, 'error')
  selectedAutos.value.clear(); await fetchAutomations()
}
async function bulkDeleteAutomations() {
  const targets = Array.from(selectedAutos.value); if (!targets.length) return
  if (!await modals.confirm(`PERMANENTLY DELETE ${targets.length} automations?`)) return
  let success = 0, fail = 0
  for (const id of targets) { try { await del(`/api/automations/${id}`); success++ } catch { fail++ } }
  if (success) notify.addToast(`Deleted ${success} automations`, 'success')
  if (fail) notify.addToast(`${fail} automations failed to delete`, 'error')
  selectedAutos.value.clear(); await fetchAutomations(); await fetchAutoStats()
}

// ── Create / Edit / Delete ─────────────────────────────────────────────────
const showFormModal = ref(false)
const formModalMode = ref('create')
const editingAuto   = ref(null)

function openCreate() { editingAuto.value = null; formModalMode.value = 'create'; showFormModal.value = true }
function openEdit(auto) { editingAuto.value = auto; formModalMode.value = 'edit'; showFormModal.value = true }
async function onSaved() { await fetchAutomations(); await fetchAutoStats() }

async function deleteAutomation(auto) {
  if (!await modals.confirm(`Delete automation "${auto.name}"?`)) return
  try { await del(`/api/automations/${auto.id}`); notify.addToast('Automation deleted', 'success'); await fetchAutomations(); await fetchAutoStats() }
  catch (e) { notify.addToast('Delete failed: ' + e.message, 'error') }
}

// ── Run ────────────────────────────────────────────────────────────────────
const runOutputRef = ref(null)
const showRunModal = ref(false)
async function runAutomation(auto) {
  showRunModal.value = true
  await new Promise(r => setTimeout(r, 0))
  runOutputRef.value?.startRun(auto)
}

// ── Import / Export ────────────────────────────────────────────────────────
const importInputRef = ref(null)
async function exportAutomations() {
  try {
    const res = await download('/api/automations/export'); const blob = await res.blob()
    const objUrl = URL.createObjectURL(blob)
    try { const a = document.createElement('a'); a.href = objUrl; a.download = 'noba-automations.yaml'; document.body.appendChild(a); a.click(); document.body.removeChild(a) }
    finally { URL.revokeObjectURL(objUrl) }
    notify.addToast('Automations exported', 'success')
  } catch (e) { notify.addToast('Export failed: ' + e.message, 'error') }
}
async function importAutomations(event) {
  const file = event.target.files?.[0]; if (!file) return
  if (!file.name.match(/\.(yaml|yml)$/i)) { notify.addToast('Please select a .yaml or .yml file', 'error'); return }
  try {
    const body = await file.arrayBuffer()
    const res = await fetch('/api/automations/import?mode=skip', { method: 'POST', headers: { 'Content-Type': 'application/x-yaml', Authorization: `Bearer ${authStore.token}` }, body })
    const data = await res.json().catch(() => ({}))
    if (res.ok) { notify.addToast(`Imported ${data.imported}, skipped ${data.skipped}`, 'success'); await fetchAutomations(); await fetchAutoStats() }
    else { notify.addToast(data.detail || 'Import failed', 'error') }
  } catch (e) { notify.addToast('Import error: ' + e.message, 'error') }
  finally { event.target.value = '' }
}

// ── Lifecycle ──────────────────────────────────────────────────────────────
const showRunHistory = ref(false)
const runHistoryRef  = ref(null)
const traceModalRef  = ref(null)
const webhooksRef    = ref(null)

onMounted(async () => {
  await fetchAutomations(); await fetchAutoStats()
})

defineExpose({ fetchAutomations, fetchAutoStats })
</script>

<template>
  <div>
    <!-- Page header -->
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem">
      <div></div>
      <div v-if="authStore.isOperator" style="display:flex;gap:.4rem;flex-wrap:wrap">
        <button class="btn btn-sm btn-primary" @click="openCreate"><i class="fas fa-plus" style="margin-right:.3rem"></i>New</button>
        <button class="btn btn-sm" :disabled="autoListLoading" @click="fetchAutomations">
          <i class="fas" :class="autoListLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i>
        </button>
        <button class="btn btn-sm" @click="showRunHistory = !showRunHistory; showRunHistory && runHistoryRef?.fetchRunHistory()">
          <i class="fas fa-history" style="margin-right:.3rem"></i>History
        </button>
        <button class="btn btn-sm" @click="exportAutomations"><i class="fas fa-download" style="margin-right:.3rem"></i>Export</button>
        <label class="btn btn-sm" style="cursor:pointer;margin:0">
          <i class="fas fa-upload" style="margin-right:.3rem"></i>Import
          <input ref="importInputRef" type="file" accept=".yaml,.yml" style="display:none" @change="importAutomations" />
        </label>
      </div>
    </div>

    <!-- Filter bar -->
    <div style="display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.8rem;align-items:center">
      <template v-for="tab in ['all','script','webhook','workflow','cron','alert']" :key="tab">
        <button class="btn btn-xs" :class="autoFilter === tab ? 'btn-primary' : ''" @click="autoFilter = tab">{{ tab }}</button>
      </template>
      <input v-model="autoSearch" type="text" class="field-input" placeholder="Search..." style="margin-left:auto;width:160px;height:28px;font-size:.75rem" />
    </div>

    <!-- Selection Bar -->
    <div
      v-if="selectedAutos.size > 0 || filteredAutoList.length > 0"
      class="selection-bar"
      :style="selectedAutos.size > 0 ? '' : 'border-color:transparent;background:transparent;box-shadow:none;padding:0;margin-bottom:.75rem'"
    >
      <div style="display:flex;align-items:center;gap:.8rem;flex:1">
        <button class="btn btn-xs" :class="selectedAutos.size === filteredAutoList.length ? 'btn-primary' : 'btn-secondary'" @click="selectAllAutos">
          <i class="fas" :class="selectedAutos.size === filteredAutoList.length ? 'fa-check-square' : 'fa-square'"></i>
          {{ selectedAutos.size === filteredAutoList.length ? 'Deselect All' : 'Select All' }}
        </button>
        <template v-if="selectedAutos.size > 0">
          <div style="width:1px;height:16px;background:var(--border);margin:0 .2rem"></div>
          <span style="font-weight:600;font-size:.85rem">{{ selectedAutos.size }} automation{{ selectedAutos.size > 1 ? 's' : '' }} selected</span>
        </template>
      </div>
      <div v-if="selectedAutos.size > 0" style="display:flex;gap:.5rem;align-items:center">
        <button class="btn btn-xs btn-primary" @click="bulkToggleAutomations(true)"><i class="fas fa-check"></i> Enable</button>
        <button class="btn btn-xs btn-secondary" @click="bulkToggleAutomations(false)"><i class="fas fa-ban"></i> Disable</button>
        <div style="width:1px;height:16px;background:var(--border);margin:0 .2rem"></div>
        <button class="btn btn-xs btn-danger" @click="bulkDeleteAutomations"><i class="fas fa-trash"></i> Delete</button>
      </div>
    </div>

    <!-- Loading / Empty states -->
    <div v-if="autoListLoading" class="empty-msg">Loading...</div>
    <div v-else-if="filteredAutoList.length === 0" class="empty-msg" style="padding:2rem;text-align:center">
      <template v-if="autoSearch || autoFilter !== 'all'">
        <i class="fas fa-filter" style="font-size:1.5rem;opacity:.3;display:block;margin-bottom:.5rem"></i>
        No automations match the current filter.
      </template>
      <template v-else>
        <i class="fas fa-robot" style="font-size:2rem;opacity:.3;display:block;margin-bottom:.5rem"></i>
        No automations defined yet.
        <br><small style="opacity:.6">Create scripts, webhooks, or workflows to automate your infrastructure.</small>
        <br><button v-if="authStore.isOperator" class="btn btn-primary" style="margin-top:.75rem" @click="openCreate"><i class="fas fa-plus"></i> Create Automation</button>
      </template>
    </div>

    <!-- Automation grid -->
    <div v-else style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:.8rem;margin-bottom:1.5rem">
      <AutomationRow
        v-for="a in filteredAutoList" :key="a.id"
        :automation="a" :stat="autoStats[a.id] || null"
        :selected="selectedAutos.has(a.id)" :is-operator="authStore.isOperator"
        @run="runAutomation" @edit="openEdit" @delete="deleteAutomation"
        @trace="traceModalRef?.open($event)" @toggle-select="toggleSelectAuto"
      />
    </div>

    <!-- Run History panel -->
    <AutomationRunHistory v-if="showRunHistory" ref="runHistoryRef" :automations="autoList" style="margin-bottom:1.5rem" />

    <!-- Webhooks (admin only) -->
    <AutomationWebhooks v-if="authStore.isAdmin" ref="webhooksRef" :automations="autoList" />

    <!-- Modals -->
    <AutomationFormModal :show="showFormModal" :mode="formModalMode" :initial="editingAuto || {}" :automations="autoList" @close="showFormModal = false" @saved="onSaved" />
    <RunOutputModal ref="runOutputRef" :show="showRunModal" @close="showRunModal = false" />
    <AutomationTraceModal ref="traceModalRef" />
  </div>
</template>

<style scoped>
.field-input {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  padding: .4rem .5rem;
  font-size: .85rem;
  box-sizing: border-box;
}
.field-input:focus { outline: none; border-color: var(--accent); }
.selection-bar {
  display: flex;
  align-items: center;
  padding: .6rem 1rem;
  background: var(--surface);
  border: 1px solid var(--accent);
  border-radius: 6px;
  margin-bottom: 1rem;
  box-shadow: 0 4px 12px rgba(0,0,0,0.2), 0 0 8px var(--accent-glow);
  animation: slide-down 0.2s ease-out;
}
@keyframes slide-down {
  from { transform: translateY(-10px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}
</style>
