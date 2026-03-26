<script setup>
import { ref } from 'vue'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'
import AppModal from '../ui/AppModal.vue'
import AutomationStatusBadge from './AutomationStatusBadge.vue'

const props = defineProps({
  automations: Array, // full automation list for name lookup
})

const notify = useNotificationsStore()
const { get } = useApi()

const runHistory        = ref([])
const runHistoryLoading = ref(false)

const showRunDetailModal = ref(false)
const runDetailData      = ref(null)
const runDetailSteps     = ref([])
const runDetailLoading   = ref(false)

async function fetchRunHistory() {
  runHistoryLoading.value = true
  try {
    const data = await get('/api/runs?limit=50')
    runHistory.value = Array.isArray(data) ? data : []
  } catch (e) {
    notify.addToast('Failed to load run history: ' + e.message, 'error')
  } finally {
    runHistoryLoading.value = false
  }
}

async function openRunDetail(run) {
  runDetailData.value  = run
  runDetailSteps.value = []
  showRunDetailModal.value = true
  runDetailLoading.value = true
  try {
    const full = await get(`/api/runs/${run.id}`)
    if (full) runDetailData.value = full

    const trigger = (runDetailData.value.trigger || '')
    if (trigger.startsWith('workflow:')) {
      const parts = trigger.split(':')
      if (parts.length >= 2) {
        const prefix = `workflow:${parts[1]}`
        const steps  = await get(`/api/runs?trigger_prefix=${encodeURIComponent(prefix)}&limit=50`)
        if (Array.isArray(steps)) {
          runDetailSteps.value = steps.sort((a, b) => (a.started_at || 0) - (b.started_at || 0))
        }
      }
    }
  } catch (e) {
    notify.addToast('Failed to load run details: ' + e.message, 'error')
  } finally {
    runDetailLoading.value = false
  }
}

function autoName(id) {
  return ((props.automations || []).find(a => a.id === id) || {}).name || id || '\u2014'
}

defineExpose({ fetchRunHistory })
</script>

<template>
  <div>
    <!-- Run History panel header -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.6rem">
      <span style="font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted)">
        <i class="fas fa-history" style="margin-right:.3rem"></i>Run History
      </span>
      <button class="btn btn-xs" :disabled="runHistoryLoading" @click="fetchRunHistory">
        <i class="fas" :class="runHistoryLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i>
      </button>
    </div>

    <div v-if="runHistoryLoading" class="empty-msg">Loading...</div>
    <div v-else-if="runHistory.length === 0" class="empty-msg">No runs yet.</div>
    <div v-else style="overflow-x:auto">
      <table style="width:100%;font-size:.78rem;border-collapse:collapse">
        <thead>
          <tr style="border-bottom:1px solid var(--border)">
            <th style="padding:.4rem;text-align:left">#</th>
            <th style="padding:.4rem;text-align:left">Automation</th>
            <th style="padding:.4rem;text-align:left">Trigger</th>
            <th style="padding:.4rem;text-align:center">Status</th>
            <th style="padding:.4rem;text-align:center">Duration</th>
            <th style="padding:.4rem;text-align:center">Started</th>
            <th style="padding:.4rem;text-align:center">Detail</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in runHistory" :key="run.id" style="border-bottom:1px solid var(--border)">
            <td style="padding:.4rem;opacity:.6">{{ run.id }}</td>
            <td style="padding:.4rem">{{ autoName(run.automation_id) }}</td>
            <td style="padding:.4rem;opacity:.7;font-size:.72rem">{{ run.trigger || '\u2014' }}</td>
            <td style="padding:.4rem;text-align:center">
              <AutomationStatusBadge :status="run.status" />
            </td>
            <td style="padding:.4rem;text-align:center">
              {{ run.finished_at && run.started_at ? (run.finished_at - run.started_at) + 's' : '\u2014' }}
            </td>
            <td style="padding:.4rem;text-align:center;font-size:.72rem">
              {{ run.started_at ? new Date(run.started_at * 1000).toLocaleString() : '\u2014' }}
            </td>
            <td style="padding:.4rem;text-align:center">
              <button class="btn btn-xs" title="View detail" @click="openRunDetail(run)">
                <i class="fas fa-eye"></i>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Run detail modal -->
    <AppModal :show="showRunDetailModal" title="Run Detail" width="680px" @close="showRunDetailModal = false">
      <div style="padding:1rem">
        <div v-if="runDetailLoading" class="empty-msg">Loading...</div>
        <template v-else-if="runDetailData">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:.4rem .8rem;font-size:.8rem;margin-bottom:.8rem">
            <div><span style="color:var(--text-muted)">ID:</span> {{ runDetailData.id }}</div>
            <div>
              <span style="color:var(--text-muted)">Status:</span>
              <AutomationStatusBadge :status="runDetailData.status" style="margin-left:.3rem;font-size:.6rem" />
            </div>
            <div><span style="color:var(--text-muted)">Trigger:</span> {{ runDetailData.trigger || '\u2014' }}</div>
            <div>
              <span style="color:var(--text-muted)">Duration:</span>
              {{ runDetailData.finished_at && runDetailData.started_at
                  ? (runDetailData.finished_at - runDetailData.started_at) + 's'
                  : '\u2014' }}
            </div>
          </div>

          <div style="font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--text-muted);margin-bottom:.3rem">
            Output
          </div>
          <pre style="background:#0e0e10;color:#e0e0e0;font-family:monospace;font-size:.73rem;line-height:1.5;padding:.6rem;border-radius:4px;max-height:300px;overflow-y:auto;white-space:pre-wrap;word-break:break-all">{{ runDetailData.output || '(no output)' }}</pre>

          <div
            v-if="runDetailData.error"
            style="margin-top:.5rem;padding:.5rem;background:color-mix(in srgb, var(--danger) 10%, var(--surface));border:1px solid var(--danger);border-radius:4px;font-size:.78rem;font-family:monospace"
          >{{ runDetailData.error }}</div>

          <div v-if="runDetailSteps.length > 0" style="margin-top:.8rem">
            <div style="font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--text-muted);margin-bottom:.3rem">
              Workflow Steps
            </div>
            <div style="display:flex;flex-direction:column;gap:.3rem">
              <div
                v-for="step in runDetailSteps"
                :key="step.id"
                style="display:flex;justify-content:space-between;align-items:center;padding:.3rem .5rem;border:1px solid var(--border);border-radius:4px;font-size:.78rem"
              >
                <span>{{ autoName(step.automation_id) }}</span>
                <AutomationStatusBadge :status="step.status" />
              </div>
            </div>
          </div>
        </template>
      </div>
      <template #footer>
        <button class="btn" @click="showRunDetailModal = false">Close</button>
      </template>
    </AppModal>
  </div>
</template>
