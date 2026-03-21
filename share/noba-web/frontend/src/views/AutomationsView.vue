<script setup>
import { ref, computed, onMounted } from 'vue'
import { useApi }                   from '../composables/useApi'
import { useAuthStore }             from '../stores/auth'
import { useNotificationsStore }    from '../stores/notifications'
import { useApprovalsStore }        from '../stores/approvals'
import AppModal                     from '../components/ui/AppModal.vue'
import ConfirmDialog                from '../components/ui/ConfirmDialog.vue'
import AutomationFormModal          from '../components/automations/AutomationFormModal.vue'
import RunOutputModal               from '../components/automations/RunOutputModal.vue'
import ApprovalQueue                from '../components/automations/ApprovalQueue.vue'
import MaintenanceWindows           from '../components/automations/MaintenanceWindows.vue'

const authStore = useAuthStore()
const notify    = useNotificationsStore()
const approvalsStore = useApprovalsStore()
const { get, post, del, download } = useApi()

// ── Tabs ───────────────────────────────────────────────────────────────────
const activeTab = ref('automations')

// ── Automation list ────────────────────────────────────────────────────────
const autoList        = ref([])
const autoListLoading = ref(false)
const autoFilter      = ref('all')
const autoSearch      = ref('')
const autoStats       = ref({})

const filteredAutoList = computed(() => {
  let list = autoList.value
  if (autoFilter.value !== 'all') list = list.filter(a => a.type === autoFilter.value)
  if (autoSearch.value) {
    const q = autoSearch.value.toLowerCase()
    list = list.filter(a => a.name.toLowerCase().includes(q))
  }
  return list
})

async function fetchAutomations() {
  autoListLoading.value = true
  try {
    const data = await get('/api/automations')
    autoList.value = Array.isArray(data) ? data : []
  } catch (e) {
    notify.addToast('Failed to load automations: ' + e.message, 'error')
  } finally {
    autoListLoading.value = false
  }
}

async function fetchAutoStats() {
  try {
    const data = await get('/api/automations/stats')
    if (data && typeof data === 'object') autoStats.value = data
  } catch { /* silent */ }
}

function getAutoStat(id) {
  return autoStats.value[id] || null
}

// ── Create / Edit modal ────────────────────────────────────────────────────
const showFormModal  = ref(false)
const formModalMode  = ref('create')
const editingAuto    = ref(null)

function openCreate() {
  editingAuto.value   = null
  formModalMode.value = 'create'
  showFormModal.value = true
}

function openEdit(auto) {
  editingAuto.value   = auto
  formModalMode.value = 'edit'
  showFormModal.value = true
}

async function onSaved() {
  await fetchAutomations()
  await fetchAutoStats()
}

// ── Delete ─────────────────────────────────────────────────────────────────
const confirmRef = ref(null)

async function deleteAutomation(auto) {
  const ok = await confirmRef.value.confirm(`Delete automation "${auto.name}"?`)
  if (!ok) return
  try {
    await del(`/api/automations/${auto.id}`)
    notify.addToast('Automation deleted', 'success')
    await fetchAutomations()
    await fetchAutoStats()
  } catch (e) {
    notify.addToast('Delete failed: ' + e.message, 'error')
  }
}

// ── Run execution ──────────────────────────────────────────────────────────
const runOutputRef = ref(null)
const showRunModal = ref(false)

async function runAutomation(auto) {
  showRunModal.value = true
  await nextTick()
  runOutputRef.value?.startRun(auto)
}

// nextTick helper (inline to avoid import when unused elsewhere)
function nextTick() {
  return new Promise(r => setTimeout(r, 0))
}

// ── Run history ────────────────────────────────────────────────────────────
const showRunHistory       = ref(false)
const runHistory           = ref([])
const runHistoryLoading    = ref(false)
const showRunDetailModal   = ref(false)
const runDetailData        = ref(null)
const runDetailSteps       = ref([])
const runDetailLoading     = ref(false)

