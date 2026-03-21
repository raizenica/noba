<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useApi } from '../composables/useApi'
import { useSettingsStore } from '../stores/settings'
import { useNotificationsStore } from '../stores/notifications'
import { Chart, registerables } from 'chart.js'

import SlaTable     from '../components/monitoring/SlaTable.vue'
import IncidentList from '../components/monitoring/IncidentList.vue'
import EndpointTable from '../components/monitoring/EndpointTable.vue'
import AppModal     from '../components/ui/AppModal.vue'

Chart.register(...registerables)

const { get, post, del } = useApi()
const settingsStore = useSettingsStore()
const notif         = useNotificationsStore()

// ── Active tab ────────────────────────────────────────────────────────────────
const activeTab = ref('sla')

function setTab(tab) {
  activeTab.value = tab
  if (tab === 'correlation' && correlateMetrics.value.trim()) {
    nextTick(() => renderCorrelationChart())
  }
  if (tab === 'charts') {
    fetchAvailableMetrics()
    fetchDashboards()
    if (multiMetrics.value.length) fetchMultiMetricChart()
  }
  if (tab === 'influxdb' && influxResults.value.length) {
    nextTick(() => renderInfluxChart())
  }
}

// ── Correlation tab ───────────────────────────────────────────────────────────
const correlateMetrics = ref('cpu_percent,mem_percent')
const correlateHours   = ref(24)
const correlateLoading = ref(false)
const correlateData    = ref(null)
let   _correlateChart  = null
const correlateCanvas  = ref(null)

async function fetchCorrelation() {
  if (!correlateMetrics.value.trim()) return
  correlateLoading.value = true
  try {
    const data = await get(
      `/api/metrics/correlate?metrics=${encodeURIComponent(correlateMetrics.value)}&hours=${correlateHours.value}`
    )
    correlateData.value = data
    await nextTick()
    renderCorrelationChart()
  } catch (e) {
    notif.addToast('Correlation error: ' + e.message, 'error')
  } finally {
    correlateLoading.value = false
  }
}

function renderCorrelationChart() {
  if (!correlateCanvas.value || !correlateData.value) return
  if (_correlateChart) { _correlateChart.destroy(); _correlateChart = null }
  const colors   = ['#00c8ff','#00e676','#ffb300','#ff1744','#ab47bc','#26c6da','#ff7043','#66bb6a']
  const datasets = []
  let i = 0
  for (const [name, points] of Object.entries(correlateData.value)) {
    datasets.push({
      label: name,
      data: points.map(p => ({ x: p.time * 1000, y: p.value })),
      borderColor: colors[i % colors.length],
      borderWidth: 1.5,
      pointRadius: 0,
      fill: false,
      tension: 0.3,
    })
    i++
  }
  _correlateChart = new Chart(correlateCanvas.value.getContext('2d'), {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
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
  })
}

// ── Graylog tab ───────────────────────────────────────────────────────────────
const graylogQuery   = ref('')
const graylogLoading = ref(false)
const graylogResults = ref(null)

async function searchGraylog() {
  graylogLoading.value = true
  try {
    const data = await get(
      `/api/graylog/search?q=${encodeURIComponent(graylogQuery.value)}&hours=1`
    )
    graylogResults.value = data
  } catch { /* silent */ }
  finally { graylogLoading.value = false }
}

// ── InfluxDB tab ──────────────────────────────────────────────────────────────
const influxQuery   = ref('')
const influxLoading = ref(false)
const influxResults = ref([])
let   _influxChart  = null
const influxCanvas  = ref(null)

async function runInfluxQuery() {
  if (!influxQuery.value.trim()) return
  influxLoading.value = true
  try {
    const data = await post('/api/influxdb/query', { query: influxQuery.value })
    influxResults.value = Array.isArray(data) ? data : []
    await nextTick()
    renderInfluxChart()
  } catch (e) {
    notif.addToast('Query error: ' + e.message, 'error')
  } finally {
    influxLoading.value = false }
}

function influxTableKeys() {
  if (!influxResults.value.length) return []
  return Object.keys(influxResults.value[0] || {})
}

function renderInfluxChart() {
  if (!influxCanvas.value || !influxResults.value.length) return
  if (_influxChart) { _influxChart.destroy(); _influxChart = null }
  const rows = influxResults.value
  const valueKey = Object.keys(rows[0] || {}).find(k => k === '_value' || k === 'value') || null
  const timeKey  = Object.keys(rows[0] || {}).find(k => k === '_time'  || k === 'time')  || null
  if (!valueKey) return
  const labels = timeKey ? rows.map(r => r[timeKey]) : rows.map((_, i) => i)
  const values = rows.map(r => parseFloat(r[valueKey]) || 0)
  _influxChart = new Chart(influxCanvas.value.getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: valueKey,
        data: values,
        borderColor: '#00c8ff',
        backgroundColor: 'rgba(0,200,255,.1)',
        borderWidth: 1.5,
        pointRadius: 0,
        fill: true,
        tension: 0.3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      scales: {
        x: { ticks: { color: 'rgba(255,255,255,.5)', maxTicksLimit: 8 }, grid: { color: 'rgba(255,255,255,.05)' } },
        y: { ticks: { color: 'rgba(255,255,255,.5)' }, grid: { color: 'rgba(255,255,255,.05)' } },
      },
      plugins: { legend: { labels: { color: 'rgba(255,255,255,.7)' } } },
    },
  })
}

