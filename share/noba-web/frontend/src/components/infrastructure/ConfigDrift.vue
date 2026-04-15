<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'
import { useDashboardStore } from '../../stores/dashboard'
import { useModalsStore } from '../../stores/modals'

const { get, post, del } = useApi()
const authStore      = useAuthStore()
const notif          = useNotificationsStore()
const dashboardStore = useDashboardStore()
const modals         = useModalsStore()

const agents = computed(() => dashboardStore.live.agents || [])

const baselines       = ref([])
const baselinesLoading = ref(false)
const checkLoading    = ref(false)

const newPath  = ref('')
const newGroup = ref('__all__')

const expandedId  = ref(null)
const driftResults = ref([])

const setFromHost = ref('')

async function fetchBaselines() {
  baselinesLoading.value = true
  try {
    const data = await get('/api/baselines')
    baselines.value = Array.isArray(data) ? data : (data?.baselines || [])
  } catch { baselines.value = [] }
  finally { baselinesLoading.value = false }
}

async function createBaseline() {
  if (!newPath.value.trim()) return
  try {
    await post('/api/baselines', { path: newPath.value.trim(), agent_group: newGroup.value })
    notif.addToast('Baseline added', 'success')
    newPath.value = ''
    fetchBaselines()
  } catch (e) {
    notif.addToast('Failed: ' + e.message, 'error')
  }
}

async function deleteBaseline(id) {
  if (!await modals.confirm('Delete this baseline?')) return
  try {
    await del(`/api/baselines/${id}`)
    notif.addToast('Baseline deleted', 'success')
    baselines.value = baselines.value.filter(b => b.id !== id)
    if (expandedId.value === id) expandedId.value = null
  } catch (e) {
    notif.addToast('Delete failed: ' + e.message, 'error')
  }
}

async function setBaselineFromAgent(id, hostname) {
  if (!hostname) { notif.addToast('Select an agent first', 'error'); return }
  try {
    await post(`/api/baselines/${id}/set-from/${encodeURIComponent(hostname)}`)
    notif.addToast('Baseline hash updated from ' + hostname, 'success')
    fetchBaselines()
  } catch (e) {
    notif.addToast('Failed: ' + e.message, 'error')
  }
}

async function triggerCheck() {
  checkLoading.value = true
  try {
    await post('/api/baselines/check')
    notif.addToast('Drift check triggered', 'success')
    setTimeout(fetchBaselines, 2000)
  } catch (e) {
    notif.addToast('Check failed: ' + e.message, 'error')
  }
  checkLoading.value = false
}

async function toggleExpand(id) {
  if (expandedId.value === id) {
    expandedId.value = null
    driftResults.value = []
    return
  }
  expandedId.value = id
  driftResults.value = []
  try {
    const data = await get(`/api/baselines/${id}/results`)
    driftResults.value = Array.isArray(data) ? data : (data?.results || [])
  } catch { driftResults.value = [] }
}

function statusClass(status) {
  if (status === 'match')   return 'bs'
  if (status === 'drift')   return 'bd'
  if (status === 'timeout') return 'bw'
  return 'bw'
}

fetchBaselines()
</script>

