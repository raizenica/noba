<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'
import { useModalsStore } from '../../stores/modals'
import AppModal from '../ui/AppModal.vue'
import ChartWrapper from '../ui/ChartWrapper.vue'

const { get, post, del } = useApi()
const notif  = useNotificationsStore()
const modals = useModalsStore()

// ── Metrics ──────────────────────────────────────────────────────────────────
const availableMetrics   = ref([])
const multiMetrics       = ref([])
const historyRange       = ref(24)
const multiMetricData    = ref({})
const multiMetricLoading = ref(false)

// ── Saved dashboards ────────────────────────────────────────────────────────
const savedDashboards    = ref([])
const showSaveDashModal  = ref(false)
const saveDashId         = ref(null)
const saveDashName       = ref('')
const saveDashShared     = ref(false)

async function fetchAvailableMetrics() {
  try {
    const data = await get('/api/metrics/available')
    availableMetrics.value = Array.isArray(data) ? data : []
  } catch { /* silent */ }
}

async function fetchMultiMetricChart() {
  if (!multiMetrics.value.length) return
  multiMetricLoading.value = true
  try {
    const metrics = multiMetrics.value.join(',')
    const data    = await get(`/api/history/multi?metrics=${metrics}&range=${historyRange.value}`)
    multiMetricData.value = data || {}
  } catch { /* silent */ }
  finally { multiMetricLoading.value = false }
}

function addMetric(metric) {
  if (!metric) return
  if (!multiMetrics.value.includes(metric) && multiMetrics.value.length < 10) {
    multiMetrics.value.push(metric)
    fetchMultiMetricChart()
  }
}

function removeMetric(metric) {
  multiMetrics.value = multiMetrics.value.filter(m => m !== metric)
  fetchMultiMetricChart()
}

const multiChartConfig = computed(() => {
  if (!Object.keys(multiMetricData.value).length) return null
  const colors   = ['#7aa2f7','#f7768e','#9ece6a','#e0af68','#bb9af7','#7dcfff','#ff9e64','#c0caf5','#73daca','#b4f9f8']
  const datasets = []
  let i = 0
  for (const [metric, points] of Object.entries(multiMetricData.value)) {
    if (!Array.isArray(points)) continue
    datasets.push({
      label: metric,
      data: points.map(p => ({ x: p.time * 1000, y: p.value })),
      borderColor: colors[i % colors.length],
      backgroundColor: 'transparent',
      borderWidth: 1.5,
      pointRadius: 0,
      tension: 0.3,
    })
    i++
  }
  return {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          type: 'linear',
          ticks: {
            color: 'rgba(255,255,255,.5)',
            maxTicksLimit: 8,
            callback: v => new Date(v).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
          grid: { color: 'rgba(255,255,255,.05)' },
        },
        y: {
          ticks: { color: 'rgba(255,255,255,.5)' },
          grid:  { color: 'rgba(255,255,255,.05)' },
        },
      },
      plugins: { legend: { labels: { color: 'rgba(255,255,255,.7)' } } },
    },
  }
})

const selectableMetrics = computed(() =>
  availableMetrics.value.filter(m => m.type === 'history' || m.type === 'number')
)

// ── Saved dashboards CRUD ────────────────────────────────────────────────────
async function fetchDashboards() {
  try {
    const data = await get('/api/dashboards')
    savedDashboards.value = Array.isArray(data) ? data : []
  } catch { /* silent */ }
}

function loadDashboard(dashboard) {
  try {
    const config = JSON.parse(dashboard.config_json)
    if (config.metrics && Array.isArray(config.metrics)) {
      multiMetrics.value = config.metrics
    }
    if (config.range) historyRange.value = config.range
    fetchAvailableMetrics()
    fetchMultiMetricChart()
    notif.addToast('Loaded dashboard: ' + dashboard.name, 'success')
  } catch {
    notif.addToast('Failed to load dashboard config', 'error')
  }
}

async function saveDashboard() {
  const name = (saveDashName.value || '').trim()
  if (!name) { notif.addToast('Dashboard name is required', 'error'); return }
  const config = {
    metrics: [...multiMetrics.value],
    range:   historyRange.value,
  }
  const body   = { name, config_json: JSON.stringify(config), shared: saveDashShared.value }
  const isEdit = !!saveDashId.value
  try {
    if (isEdit) {
      await post(`/api/dashboards/${saveDashId.value}`, body)
    } else {
      await post('/api/dashboards', body)
    }
    notif.addToast(isEdit ? 'Dashboard updated' : 'Dashboard saved', 'success')
    showSaveDashModal.value = false
    saveDashName.value  = ''
    saveDashShared.value = false
    saveDashId.value    = null
    await fetchDashboards()
  } catch (e) {
    notif.addToast('Error: ' + e.message, 'error')
  }
}

async function deleteDashboard(id, name) {
  if (!await modals.confirm(`Delete dashboard "${name}"?`)) return
  try {
    await del(`/api/dashboards/${id}`)
    notif.addToast('Dashboard deleted', 'success')
    await fetchDashboards()
  } catch (e) {
    notif.addToast('Error: ' + e.message, 'error')
  }
}