// ── Custom Charts tab ─────────────────────────────────────────────────────────
const availableMetrics  = ref([])
const multiMetrics      = ref([])
const historyRange      = ref(24)
const multiMetricData   = ref({})
const multiMetricLoading = ref(false)
let   _multiChart       = null
const multiCanvas       = ref(null)

// Saved dashboards
const savedDashboards       = ref([])
const showSaveDashModal     = ref(false)
const saveDashId            = ref(null)
const saveDashName          = ref('')
const saveDashShared        = ref(false)

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
    await nextTick()
    renderMultiChart()
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

function renderMultiChart() {
  if (!multiCanvas.value) return
  if (_multiChart) { _multiChart.destroy(); _multiChart = null }
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
  _multiChart = new Chart(multiCanvas.value.getContext('2d'), {
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
  })
}

const selectableMetrics = computed(() =>
  availableMetrics.value.filter(m => m.type === 'history' || m.type === 'number')
)

// ── Saved dashboards ──────────────────────────────────────────────────────────
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
    if (config.range)      historyRange.value = config.range
    activeTab.value = 'charts'
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
    metrics:    [...multiMetrics.value],
    range:      historyRange.value,
  }
  const body   = { name, config_json: JSON.stringify(config), shared: saveDashShared.value }
  const isEdit = !!saveDashId.value
  try {
    if (isEdit) {
      await post(`/api/dashboards/${saveDashId.value}`, body)    // PUT or POST per API
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
  if (!confirm(`Delete dashboard "${name}"?`)) return
  try {
    await del(`/api/dashboards/${id}`)
    notif.addToast('Dashboard deleted', 'success')
    await fetchDashboards()
  } catch (e) {
    notif.addToast('Error: ' + e.message, 'error')
  }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  // SLA tab is default — SlaTable fetches on its own mount
})
</script>

