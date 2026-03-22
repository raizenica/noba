<script setup>
import { ref, computed, onMounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useAuthStore }      from '../stores/auth'
import { useApi }            from '../composables/useApi'
import { useNotificationsStore } from '../stores/notifications'

import ServiceList    from '../components/infrastructure/ServiceList.vue'
import K8sBrowser     from '../components/infrastructure/K8sBrowser.vue'
import NetworkDevices from '../components/infrastructure/NetworkDevices.vue'
import ConfigDrift    from '../components/infrastructure/ConfigDrift.vue'
import AppModal       from '../components/ui/AppModal.vue'
import ChartWrapper   from '../components/ui/ChartWrapper.vue'

const dashboardStore = useDashboardStore()
const authStore      = useAuthStore()
const notif          = useNotificationsStore()
const { get, post, del } = useApi()

// ── Active tab ─────────────────────────────────────────────────────────────────
const activeTab = ref('servicemap')

function setTab(tab) {
  activeTab.value = tab
  if (tab === 'servicemap')  fetchServiceMap()
  if (tab === 'topology')    fetchTopology()
  if (tab === 'sync')        fetchSyncStatus()
  if (tab === 'drift')       { /* ConfigDrift handles its own fetch */ }
  if (tab === 'networkmap')  { /* NetworkDevices handles its own fetch */ }
  if (tab === 'traffic' && trafficAgent.value) fetchNetworkStats()
  if (tab === 'predictions') { fetchPredictions(); fetchPredictHealth() }
}

// ── Shared ─────────────────────────────────────────────────────────────────────
const agents   = computed(() => dashboardStore.live.agents || [])
const tailscale = computed(() => dashboardStore.live.tailscale)

// ── Service Map tab ────────────────────────────────────────────────────────────
const serviceMap        = ref(null)
const serviceMapLoading = ref(false)

async function fetchServiceMap() {
  serviceMapLoading.value = true
  try {
    const data = await get('/api/services/map')
    serviceMap.value = data
  } catch { serviceMap.value = null }
  finally { serviceMapLoading.value = false }
}

function nodeStatusClass(status) {
  if (status === 'online' || status === 'active') return 'bs'
  if (status === 'configured') return 'bn'
  if (status === 'inactive')   return 'bw'
  return 'bd'
}

// ── Topology tab ───────────────────────────────────────────────────────────────
const topologyData    = ref(null)
const topologyLoading = ref(false)
const topologyViewMode = ref('graph')
const topologyImpact  = ref(null)
const topologyImpactService = ref('')
const topoNewSource   = ref('')
const topoNewTarget   = ref('')
const topoNewType     = ref('requires')

async function fetchTopology() {
  topologyLoading.value = true
  try {
    const [conn, ports, ifaces] = await Promise.all([
      get('/api/network/connections').catch(() => []),
      get('/api/network/ports').catch(() => []),
      get('/api/network/interfaces').catch(() => []),
    ])
    topologyData.value = { connections: conn, ports, interfaces: ifaces, nodes: [], dependencies: [] }
  } catch { topologyData.value = null }
  finally { topologyLoading.value = false }
}

async function fetchImpactAnalysis(service) {
  if (!service) return
  topologyImpactService.value = service
  try {
    const data = await get(`/api/topology/impact/${encodeURIComponent(service)}`)
    topologyImpact.value = data
  } catch { topologyImpact.value = { affected: [], count: 0 } }
}

async function addDependency() {
  if (!topoNewSource.value.trim() || !topoNewTarget.value.trim()) return
  try {
    await post('/api/topology/dependencies', {
      source_service: topoNewSource.value.trim(),
      target_service: topoNewTarget.value.trim(),
      dependency_type: topoNewType.value,
    })
    notif.addToast('Dependency added', 'success')
    topoNewSource.value = ''
    topoNewTarget.value = ''
    fetchTopology()
  } catch (e) {
    notif.addToast('Failed: ' + e.message, 'error')
  }
}

async function deleteDependency(id) {
  if (!confirm('Delete this dependency?')) return
  try {
    await del(`/api/topology/dependencies/${id}`)
    notif.addToast('Dependency deleted', 'success')
    fetchTopology()
  } catch (e) {
    notif.addToast('Delete failed: ' + e.message, 'error')
  }
}

async function discoverServices(hostname) {
  try {
    await post(`/api/agents/${encodeURIComponent(hostname)}/discover-services`)
    notif.addToast(`Discovery triggered on ${hostname}`, 'success')
  } catch (e) {
    notif.addToast('Discovery failed: ' + e.message, 'error')
  }
}

// ── Cross-Site Sync tab ────────────────────────────────────────────────────────
const syncStatus  = ref(null)
const syncLoading = ref(false)

async function fetchSyncStatus() {
  syncLoading.value = true
  try {
    const data = await get('/api/site-sync/status')
    syncStatus.value = data
  } catch { syncStatus.value = null }
  finally { syncLoading.value = false }
}

// ── Export tab ─────────────────────────────────────────────────────────────────
const iacFormat   = ref('ansible')
const iacHostname = ref('')
const iacLoading  = ref(false)
const iacOutput   = ref('')

