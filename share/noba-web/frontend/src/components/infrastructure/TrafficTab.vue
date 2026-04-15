<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useApi } from '../../composables/useApi'
import { useDashboardStore } from '../../stores/dashboard'
import { useNotificationsStore } from '../../stores/notifications'

const { post } = useApi()
const dashboardStore = useDashboardStore()
const notif          = useNotificationsStore()

const agents = computed(() => dashboardStore.live.agents || [])

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

defineExpose({ fetchNetworkStats })
</script>

<template>
  <div>
    <div style="display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap;align-items:flex-end">
      <div style="display:flex;flex-direction:column;gap:.2rem;min-width:160px">
        <label class="field-label">Agent</label>
        <select
          v-model="trafficAgent"
          class="field-select"
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
        <i class="fas fa-network-wired mr-sm"></i> Interfaces
      </h3>
      <div style="overflow-x:auto;margin-bottom:1.5rem">
        <table style="width:100%;font-size:.8rem;border-collapse:collapse">
          <thead>
            <tr style="border-bottom:2px solid var(--border)">
              <th class="td-left">Interface</th>
              <th class="td-right">RX Rate</th>
              <th class="td-right">TX Rate</th>
              <th class="td-right">Total RX</th>
              <th class="td-right">Total TX</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="iface in (trafficData.interfaces || [])"
              :key="iface.name"
              class="border-b"
            >
              <td class="td-cell" style="font-weight:600;font-family:monospace">{{ iface.name }}</td>
              <td class="td-right" style="color:var(--success)">{{ humanBps(iface.rx_rate || 0) }}</td>
              <td class="td-right" style="color:var(--accent)">{{ humanBps(iface.tx_rate || 0) }}</td>
              <td class="td-right">{{ humanBytes(iface.rx_bytes || 0) }}</td>
              <td class="td-right">{{ humanBytes(iface.tx_bytes || 0) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!trafficData.interfaces || trafficData.interfaces.length === 0" class="empty-msg">No interface data available.</div>
      </div>

      <!-- Top Talkers -->
      <h3 style="font-size:.9rem;margin-bottom:.5rem;font-weight:600">
        <i class="fas fa-fire mr-sm"></i> Top Talkers
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
        <i class="fas fa-plug mr-sm"></i> Connections
      </h3>
      <div style="display:flex;gap:.5rem;margin-bottom:.5rem;flex-wrap:wrap">
        <input
          v-model="trafficConnFilter"
          type="text"
          class="field-input"
          placeholder="Filter by process, address, state..."
          style="flex:1;min-width:200px"
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
              class="border-b"
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
</template>