async function fetchRunHistory() {
  runHistoryLoading.value = true
  try {
    const data = await get('/api/runs?limit=50')
    runHistory.value = Array.isArray(data) ? data : []
  } catch (e) {
    notify.addToast('Failed to load run history: ' + e.message, 'error')
  } finally {
    runHistoryLoading.value = false }
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
    runDetailLoading.value = false }
}

function runStatusClass(status) {
  if (status === 'done')      return 'bs'
  if (status === 'failed')    return 'bd'
  if (status === 'running')   return 'ba'
  if (status === 'cancelled') return 'bw'
  if (status === 'timeout')   return 'bd'
  return 'bn'
}

// ── Workflow trace ─────────────────────────────────────────────────────────
const showTraceModal      = ref(false)
const traceData           = ref(null)
const traceLoading        = ref(false)

async function fetchTrace(auto) {
  traceLoading.value  = true
  showTraceModal.value = true
  traceData.value     = null
  try {
    const data = await get(`/api/automations/${auto.id}/trace`)
    traceData.value = data
  } catch (e) {
    notify.addToast('Failed to load trace: ' + e.message, 'error')
  } finally {
    traceLoading.value = false }
}

// ── Import / Export ────────────────────────────────────────────────────────
const importInputRef = ref(null)

async function exportAutomations() {
  try {
    const res = await download('/api/automations/export')
    const blob = await res.blob()
    const objUrl = URL.createObjectURL(blob)
    try {
      const a = document.createElement('a')
      a.href = objUrl; a.download = 'noba-automations.yaml'
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
    } finally { URL.revokeObjectURL(objUrl) }
    notify.addToast('Automations exported', 'success')
  } catch (e) {
    notify.addToast('Export failed: ' + e.message, 'error')
  }
}

async function importAutomations(event) {
  const file = event.target.files && event.target.files[0]
  if (!file) return
  if (!file.name.match(/\.(yaml|yml)$/i)) {
    notify.addToast('Please select a .yaml or .yml file', 'error')
    return
  }
  try {
    const body = await file.arrayBuffer()
    const authStore2 = useAuthStore()
    const res = await fetch('/api/automations/import?mode=skip', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-yaml',
        Authorization: `Bearer ${authStore2.token}`,
      },
      body,
    })
    const data = await res.json().catch(() => ({}))
    if (res.ok) {
      notify.addToast(`Imported ${data.imported}, skipped ${data.skipped}`, 'success')
      await fetchAutomations()
      await fetchAutoStats()
    } else {
      notify.addToast(data.detail || 'Import failed', 'error')
    }
  } catch (e) {
    notify.addToast('Import error: ' + e.message, 'error')
  } finally {
    event.target.value = ''
  }
}

// ── Webhooks ───────────────────────────────────────────────────────────────
const webhookList        = ref([])
const webhookListLoading = ref(false)
const showWebhookModal   = ref(false)
const lastCreatedWebhook = ref(null)
const newWebhookName     = ref('')
const newWebhookAutoId   = ref('')

async function fetchWebhooks() {
  webhookListLoading.value = true
  try {
    const data = await get('/api/webhooks')
    webhookList.value = Array.isArray(data) ? data : []
  } catch (e) {
    notify.addToast('Failed to load webhooks: ' + e.message, 'error')
  } finally {
    webhookListLoading.value = false }
}

async function createWebhook() {
  if (!newWebhookName.value.trim()) { notify.addToast('Name is required', 'error'); return }
  try {
    const data = await post('/api/webhooks', {
      name: newWebhookName.value.trim(),
      automation_id: newWebhookAutoId.value || null,
    })
    lastCreatedWebhook.value = data
    await fetchWebhooks()
    notify.addToast('Webhook created', 'success')
  } catch (e) {
    notify.addToast('Create webhook failed: ' + e.message, 'error')
  }
}

async function deleteWebhook(wh) {
  const ok = await confirmRef.value.confirm(`Delete webhook "${wh.name}"?`)
  if (!ok) return
  try {
    await del(`/api/webhooks/${wh.id}`)
    notify.addToast('Webhook deleted', 'success')
    await fetchWebhooks()
  } catch (e) {
    notify.addToast('Delete webhook failed: ' + e.message, 'error')
  }
}

