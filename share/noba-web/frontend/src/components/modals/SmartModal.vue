<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, watch } from 'vue'
import AppModal from '../ui/AppModal.vue'
import { useModalsStore } from '../../stores/modals'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const modals = useModalsStore()
const notif = useNotificationsStore()
const { get } = useApi()

const smartData = ref([])
const loading = ref(false)

async function fetchSmart() {
  loading.value = true
  smartData.value = []
  try {
    const data = await get('/api/smart')
    smartData.value = Array.isArray(data) ? data : (data?.disks ?? [])
  } catch (e) {
    notif.addToast('Failed to load SMART data: ' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

watch(() => modals.smartModal, (val) => { if (val) fetchSmart() })

function riskClass(score) {
  if (score == null) return 'bn'
  if (score >= 75) return 'bd'
  if (score >= 40) return 'bw'
  return 'bs'
}

function riskLabel(score) {
  if (score == null) return 'Unknown'
  if (score >= 75) return 'Critical'
  if (score >= 40) return 'Warning'
  return 'Healthy'
}

function formatPoh(hours) {
  if (hours == null) return '—'
  const d = Math.floor(hours / 24)
  const h = hours % 24
  return d > 0 ? `${d}d ${h}h` : `${h}h`
}
</script>

<template>
  <AppModal
    :show="modals.smartModal"
    title="SMART Disk Health"
    width="860px"
    @close="modals.smartModal = false"
  >
    <div style="padding: 0 1rem 1rem">
      <div v-if="loading" style="padding:2rem;text-align:center;opacity:.5">Loading SMART data...</div>
      <div v-else-if="!smartData.length" style="padding:2rem;text-align:center;opacity:.4;font-size:.85rem">
        No SMART data available
      </div>
      <table v-else class="data-table" style="width:100%">
        <thead>
          <tr>
            <th>Device</th>
            <th>Model</th>
            <th>Serial</th>
            <th>Temp</th>
            <th>Power-On</th>
            <th>Health</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="disk in smartData" :key="disk.device">
            <td><code style="font-size:.8rem">{{ disk.device }}</code></td>
            <td style="font-size:.85rem">{{ disk.model || '—' }}</td>
            <td style="font-size:.8rem;opacity:.7">{{ disk.serial || '—' }}</td>
            <td>
              <span v-if="disk.temperature != null">
                {{ disk.temperature }}&deg;C
              </span>
              <span v-else>—</span>
            </td>
            <td style="font-size:.85rem">{{ formatPoh(disk.power_on_hours) }}</td>
            <td style="font-size:.8rem">{{ disk.smart_status || '—' }}</td>
            <td>
              <span class="badge" :class="riskClass(disk.risk_score)">
                {{ riskLabel(disk.risk_score) }}
                <span v-if="disk.risk_score != null" style="opacity:.6;margin-left:4px">({{ disk.risk_score }})</span>
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </AppModal>
</template>
