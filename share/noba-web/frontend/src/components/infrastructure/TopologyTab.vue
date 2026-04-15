<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'
import { useDashboardStore } from '../../stores/dashboard'
import { useNotificationsStore } from '../../stores/notifications'
import { useModalsStore } from '../../stores/modals'

const { get, post, del } = useApi()
const authStore      = useAuthStore()
const dashboardStore = useDashboardStore()
const notif          = useNotificationsStore()
const modals         = useModalsStore()

const agents = computed(() => dashboardStore.live.agents || [])

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
    const data = await get(`/api/dependencies/impact/${encodeURIComponent(service)}`)
    topologyImpact.value = data
  } catch { topologyImpact.value = { affected: [], count: 0 } }
}

async function addDependency() {
  if (!topoNewSource.value.trim() || !topoNewTarget.value.trim()) return
  try {
    await post('/api/dependencies', {
      source: topoNewSource.value.trim(),
      target: topoNewTarget.value.trim(),
      type: topoNewType.value,
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
  if (!await modals.confirm('Delete this dependency?')) return
  try {
    await del(`/api/dependencies/${id}`)
    notif.addToast('Dependency deleted', 'success')
    fetchTopology()
  } catch (e) {
    notif.addToast('Delete failed: ' + e.message, 'error')
  }
}

async function discoverServices(hostname) {
  try {
    await post(`/api/dependencies/discover/${encodeURIComponent(hostname)}`)
    notif.addToast(`Discovery triggered on ${hostname}`, 'success')
  } catch (e) {
    notif.addToast('Discovery failed: ' + e.message, 'error')
  }
}

function connStateClass(state) {
  if (state === 'ESTAB')  return 'bs'
  if (state === 'LISTEN') return 'bn'
  return 'bw'
}

defineExpose({ fetchTopology })
</script>

<template>
  <div>
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
      <div style="border:1px solid var(--border);border-radius:8px;background:var(--surface-2);position:relative;min-height:400px;display:flex;align-items:center;justify-content:center;overflow:hidden">
        <div style="position:absolute;top:10px;right:10px;display:flex;gap:4px;opacity:0.6;pointer-events:none">
          <button class="btn btn-xs btn-secondary" title="Zoom In"><i class="fas fa-search-plus"></i></button>
          <button class="btn btn-xs btn-secondary" title="Zoom Out"><i class="fas fa-search-minus"></i></button>
          <button class="btn btn-xs btn-secondary" title="Reset View"><i class="fas fa-compress-arrows-alt"></i></button>
        </div>
        <div style="text-align:center;color:var(--text-dim);max-width:400px">
          <i class="fas fa-project-diagram" style="font-size:2rem;margin-bottom:1rem;display:block;opacity:.3"></i>
          <div style="font-size:.9rem;font-weight:600;color:var(--text)">Topology Canvas</div>
          <div style="font-size:.8rem;margin-top:.5rem;opacity:.8;line-height:1.4">
            Graph visualization is currently under development. To map your infrastructure, run network discovery on your agents, then switch to <strong>Table View</strong> to browse the raw connection matrix and open ports.
          </div>
          <button class="btn btn-primary btn-sm" style="margin-top:1.5rem" @click="topologyViewMode = 'table'">
            Go to Table View
          </button>
        </div>
      </div>
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
            <tr class="border-b">
              <th class="td-left">Local</th>
              <th class="td-left">Remote</th>
              <th class="td-left">State</th>
              <th class="td-left">Proto</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(c, idx) in topologyData.connections"
              :key="idx"
              class="border-b"
            >
              <td class="td-cell" style="font-family:monospace;font-size:.75rem">{{ c.local || '-' }}</td>
              <td class="td-cell" style="font-family:monospace;font-size:.75rem">{{ c.remote || '-' }}</td>
              <td class="td-cell">
                <span class="badge" :class="connStateClass(c.state)" style="font-size:.55rem">{{ c.state || '-' }}</span>
              </td>
              <td class="td-cell" style="font-size:.75rem">{{ c.proto || 'tcp' }}</td>
            </tr>
          </tbody>
        </table>
      </template>
      <template v-else-if="topologyData && topologyData.dependencies && topologyData.dependencies.length">
        <table style="width:100%;font-size:.8rem;border-collapse:collapse">
          <thead>
            <tr class="border-b">
              <th class="td-left">Source</th>
              <th class="td-left">Target</th>
              <th class="td-left">Type</th>
              <th class="td-left">Auto</th>
              <th v-if="authStore.isAdmin" class="td-cell">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="d in topologyData.dependencies"
              :key="d.id"
              class="border-b"
            >
              <td class="td-cell" style="cursor:pointer" @click="fetchImpactAnalysis(d.source_service)">{{ d.source_service }}</td>
              <td class="td-cell" style="cursor:pointer" @click="fetchImpactAnalysis(d.target_service)">{{ d.target_service }}</td>
              <td class="td-cell"><span class="badge bn text-xs">{{ d.dependency_type }}</span></td>
              <td class="td-cell">
                <span v-if="d.auto_discovered" class="badge bw text-xs">auto</span>
              </td>
              <td v-if="authStore.isAdmin" class="td-cell">
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
          <i class="fas fa-plus mr-sm"></i>Add
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
          <i class="fas fa-search mr-sm"></i>{{ a.hostname }}
        </button>
      </div>
      <div style="font-size:.65rem;color:var(--text-muted);margin-top:.4rem">
        Discover running services and connections on each agent.
      </div>
    </div>
  </div>
</template>
