<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref } from 'vue'
import { useApi } from '../../composables/useApi'

const { get } = useApi()

const syncStatus  = ref(null)
const syncLoading = ref(false)

async function fetchSyncStatus() {
  syncLoading.value = true
  try {
    const data = await get('/api/sites/sync-status')
    syncStatus.value = data
  } catch { syncStatus.value = null }
  finally { syncLoading.value = false }
}

defineExpose({ fetchSyncStatus })
</script>

<template>
  <div>
    <div v-if="syncLoading" class="empty-msg">Loading...</div>
    <template v-else-if="syncStatus">
      <template v-if="syncStatus.services && syncStatus.services.length">
        <table style="width:100%;font-size:.8rem;border-collapse:collapse">
          <thead>
            <tr class="border-b">
              <th class="td-left">Service</th>
              <th class="td-cell">Sites</th>
              <th class="td-cell">Status</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in syncStatus.services"
              :key="s.key"
              class="border-b"
            >
              <td class="td-cell">{{ s.key }}</td>
              <td class="td-cell" style="font-size:.7rem">{{ Object.keys(s.sites || {}).join(', ') }}</td>
              <td class="td-center">
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
</template>
