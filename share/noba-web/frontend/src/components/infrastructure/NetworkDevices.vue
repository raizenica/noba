<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'
import { useDashboardStore } from '../../stores/dashboard'
import { useModalsStore } from '../../stores/modals'
import { NETWORK_DISCOVER_FETCH_DELAY_MS } from '../../constants'

const { get, post, del } = useApi()
const authStore      = useAuthStore()
const notif          = useNotificationsStore()
const dashboardStore = useDashboardStore()
const modals         = useModalsStore()

const agents  = computed(() => dashboardStore.live.agents || [])

const devices          = ref([])
const discoverHost     = ref('')
const discoverLoading  = ref(false)
const devicesLoading   = ref(false)

async function fetchDevices() {
  devicesLoading.value = true
  try {
    const data = await get('/api/network/devices')
    devices.value = Array.isArray(data) ? data : (data?.devices || [])
  } catch { devices.value = [] }
  finally { devicesLoading.value = false }
}

async function triggerDiscover() {
  if (!discoverHost.value) return
  discoverLoading.value = true
  try {
    await post(`/api/network/discover/${encodeURIComponent(discoverHost.value)}`)
    notif.addToast(`Discovery started on ${discoverHost.value}`, 'success')
    setTimeout(fetchDevices, NETWORK_DISCOVER_FETCH_DELAY_MS)
  } catch (e) {
    notif.addToast('Discovery failed: ' + e.message, 'error')
  }
  discoverLoading.value = false
}

async function deleteDevice(id) {
  if (!await modals.confirm('Remove this device from the map?')) return
  try {
    await del(`/api/network/devices/${id}`)
    notif.addToast('Device removed', 'success')
    devices.value = devices.value.filter(d => d.id !== id)
  } catch (e) {
    notif.addToast('Delete failed: ' + e.message, 'error')
  }
}

// Group devices by subnet prefix (first 3 octets)
function subnetGroups() {
  const groups = {}
  for (const d of devices.value) {
    const parts = (d.ip || '').split('.')
    const prefix = parts.length >= 3 ? parts.slice(0, 3).join('.') : 'unknown'
    if (!groups[prefix]) groups[prefix] = []
    groups[prefix].push(d)
  }
  return Object.entries(groups).map(([prefix, devs]) => ({ prefix, devices: devs }))
    .sort((a, b) => a.prefix.localeCompare(b.prefix))
}

function formatLastSeen(ts) {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString()
}

// Init
fetchDevices()
</script>

<template>
  <div>
    <!-- Controls -->
    <div style="display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap;align-items:center">
      <span style="font-size:.85rem;font-weight:600">
        <i class="fas fa-network-wired" style="margin-right:.3rem"></i>
        Discovered Devices: {{ devices.length }}
      </span>
      <div style="flex:1"></div>
      <template v-if="authStore.isOperator">
        <select
          v-model="discoverHost"
          style="font-size:.75rem;padding:.25rem .4rem;border:1px solid var(--border);border-radius:4px;background:var(--surface-2);color:var(--text)"
        >
          <option value="">Select agent...</option>
          <option v-for="a in agents" :key="a.hostname" :value="a.hostname">{{ a.hostname }}</option>
        </select>
        <button
          class="btn btn-sm btn-primary"
          @click="triggerDiscover"
          :disabled="discoverLoading || !discoverHost"
        >
          <i class="fas fa-search" :class="discoverLoading ? 'fa-spin' : ''"></i> Discover
        </button>
      </template>
      <button class="btn btn-sm" @click="fetchDevices" :disabled="devicesLoading">
        <i class="fas fa-sync-alt" :class="devicesLoading ? 'fa-spin' : ''"></i>
      </button>
    </div>

    <!-- Empty state -->
    <div v-if="devices.length === 0 && !devicesLoading" class="empty-msg">
      No devices discovered yet. Select an agent and click "Discover" to scan the local network.
    </div>
    <div v-if="devicesLoading" class="empty-msg">Loading...</div>

    <!-- Subnet groups -->
    <div v-if="devices.length > 0">
      <div v-for="group in subnetGroups()" :key="group.prefix" style="margin-bottom:1rem">
        <div style="font-size:.78rem;font-weight:600;padding:.3rem .5rem;background:var(--surface-2);border-radius:4px;margin-bottom:.3rem;border:1px solid var(--border)">
          <i class="fas fa-sitemap" style="margin-right:.3rem;opacity:.6"></i>
          {{ group.prefix }}.x
          <span style="font-weight:normal;color:var(--text-dim);margin-left:.5rem">({{ group.devices.length }} devices)</span>
        </div>
        <div style="overflow-x:auto">
          <table style="width:100%;font-size:.78rem;border-collapse:collapse">
            <thead>
              <tr style="border-bottom:2px solid var(--border)">
                <th style="padding:.3rem .4rem;text-align:left">IP</th>
                <th style="padding:.3rem .4rem;text-align:left">MAC</th>
                <th style="padding:.3rem .4rem;text-align:left">Hostname</th>
                <th style="padding:.3rem .4rem;text-align:left">Vendor</th>
                <th style="padding:.3rem .4rem;text-align:left">Open Ports</th>
                <th style="padding:.3rem .4rem;text-align:left">Discovered By</th>
                <th style="padding:.3rem .4rem;text-align:left">Last Seen</th>
                <th v-if="authStore.isOperator" style="padding:.3rem .4rem"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="d in group.devices"
                :key="d.id"
                style="border-bottom:1px solid var(--border)"
              >
                <td style="padding:.3rem .4rem;font-family:monospace">{{ d.ip }}</td>
                <td style="padding:.3rem .4rem;font-family:monospace;font-size:.7rem;color:var(--text-dim)">{{ d.mac || '-' }}</td>
                <td style="padding:.3rem .4rem;font-weight:600">{{ d.hostname || '-' }}</td>
                <td style="padding:.3rem .4rem;font-size:.72rem;color:var(--text-dim)">{{ d.vendor || '-' }}</td>
                <td style="padding:.3rem .4rem">
                  <template v-if="d.open_ports && d.open_ports.length">
                    <span
                      v-for="p in d.open_ports"
                      :key="p"
                      class="badge bn"
                      style="font-size:.6rem;margin:1px"
                    >{{ p }}</span>
                  </template>
                  <span v-else style="color:var(--text-dim);font-size:.7rem">none</span>
                </td>
                <td style="padding:.3rem .4rem;font-size:.72rem">{{ d.discovered_by || '-' }}</td>
                <td style="padding:.3rem .4rem;font-size:.7rem;color:var(--text-dim)">{{ formatLastSeen(d.last_seen) }}</td>
                <td v-if="authStore.isOperator" style="padding:.3rem .4rem;text-align:center">
                  <button
                    class="btn btn-xs btn-danger"
                    title="Remove"
                    @click="deleteDevice(d.id)"
                  >
                    <i class="fas fa-trash"></i>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>