<template>
  <div>
    <!-- Controls (operator+) -->
    <div v-if="authStore.isOperator" style="display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap;align-items:flex-end">
      <div style="display:flex;flex-direction:column;gap:.2rem;flex:1;min-width:200px">
        <label style="font-size:.7rem;color:var(--text-dim)">File Path</label>
        <input
          v-model="newPath"
          type="text"
          placeholder="/etc/resolv.conf"
          style="padding:.3rem .5rem;font-size:.8rem;border:1px solid var(--border);border-radius:4px;background:var(--surface-2);color:var(--text)"
        >
      </div>
      <div style="display:flex;flex-direction:column;gap:.2rem;min-width:120px">
        <label style="font-size:.7rem;color:var(--text-dim)">Agent Group</label>
        <select
          v-model="newGroup"
          style="padding:.3rem .5rem;font-size:.8rem;border:1px solid var(--border);border-radius:4px;background:var(--surface-2);color:var(--text)"
        >
          <option value="__all__">All Agents</option>
          <option v-for="a in agents" :key="a.hostname" :value="a.hostname">{{ a.hostname }}</option>
        </select>
      </div>
      <button class="btn btn-sm btn-primary" @click="createBaseline">
        <i class="fas fa-plus"></i> Add Baseline
      </button>
      <button class="btn btn-sm" @click="triggerCheck" :disabled="checkLoading">
        <i class="fas fa-sync-alt" :class="checkLoading ? 'fa-spin' : ''"></i> Check Now
      </button>
    </div>

    <div v-if="baselinesLoading" class="empty-msg">Loading...</div>
    <div v-else-if="baselines.length === 0" class="empty-msg">
      No config baselines defined. Add files to track for drift detection.
    </div>

    <table v-if="baselines.length > 0" style="width:100%;font-size:.8rem;border-collapse:collapse">
      <thead>
        <tr style="border-bottom:2px solid var(--border)">
          <th class="td-left">File Path</th>
          <th class="td-left">Expected Hash</th>
          <th class="td-cell">Group</th>
          <th class="td-cell">Agents</th>
          <th class="td-cell">Status</th>
          <th v-if="authStore.isOperator" class="td-cell">Actions</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="b in baselines" :key="b.id">
          <tr
            style="border-bottom:1px solid var(--border);cursor:pointer"
            :style="b.status === 'drift' ? 'background:rgba(239,68,68,0.08)' : ''"
            @click="toggleExpand(b.id)"
          >
            <td class="td-cell" style="font-family:monospace;font-size:.75rem">{{ b.path }}</td>
            <td class="td-cell" style="font-family:monospace;font-size:.7rem;color:var(--text-dim)">
              {{ b.expected_hash ? b.expected_hash.substring(0, 16) + (b.expected_hash.length > 16 ? '...' : '') : '-' }}
            </td>
            <td class="td-center" style="font-size:.75rem">
              {{ b.agent_group === '__all__' ? 'All' : b.agent_group }}
            </td>
            <td class="td-center">{{ b.agent_count || 0 }}</td>
            <td class="td-center">
              <span class="badge" :class="statusClass(b.status)" style="font-size:.6rem">{{ b.status || 'unknown' }}</span>
              <span v-if="b.drift_count > 0" style="font-size:.65rem;color:var(--danger);margin-left:.2rem">
                {{ b.drift_count }} drifted
              </span>
            </td>
            <td v-if="authStore.isOperator" class="td-center" @click.stop>
              <div style="display:flex;gap:.3rem;justify-content:center;align-items:center">
                <select
                  v-model="setFromHost"
                  style="font-size:.65rem;padding:.15rem .3rem;border:1px solid var(--border);border-radius:3px;background:var(--surface-2);color:var(--text);max-width:90px"
                  @click.stop
                >
                  <option value="">agent...</option>
                  <option v-for="a in agents" :key="a.hostname" :value="a.hostname">{{ a.hostname }}</option>
                </select>
                <button
                  class="btn btn-xs"
                  title="Set hash from agent"
                  @click.stop="setBaselineFromAgent(b.id, setFromHost)"
                >
                  <i class="fas fa-download"></i>
                </button>
                <button
                  class="btn btn-xs btn-danger"
                  title="Delete"
                  @click.stop="deleteBaseline(b.id)"
                >
                  <i class="fas fa-trash"></i>
                </button>
              </div>
            </td>
          </tr>

          <!-- Expanded drift results -->
          <tr v-if="expandedId === b.id" :key="'exp-' + b.id">
            <td :colspan="authStore.isOperator ? 6 : 5" style="padding:0">
              <div style="padding:.6rem;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);margin:.3rem">
                <h4 style="margin:0 0 .5rem 0;font-size:.85rem">
                  <i class="fas fa-search mr-sm"></i> Per-Agent Results
                </h4>
                <div v-if="driftResults.length === 0" class="empty-msg" style="margin:0">
                  No drift check results yet. Click "Check Now" to run a check.
                </div>
                <table v-else style="width:100%;font-size:.78rem;border-collapse:collapse">
                  <thead>
                    <tr class="border-b">
                      <th style="padding:.3rem;text-align:left">Hostname</th>
                      <th style="padding:.3rem;text-align:left">Actual Hash</th>
                      <th style="padding:.3rem">Status</th>
                      <th style="padding:.3rem">Checked At</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="r in driftResults"
                      :key="r.id"
                      class="border-b"
                      :style="r.status === 'drift' ? 'background:rgba(239,68,68,0.08)' : ''"
                    >
                      <td style="padding:.3rem;font-weight:600">{{ r.hostname }}</td>
                      <td style="padding:.3rem;font-family:monospace;font-size:.7rem;color:var(--text-dim)">
                        {{ r.actual_hash ? r.actual_hash.substring(0, 16) + '...' : 'N/A' }}
                      </td>
                      <td style="padding:.3rem;text-align:center">
                        <i v-if="r.status === 'match'" class="fas fa-check-circle" style="color:var(--success)"></i>
                        <i v-else-if="r.status === 'drift'" class="fas fa-exclamation-triangle" style="color:var(--danger)"></i>
                        <i v-else class="fas fa-clock" style="color:var(--warning)"></i>
                      </td>
                      <td style="padding:.3rem;text-align:center;font-size:.7rem;color:var(--text-dim)">
                        {{ r.checked_at ? new Date(r.checked_at * 1000).toLocaleString() : '-' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>