function webhookUrl(hookId) {
  return `${window.location.origin}/hooks/${hookId}`
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    notify.addToast('Copied to clipboard', 'success')
  } catch {
    notify.addToast('Copy failed', 'error')
  }
}

function openWebhookModal() {
  newWebhookName.value     = ''
  newWebhookAutoId.value   = ''
  lastCreatedWebhook.value = null
  showWebhookModal.value   = true
}

// ── Lifecycle ──────────────────────────────────────────────────────────────
onMounted(async () => {
  await fetchAutomations()
  await fetchAutoStats()
  if (authStore.isAdmin) await fetchWebhooks()
  approvalsStore.fetchCount()
})
</script>

<template>
  <div>
    <!-- Page header -->
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem">
      <h2 style="margin:0">
        <i class="fas fa-bolt" style="margin-right:.5rem;color:var(--accent)"></i>
        Automations
      </h2>
      <div v-if="authStore.isOperator" style="display:flex;gap:.4rem;flex-wrap:wrap">
        <button class="btn btn-sm btn-primary" @click="openCreate">
          <i class="fas fa-plus" style="margin-right:.3rem"></i>New
        </button>
        <button class="btn btn-sm" :disabled="autoListLoading" @click="fetchAutomations">
          <i class="fas" :class="autoListLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i>
        </button>
        <button class="btn btn-sm" @click="showRunHistory = !showRunHistory">
          <i class="fas fa-history" style="margin-right:.3rem"></i>History
        </button>
        <button class="btn btn-sm" @click="exportAutomations">
          <i class="fas fa-download" style="margin-right:.3rem"></i>Export
        </button>
        <label class="btn btn-sm" style="cursor:pointer;margin:0">
          <i class="fas fa-upload" style="margin-right:.3rem"></i>Import
          <input
            ref="importInputRef"
            type="file"
            accept=".yaml,.yml"
            style="display:none"
            @change="importAutomations"
          />
        </label>
      </div>
    </div>

    <!-- Tab bar -->
    <div style="display:flex;gap:.25rem;border-bottom:1px solid var(--border);margin-bottom:1rem">
      <button
        class="btn btn-xs"
        :class="activeTab === 'automations' ? 'btn-primary' : ''"
        style="border-radius:4px 4px 0 0;border-bottom:none"
        @click="activeTab = 'automations'"
      >
        <i class="fas fa-bolt" style="margin-right:.25rem"></i>Automations
      </button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'approvals' ? 'btn-primary' : ''"
        style="border-radius:4px 4px 0 0;border-bottom:none;position:relative"
        @click="activeTab = 'approvals'; approvalsStore.fetchPending()"
      >
        <i class="fas fa-check-circle" style="margin-right:.25rem"></i>Approvals
        <span
          v-if="(approvalsStore.count || 0) > 0"
          style="
            position:absolute;top:-4px;right:-4px;
            background:var(--warning, #f0a500);
            color:#000;
            border-radius:50%;
            font-size:.55rem;
            min-width:14px;
            height:14px;
            display:flex;
            align-items:center;
            justify-content:center;
            padding:0 2px;
            font-weight:700;
          "
        >{{ approvalsStore.count }}</span>
      </button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'maintenance' ? 'btn-primary' : ''"
        style="border-radius:4px 4px 0 0;border-bottom:none"
        @click="activeTab = 'maintenance'"
      >
        <i class="fas fa-wrench" style="margin-right:.25rem"></i>Maintenance
      </button>
    </div>

    <!-- Approvals tab content -->
    <div v-if="activeTab === 'approvals'">
      <ApprovalQueue />
    </div>

    <!-- Maintenance tab content -->
    <div v-if="activeTab === 'maintenance'">
      <MaintenanceWindows />
    </div>

    <!-- Automations tab content -->
    <div v-if="activeTab === 'automations'">

    <!-- Filter bar -->
    <div style="display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.8rem;align-items:center">
      <template v-for="tab in ['all','script','webhook','workflow','cron','alert']" :key="tab">
        <button
          class="btn btn-xs"
          :class="autoFilter === tab ? 'btn-primary' : ''"
          @click="autoFilter = tab"
        >{{ tab }}</button>
      </template>
      <input
        v-model="autoSearch"
        type="text"
        placeholder="Search..."
        style="
          margin-left:auto;
          background:var(--surface);
          border:1px solid var(--border);
          border-radius:4px;
          color:var(--text);
          padding:.25rem .5rem;
          font-size:.8rem;
          width:160px;
        "
      />
    </div>

    <!-- Loading state -->
    <div v-if="autoListLoading" class="empty-msg">Loading...</div>

    <!-- Empty state -->
    <div v-else-if="filteredAutoList.length === 0" class="empty-msg">
      {{ autoSearch || autoFilter !== 'all' ? 'No automations match the filter.' : 'No automations defined yet.' }}
    </div>

    <!-- Automation grid -->
    <div
      v-else
      style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:.8rem;margin-bottom:1.5rem"
    >
      <div
        v-for="a in filteredAutoList"
        :key="a.id"
        style="padding:.8rem;border:1px solid var(--border);border-radius:6px;background:var(--surface-2)"
      >
        <!-- Header row -->
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.4rem">
          <span style="font-weight:600;font-size:.85rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0">
            {{ a.name }}
          </span>
          <div style="display:flex;gap:.3rem;align-items:center;flex-shrink:0;margin-left:.4rem">
            <span class="badge" :class="a.enabled ? 'bs' : 'bw'" style="font-size:.55rem">
              {{ a.enabled ? 'on' : 'off' }}
            </span>
            <span class="badge bn" style="font-size:.55rem">{{ a.type }}</span>
          </div>
        </div>

        <!-- Meta -->
        <div style="font-size:.7rem;color:var(--text-muted);margin-bottom:.4rem">
          <div v-if="a.schedule">Schedule: {{ a.schedule }}</div>
          <div v-if="a.last_run">
            Last run: {{ new Date(a.last_run * 1000).toLocaleString() }}
          </div>
          <div v-if="getAutoStat(a.id)" style="display:flex;gap:.6rem;margin-top:.2rem">
            <span>Runs: {{ getAutoStat(a.id).total || 0 }}</span>
            <span style="color:var(--success)">
              OK: {{ getAutoStat(a.id).done || 0 }}
            </span>
            <span v-if="(getAutoStat(a.id).failed || 0) > 0" style="color:var(--danger)">
              Fail: {{ getAutoStat(a.id).failed }}
            </span>
          </div>
        </div>

        <!-- Actions (operator+) -->
        <div v-if="authStore.isOperator" style="display:flex;gap:.3rem;flex-wrap:wrap">
          <button
            class="btn btn-xs btn-primary"
            :disabled="!a.enabled"
            title="Run now"
            @click="runAutomation(a)"
          >
            <i class="fas fa-play"></i>
          </button>
          <button class="btn btn-xs" title="Edit" @click="openEdit(a)">
            <i class="fas fa-pen"></i>
          </button>
          <button
            v-if="a.type === 'workflow'"
            class="btn btn-xs"
            title="Workflow trace"
            @click="fetchTrace(a)"
          >
            <i class="fas fa-project-diagram"></i>
          </button>
          <button
            class="btn btn-xs btn-danger"
            title="Delete"
            @click="deleteAutomation(a)"
          >
            <i class="fas fa-trash"></i>
          </button>
        </div>
      </div>
    </div>

    <!-- Run History panel -->
    <div v-if="showRunHistory" style="margin-bottom:1.5rem">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.6rem">
        <span style="font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted)">
          <i class="fas fa-history" style="margin-right:.3rem"></i>Run History
        </span>
        <button
          class="btn btn-xs"
          :disabled="runHistoryLoading"
          @click="fetchRunHistory"
        >
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
            <tr
              v-for="run in runHistory"
              :key="run.id"
              style="border-bottom:1px solid var(--border)"
            >
              <td style="padding:.4rem;opacity:.6">{{ run.id }}</td>
              <td style="padding:.4rem">
                {{ (autoList.find(a => a.id === run.automation_id) || {}).name || run.automation_id || '—' }}
              </td>
              <td style="padding:.4rem;opacity:.7;font-size:.72rem">{{ run.trigger || '—' }}</td>
              <td style="padding:.4rem;text-align:center">
                <span class="badge" :class="runStatusClass(run.status)" style="font-size:.55rem">
                  {{ run.status }}
                </span>
              </td>
              <td style="padding:.4rem;text-align:center">
                {{ run.finished_at && run.started_at ? (run.finished_at - run.started_at) + 's' : '—' }}
              </td>
              <td style="padding:.4rem;text-align:center;font-size:.72rem">
                {{ run.started_at ? new Date(run.started_at * 1000).toLocaleString() : '—' }}
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
    </div>

    <!-- Webhooks section (admin only) -->
    <div v-if="authStore.isAdmin" style="margin-top:.5rem">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.6rem">
        <h3 style="margin:0;font-size:.9rem">
          <i class="fas fa-link" style="margin-right:.4rem"></i>Webhooks
        </h3>
        <div style="display:flex;gap:.4rem">
          <button class="btn btn-sm btn-primary" @click="openWebhookModal">
            <i class="fas fa-plus" style="margin-right:.3rem"></i>New Webhook
          </button>
          <button class="btn btn-sm" :disabled="webhookListLoading" @click="fetchWebhooks">
            <i class="fas" :class="webhookListLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i>
          </button>
        </div>
      </div>

      <div v-if="webhookListLoading" class="empty-msg">Loading...</div>
      <div v-else-if="webhookList.length === 0" class="empty-msg">
        No webhooks configured. Create one to receive external triggers.
      </div>
      <div v-else style="overflow-x:auto">
        <table style="width:100%;font-size:.78rem;border-collapse:collapse">
          <thead>
            <tr style="border-bottom:1px solid var(--border)">
              <th style="padding:.4rem;text-align:left">Name</th>
              <th style="padding:.4rem;text-align:left">URL</th>
              <th style="padding:.4rem;text-align:left">Automation</th>
              <th style="padding:.4rem;text-align:center">Triggers</th>
              <th style="padding:.4rem;text-align:center">Last Triggered</th>
              <th style="padding:.4rem;text-align:center">Enabled</th>
              <th style="padding:.4rem;text-align:center">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="wh in webhookList"
              :key="wh.id"
              style="border-bottom:1px solid var(--border)"
            >
              <td style="padding:.4rem;font-weight:500">{{ wh.name }}</td>
              <td style="padding:.4rem">
                <code
                  style="font-size:.65rem;background:var(--surface);padding:1px 4px;border-radius:3px;word-break:break-all"
                >{{ webhookUrl(wh.hook_id) }}</code>
                <button
                  class="btn btn-xs"
                  style="margin-left:.3rem;padding:1px 4px"
                  title="Copy URL"
                  @click="copyToClipboard(webhookUrl(wh.hook_id))"
                >
                  <i class="fas fa-copy"></i>
                </button>
              </td>
              <td style="padding:.4rem;font-size:.75rem">
                {{ wh.automation_id
                    ? (autoList.find(a => a.id === wh.automation_id) || {}).name || wh.automation_id
                    : '(none)' }}
              </td>
              <td style="padding:.4rem;text-align:center">{{ wh.trigger_count || 0 }}</td>
              <td style="padding:.4rem;text-align:center;font-size:.7rem">
                {{ wh.last_triggered ? new Date(wh.last_triggered * 1000).toLocaleString() : 'Never' }}
              </td>
              <td style="padding:.4rem;text-align:center">
                <span class="badge" :class="wh.enabled ? 'bs' : 'bw'" style="font-size:.55rem">
                  {{ wh.enabled ? 'Yes' : 'No' }}
                </span>
              </td>
              <td style="padding:.4rem;text-align:center">
                <button class="btn btn-xs btn-danger" title="Delete" @click="deleteWebhook(wh)">
                  <i class="fas fa-trash"></i>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    </div><!-- end automations tab content -->

    <!-- ── Modals ──────────────────────────────────────────────────────── -->

    <!-- Create / Edit automation -->
    <AutomationFormModal
      :show="showFormModal"
      :mode="formModalMode"
      :initial="editingAuto || {}"
      :automations="autoList"
      @close="showFormModal = false"
      @saved="onSaved"
    />

    <!-- Run output -->
    <RunOutputModal
      ref="runOutputRef"
      :show="showRunModal"
      @close="showRunModal = false"
    />

    <!-- Run detail modal -->
    <AppModal
      :show="showRunDetailModal"
      title="Run Detail"
      width="680px"
      @close="showRunDetailModal = false"
    >
      <div style="padding:1rem">
        <div v-if="runDetailLoading" class="empty-msg">Loading...</div>
        <template v-else-if="runDetailData">
          <!-- Summary -->
          <div
            style="display:grid;grid-template-columns:1fr 1fr;gap:.4rem .8rem;font-size:.8rem;margin-bottom:.8rem"
          >
            <div><span style="color:var(--text-muted)">ID:</span> {{ runDetailData.id }}</div>
            <div>
              <span style="color:var(--text-muted)">Status:</span>
              <span class="badge" :class="runStatusClass(runDetailData.status)" style="font-size:.6rem;margin-left:.3rem">
                {{ runDetailData.status }}
              </span>
            </div>
            <div><span style="color:var(--text-muted)">Trigger:</span> {{ runDetailData.trigger || '—' }}</div>
            <div>
              <span style="color:var(--text-muted)">Duration:</span>
              {{ runDetailData.finished_at && runDetailData.started_at
                  ? (runDetailData.finished_at - runDetailData.started_at) + 's'
                  : '—' }}
            </div>
          </div>

          <!-- Output -->
          <div style="font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--text-muted);margin-bottom:.3rem">
            Output
          </div>
          <pre
            style="
              background:#0e0e10;color:#e0e0e0;font-family:monospace;font-size:.73rem;
              line-height:1.5;padding:.6rem;border-radius:4px;
              max-height:300px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;
            "
          >{{ runDetailData.output || '(no output)' }}</pre>

          <!-- Error -->
          <div
            v-if="runDetailData.error"
            style="margin-top:.5rem;padding:.5rem;background:color-mix(in srgb, var(--danger) 10%, var(--surface));border:1px solid var(--danger);border-radius:4px;font-size:.78rem;font-family:monospace"
          >
            {{ runDetailData.error }}
          </div>

          <!-- Workflow steps -->
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
                <span>
                  {{ (autoList.find(a => a.id === step.automation_id) || {}).name || step.automation_id }}
                </span>
                <span class="badge" :class="runStatusClass(step.status)" style="font-size:.55rem">
                  {{ step.status }}
                </span>
              </div>
            </div>
          </div>
        </template>
      </div>
      <template #footer>
        <button class="btn" @click="showRunDetailModal = false">Close</button>
      </template>
    </AppModal>

    <!-- Workflow trace modal -->
    <AppModal
      :show="showTraceModal"
      title="Workflow Trace"
      width="620px"
      @close="showTraceModal = false"
    >
      <div style="padding:1rem">
        <div v-if="traceLoading" class="empty-msg">Loading...</div>
        <div v-else-if="!traceData" class="empty-msg">No trace data available.</div>
        <template v-else>
          <!-- Execution steps list -->
          <div
            v-if="traceData.steps && traceData.steps.length"
            style="display:flex;flex-direction:column;gap:.4rem"
          >
            <div
              v-for="(step, i) in traceData.steps"
              :key="i"
              style="display:flex;align-items:center;gap:.5rem;padding:.4rem .6rem;border:1px solid var(--border);border-radius:5px;font-size:.8rem"
            >
              <span
                style="font-size:.7rem;opacity:.5;min-width:1.5rem;text-align:right"
              >{{ i + 1 }}</span>
              <i
                class="fas"
                :class="step.status === 'done' ? 'fa-check-circle' : step.status === 'failed' ? 'fa-times-circle' : 'fa-circle'"
                :style="step.status === 'done' ? 'color:var(--success)' : step.status === 'failed' ? 'color:var(--danger)' : 'color:var(--text-muted)'"
              ></i>
              <span style="flex:1">
                {{ step.name || step.automation_id || ('Step ' + (i + 1)) }}
              </span>
              <span v-if="step.duration" style="opacity:.6;font-size:.72rem">{{ step.duration }}s</span>
              <span class="badge" :class="runStatusClass(step.status)" style="font-size:.55rem">
                {{ step.status || 'pending' }}
              </span>
            </div>
          </div>
          <!-- Raw JSON fallback -->
          <pre
            v-else
            style="background:#0e0e10;color:#e0e0e0;font-family:monospace;font-size:.73rem;
                   padding:.6rem;border-radius:4px;max-height:300px;overflow-y:auto;white-space:pre-wrap"
          >{{ JSON.stringify(traceData, null, 2) }}</pre>
        </template>
      </div>
      <template #footer>
        <button class="btn" @click="showTraceModal = false">Close</button>
      </template>
    </AppModal>

    <!-- Webhook create modal -->
    <AppModal
      :show="showWebhookModal"
      title="Create Webhook"
      width="500px"
      @close="showWebhookModal = false"
    >
      <div style="padding:1rem;display:flex;flex-direction:column;gap:.75rem">
        <div>
          <label class="field-label">Name</label>
          <input
            v-model="newWebhookName"
            type="text"
            class="field-input"
            placeholder="GitHub Deploy Hook"
            style="width:100%"
          />
        </div>
        <div>
          <label class="field-label">Linked Automation (optional)</label>
          <select v-model="newWebhookAutoId" class="field-input" style="width:100%">
            <option value="">None</option>
            <option
              v-for="a in autoList"
              :key="a.id"
              :value="a.id"
            >{{ a.name }} ({{ a.type }})</option>
          </select>
        </div>

        <!-- Created webhook details -->
        <div
          v-if="lastCreatedWebhook"
          style="padding:.6rem;background:var(--surface);border:1px solid var(--border);border-radius:6px"
        >
          <div style="font-weight:600;font-size:.8rem;margin-bottom:.4rem;color:var(--success)">
            <i class="fas fa-check-circle"></i> Webhook Created
          </div>
          <label class="field-label">Webhook URL</label>
          <div style="display:flex;gap:.3rem;margin-bottom:.5rem">
            <code
              style="flex:1;font-size:.65rem;background:var(--surface-2);padding:4px 6px;border-radius:3px;word-break:break-all"
            >{{ webhookUrl(lastCreatedWebhook.hook_id) }}</code>
            <button class="btn btn-xs" @click="copyToClipboard(webhookUrl(lastCreatedWebhook.hook_id))">
              <i class="fas fa-copy"></i>
            </button>
          </div>
          <label class="field-label">Secret (for HMAC-SHA256 signing)</label>
          <div style="display:flex;gap:.3rem">
            <code
              style="flex:1;font-size:.65rem;background:var(--surface-2);padding:4px 6px;border-radius:3px;word-break:break-all"
            >{{ lastCreatedWebhook.secret }}</code>
            <button class="btn btn-xs" @click="copyToClipboard(lastCreatedWebhook.secret)">
              <i class="fas fa-copy"></i>
            </button>
          </div>
          <div style="font-size:.65rem;color:var(--text-muted);margin-top:.4rem">
            <i class="fas fa-info-circle"></i> Save the secret now. It will not be shown again.
          </div>
        </div>
      </div>

      <template #footer>
        <button class="btn" @click="showWebhookModal = false">Close</button>
        <button
          v-if="!lastCreatedWebhook"
          class="btn btn-primary"
          @click="createWebhook"
        >
          <i class="fas fa-plus" style="margin-right:.3rem"></i>Create
        </button>
      </template>
    </AppModal>

    <!-- Confirm dialog -->
    <ConfirmDialog ref="confirmRef" />
  </div>
</template>

<style scoped>
.field-input {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  padding: .4rem .5rem;
  font-size: .85rem;
  box-sizing: border-box;
}
.field-input:focus { outline: none; border-color: var(--accent); }
</style>