defineExpose({ fetchAvailableMetrics, fetchDashboards, fetchMultiMetricChart })
</script>

<template>
  <div>
    <!-- Saved dashboards section -->
    <div style="margin-bottom:1.2rem">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem">
        <h3 style="font-size:.9rem;margin:0">
          <i class="fas fa-th-large" style="margin-right:.4rem"></i>My Dashboards
        </h3>
      </div>
      <div
        v-if="savedDashboards.length === 0"
        style="font-size:.75rem;color:var(--text-muted);padding:.3rem 0"
      >No saved dashboards yet. Build a chart below and save it.</div>
      <div style="display:flex;flex-wrap:wrap;gap:.5rem">
        <div
          v-for="d in savedDashboards"
          :key="d.id"
          style="background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:.5rem .7rem;display:flex;align-items:center;gap:.5rem;font-size:.8rem;cursor:pointer;transition:border-color .15s"
          @click="loadDashboard(d)"
        >
          <i class="fas fa-chart-line" style="color:var(--accent);font-size:.7rem"></i>
          <span style="font-weight:600">{{ d.name }}</span>
          <span v-if="d.shared" class="badge bs" style="font-size:.6rem;padding:1px 5px">shared</span>
          <span style="font-size:.65rem;color:var(--text-muted)">{{ d.owner }}</span>
          <button
            class="btn btn-xs"
            style="padding:2px 5px;font-size:.6rem;margin-left:auto"
            title="Edit"
            @click.stop="saveDashId = d.id; saveDashName = d.name; saveDashShared = d.shared; showSaveDashModal = true"
          ><i class="fas fa-pen"></i></button>
          <button
            class="btn btn-xs"
            style="padding:2px 5px;font-size:.6rem;color:var(--danger)"
            title="Delete"
            @click.stop="deleteDashboard(d.id, d.name)"
          ><i class="fas fa-trash"></i></button>
        </div>
      </div>
    </div>

    <!-- Chart builder controls -->
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:1rem;align-items:center">
      <span
        v-for="m in multiMetrics"
        :key="m"
        class="badge bs"
        style="cursor:pointer"
        @click="removeMetric(m)"
      >
        {{ m }} <i class="fas fa-times" style="margin-left:4px;font-size:.6rem"></i>
      </span>

      <select
        style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:4px;font-size:.8rem"
        @change="e => { addMetric(e.target.value); e.target.value = '' }"
      >
        <option value="">+ Add metric</option>
        <option
          v-for="m in selectableMetrics"
          :key="m.name"
          :value="m.name"
        >{{ m.name }}</option>
      </select>

      <select
        v-model.number="historyRange"
        style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);padding:4px;border-radius:4px"
        @change="fetchMultiMetricChart"
      >
        <option :value="1">1h</option>
        <option :value="6">6h</option>
        <option :value="24">24h</option>
        <option :value="168">7d</option>
        <option :value="720">30d</option>
      </select>

      <button
        class="btn btn-sm"
        :disabled="multiMetricLoading"
        @click="fetchMultiMetricChart"
      >
        <i class="fas" :class="multiMetricLoading ? 'fa-spinner fa-spin' : 'fa-sync'"></i> Refresh
      </button>

      <button
        v-if="multiMetrics.length > 0"
        class="btn btn-primary btn-sm"
        @click="saveDashId = null; saveDashName = ''; saveDashShared = false; showSaveDashModal = true"
      >
        <i class="fas fa-save"></i> Save Dashboard
      </button>
    </div>

    <!-- Chart canvas -->
    <div style="position:relative;height:400px">
      <ChartWrapper
        v-if="multiChartConfig"
        :config="multiChartConfig"
        style="width:100%;height:100%"
      />
    </div>
    <div
      v-if="multiMetrics.length === 0"
      style="font-size:.75rem;color:var(--text-muted);text-align:center;margin-top:-380px;pointer-events:none"
    >Select metrics above to build a chart.</div>

    <!-- Save Dashboard modal -->
    <AppModal
      :show="showSaveDashModal"
      :title="saveDashId ? 'Edit Dashboard' : 'Save Dashboard'"
      width="380px"
      @close="showSaveDashModal = false"
    >
      <div style="padding:1rem;display:grid;gap:.6rem">
        <label style="font-size:.75rem;font-weight:600">Name
          <input
            v-model="saveDashName"
            class="field-input"
            placeholder="My Dashboard"
            style="margin-top:.2rem"
            @keyup.enter="saveDashboard"
          >
        </label>
        <label style="font-size:.75rem;display:flex;align-items:center;gap:.4rem">
          <input v-model="saveDashShared" type="checkbox"> Share with all users
        </label>
      </div>
      <template #footer>
        <button class="btn" @click="showSaveDashModal = false">Cancel</button>
        <button class="btn btn-primary" @click="saveDashboard">
          {{ saveDashId ? 'Update' : 'Save' }}
        </button>
      </template>
    </AppModal>
  </div>
</template>
