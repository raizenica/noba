<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, watch } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'
import AppModal from '../ui/AppModal.vue'

const { get, post } = useApi()
const authStore = useAuthStore()
const notif     = useNotificationsStore()

// ── State ──────────────────────────────────────────────────────────────────────
const namespaces   = ref([])
const selectedNs   = ref('')
const pods         = ref([])
const deployments  = ref([])
const loading      = ref(false)

// Pod logs modal
const showLogsModal = ref(false)
const logsTitle     = ref('')
const podLogs       = ref('')
const logsLoading   = ref(false)

// Scale modal
const showScaleModal = ref(false)
const scaleTitle     = ref('')
const scaleNs        = ref('')
const scaleTarget    = ref('')
const scaleValue     = ref(1)
const scaleLoading   = ref(false)

// Active sub-tab
const subTab = ref('pods')

// ── Fetch helpers ──────────────────────────────────────────────────────────────
async function fetchNamespaces() {
  try {
    const data = await get('/api/k8s/namespaces')
    namespaces.value = Array.isArray(data) ? data : (data?.namespaces || [])
  } catch { /* silent */ }
}

async function fetchPods(ns) {
  loading.value = true
  try {
    const qs = ns ? `?namespace=${encodeURIComponent(ns)}` : ''
    const data = await get(`/api/k8s/pods${qs}`)
    pods.value = Array.isArray(data) ? data : (data?.pods || [])
  } catch { pods.value = [] }
  finally { loading.value = false }
}

async function fetchDeployments(ns) {
  try {
    const qs = ns ? `?namespace=${encodeURIComponent(ns)}` : ''
    const data = await get(`/api/k8s/deployments${qs}`)
    deployments.value = Array.isArray(data) ? data : (data?.deployments || [])
  } catch { deployments.value = [] }
}

async function fetchPodLogs(namespace, name) {
  logsTitle.value   = `${namespace}/${name}`
  showLogsModal.value = true
  logsLoading.value = true
  podLogs.value     = ''
  try {
    const text = await get(`/api/k8s/pods/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/logs?lines=200`)
    podLogs.value = typeof text === 'string' ? text : JSON.stringify(text, null, 2)
  } catch (e) {
    podLogs.value = 'Error: ' + e.message
  }
  logsLoading.value = false
}

function openScale(namespace, name, currentReplicas) {
  scaleNs.value = namespace
  scaleTarget.value = name
  scaleValue.value = currentReplicas ?? 1
  scaleTitle.value = `${namespace}/${name}`
  showScaleModal.value = true
}

async function doScale() {
  const replicas = parseInt(String(scaleValue.value), 10)
  if (isNaN(replicas) || replicas < 0) {
    notif.addToast('Invalid replica count', 'error')
    return
  }
  scaleLoading.value = true
  try {
    const data = await post(
      `/api/k8s/deployments/${encodeURIComponent(scaleNs.value)}/${encodeURIComponent(scaleTarget.value)}/scale`,
      { replicas }
    )
    if (data?.success) {
      notif.addToast(`Scaled to ${data.replicas} replicas`, 'success')
      showScaleModal.value = false
      fetchDeployments(selectedNs.value)
    } else {
      notif.addToast('Scale failed', 'error')
    }
  } catch (e) {
    notif.addToast('Scale failed: ' + e.message, 'error')
  } finally {
    scaleLoading.value = false
  }
}

// ── Watchers ───────────────────────────────────────────────────────────────────
watch(selectedNs, (ns) => {
  fetchPods(ns)
  fetchDeployments(ns)
})

// ── Init ───────────────────────────────────────────────────────────────────────
fetchNamespaces()
fetchPods('')
fetchDeployments('')

// ── Helpers ────────────────────────────────────────────────────────────────────
function podStatusClass(phase) {
  if (phase === 'Running')   return 'bs'
  if (phase === 'Pending')   return 'bn'
  if (phase === 'Failed')    return 'bd'
  if (phase === 'Succeeded') return 'bw'
  return 'bw'
}
</script>