async function generateIaC() {
  iacLoading.value = true
  iacOutput.value  = ''
  try {
    const qs = new URLSearchParams({ format: iacFormat.value })
    if (iacHostname.value) qs.set('hostname', iacHostname.value)
    const text = await get(`/api/iac/export?${qs}`)
    iacOutput.value = typeof text === 'string' ? text : JSON.stringify(text, null, 2)
  } catch (e) {
    notif.addToast('Export failed: ' + e.message, 'error')
  }
  iacLoading.value = false
}

function downloadIaC() {
  if (!iacOutput.value) return
  const ext = iacFormat.value === 'docker-compose' ? 'yml' : iacFormat.value === 'ansible' ? 'yml' : 'sh'
  const blob = new Blob([iacOutput.value], { type: 'text/plain' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `noba-export.${ext}`
  a.click()
  URL.revokeObjectURL(url)
}

async function copyIaC() {
  if (!iacOutput.value) return
  try {
    await navigator.clipboard.writeText(iacOutput.value)
    notif.addToast('Copied to clipboard', 'success')
  } catch {
    notif.addToast('Copy failed', 'error')
  }
}

// ── Traffic tab ────────────────────────────────────────────────────────────────
const trafficAgent      = ref('')
const trafficLoading    = ref(false)
const trafficData       = ref(null)
const trafficConnFilter = ref('')

async function fetchNetworkStats() {
  if (!trafficAgent.value) return
  trafficLoading.value = true
  trafficData.value    = null
  try {
    const data = await post(`/api/agents/${encodeURIComponent(trafficAgent.value)}/network-stats`)
    trafficData.value = data
  } catch (e) {
    notif.addToast('Failed: ' + e.message, 'error')
  }
  trafficLoading.value = false
}

function filteredTrafficConns() {
  const conns = trafficData.value?.connections || []
  if (!trafficConnFilter.value) return conns
  const q = trafficConnFilter.value.toLowerCase()
  return conns.filter(c =>
    (c.process || '').toLowerCase().includes(q) ||
    (c.local || '').toLowerCase().includes(q) ||
    (c.remote || '').toLowerCase().includes(q) ||
    (c.state || '').toLowerCase().includes(q)
  )
}

function humanBps(bps) {
  if (!bps) return '0 B/s'
  if (bps < 1024)          return bps.toFixed(0) + ' B/s'
  if (bps < 1048576)       return (bps / 1024).toFixed(1) + ' KB/s'
  if (bps < 1073741824)    return (bps / 1048576).toFixed(1) + ' MB/s'
  return (bps / 1073741824).toFixed(2) + ' GB/s'
}

function humanBytes(b) {
  if (!b) return '0 B'
  if (b < 1024)       return b + ' B'
  if (b < 1048576)    return (b / 1024).toFixed(1) + ' KB'
  if (b < 1073741824) return (b / 1048576).toFixed(1) + ' MB'
  return (b / 1073741824).toFixed(2) + ' GB'
}

function connStateClass(state) {
  if (state === 'ESTAB')  return 'bs'
  if (state === 'LISTEN') return 'bn'
  return 'bw'
}

// ── Predictions tab ────────────────────────────────────────────────────────────
const predMetrics        = ref(['disk_percent'])
const predRange          = ref('30d')
const predProjection     = ref('90d')
const predCapacity       = ref(null)
const predHealth         = ref(null)
const predLoading        = ref(false)
const predHealthLoading  = ref(false)

const metricOptions = [
  { key: 'disk_percent',  label: 'Disk %' },
  { key: 'cpu_percent',   label: 'CPU %' },
  { key: 'mem_percent',   label: 'Memory %' },
]
const rangeOptions      = ['7d', '30d', '90d']
const projectionOptions = ['30d', '90d', '180d']

function togglePredMetric(key) {
  const idx = predMetrics.value.indexOf(key)
  if (idx === -1) {
    predMetrics.value = [...predMetrics.value, key]
  } else if (predMetrics.value.length > 1) {
    predMetrics.value = predMetrics.value.filter(k => k !== key)
  }
  fetchPredictions()
}

async function fetchPredictions() {
  predLoading.value = true
  try {
    const qs = predMetrics.value.map(m => `metrics=${encodeURIComponent(m)}`).join('&')
    predCapacity.value = await get(`/api/predict/capacity?${qs}`)
  } catch { predCapacity.value = null }
  finally { predLoading.value = false }
}

async function fetchPredictHealth() {
  predHealthLoading.value = true
  try {
    predHealth.value = await get('/api/predict/health')
  } catch { predHealth.value = null }
  finally { predHealthLoading.value = false }
}

function predScoreClass(score) {
  if (score == null) return ''
  if (score >= 80) return 'bs'
  if (score >= 60) return 'bw'
  return 'bd'
}

function predScoreColor(score) {
  if (score == null) return 'var(--text-muted)'
  if (score >= 80) return 'var(--success)'
  if (score >= 60) return 'var(--warning)'
  return 'var(--danger)'
}

function formatPct(v) {
  if (v == null) return '—'
  return (v * 100).toFixed(1) + '%'
}

function formatMs(v) {
  if (v == null) return '—'
  return v.toFixed(0) + ' ms'
}

// Build a multi-dataset chart config from predCapacity
const predChartConfig = computed(() => {
  if (!predCapacity.value?.metrics) return null
  const colors = ['var(--accent)', 'var(--success)', 'var(--warning)']
  const datasets = []
  let labels = null

  Object.entries(predCapacity.value.metrics).forEach(([key, info], i) => {
    const points = info.projection || []
    if (!points.length) return
    if (!labels) labels = points.map(p => new Date(p.time * 1000))
    const color = colors[i % colors.length]
    const alpha = 'rgba(0,200,255,0.07)'
    datasets.push(
      {
        label: key.replace(/_/g, ' '),
        data: points.map(p => p.predicted),
        borderColor: color,
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
      },
      {
        label: `${key} 68% band`,
        data: points.map(p => p.upper_68),
        borderColor: 'transparent',
        backgroundColor: alpha,
        pointRadius: 0,
        fill: '+1',
      },
      {
        label: `${key} 68% lower`,
        data: points.map(p => p.lower_68),
        borderColor: 'transparent',
        pointRadius: 0,
        fill: false,
      },
      {
        label: `${key} 95% upper`,
        data: points.map(p => p.upper_95),
        borderDash: [5, 5],
        borderColor: 'rgba(0,200,255,0.25)',
        borderWidth: 1,
        pointRadius: 0,
        fill: false,
      },
      {
        label: `${key} 95% lower`,
        data: points.map(p => p.lower_95),
        borderDash: [5, 5],
        borderColor: 'rgba(0,200,255,0.25)',
        borderWidth: 1,
        pointRadius: 0,
        fill: false,
      },
    )
  })

  if (!labels || !datasets.length) return null

  return {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      scales: {
        x: {
          type: 'category',
          ticks: { color: 'rgba(200,223,240,.6)', maxTicksLimit: 8 },
          grid: { display: false },
        },
        y: {
          min: 0,
          max: 100,
          ticks: { color: 'rgba(200,223,240,.6)', callback: v => v + '%' },
          grid: { color: 'rgba(255,255,255,.06)' },
        },
      },
      plugins: {
        legend: {
          display: true,
          labels: {
            color: 'rgba(200,223,240,.7)',
            filter: item => !item.text.includes('band') && !item.text.includes('lower') && !item.text.includes('upper'),
          },
        },
        tooltip: {
          callbacks: {
            label: ctx => {
              if (ctx.dataset.label?.includes('band') || ctx.dataset.label?.includes('lower') || ctx.dataset.label?.includes('upper')) return null
              return `${ctx.dataset.label}: ${(ctx.parsed.y || 0).toFixed(1)}%`
            },
          },
          filter: item => !item.dataset.label?.includes('band') && !item.dataset.label?.includes('95'),
        },
      },
    },
  }
})

// ── Init ───────────────────────────────────────────────────────────────────────
onMounted(() => {
  fetchServiceMap()
})
</script>

<template>
  <div style="padding:1rem">
    <h2 style="margin-bottom:1rem">
      <i class="fas fa-server" style="margin-right:.5rem"></i> Infrastructure
    </h2>

    <!-- Tab bar -->
    <div class="tab-bar" style="margin-bottom:1rem;display:flex;flex-wrap:wrap;gap:.3rem">
      <button
        class="btn btn-xs"
        :class="activeTab === 'servicemap' ? 'btn-primary' : ''"
        @click="setTab('servicemap')"
      >Service Map</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'services' ? 'btn-primary' : ''"
        @click="setTab('services')"
      >Services</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'topology' ? 'btn-primary' : ''"
        @click="setTab('topology')"
      >Topology</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'k8s' ? 'btn-primary' : ''"
        @click="setTab('k8s')"
      >Kubernetes</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'tailscale' ? 'btn-primary' : ''"
        @click="setTab('tailscale')"
      >Tailscale</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'sync' ? 'btn-primary' : ''"
        @click="setTab('sync')"
      >Cross-Site Sync</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'drift' ? 'btn-primary' : ''"
        @click="setTab('drift')"
      >Config Drift</button>
      <button
        v-if="authStore.isOperator"
        class="btn btn-xs"
        :class="activeTab === 'export' ? 'btn-primary' : ''"
        @click="setTab('export')"
      >Export</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'traffic' ? 'btn-primary' : ''"
        @click="setTab('traffic')"
      >
        <i class="fas fa-chart-area" style="margin-right:.3rem"></i>Traffic
      </button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'networkmap' ? 'btn-primary' : ''"
        @click="setTab('networkmap')"
      >Network Map</button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'predictions' ? 'btn-primary' : ''"
        @click="setTab('predictions')"
      >
        <i class="fas fa-chart-line" style="margin-right:.3rem"></i>Predictions
      </button>
    </div>

    <!-- ── Service Map tab ─────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'servicemap'">
      <div v-if="serviceMapLoading" class="empty-msg">Loading service map...</div>
      <template v-else-if="serviceMap && serviceMap.nodes && serviceMap.nodes.length">
        <div style="display:flex;flex-wrap:wrap;gap:12px;justify-content:center">
          <div
            v-for="node in serviceMap.nodes"
            :key="node.id"
            style="background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:10px 16px;text-align:center;min-width:100px"
            :style="node.id === 'noba' ? 'border-color:var(--accent);box-shadow:0 0 12px var(--accent-dim)' : ''"
          >
            <div style="font-weight:600;font-size:.85rem">{{ node.label || node.id }}</div>
            <span
              class="badge"
              :class="nodeStatusClass(node.status)"
              style="font-size:.6rem;margin-top:4px"
            >{{ node.status }}</span>
            <div style="font-size:.6rem;color:var(--text-dim);margin-top:2px">{{ node.type }}</div>
          </div>
        </div>
      </template>
      <div v-else class="empty-msg">No service map data. Configure integrations to populate.</div>
    </div>

    <!-- ── Services tab ────────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'services'">
      <ServiceList />
    </div>

    <!-- ── Topology tab ────────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'topology'">
      <div style="display:flex;gap:.5rem;margin-bottom:.8rem;flex-wrap:wrap;align-items:center">
        <button
          class="btn btn-xs"
          :class="topologyViewMode === 'graph' ? 'btn-primary' : ''"
          @click="topologyViewMode = 'graph'"
        >Graph View</button>
        <button
          class="btn btn-xs"
          :class="topologyViewMode === 'table' ? 'btn-primary' : ''"
          @click="topologyViewMode = 'table'"
        >Table View</button>
        <button class="btn btn-xs" @click="fetchTopology" :disabled="topologyLoading">
          <i class="fas fa-sync-alt" :class="topologyLoading ? 'fa-spin' : ''"></i> Refresh
        </button>
      </div>

      <!-- Graph view placeholder -->
      <div v-show="topologyViewMode === 'graph'" style="margin-bottom:1rem">
        <div style="border:1px solid var(--border);border-radius:8px;background:var(--surface-2);position:relative;min-height:400px;display:flex;align-items:center;justify-content:center">
          <div style="text-align:center;color:var(--text-dim)">
            <i class="fas fa-project-diagram" style="font-size:2rem;margin-bottom:.5rem;display:block;opacity:.3"></i>
            <div style="font-size:.85rem">
              Network topology graph view
            </div>
            <div style="font-size:.75rem;margin-top:.3rem;opacity:.6">
              Switch to Table View to browse connections
            </div>
          </div>
        </div>
        <!-- Legend -->
        <div style="display:flex;gap:1rem;margin-top:.5rem;font-size:.7rem;color:var(--text-muted);flex-wrap:wrap">
          <span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#22c55e;margin-right:3px"></span>Healthy</span>
          <span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#eab308;margin-right:3px"></span>Warning</span>
          <span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#ef4444;margin-right:3px"></span>Critical</span>
          <span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#6b7280;margin-right:3px"></span>Offline</span>
          <span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#9ca3af;margin-right:3px"></span>Unknown</span>
        </div>
      </div>

      <!-- Table view -->
      <div v-show="topologyViewMode === 'table'" style="margin-bottom:1rem">
        <template v-if="topologyData && topologyData.connections && topologyData.connections.length">
          <table style="width:100%;font-size:.8rem;border-collapse:collapse">
            <thead>
              <tr style="border-bottom:1px solid var(--border)">
                <th style="padding:.4rem;text-align:left">Local</th>
                <th style="padding:.4rem;text-align:left">Remote</th>
                <th style="padding:.4rem;text-align:left">State</th>
                <th style="padding:.4rem;text-align:left">Proto</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(c, idx) in topologyData.connections"
                :key="idx"
                style="border-bottom:1px solid var(--border)"
              >
                <td style="padding:.4rem;font-family:monospace;font-size:.75rem">{{ c.local || '-' }}</td>
                <td style="padding:.4rem;font-family:monospace;font-size:.75rem">{{ c.remote || '-' }}</td>
                <td style="padding:.4rem">
                  <span class="badge" :class="connStateClass(c.state)" style="font-size:.55rem">{{ c.state || '-' }}</span>
                </td>
                <td style="padding:.4rem;font-size:.75rem">{{ c.proto || 'tcp' }}</td>
              </tr>
            </tbody>
          </table>
        </template>
        <template v-else-if="topologyData && topologyData.dependencies && topologyData.dependencies.length">
          <table style="width:100%;font-size:.8rem;border-collapse:collapse">
            <thead>
              <tr style="border-bottom:1px solid var(--border)">
                <th style="padding:.4rem;text-align:left">Source</th>
                <th style="padding:.4rem;text-align:left">Target</th>
                <th style="padding:.4rem;text-align:left">Type</th>
                <th style="padding:.4rem;text-align:left">Auto</th>
                <th v-if="authStore.isAdmin" style="padding:.4rem">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="d in topologyData.dependencies"
                :key="d.id"
                style="border-bottom:1px solid var(--border)"
              >
                <td style="padding:.4rem;cursor:pointer" @click="fetchImpactAnalysis(d.source_service)">{{ d.source_service }}</td>
                <td style="padding:.4rem;cursor:pointer" @click="fetchImpactAnalysis(d.target_service)">{{ d.target_service }}</td>
                <td style="padding:.4rem"><span class="badge bn" style="font-size:.55rem">{{ d.dependency_type }}</span></td>
                <td style="padding:.4rem">
                  <span v-if="d.auto_discovered" class="badge bw" style="font-size:.55rem">auto</span>
                </td>
                <td v-if="authStore.isAdmin" style="padding:.4rem">
                  <button class="btn btn-xs btn-danger" @click="deleteDependency(d.id)">
                    <i class="fas fa-trash"></i>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </template>
        <div v-else class="empty-msg">No connection data. Click Refresh to fetch network connections.</div>
      </div>

      <!-- Impact Analysis Panel -->
      <div v-if="topologyImpact" style="margin-bottom:1rem;padding:.8rem;border:1px solid var(--border);border-radius:8px;background:var(--surface-2)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.4rem">
          <span style="font-weight:600;font-size:.85rem">Impact Analysis: {{ topologyImpactService }}</span>
          <button class="btn btn-xs" @click="topologyImpact = null; topologyImpactService = ''">
            <i class="fas fa-times"></i>
          </button>
        </div>
        <template v-if="topologyImpact.affected && topologyImpact.affected.length">
          <div style="font-size:.75rem;color:var(--text-muted);margin-bottom:.4rem">
            If <strong>{{ topologyImpactService }}</strong> goes down, these {{ topologyImpact.count }} service(s) are affected:
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:.3rem">
            <span v-for="svc in topologyImpact.affected" :key="svc" class="badge bd" style="font-size:.65rem">{{ svc }}</span>
          </div>
        </template>
        <div v-else style="font-size:.75rem;color:var(--text-muted)">
          No other services depend on {{ topologyImpactService }}.
        </div>
      </div>

      <!-- Add Dependency (admin) -->
      <div v-if="authStore.isAdmin" style="padding:.8rem;border:1px solid var(--border);border-radius:8px;background:var(--surface-2);margin-bottom:1rem">
        <div style="font-weight:600;font-size:.85rem;margin-bottom:.5rem">Add Dependency</div>
        <div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:flex-end">
          <div>
            <label style="font-size:.7rem;display:block;margin-bottom:.2rem">Source</label>
            <input
              v-model="topoNewSource"
              type="text"
              placeholder="e.g. nginx"
              style="padding:.3rem .5rem;font-size:.8rem;border:1px solid var(--border);border-radius:4px;background:var(--surface);color:var(--text);width:140px"
            >
          </div>
          <div>
            <label style="font-size:.7rem;display:block;margin-bottom:.2rem">Target</label>
            <input
              v-model="topoNewTarget"
              type="text"
              placeholder="e.g. postgresql"
              style="padding:.3rem .5rem;font-size:.8rem;border:1px solid var(--border);border-radius:4px;background:var(--surface);color:var(--text);width:140px"
            >
          </div>
          <div>
            <label style="font-size:.7rem;display:block;margin-bottom:.2rem">Type</label>
            <select
              v-model="topoNewType"
              style="padding:.3rem .5rem;font-size:.8rem;border:1px solid var(--border);border-radius:4px;background:var(--surface);color:var(--text)"
            >
              <option value="requires">requires</option>
              <option value="optional">optional</option>
              <option value="network">network</option>
            </select>
          </div>
          <button class="btn btn-sm btn-primary" @click="addDependency">
            <i class="fas fa-plus" style="margin-right:.3rem"></i>Add
          </button>
        </div>
      </div>

      <!-- Discover from agents (admin) -->
      <div v-if="authStore.isAdmin && agents.length" style="padding:.8rem;border:1px solid var(--border);border-radius:8px;background:var(--surface-2)">
        <div style="font-weight:600;font-size:.85rem;margin-bottom:.5rem">Discover Services</div>
        <div style="display:flex;flex-wrap:wrap;gap:.4rem">
          <button
            v-for="a in agents"
            :key="a.hostname"
            class="btn btn-xs"
            @click="discoverServices(a.hostname)"
          >
            <i class="fas fa-search" style="margin-right:.3rem"></i>{{ a.hostname }}
          </button>
        </div>
        <div style="font-size:.65rem;color:var(--text-muted);margin-top:.4rem">
          Discover running services and connections on each agent.
        </div>
      </div>
    </div>

    <!-- ── Kubernetes tab ──────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'k8s'">
      <K8sBrowser />
    </div>

    <!-- ── Tailscale tab ───────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'tailscale'">
      <template v-if="tailscale">
        <div class="row" style="margin-bottom:.8rem">
          <span class="row-label">Tailnet</span>
          <span class="row-val">{{ tailscale.tailnet }}</span>
        </div>
        <div class="row" style="margin-bottom:.8rem">
          <span class="row-label">This Node</span>
          <span class="row-val">{{ (tailscale.self?.hostname || '') + ' (' + (tailscale.self?.ip || '') + ')' }}</span>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.6rem">
          <div
            v-for="p in [...(tailscale.peers || [])].sort((a, b) => (b.online ? 1 : 0) - (a.online ? 1 : 0))"
            :key="p.hostname + '-' + (p.ip || '')"
            style="padding:.6rem;border-radius:6px;border:1px solid var(--border);background:var(--surface-2)"
          >
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.3rem">
              <span style="font-weight:600;font-size:.85rem">{{ p.hostname }}</span>
              <span :class="p.online ? 'dot-up' : 'dot-down'" style="font-size:.5rem">&#9679;</span>
            </div>
            <div style="font-size:.7rem;color:var(--text-muted)">
              <div>{{ p.ip }}</div>
              <div>{{ p.os }}</div>
              <div v-if="p.online && p.curAddr">{{ p.direct ? 'Direct' : 'Relay' }}: {{ p.curAddr }}</div>
              <div v-if="p.subnets && p.subnets.length">Routes: {{ p.subnets.join(', ') }}</div>
              <div v-if="!p.online && p.lastSeen">Last seen: {{ new Date(p.lastSeen).toLocaleDateString() }}</div>
            </div>
          </div>
        </div>
      </template>
      <div v-else class="empty-msg">Tailscale not available</div>
    </div>

    <!-- ── Cross-Site Sync tab ─────────────────────────────────────────────── -->
    <div v-show="activeTab === 'sync'">
      <div v-if="syncLoading" class="empty-msg">Loading...</div>
      <template v-else-if="syncStatus">
        <template v-if="syncStatus.services && syncStatus.services.length">
          <table style="width:100%;font-size:.8rem;border-collapse:collapse">
            <thead>
              <tr style="border-bottom:1px solid var(--border)">
                <th style="padding:.4rem;text-align:left">Service</th>
                <th style="padding:.4rem">Sites</th>
                <th style="padding:.4rem">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="s in syncStatus.services"
                :key="s.key"
                style="border-bottom:1px solid var(--border)"
              >
                <td style="padding:.4rem">{{ s.key }}</td>
                <td style="padding:.4rem;font-size:.7rem">{{ Object.keys(s.sites || {}).join(', ') }}</td>
                <td style="padding:.4rem;text-align:center">
                  <span class="badge" :class="s.online ? 'bs' : 'bd'">{{ s.online ? 'online' : 'offline' }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </template>
        <div v-if="syncStatus.message" class="empty-msg">{{ syncStatus.message }}</div>
      </template>
      <div v-else class="empty-msg">No cross-site data available. Configure multiple sites first.</div>
    </div>

    <!-- ── Config Drift tab ────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'drift'">
      <ConfigDrift />
    </div>

    <!-- ── Export tab ──────────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'export'">
      <div style="display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap;align-items:flex-end">
        <div style="display:flex;flex-direction:column;gap:.2rem;min-width:160px">
          <label style="font-size:.7rem;color:var(--text-dim)">Format</label>
          <select
            v-model="iacFormat"
            style="padding:.3rem .5rem;font-size:.8rem;border:1px solid var(--border);border-radius:4px;background:var(--surface-2);color:var(--text)"
          >
            <option value="ansible">Ansible Playbook</option>
            <option value="docker-compose">Docker Compose</option>
            <option value="shell">Shell Script</option>
          </select>
        </div>
        <div style="display:flex;flex-direction:column;gap:.2rem;min-width:160px">
          <label style="font-size:.7rem;color:var(--text-dim)">Agent</label>
          <select
            v-model="iacHostname"
            style="padding:.3rem .5rem;font-size:.8rem;border:1px solid var(--border);border-radius:4px;background:var(--surface-2);color:var(--text)"
          >
            <option value="">All Agents</option>
            <option v-for="a in agents" :key="a.hostname" :value="a.hostname">{{ a.hostname }}</option>
          </select>
        </div>
        <button class="btn btn-sm btn-primary" @click="generateIaC" :disabled="iacLoading">
          <i class="fas fa-file-code" :class="iacLoading ? 'fa-spin' : ''"></i> Generate
        </button>
        <button class="btn btn-sm" @click="downloadIaC" :disabled="!iacOutput" title="Download file">
          <i class="fas fa-download"></i> Download
        </button>
        <button class="btn btn-sm" @click="copyIaC" :disabled="!iacOutput" title="Copy to clipboard">
          <i class="fas fa-copy"></i> Copy
        </button>
      </div>
      <div v-if="iacLoading" class="empty-msg">Generating...</div>
      <div v-else-if="!iacOutput" class="empty-msg">
        Select a format and agent, then click Generate to create an Infrastructure-as-Code export.
      </div>
      <div v-else style="position:relative">
        <pre style="background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:.8rem;font-size:.75rem;line-height:1.5;overflow-x:auto;max-height:600px;overflow-y:auto;font-family:'Fira Code','Cascadia Code',monospace;white-space:pre;tab-size:2;color:var(--text)">{{ iacOutput }}</pre>
      </div>
    </div>

    <!-- ── Traffic tab ─────────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'traffic'">
      <div style="display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap;align-items:flex-end">
        <div style="display:flex;flex-direction:column;gap:.2rem;min-width:160px">
          <label style="font-size:.7rem;color:var(--text-dim)">Agent</label>
          <select
            v-model="trafficAgent"
            style="padding:.3rem .5rem;font-size:.8rem;border:1px solid var(--border);border-radius:4px;background:var(--surface-2);color:var(--text)"
          >
            <option value="">Select agent...</option>
            <option v-for="a in agents" :key="a.hostname" :value="a.hostname">{{ a.hostname }}</option>
          </select>
        </div>
        <button
          class="btn btn-sm btn-primary"
          @click="fetchNetworkStats"
          :disabled="!trafficAgent || trafficLoading"
        >
          <i class="fas fa-sync-alt" :class="trafficLoading ? 'fa-spin' : ''"></i> Refresh
        </button>
      </div>

      <div v-if="!trafficAgent" class="empty-msg">Select an agent to view network traffic analysis.</div>
      <div v-else-if="trafficLoading" class="empty-msg">Loading network stats...</div>
      <div v-else-if="trafficData">
        <!-- Interfaces -->
        <h3 style="font-size:.9rem;margin-bottom:.5rem;font-weight:600">
          <i class="fas fa-network-wired" style="margin-right:.3rem"></i> Interfaces
        </h3>
        <div style="overflow-x:auto;margin-bottom:1.5rem">
          <table style="width:100%;font-size:.8rem;border-collapse:collapse">
            <thead>
              <tr style="border-bottom:2px solid var(--border)">
                <th style="padding:.4rem;text-align:left">Interface</th>
                <th style="padding:.4rem;text-align:right">RX Rate</th>
                <th style="padding:.4rem;text-align:right">TX Rate</th>
                <th style="padding:.4rem;text-align:right">Total RX</th>
                <th style="padding:.4rem;text-align:right">Total TX</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="iface in (trafficData.interfaces || [])"
                :key="iface.name"
                style="border-bottom:1px solid var(--border)"
              >
                <td style="padding:.4rem;font-weight:600;font-family:monospace">{{ iface.name }}</td>
                <td style="padding:.4rem;text-align:right;color:var(--success)">{{ humanBps(iface.rx_rate || 0) }}</td>
                <td style="padding:.4rem;text-align:right;color:var(--accent)">{{ humanBps(iface.tx_rate || 0) }}</td>
                <td style="padding:.4rem;text-align:right">{{ humanBytes(iface.rx_bytes || 0) }}</td>
                <td style="padding:.4rem;text-align:right">{{ humanBytes(iface.tx_bytes || 0) }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="!trafficData.interfaces || trafficData.interfaces.length === 0" class="empty-msg">No interface data available.</div>
        </div>

        <!-- Top Talkers -->
        <h3 style="font-size:.9rem;margin-bottom:.5rem;font-weight:600">
          <i class="fas fa-fire" style="margin-right:.3rem"></i> Top Talkers
        </h3>
        <div style="display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1.5rem">
          <div
            v-for="t in (trafficData.top_talkers || [])"
            :key="t.process"
            style="padding:.4rem .8rem;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);font-size:.8rem;display:flex;align-items:center;gap:.4rem"
          >
            <span style="font-weight:600">{{ t.process }}</span>
            <span class="badge bn" style="font-size:.6rem">{{ t.connections }} conn</span>
          </div>
          <div v-if="!trafficData.top_talkers || trafficData.top_talkers.length === 0" class="empty-msg" style="width:100%">No active process connections detected.</div>
        </div>

        <!-- Connections -->
        <h3 style="font-size:.9rem;margin-bottom:.5rem;font-weight:600">
          <i class="fas fa-plug" style="margin-right:.3rem"></i> Connections
        </h3>
        <div style="display:flex;gap:.5rem;margin-bottom:.5rem;flex-wrap:wrap">
          <input
            v-model="trafficConnFilter"
            type="text"
            placeholder="Filter by process, address, state..."
            style="padding:.3rem .5rem;font-size:.8rem;border:1px solid var(--border);border-radius:4px;background:var(--surface-2);color:var(--text);flex:1;min-width:200px"
          >
        </div>
        <div style="overflow-x:auto;max-height:400px;overflow-y:auto">
          <table style="width:100%;font-size:.75rem;border-collapse:collapse">
            <thead style="position:sticky;top:0;background:var(--surface)">
              <tr style="border-bottom:2px solid var(--border)">
                <th style="padding:.3rem;text-align:left">PID</th>
                <th style="padding:.3rem;text-align:left">Process</th>
                <th style="padding:.3rem;text-align:left">Local</th>
                <th style="padding:.3rem;text-align:left">Remote</th>
                <th style="padding:.3rem;text-align:center">State</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="conn in filteredTrafficConns()"
                :key="(conn.pid || '') + conn.local + conn.remote"
                style="border-bottom:1px solid var(--border)"
              >
                <td style="padding:.3rem;font-family:monospace">{{ conn.pid || '-' }}</td>
                <td style="padding:.3rem;font-weight:600">{{ conn.process || '-' }}</td>
                <td style="padding:.3rem;font-family:monospace;font-size:.7rem">{{ conn.local }}</td>
                <td style="padding:.3rem;font-family:monospace;font-size:.7rem">{{ conn.remote }}</td>
                <td style="padding:.3rem;text-align:center">
                  <span class="badge" :class="connStateClass(conn.state)" style="font-size:.55rem">{{ conn.state }}</span>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="!trafficData.connections || trafficData.connections.length === 0" class="empty-msg">No TCP connections found.</div>
        </div>
      </div>
    </div>

    <!-- ── Network Map tab ─────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'networkmap'">
      <NetworkDevices />
    </div>

    <!-- ── Predictions tab ─────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'predictions'">

      <!-- Controls row -->
      <div style="display:flex;flex-wrap:wrap;gap:1rem;margin-bottom:1rem;align-items:flex-start">

        <!-- Metric checkboxes -->
        <div>
          <div style="font-size:.7rem;color:var(--text-dim);margin-bottom:.3rem">Metrics</div>
          <div style="display:flex;gap:.5rem;flex-wrap:wrap">
            <label
              v-for="m in metricOptions"
              :key="m.key"
              style="display:flex;align-items:center;gap:.3rem;font-size:.8rem;cursor:pointer;padding:.25rem .5rem;border:1px solid var(--border);border-radius:4px;background:var(--surface-2)"
              :style="predMetrics.includes(m.key) ? 'border-color:var(--accent);background:var(--accent-dim,rgba(0,200,255,.08))' : ''"
            >
              <input
                type="checkbox"
                :checked="predMetrics.includes(m.key)"
                @change="togglePredMetric(m.key)"
                style="accent-color:var(--accent)"
              >
              {{ m.label }}
            </label>
          </div>
        </div>

        <!-- Range buttons -->
        <div>
          <div style="font-size:.7rem;color:var(--text-dim);margin-bottom:.3rem">History range</div>
          <div style="display:flex;gap:.3rem">
            <button
              v-for="r in rangeOptions"
              :key="r"
              class="btn btn-xs"
              :class="predRange === r ? 'btn-primary' : ''"
              @click="predRange = r; fetchPredictions()"
            >{{ r }}</button>
          </div>
        </div>

        <!-- Projection buttons -->
        <div>
          <div style="font-size:.7rem;color:var(--text-dim);margin-bottom:.3rem">Projection</div>
          <div style="display:flex;gap:.3rem">
            <button
              v-for="p in projectionOptions"
              :key="p"
              class="btn btn-xs"
              :class="predProjection === p ? 'btn-primary' : ''"
              @click="predProjection = p; fetchPredictions()"
            >{{ p }}</button>
          </div>
        </div>

        <!-- Refresh -->
        <div style="align-self:flex-end">
          <button
            class="btn btn-xs btn-secondary"
            :disabled="predLoading"
            @click="fetchPredictions(); fetchPredictHealth()"
          >
            <i class="fas fa-sync-alt" :class="predLoading ? 'fa-spin' : ''"></i> Refresh
          </button>
        </div>
      </div>

      <!-- Full-size chart -->
      <div v-if="predLoading" class="empty-msg">Loading predictions...</div>
      <div v-else-if="predChartConfig" style="position:relative;height:320px;margin-bottom:1.5rem">
        <ChartWrapper :config="predChartConfig" style="width:100%;height:100%" />
      </div>
      <div v-else class="empty-msg" style="margin-bottom:1.5rem">
        No prediction data available. Ensure there is enough history to generate projections.
      </div>

      <!-- Per-service health table -->
      <div>
        <h3 style="font-size:.9rem;font-weight:600;margin-bottom:.6rem">
          <i class="fas fa-heartbeat" style="margin-right:.3rem;color:var(--accent)"></i>
          Service Health Scores
        </h3>

        <div v-if="predHealthLoading" class="empty-msg">Loading health scores...</div>

        <template v-else-if="predHealth && predHealth.services && predHealth.services.length">
          <!-- Overall score summary -->
          <div
            style="display:flex;align-items:center;gap:.75rem;padding:.6rem .8rem;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);margin-bottom:.75rem"
          >
            <span style="font-size:1.3rem;font-weight:700" :style="'color:' + predScoreColor(predHealth.overall)">
              {{ predHealth.overall != null ? predHealth.overall.toFixed(0) : '—' }}
            </span>
            <div>
              <div style="font-size:.8rem;font-weight:600">Overall Health</div>
              <div style="font-size:.7rem;color:var(--text-muted)">
                Grade:
                <span class="badge" :class="predScoreClass(predHealth.overall)" style="font-size:.6rem">
                  {{ predHealth.grade || '—' }}
                </span>
              </div>
            </div>
          </div>

          <!-- Service rows -->
          <div style="overflow-x:auto">
            <table style="width:100%;font-size:.78rem;border-collapse:collapse">
              <thead style="position:sticky;top:0;background:var(--surface)">
                <tr style="border-bottom:2px solid var(--border)">
                  <th style="padding:.4rem;text-align:left">Service</th>
                  <th style="padding:.4rem;text-align:center">Score</th>
                  <th style="padding:.4rem;text-align:right">Uptime</th>
                  <th style="padding:.4rem;text-align:right">Latency</th>
                  <th style="padding:.4rem;text-align:right">Error rate</th>
                  <th style="padding:.4rem;text-align:right">Headroom</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="svc in predHealth.services"
                  :key="svc.name"
                  style="border-bottom:1px solid var(--border)"
                >
                  <td style="padding:.4rem;font-weight:600">{{ svc.name }}</td>
                  <td style="padding:.4rem;text-align:center">
                    <span
                      class="badge"
                      :class="predScoreClass(svc.composite_score)"
                      style="font-size:.65rem;min-width:36px;display:inline-block;text-align:center"
                    >{{ svc.composite_score != null ? svc.composite_score.toFixed(0) : '—' }}</span>
                    <span
                      v-if="svc.grade"
                      style="font-size:.65rem;color:var(--text-muted);margin-left:.3rem"
                    >{{ svc.grade }}</span>
                  </td>
                  <td style="padding:.4rem;text-align:right">{{ formatPct(svc.uptime_ratio) }}</td>
                  <td style="padding:.4rem;text-align:right">{{ formatMs(svc.avg_latency_ms) }}</td>
                  <td style="padding:.4rem;text-align:right">
                    <span :style="(svc.error_rate || 0) > 0.05 ? 'color:var(--danger)' : ''">
                      {{ formatPct(svc.error_rate) }}
                    </span>
                  </td>
                  <td style="padding:.4rem;text-align:right">
                    <span :style="(svc.headroom || 1) < 0.2 ? 'color:var(--warning)' : ''">
                      {{ formatPct(svc.headroom) }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>

        <div v-else class="empty-msg">No service health data available.</div>
      </div>
    </div>
  </div>
</template>
