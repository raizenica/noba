<script setup>
import { ref, watch } from 'vue'
import AppModal from '../ui/AppModal.vue'
import { useModalsStore } from '../../stores/modals'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const modals = useModalsStore()
const notif = useNotificationsStore()
const { get } = useApi()

const connections = ref([])
const ports = ref([])
const loading = ref(false)
const activeTab = ref('connections')

async function fetchData() {
  loading.value = true
  try {
    const [conns, pts] = await Promise.all([
      get('/api/network/connections').catch(() => []),
      get('/api/network/ports').catch(() => []),
    ])
    connections.value = Array.isArray(conns) ? conns : (conns?.connections ?? [])
    ports.value = Array.isArray(pts) ? pts : (pts?.ports ?? [])
  } catch (e) {
    notif.addToast('Failed to load network data: ' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

watch(() => modals.networkModal, (val) => { if (val) fetchData() })
</script>

<template>
  <AppModal
    :show="modals.networkModal"
    title="Network"
    width="800px"
    @close="modals.networkModal = false"
  >
    <div style="padding: 0 1rem 1rem">
      <!-- Tabs -->
      <div style="display:flex;gap:.25rem;margin-bottom:.75rem;border-bottom:1px solid var(--border);padding-bottom:.5rem">
        <button
          class="btn btn-sm"
          :class="activeTab === 'connections' ? 'btn-primary' : ''"
          @click="activeTab = 'connections'"
        >Connections ({{ connections.length }})</button>
        <button
          class="btn btn-sm"
          :class="activeTab === 'ports' ? 'btn-primary' : ''"
          @click="activeTab = 'ports'"
        >Listening Ports ({{ ports.length }})</button>
        <button class="btn btn-sm" style="margin-left:auto" @click="fetchData" :disabled="loading">
          <i class="fas fa-sync-alt" :class="{ 'fa-spin': loading }"></i>
        </button>
      </div>

      <div v-if="loading" style="padding:2rem;text-align:center;opacity:.5">Loading...</div>

      <!-- Connections table -->
      <div v-else-if="activeTab === 'connections'">
        <div v-if="!connections.length" style="padding:2rem;text-align:center;opacity:.4;font-size:.85rem">No connection data</div>
        <div v-else style="max-height:400px;overflow-y:auto">
          <table class="data-table" style="width:100%">
            <thead>
              <tr>
                <th>Protocol</th>
                <th>Local</th>
                <th>Remote</th>
                <th>Status</th>
                <th>PID</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(c, i) in connections" :key="i">
                <td style="font-size:.8rem">{{ c.type || c.proto || '—' }}</td>
                <td style="font-family:monospace;font-size:.78rem">{{ c.laddr || c.local || '—' }}</td>
                <td style="font-family:monospace;font-size:.78rem">{{ c.raddr || c.remote || '—' }}</td>
                <td><span class="badge" :class="c.status === 'ESTABLISHED' ? 'bs' : 'bn'" style="font-size:.7rem">{{ c.status || '—' }}</span></td>
                <td style="font-size:.8rem;opacity:.6">{{ c.pid || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Ports table -->
      <div v-else-if="activeTab === 'ports'">
        <div v-if="!ports.length" style="padding:2rem;text-align:center;opacity:.4;font-size:.85rem">No port data</div>
        <div v-else style="max-height:400px;overflow-y:auto">
          <table class="data-table" style="width:100%">
            <thead>
              <tr>
                <th>Port</th>
                <th>Protocol</th>
                <th>Address</th>
                <th>PID</th>
                <th>Process</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(p, i) in ports" :key="i">
                <td style="font-weight:500">{{ p.port || p.lport || '—' }}</td>
                <td style="font-size:.8rem">{{ p.proto || p.type || '—' }}</td>
                <td style="font-family:monospace;font-size:.78rem">{{ p.address || p.laddr || '—' }}</td>
                <td style="font-size:.8rem;opacity:.6">{{ p.pid || '—' }}</td>
                <td style="font-size:.8rem">{{ p.process || p.name || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </AppModal>
</template>
