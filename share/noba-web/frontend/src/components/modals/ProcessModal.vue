<script setup>
import { ref, watch, computed } from 'vue'
import AppModal from '../ui/AppModal.vue'
import { useModalsStore } from '../../stores/modals'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const modals = useModalsStore()
const notif = useNotificationsStore()
const { get } = useApi()

const processes = ref([])
const loading = ref(false)
const filterText = ref('')
const sortField = ref('cpu_percent')
const sortDir = ref('desc')

async function fetchProcesses() {
  loading.value = true
  try {
    const data = await get('/api/system/processes')
    processes.value = Array.isArray(data) ? data : (data?.processes ?? [])
  } catch (e) {
    notif.addToast('Failed to load processes: ' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

function setSort(field) {
  if (sortField.value === field) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortField.value = field
    sortDir.value = 'desc'
  }
}

const filtered = computed(() => {
  const q = filterText.value.toLowerCase()
  let list = processes.value
  if (q) list = list.filter(p => (p.name || '').toLowerCase().includes(q) || String(p.pid || '').includes(q))
  const field = sortField.value
  const dir = sortDir.value === 'asc' ? 1 : -1
  return [...list].sort((a, b) => {
    const va = a[field] ?? 0
    const vb = b[field] ?? 0
    return (typeof va === 'string' ? va.localeCompare(vb) : (va - vb)) * dir
  })
})

watch(() => modals.processModal, (val) => { if (val) fetchProcesses() })
</script>

<template>
  <AppModal
    :show="modals.processModal"
    title="Process List"
    width="800px"
    @close="modals.processModal = false"
  >
    <div style="padding: 0 1rem 1rem">
      <div style="display:flex;gap:.5rem;margin-bottom:.75rem;align-items:center">
        <input
          v-model="filterText"
          type="text"
          class="field-input"
          style="flex:1;max-width:240px"
          placeholder="Filter by name or PID..."
        />
        <button class="btn btn-sm" style="margin-left:auto" @click="fetchProcesses" :disabled="loading">
          <i class="fas fa-sync-alt" :class="{ 'fa-spin': loading }" style="margin-right:4px"></i>Refresh
        </button>
      </div>

      <div v-if="loading" style="padding:2rem;text-align:center;opacity:.5">Loading...</div>
      <div v-else-if="!filtered.length" style="padding:2rem;text-align:center;opacity:.4;font-size:.85rem">No processes</div>
      <div v-else style="max-height:420px;overflow-y:auto">
        <table class="data-table" style="width:100%">
          <thead>
            <tr>
              <th @click="setSort('pid')" style="cursor:pointer">PID <i class="fas" :class="sortField==='pid' ? (sortDir==='asc' ? 'fa-sort-up':'fa-sort-down') : 'fa-sort'" style="opacity:.4;font-size:.7rem"></i></th>
              <th @click="setSort('name')" style="cursor:pointer">Name <i class="fas" :class="sortField==='name' ? (sortDir==='asc' ? 'fa-sort-up':'fa-sort-down') : 'fa-sort'" style="opacity:.4;font-size:.7rem"></i></th>
              <th @click="setSort('cpu_percent')" style="cursor:pointer">CPU% <i class="fas" :class="sortField==='cpu_percent' ? (sortDir==='asc' ? 'fa-sort-up':'fa-sort-down') : 'fa-sort'" style="opacity:.4;font-size:.7rem"></i></th>
              <th @click="setSort('memory_percent')" style="cursor:pointer">MEM% <i class="fas" :class="sortField==='memory_percent' ? (sortDir==='asc' ? 'fa-sort-up':'fa-sort-down') : 'fa-sort'" style="opacity:.4;font-size:.7rem"></i></th>
              <th>User</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in filtered.slice(0, 200)" :key="p.pid">
              <td style="font-size:.8rem;opacity:.6">{{ p.pid }}</td>
              <td style="font-size:.85rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ p.name }}</td>
              <td>
                <span :style="{ color: (p.cpu_percent||0) > 50 ? 'var(--danger)' : (p.cpu_percent||0) > 10 ? 'var(--warning)' : '' }">
                  {{ (p.cpu_percent || 0).toFixed(1) }}%
                </span>
              </td>
              <td style="font-size:.85rem">{{ (p.memory_percent || 0).toFixed(1) }}%</td>
              <td style="font-size:.8rem;opacity:.6">{{ p.username || p.user || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="filtered.length > 200" style="text-align:center;padding:.5rem;font-size:.8rem;opacity:.4">
          Showing top 200 of {{ filtered.length }} processes
        </div>
      </div>
    </div>
  </AppModal>
</template>
