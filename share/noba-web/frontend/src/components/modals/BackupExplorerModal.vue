<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, watch } from 'vue'
import AppModal from '../ui/AppModal.vue'
import { useModalsStore } from '../../stores/modals'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'
import { useAuthStore } from '../../stores/auth'

const modals = useModalsStore()
const notif = useNotificationsStore()
const auth = useAuthStore()
const { get, post } = useApi()

const snapshots = ref([])
const loading = ref(false)
const restoring = ref(false)

async function fetchSnapshots() {
  loading.value = true
  try {
    const data = await get('/api/backup/history')
    snapshots.value = data?.snapshots ?? (Array.isArray(data) ? data : [])
  } catch (e) {
    notif.addToast('Failed to load backups: ' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

function downloadSnapshot(name) {
  const url = `/api/backup/snapshots/${encodeURIComponent(name)}/download?token=${encodeURIComponent(auth.token)}`
  window.open(url, '_blank')
}

async function restoreSnapshot(name) {
  if (!await modals.confirm(`Restore snapshot "${name}"? This will overwrite current data.`)) return
  restoring.value = true
  try {
    const d = await post('/api/backup/restore', { snapshot: name })
    notif.addToast(`Restored: ${d?.restored_to || name}`, 'success')
  } catch (e) {
    notif.addToast('Restore failed: ' + e.message, 'error')
  } finally {
    restoring.value = false
  }
}

function formatSize(bytes) {
  if (bytes == null) return '—'
  if (bytes > 1e9) return (bytes / 1e9).toFixed(1) + ' GB'
  if (bytes > 1e6) return (bytes / 1e6).toFixed(1) + ' MB'
  if (bytes > 1e3) return (bytes / 1e3).toFixed(1) + ' KB'
  return bytes + ' B'
}

watch(() => modals.backupExplorerModal, (val) => { if (val) fetchSnapshots() })
</script>

<template>
  <AppModal
    :show="modals.backupExplorerModal"
    title="Backup Explorer"
    width="720px"
    @close="modals.backupExplorerModal = false"
  >
    <div style="padding: 0 1rem 1rem">
      <div style="display:flex;justify-content:flex-end;margin-bottom:.75rem">
        <button class="btn btn-sm" @click="fetchSnapshots" :disabled="loading">
          <i class="fas fa-sync-alt" :class="{ 'fa-spin': loading }" style="margin-right:4px"></i>Refresh
        </button>
      </div>

      <div v-if="loading" style="padding:2rem;text-align:center;opacity:.5">Loading snapshots...</div>
      <div v-else-if="!snapshots.length" style="padding:2rem;text-align:center;opacity:.4;font-size:.85rem">
        No snapshots available
      </div>
      <table v-else class="data-table" style="width:100%">
        <thead>
          <tr>
            <th>Snapshot</th>
            <th>Created</th>
            <th>Size</th>
            <th>Type</th>
            <th style="text-align:right">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="snap in snapshots" :key="snap.name || snap.id">
            <td style="font-family:monospace;font-size:.8rem">{{ snap.name || snap.id }}</td>
            <td style="font-size:.8rem;opacity:.7">
              {{ snap.created_at ? new Date(snap.created_at * 1000).toLocaleString() : (snap.date || '—') }}
            </td>
            <td style="font-size:.8rem">{{ formatSize(snap.size) }}</td>
            <td>
              <span class="badge bn" style="font-size:.7rem">{{ snap.type || 'backup' }}</span>
            </td>
            <td style="text-align:right">
              <div style="display:flex;gap:.3rem;justify-content:flex-end">
                <button
                  class="btn btn-sm"
                  @click="downloadSnapshot(snap.name || snap.id)"
                  title="Download snapshot"
                >
                  <i class="fas fa-download"></i>
                </button>
                <button
                  class="btn btn-sm bw"
                  @click="restoreSnapshot(snap.name || snap.id)"
                  :disabled="restoring"
                  title="Restore snapshot"
                >
                  <i class="fas fa-undo"></i>
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </AppModal>
</template>