<template>
  <div>
    <!-- Namespace selector + sub-tabs -->
    <div style="display:flex;gap:.5rem;margin-bottom:.8rem;flex-wrap:wrap;align-items:center">
      <div style="display:flex;flex-direction:column;gap:.2rem">
        <label class="field-label">Namespace</label>
        <select
          v-model="selectedNs"
          class="field-select"
          style="min-width:160px"
        >
          <option value="">All namespaces</option>
          <option v-for="ns in namespaces" :key="ns.name || ns" :value="ns.name || ns">
            {{ ns.name || ns }}
          </option>
        </select>
      </div>
      <div style="display:flex;gap:.3rem;align-self:flex-end">
        <button
          class="btn btn-xs"
          :class="subTab === 'pods' ? 'btn-primary' : ''"
          @click="subTab = 'pods'"
        >Pods</button>
        <button
          class="btn btn-xs"
          :class="subTab === 'deployments' ? 'btn-primary' : ''"
          @click="subTab = 'deployments'"
        >Deployments</button>
      </div>
      <button
        class="btn btn-xs"
        style="align-self:flex-end"
        @click="fetchPods(selectedNs); fetchDeployments(selectedNs)"
        :disabled="loading"
      >
        <i class="fas fa-sync-alt" :class="loading ? 'fa-spin' : ''"></i>
      </button>
    </div>

    <!-- Pods tab -->
    <div v-show="subTab === 'pods'">
      <div v-if="loading" class="empty-msg">Loading pods...</div>
      <div v-else-if="pods.length === 0" class="empty-msg">No pods found.</div>
      <div v-else style="overflow-x:auto">
        <table style="width:100%;font-size:.78rem;border-collapse:collapse">
          <thead>
            <tr style="border-bottom:2px solid var(--border)">
              <th style="padding:.3rem;text-align:left">Namespace</th>
              <th style="padding:.3rem;text-align:left">Pod</th>
              <th style="padding:.3rem;text-align:center">Status</th>
              <th style="padding:.3rem;text-align:center">Restarts</th>
              <th style="padding:.3rem;text-align:left">Node</th>
              <th style="padding:.3rem;text-align:center">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="pod in pods"
              :key="(pod.namespace || '') + '/' + pod.name"
              style="border-bottom:1px solid var(--border)"
            >
              <td style="padding:.3rem;font-size:.7rem;color:var(--text-dim)">{{ pod.namespace || '-' }}</td>
              <td style="padding:.3rem;font-family:monospace;font-size:.75rem">{{ pod.name }}</td>
              <td style="padding:.3rem;text-align:center">
                <span class="badge" :class="podStatusClass(pod.phase)" style="font-size:.58rem">
                  {{ pod.phase || 'unknown' }}
                </span>
              </td>
              <td style="padding:.3rem;text-align:center">{{ pod.restarts ?? '-' }}</td>
              <td style="padding:.3rem;font-size:.72rem">{{ pod.node || '-' }}</td>
              <td style="padding:.3rem;text-align:center">
                <button
                  class="btn btn-xs"
                  title="View logs"
                  @click="fetchPodLogs(pod.namespace || selectedNs, pod.name)"
                >
                  <i class="fas fa-file-alt"></i>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Deployments tab -->
    <div v-show="subTab === 'deployments'">
      <div v-if="deployments.length === 0" class="empty-msg">No deployments found.</div>
      <div v-else style="overflow-x:auto">
        <table style="width:100%;font-size:.78rem;border-collapse:collapse">
          <thead>
            <tr style="border-bottom:2px solid var(--border)">
              <th style="padding:.3rem;text-align:left">Namespace</th>
              <th style="padding:.3rem;text-align:left">Deployment</th>
              <th style="padding:.3rem;text-align:center">Ready</th>
              <th style="padding:.3rem;text-align:center">Desired</th>
              <th v-if="authStore.isOperator" style="padding:.3rem;text-align:center">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="dep in deployments"
              :key="(dep.namespace || '') + '/' + dep.name"
              style="border-bottom:1px solid var(--border)"
            >
              <td style="padding:.3rem;font-size:.7rem;color:var(--text-dim)">{{ dep.namespace || '-' }}</td>
              <td style="padding:.3rem;font-family:monospace;font-size:.75rem">{{ dep.name }}</td>
              <td style="padding:.3rem;text-align:center">
                <span
                  :style="(dep.ready || 0) < (dep.replicas || 0) ? 'color:var(--danger)' : 'color:var(--success)'"
                >{{ dep.ready ?? '-' }}</span>
              </td>
              <td style="padding:.3rem;text-align:center">{{ dep.replicas ?? '-' }}</td>
              <td v-if="authStore.isOperator" style="padding:.3rem;text-align:center">
                <button
                  class="btn btn-xs"
                  title="Scale"
                  @click="openScale(dep.namespace || selectedNs, dep.name, dep.replicas)"
                >
                  <i class="fas fa-sliders-h"></i> Scale
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Pod logs modal -->
    <AppModal :show="showLogsModal" :title="'Logs: ' + logsTitle" width="800px" @close="showLogsModal = false">
      <div v-if="logsLoading" class="empty-msg">Loading logs...</div>
      <pre
        v-else
        style="background:var(--surface-2);border-radius:4px;padding:.6rem;font-size:.72rem;line-height:1.5;
               max-height:500px;overflow:auto;white-space:pre-wrap;word-break:break-all;font-family:'Fira Code',monospace"
      >{{ podLogs || 'No log output.' }}</pre>
    </AppModal>

    <!-- Scale modal -->
    <AppModal :show="showScaleModal" :title="'Scale Deployment: ' + scaleTitle" width="400px" @close="showScaleModal = false">
      <div style="padding:1rem">
        <label class="field-label">Desired Replicas</label>
        <input
          v-model.number="scaleValue"
          type="number"
          min="0"
          max="100"
          class="field-input"
          style="width:100%"
          @keyup.enter="doScale"
        />
        <div style="font-size:.65rem;color:var(--text-muted);margin-top:.5rem">
          Enter the number of pods to run for this deployment.
        </div>
      </div>
      <template #footer>
        <button class="btn" @click="showScaleModal = false">Cancel</button>
        <button class="btn btn-primary" :disabled="scaleLoading" @click="doScale">
          <i v-if="scaleLoading" class="fas fa-spinner fa-spin mr-sm"></i>Scale
        </button>
      </template>
    </AppModal>
  </div>
</template>
