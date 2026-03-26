<script setup>
import { ref } from 'vue'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'
import AppModal from '../ui/AppModal.vue'
import AutomationStatusBadge from './AutomationStatusBadge.vue'

const notify = useNotificationsStore()
const { get } = useApi()

const show        = ref(false)
const traceData   = ref(null)
const traceLoading = ref(false)

async function open(auto) {
  traceLoading.value = true; show.value = true; traceData.value = null
  try { traceData.value = await get(`/api/automations/${auto.id}/trace`) }
  catch (e) { notify.addToast('Failed to load trace: ' + e.message, 'error') }
  finally { traceLoading.value = false }
}

defineExpose({ open })
</script>

<template>
  <AppModal :show="show" title="Workflow Trace" width="620px" @close="show = false">
    <div style="padding:1rem">
      <div v-if="traceLoading" class="empty-msg">Loading...</div>
      <div v-else-if="!traceData" class="empty-msg">No trace data available.</div>
      <template v-else>
        <div v-if="traceData.steps && traceData.steps.length" style="display:flex;flex-direction:column;gap:.4rem">
          <div
            v-for="(step, i) in traceData.steps" :key="i"
            style="display:flex;align-items:center;gap:.5rem;padding:.4rem .6rem;border:1px solid var(--border);border-radius:5px;font-size:.8rem"
          >
            <span style="font-size:.7rem;opacity:.5;min-width:1.5rem;text-align:right">{{ i + 1 }}</span>
            <i class="fas"
              :class="step.status === 'done' ? 'fa-check-circle' : step.status === 'failed' ? 'fa-times-circle' : 'fa-circle'"
              :style="step.status === 'done' ? 'color:var(--success)' : step.status === 'failed' ? 'color:var(--danger)' : 'color:var(--text-muted)'"
            ></i>
            <span style="flex:1">{{ step.name || step.automation_id || ('Step ' + (i + 1)) }}</span>
            <span v-if="step.duration" style="opacity:.6;font-size:.72rem">{{ step.duration }}s</span>
            <AutomationStatusBadge :status="step.status || 'pending'" />
          </div>
        </div>
        <pre v-else style="background:#0e0e10;color:#e0e0e0;font-family:monospace;font-size:.73rem;padding:.6rem;border-radius:4px;max-height:300px;overflow-y:auto;white-space:pre-wrap">{{ JSON.stringify(traceData, null, 2) }}</pre>
      </template>
    </div>
    <template #footer>
      <button class="btn" @click="show = false">Close</button>
    </template>
  </AppModal>
</template>
