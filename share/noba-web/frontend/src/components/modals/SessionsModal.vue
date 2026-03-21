<script setup>
import { ref, watch } from 'vue'
import AppModal from '../ui/AppModal.vue'
import { useModalsStore } from '../../stores/modals'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const modals = useModalsStore()
const notif = useNotificationsStore()
const { get, post } = useApi()

const sessions = ref([])
const loading = ref(false)

async function fetchSessions() {
  loading.value = true
  try {
    sessions.value = await get('/api/admin/sessions') || []
  } catch (e) {
    notif.addToast('Failed to fetch sessions: ' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

async function revokeSession(prefix) {
  try {
    await post('/api/admin/sessions/revoke', { prefix })
    notif.addToast('Session revoked', 'success')
    await fetchSessions()
  } catch (e) {
    notif.addToast('Failed to revoke session: ' + e.message, 'error')
  }
}

function formatDate(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString()
}

watch(() => modals.sessionsModal, (val) => { if (val) fetchSessions() })
</script>

<template>
  <AppModal
    :show="modals.sessionsModal"
    title="Active Sessions"
    width="720px"
    @close="modals.sessionsModal = false"
  >
    <div style="padding: 0 1rem 1rem">
      <div style="display:flex;justify-content:flex-end;margin-bottom:.75rem">
        <button class="btn btn-sm" @click="fetchSessions" :disabled="loading">
          <i class="fas fa-sync-alt" style="margin-right:4px" :class="{ 'fa-spin': loading }"></i>Refresh
        </button>
      </div>

      <div v-if="loading" style="padding:2rem;text-align:center;opacity:.5">Loading sessions...</div>
      <div v-else-if="!sessions.length" style="padding:2rem;text-align:center;opacity:.4;font-size:.85rem">
        No active sessions
      </div>
      <table v-else class="data-table" style="width:100%">
        <thead>
          <tr>
            <th>Token Prefix</th>
            <th>User</th>
            <th>Created</th>
            <th>Last Used</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in sessions" :key="s.prefix || s.id">
            <td><code style="font-size:.8rem">{{ s.prefix || s.token_prefix || '—' }}...</code></td>
            <td>{{ s.username || s.user || '—' }}</td>
            <td style="font-size:.8rem;opacity:.7">{{ formatDate(s.created_at || s.created) }}</td>
            <td style="font-size:.8rem;opacity:.7">{{ formatDate(s.last_used) }}</td>
            <td>
              <button
                class="btn btn-sm bd"
                @click="revokeSession(s.prefix || s.token_prefix)"
                title="Revoke session"
              >
                <i class="fas fa-ban"></i>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </AppModal>
</template>
