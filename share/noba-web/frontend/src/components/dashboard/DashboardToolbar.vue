<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { useSettingsStore } from '../../stores/settings'
import { useModalsStore } from '../../stores/modals'

const emit = defineEmits(['dashboard-loaded'])

const { get, post, del } = useApi()
const settingsStore = useSettingsStore()
const modals        = useModalsStore()

const savedDashboards   = ref([])
const saveDashboardName = ref('')
const showSaveModal     = ref(false)
const showManage        = ref(false)

async function fetchDashboards() {
  try {
    savedDashboards.value = await get('/api/dashboards')
  } catch { /* silent */ }
}

async function saveDashboard() {
  const name = saveDashboardName.value.trim()
  if (!name) return
  try {
    // Read current order from the live Sortable instance so it reflects
    // the actual DOM order regardless of whether store.set has fired.
    const grid = document.querySelector('.grid')
    const liveOrder = grid?._sortable?.toArray() || settingsStore.preferences.cardOrder || []
    const config = {
      vis: { ...settingsStore.vis },
      cardOrder: liveOrder,
    }
    await post('/api/dashboards', { name, config_json: JSON.stringify(config), shared: false })
    saveDashboardName.value = ''
    showSaveModal.value = false
    await fetchDashboards()
  } catch { /* silent */ }
}

async function loadDashboard(dashboard) {
  try {
    const config = JSON.parse(dashboard.config_json)
    if (config.vis) Object.assign(settingsStore.vis, config.vis)
    if (config.cardOrder) {
      if (!settingsStore.preferences.preferences) settingsStore.preferences.preferences = {}
      settingsStore.preferences.preferences.cardOrder = config.cardOrder
    }
    await settingsStore.savePreferences()
    emit('dashboard-loaded')
  } catch { /* silent */ }
}

async function deleteDashboard(id) {
  if (!await modals.confirm('Delete this saved dashboard?')) return
  try {
    await del('/api/dashboards/' + id)
    await fetchDashboards()
    if (savedDashboards.value.length === 0) showManage.value = false
  } catch { /* silent */ }
}

onMounted(() => { fetchDashboards() })

defineExpose({ fetchDashboards })
</script>

<template>
  <div style="display:flex;align-items:center;gap:.5rem;margin:.75rem 0;flex-wrap:wrap">
    <select
      v-if="savedDashboards.length > 0"
      class="theme-select"
      style="font-size:.75rem;padding:.3rem .5rem"
      @change="e => { const d = savedDashboards.find(x => String(x.id) === e.target.value); if (d) loadDashboard(d); e.target.value = '' }"
    >
      <option value="">Load dashboard...</option>
      <option v-for="d in savedDashboards" :key="d.id" :value="d.id">{{ d.name }}</option>
    </select>

    <button
      class="btn btn-xs btn-secondary"
      type="button"
      title="Save current layout"
      @click="showSaveModal = !showSaveModal; showManage = false"
    >
      <i class="fas fa-save"></i> Save Layout
    </button>

    <template v-if="showSaveModal">
      <input
        v-model="saveDashboardName"
        class="field-input"
        type="text"
        placeholder="Dashboard name..."
        style="font-size:.75rem;padding:.3rem .5rem;max-width:180px"
        @keyup.enter="saveDashboard"
      >
      <button
        class="btn btn-xs"
        type="button"
        :disabled="!saveDashboardName.trim()"
        @click="saveDashboard"
      >Save</button>
    </template>

    <button
      v-if="savedDashboards.length > 0"
      class="btn btn-xs btn-secondary"
      type="button"
      title="Manage saved dashboards"
      @click="showManage = !showManage; showSaveModal = false"
    >
      <i class="fas fa-cog"></i>
    </button>

    <template v-if="showManage">
      <span
        v-for="d in savedDashboards"
        :key="'mgr-' + d.id"
        style="display:inline-flex;align-items:center;gap:.3rem;font-size:.75rem;background:var(--card-bg);padding:.2rem .5rem;border-radius:.3rem"
      >
        {{ d.name }}
        <button class="btn btn-xs btn-danger" type="button" @click="deleteDashboard(d.id)">
          <i class="fas fa-trash"></i>
        </button>
      </span>
    </template>
  </div>
</template>
