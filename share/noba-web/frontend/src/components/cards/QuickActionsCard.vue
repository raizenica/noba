<script setup>
import { ref, computed } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'
import DashboardCard from './DashboardCard.vue'

const { post } = useApi()
const auth = useAuthStore()

const runningScript = ref(false)
const scriptOutput  = ref('')
const isViewer      = computed(() => auth.userRole === 'viewer')
const isOperator    = computed(() => auth.isOperator)

async function runScript(scriptName, args = '') {
  if (runningScript.value) return
  runningScript.value = true
  scriptOutput.value  = ''
  try {
    const res = await post('/api/run-script', { script: scriptName, args })
    scriptOutput.value = res?.output || res?.result || 'Done.'
  } catch (e) {
    scriptOutput.value = 'Error: ' + e.message
  } finally {
    runningScript.value = false
  }
}
</script>

<template>
  <DashboardCard title="Quick Actions" icon="fas fa-terminal" card-id="actions">
    <div v-if="isViewer" class="empty-msg">Operator or admin role required.</div>

    <template v-else>
      <!-- NAS Backup Job -->
      <button
        class="btn"
        style="margin-bottom:.4rem"
        :disabled="runningScript"
        @click="runScript('backup')"
      >
        <i class="fas fa-database" aria-hidden="true"></i>
        NAS Backup Job
      </button>

      <!-- Cloud Sync Job -->
      <button
        class="btn"
        style="margin-bottom:.4rem"
        :disabled="runningScript"
        @click="runScript('cloud')"
      >
        <i class="fas fa-cloud-upload-alt" aria-hidden="true"></i>
        Cloud Sync Job
      </button>

      <!-- Organize Downloads -->
      <button
        class="btn"
        style="margin-bottom:.4rem"
        :disabled="runningScript"
        @click="runScript('organize')"
      >
        <i class="fas fa-folder-open" aria-hidden="true"></i>
        Organize Downloads
      </button>

      <div style="height:1px;background:var(--border);margin:.4rem 0" role="separator"></div>

      <!-- Verify Backups -->
      <button
        class="btn"
        style="margin-bottom:.4rem"
        :disabled="runningScript"
        @click="runScript('verify')"
      >
        <i class="fas fa-check-double" aria-hidden="true"></i>
        Verify Backups
      </button>

      <!-- Disk Cleanup -->
      <button
        class="btn"
        style="margin-bottom:.4rem"
        :disabled="runningScript"
        @click="runScript('diskcheck')"
      >
        <i class="fas fa-broom" aria-hidden="true"></i>
        Disk Cleanup
      </button>

      <!-- Check Updates -->
      <button
        class="btn"
        style="margin-bottom:.4rem"
        :disabled="runningScript"
        @click="runScript('check_updates')"
      >
        <i class="fas fa-arrow-circle-up" aria-hidden="true"></i>
        Check Updates
      </button>

      <!-- Script output -->
      <div
        v-if="scriptOutput"
        style="margin-top:.4rem;font-size:.75rem;padding:.3rem .5rem;background:var(--surface-2);border-radius:4px;white-space:pre-wrap;word-break:break-word"
      >{{ scriptOutput }}</div>
    </template>
  </DashboardCard>
</template>