<template>
  <div>
    <!-- Page header -->
    <h2 style="margin-bottom:1rem">
      <i class="fas fa-chart-line" style="margin-right:.5rem;color:var(--accent)"></i>
      Monitoring
    </h2>

    <!-- Tab bar -->
    <div class="tab-bar" style="margin-bottom:1rem;display:flex;flex-wrap:wrap;gap:.3rem">
      <button
        class="btn btn-xs"
        :class="activeTab === 'sla' ? 'btn-primary' : ''"
        @click="setTab('sla')"
      >SLA</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'incidents' ? 'btn-primary' : ''"
        @click="setTab('incidents')"
      >Incidents</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'correlation' ? 'btn-primary' : ''"
        @click="setTab('correlation')"
      >Correlation</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'graylog' ? 'btn-primary' : ''"
        @click="setTab('graylog')"
      >Graylog</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'influxdb' ? 'btn-primary' : ''"
        @click="setTab('influxdb')"
      >InfluxDB</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'charts' ? 'btn-primary' : ''"
        @click="setTab('charts')"
      >Custom Charts</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'endpoints' ? 'btn-primary' : ''"
        @click="setTab('endpoints')"
      >Endpoints</button>
    </div>

    <!-- ── SLA tab ─────────────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'sla'">
      <SlaTable />
    </div>

    <!-- ── Incidents tab ──────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'incidents'">
      <IncidentList />
    </div>

    <!-- ── Correlation tab ────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'correlation'">
      <div style="display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap">
        <input
          v-model="correlateMetrics"
          class="field-input"
          placeholder="cpu_percent,mem_percent,net_rx_bytes (comma-separated)"
          style="flex:1;font-size:.8rem;min-width:200px"
        >
        <select
          v-model.number="correlateHours"
          class="field-select"
          style="width:80px"
        >
          <option :value="1">1h</option>
          <option :value="6">6h</option>
          <option :value="24">24h</option>
          <option :value="72">3d</option>
          <option :value="168">7d</option>
        </select>
        <button
          class="btn btn-primary btn-sm"
          :disabled="correlateLoading || !correlateMetrics.trim()"
          @click="fetchCorrelation"
        >
          <i class="fas" :class="correlateLoading ? 'fa-spinner fa-spin' : 'fa-play'"></i>
        </button>
      </div>
      <div style="position:relative;height:300px">
        <canvas ref="correlateCanvas" style="width:100%;height:100%"></canvas>
      </div>
      <div v-if="!correlateData" style="font-size:.75rem;color:var(--text-muted);text-align:center;margin-top:.5rem">
        Enter metric names and click run to render the correlation chart.
      </div>
    </div>

    <!-- ── Graylog tab ────────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'graylog'">
      <!-- If graylogUrl is configured, show link/iframe -->
      <div v-if="settingsStore.data.graylogUrl" style="margin-bottom:1rem;display:flex;align-items:center;gap:.5rem">
        <i class="fas fa-external-link-alt" style="color:var(--accent)"></i>
        <a
          :href="settingsStore.data.graylogUrl"
          target="_blank"
          rel="noopener"
          style="color:var(--accent);font-size:.85rem"
        >Open Graylog</a>
      </div>

      <!-- Search panel -->
      <div style="display:flex;gap:.5rem;margin-bottom:1rem">
        <input
          v-model="graylogQuery"
          class="field-input"
          placeholder="Search query..."
          style="flex:1;font-size:.8rem"
          @keyup.enter="searchGraylog"
        >
        <button
          class="btn btn-primary btn-sm"
          :disabled="graylogLoading"
          @click="searchGraylog"
        >
          <i class="fas" :class="graylogLoading ? 'fa-spinner fa-spin' : 'fa-search'"></i>
        </button>
      </div>

      <div v-if="graylogLoading" class="empty-msg">Searching...</div>

      <template v-else-if="graylogResults">
        <div style="font-size:.7rem;color:var(--text-muted);margin-bottom:.5rem">
          {{ graylogResults.total || 0 }} results
        </div>
        <div style="max-height:400px;overflow-y:auto">
          <div
            v-for="(msg, i) in (graylogResults.messages || [])"
            :key="i"
            style="padding:.4rem;border-bottom:1px solid var(--border);font-size:.75rem"
          >
            <div style="display:flex;justify-content:space-between">
              <span style="color:var(--accent)">{{ msg.source }}</span>
              <span style="color:var(--text-muted);font-size:.65rem">{{ msg.timestamp }}</span>
            </div>
            <div style="margin-top:.2rem;word-break:break-word">{{ msg.message }}</div>
          </div>
          <div
            v-if="!(graylogResults.messages || []).length"
            class="empty-msg"
          >No results found.</div>
        </div>
      </template>

      <div v-else-if="!settingsStore.data.graylogUrl" class="empty-msg">
        Configure Graylog URL in Settings to enable integration, or use the search above.
      </div>
    </div>

    <!-- ── InfluxDB tab ───────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'influxdb'">
      <textarea
        v-model="influxQuery"
        class="field-input"
        rows="4"
        placeholder='from(bucket:"default") |> range(start: -1h) |> filter(fn: (r) => r._measurement == "cpu")'
        style="font-family:monospace;font-size:.8rem;resize:vertical;width:100%;box-sizing:border-box"
      ></textarea>
      <div style="margin-top:.5rem;display:flex;gap:.5rem;align-items:center">
        <button
          class="btn btn-primary btn-sm"
          :disabled="influxLoading || !influxQuery.trim()"
          @click="runInfluxQuery"
        >
          <i class="fas" :class="influxLoading ? 'fa-spinner fa-spin' : 'fa-play'"></i>
          {{ influxLoading ? 'Running...' : 'Run Query' }}
        </button>
        <span
          v-if="influxResults.length"
          style="font-size:.7rem;color:var(--text-muted)"
        >{{ influxResults.length }} rows</span>
      </div>

      <!-- Chart area -->
      <div style="margin-top:.8rem;position:relative;height:200px">
        <canvas ref="influxCanvas" style="width:100%;height:100%"></canvas>
      </div>

      <!-- Results table -->
      <div
        v-if="influxResults.length > 0"
        style="margin-top:.5rem;max-height:200px;overflow:auto;font-size:.7rem"
      >
        <table style="width:100%;border-collapse:collapse">
          <thead>
            <tr style="border-bottom:1px solid var(--border)">
              <th
                v-for="key in influxTableKeys()"
                :key="key"
                style="padding:.2rem .4rem;text-align:left"
              >{{ key }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, i) in influxResults.slice(0, 50)"
              :key="i"
              style="border-bottom:1px solid var(--border)"
            >
              <td
                v-for="key in influxTableKeys()"
                :key="key"
                style="padding:.2rem .4rem"
              >{{ row[key] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ── Custom Charts tab ──────────────────────────────────────────────── -->
    <div v-show="activeTab === 'charts'">
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
        <!-- Selected metric chips -->
        <span
          v-for="m in multiMetrics"
          :key="m"
          class="badge bs"
          style="cursor:pointer"
          @click="removeMetric(m)"
        >
          {{ m }} <i class="fas fa-times" style="margin-left:4px;font-size:.6rem"></i>
        </span>

        <!-- Add metric select -->
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

        <!-- Range select -->
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
        <canvas ref="multiCanvas" style="width:100%;height:100%"></canvas>
      </div>
      <div
        v-if="multiMetrics.length === 0"
        style="font-size:.75rem;color:var(--text-muted);text-align:center;margin-top:-380px;pointer-events:none"
      >Select metrics above to build a chart.</div>
    </div>

    <!-- ── Endpoints tab ──────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'endpoints'">
      <EndpointTable />
    </div>

    <!-- ── Save Dashboard modal ───────────────────────────────────────────── -->
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
