<script setup>
import { ref, watch } from 'vue'
import AppModal from '../ui/AppModal.vue'
import { useModalsStore } from '../../stores/modals'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const modals = useModalsStore()
const notif = useNotificationsStore()
const { get } = useApi()

const info = ref(null)
const loading = ref(false)

async function fetchInfo() {
  loading.value = true
  try {
    info.value = await get('/api/system/info')
  } catch (e) {
    notif.addToast('Failed to load system info: ' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

watch(() => modals.systemInfoModal, (val) => { if (val) fetchInfo() })

function flatten(obj, prefix = '') {
  const rows = []
  for (const [k, v] of Object.entries(obj || {})) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      rows.push(...flatten(v, key))
    } else {
      rows.push({ key, value: Array.isArray(v) ? v.join(', ') : String(v ?? '—') })
    }
  }
  return rows
}
</script>

<template>
  <AppModal
    :show="modals.systemInfoModal"
    title="System Information"
    width="600px"
    @close="modals.systemInfoModal = false"
  >
    <div style="padding: 0 1rem 1rem">
      <div v-if="loading" style="padding:2rem;text-align:center;opacity:.5">Loading...</div>
      <div v-else-if="!info" style="padding:2rem;text-align:center;opacity:.4;font-size:.85rem">No data</div>
      <table v-else class="data-table" style="width:100%">
        <tbody>
          <tr v-for="row in flatten(info)" :key="row.key">
            <td style="font-size:.8rem;opacity:.6;width:40%">{{ row.key }}</td>
            <td style="font-size:.85rem;word-break:break-word">{{ row.value }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </AppModal>
</template>
