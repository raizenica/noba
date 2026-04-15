<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref } from 'vue'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const { get } = useApi()
const notif   = useNotificationsStore()

const cmdHistory        = ref([])
const cmdHistoryLoading = ref(false)

async function fetchCommandHistory() {
  cmdHistoryLoading.value = true
  try {
    const data = await get('/api/agents/command-history?limit=50')
    cmdHistory.value = Array.isArray(data) ? data : []
  } catch (e) { notif.addToast('Failed to load command history: ' + e.message, 'danger') }
  finally { cmdHistoryLoading.value = false }
}

function historyStatusClass(status) {
  if (status === 'ok')     return 'bs'
  if (status === 'error')  return 'bd'
  if (status === 'queued') return 'bn'
  return 'bw'
}

defineExpose({ fetchCommandHistory })
</script>

<template>
  <div>
    <div v-if="cmdHistory.length > 0" class="cmd-history-table-wrap">
      <table class="cmd-history-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Host</th>
            <th>Command</th>
            <th>User</th>
            <th>Status</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in cmdHistory" :key="h.id">
            <td style="white-space:nowrap">{{ new Date((h.queued_at||0)*1000).toLocaleString() }}</td>
            <td>{{ h.hostname }}</td>
            <td><span class="badge ba" style="font-size:.55rem">{{ h.cmd_type }}</span></td>
            <td>{{ h.queued_by }}</td>
            <td>
              <span class="badge" :class="historyStatusClass(h.status)" style="font-size:.55rem">
                {{ h.status }}
              </span>
            </td>
            <td>{{ h.finished_at ? (h.finished_at - h.queued_at) + 's' : '--' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else-if="!cmdHistoryLoading" class="empty-msg">No command history yet.</div>
    <button
      class="btn btn-xs"
      style="margin-top:.5rem"
      :disabled="cmdHistoryLoading"
      @click="fetchCommandHistory"
    >
      <i class="fas" :class="cmdHistoryLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i> Refresh
    </button>
  </div>
</template>
