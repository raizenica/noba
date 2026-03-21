<script setup>
import { ref, computed, watch } from 'vue'
import AppModal from '../ui/AppModal.vue'
import WorkflowBuilder from './WorkflowBuilder.vue'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const props = defineProps({
  show: Boolean,
  mode: { type: String, default: 'create' }, // 'create' | 'edit'
  initial: { type: Object, default: () => ({}) },
  automations: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'saved'])

const notify = useNotificationsStore()
const { get, post, put, loading } = useApi()

// ── Form state ─────────────────────────────────────────────────────────────
const form = ref({
  id: '',
  name: '',
  type: 'script',
  config: {},
  schedule: '',
  enabled: true,
})

// Per-type config fields (string representations)
const configScript   = ref('')   // script: path
const configWebhook  = ref('')   // webhook: url
const configWorkflow = ref('[]') // workflow: steps JSON
const configCron     = ref('')   // cron: expression
const configAlert    = ref('')   // alert: condition

// Workflow visual editor state
const workflowTab    = ref('visual')  // 'visual' | 'code'
const workflowGraph  = ref({ nodes: [], edges: [], entry: '' })

// ── Templates ─────────────────────────────────────────────────────────────
const templates        = ref([])
const showTemplates    = ref(false)
const templatesLoading = ref(false)

async function loadTemplates() {
  if (templates.value.length) { showTemplates.value = !showTemplates.value; return }
  templatesLoading.value = true
  try {
    const data = await get('/api/automations/templates')
    templates.value = Array.isArray(data) ? data : []
    showTemplates.value = true
  } catch (e) {
    notify.addToast('Failed to load templates: ' + e.message, 'error')
  } finally {
    templatesLoading.value = false }
}

function applyTemplate(tpl) {
  form.value.name     = tpl.name
  form.value.type     = tpl.type
  form.value.schedule = tpl.schedule || ''
  form.value.enabled  = true
  syncConfigFromObject(tpl.config || {}, tpl.type)
  showTemplates.value = false
}

// ── Sync helpers ──────────────────────────────────────────────────────────
function syncConfigFromObject(cfg, type) {
  const t = type || form.value.type
  if (t === 'script')   configScript.value   = cfg.path || ''
  if (t === 'webhook')  configWebhook.value  = cfg.url || ''
  if (t === 'workflow') {
    // Support both legacy steps-array format and new graph format
    if (cfg.nodes) {
      workflowGraph.value  = { nodes: cfg.nodes || [], edges: cfg.edges || [], entry: cfg.entry || '' }
      configWorkflow.value = JSON.stringify(workflowGraph.value, null, 2)
    } else {
      configWorkflow.value = JSON.stringify(cfg.steps || [], null, 2)
      workflowGraph.value  = { nodes: [], edges: [], entry: '' }
    }
    workflowTab.value = 'visual'
  }
  if (t === 'cron')     configCron.value     = cfg.expression || ''
  if (t === 'alert')    configAlert.value    = cfg.condition || ''
}

function buildConfigObject() {
  const t = form.value.type
  if (t === 'script')   return { path: configScript.value.trim() }
  if (t === 'webhook')  return { url: configWebhook.value.trim() }
  if (t === 'workflow') {
    if (workflowTab.value === 'code') {
      // Code tab is authoritative if user was editing there
      try {
        const parsed = JSON.parse(configWorkflow.value)
        // Accept either graph format or legacy steps array
        if (Array.isArray(parsed)) return { steps: parsed }
        return { nodes: parsed.nodes || [], edges: parsed.edges || [], entry: parsed.entry || '' }
      } catch { /* fall through to graph */ }
    }
    return {
      nodes: workflowGraph.value.nodes || [],
      edges: workflowGraph.value.edges || [],
      entry: workflowGraph.value.entry || '',
    }
  }
  if (t === 'cron')  return { expression: configCron.value.trim() }
  if (t === 'alert') return { condition: configAlert.value.trim() }
  return {}
}

// ── Workflow validation ────────────────────────────────────────────────────
const validating = ref(false)
async function validateWorkflow() {
  let steps
  try { steps = JSON.parse(configWorkflow.value) }
  catch { notify.addToast('Invalid JSON in workflow steps', 'error'); return }
  validating.value = true
  try {
    const data = await post('/api/automations/validate-workflow', { steps })
    if (data && data.valid) notify.addToast('Workflow valid — all steps found', 'success')
    else notify.addToast('Invalid — some steps not found', 'error')
  } catch (e) {
    notify.addToast('Validation error: ' + e.message, 'error')
  } finally { validating.value = false }
}

// ── Reset / populate on open ───────────────────────────────────────────────
watch(() => props.show, (v) => {
  if (!v) return
  showTemplates.value = false
  if (props.mode === 'edit' && props.initial && props.initial.id) {
    form.value = {
      id:       props.initial.id,
      name:     props.initial.name || '',
      type:     props.initial.type || 'script',
      config:   props.initial.config || {},
      schedule: props.initial.schedule || '',
      enabled:  props.initial.enabled !== false,
    }
    syncConfigFromObject(props.initial.config || {}, props.initial.type)
  } else {
    form.value = { id: '', name: '', type: 'script', config: {}, schedule: '', enabled: true }
    configScript.value   = ''
    configWebhook.value  = ''
    configWorkflow.value = '[]'
    configCron.value     = ''
    configAlert.value    = ''
    workflowGraph.value  = { nodes: [], edges: [], entry: '' }
    workflowTab.value    = 'visual'
  }
})

// ── Save ──────────────────────────────────────────────────────────────────
async function save() {
  if (!form.value.name.trim()) { notify.addToast('Name is required', 'error'); return }
  const payload = {
    name:     form.value.name.trim(),
    type:     form.value.type,
    config:   buildConfigObject(),
    schedule: form.value.schedule || null,
    enabled:  form.value.enabled,
  }
  try {
    if (props.mode === 'create') {
      await post('/api/automations', payload)
    } else {
      await put(`/api/automations/${form.value.id}`, payload)
    }
    notify.addToast(
      props.mode === 'create' ? 'Automation created' : 'Automation updated',
      'success',
    )
    emit('saved')
    emit('close')
  } catch (e) {
    notify.addToast('Save failed: ' + e.message, 'error')
  }
}

const title = computed(() =>
  props.mode === 'create' ? 'New Automation' : 'Edit Automation',
)
</script>

<template>
  <AppModal
    :show="show"
    :title="title"
    :width="form.type === 'workflow' && workflowTab === 'visual' ? '1200px' : '560px'"
    @close="emit('close')"
  >
    <div style="padding:1rem;display:flex;flex-direction:column;gap:.75rem">

      <!-- Template picker toggle -->
      <div style="display:flex;justify-content:flex-end">
        <button
          class="btn btn-xs btn-secondary"
          :disabled="templatesLoading"
          @click="loadTemplates"
        >
          <i class="fas" :class="templatesLoading ? 'fa-spinner fa-spin' : 'fa-magic'"></i>
          Templates
        </button>
      </div>

      <!-- Template list -->
      <div
        v-if="showTemplates && templates.length"
        style="border:1px solid var(--border);border-radius:5px;padding:.5rem;background:var(--surface-2);max-height:150px;overflow-y:auto"
      >
        <div style="font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--text-muted);margin-bottom:.4rem">
          Pick a template
        </div>
        <div
          v-for="tpl in templates"
          :key="tpl.name"
          style="display:flex;justify-content:space-between;align-items:center;padding:.25rem .4rem;cursor:pointer;border-radius:3px"
          class="tpl-row"
          @click="applyTemplate(tpl)"
        >
          <span style="font-size:.8rem">{{ tpl.name }}</span>
          <span class="badge bn" style="font-size:.55rem">{{ tpl.type }}</span>
        </div>
      </div>
      <div v-else-if="showTemplates && !templatesLoading" style="font-size:.8rem;color:var(--text-muted)">
        No templates available.
      </div>

      <!-- Name -->
      <div>
        <label class="field-label">Name <span style="color:var(--danger)">*</span></label>
        <input
          v-model="form.name"
          type="text"
          class="field-input"
          placeholder="My Automation"
          style="width:100%"
        />
      </div>

      <!-- Type -->
      <div>
        <label class="field-label">Type</label>
        <select v-model="form.type" class="field-input" style="width:100%">
          <option value="script">Script</option>
          <option value="webhook">Webhook</option>
          <option value="workflow">Workflow</option>
          <option value="cron">Cron</option>
          <option value="alert">Alert</option>
        </select>
      </div>

      <!-- Config: script -->
      <div v-if="form.type === 'script'">
        <label class="field-label">Script Path</label>
        <input
          v-model="configScript"
          type="text"
          class="field-input"
          placeholder="/opt/scripts/backup.sh"
          style="width:100%"
        />
      </div>

      <!-- Config: webhook -->
      <div v-if="form.type === 'webhook'">
        <label class="field-label">Webhook URL</label>
        <input
          v-model="configWebhook"
          type="text"
          class="field-input"
          placeholder="https://example.com/hook"
          style="width:100%"
        />
      </div>

      <!-- Config: workflow -->
      <div v-if="form.type === 'workflow'">
        <!-- Tab bar -->
        <div class="wf-tab-bar">
          <button
            class="wf-tab"
            :class="{ 'wf-tab-active': workflowTab === 'visual' }"
            @click="workflowTab = 'visual'"
          >
            <i class="fas fa-project-diagram"></i> Visual
          </button>
          <button
            class="wf-tab"
            :class="{ 'wf-tab-active': workflowTab === 'code' }"
            @click="workflowTab = 'code'"
          >
            <i class="fas fa-code"></i> Code
          </button>
          <button
            v-if="workflowTab === 'code'"
            class="btn btn-xs"
            style="margin-left:auto"
            :disabled="validating"
            @click="validateWorkflow"
          >
            <i class="fas" :class="validating ? 'fa-spinner fa-spin' : 'fa-check-circle'"></i>
            Validate
          </button>
        </div>

        <!-- Visual tab -->
        <div v-if="workflowTab === 'visual'" style="margin-top:.25rem">
          <WorkflowBuilder v-model="workflowGraph" />
        </div>

        <!-- Code tab -->
        <div v-if="workflowTab === 'code'" style="margin-top:.25rem">
          <textarea
            v-model="configWorkflow"
            class="field-input"
            style="width:100%;font-family:monospace;font-size:.75rem;min-height:160px;resize:vertical"
            placeholder='{"nodes":[],"edges":[],"entry":""}'
          ></textarea>
        </div>
      </div>

      <!-- Config: cron -->
      <div v-if="form.type === 'cron'">
        <label class="field-label">Cron Expression</label>
        <input
          v-model="configCron"
          type="text"
          class="field-input"
          placeholder="0 */6 * * *"
          style="width:100%"
        />
      </div>

      <!-- Config: alert -->
      <div v-if="form.type === 'alert'">
        <label class="field-label">Alert Condition</label>
        <input
          v-model="configAlert"
          type="text"
          class="field-input"
          placeholder="cpu_percent > 90"
          style="width:100%"
        />
      </div>

      <!-- Schedule -->
      <div>
        <label class="field-label">Schedule (cron, optional)</label>
        <input
          v-model="form.schedule"
          type="text"
          class="field-input"
          placeholder="*/15 * * * *"
          style="width:100%"
        />
      </div>

      <!-- Enabled toggle -->
      <div style="display:flex;align-items:center;gap:.5rem">
        <input
          id="auto-enabled"
          v-model="form.enabled"
          type="checkbox"
          style="width:1rem;height:1rem;accent-color:var(--accent)"
        />
        <label for="auto-enabled" style="font-size:.85rem;cursor:pointer">Enabled</label>
      </div>
    </div>

    <template #footer>
      <button class="btn" @click="emit('close')">Cancel</button>
      <button class="btn btn-primary" :disabled="loading" @click="save">
        <i v-if="loading" class="fas fa-spinner fa-spin" style="margin-right:.3rem"></i>
        {{ mode === 'create' ? 'Create' : 'Save' }}
      </button>
    </template>
  </AppModal>
</template>

<style scoped>
.tpl-row:hover { background: var(--surface); }

/* Workflow tab bar */
.wf-tab-bar {
  display: flex;
  align-items: center;
  gap: .25rem;
  border-bottom: 1px solid var(--border);
  margin-bottom: .1rem;
  padding-bottom: .25rem;
}
.wf-tab {
  display: inline-flex;
  align-items: center;
  gap: .25rem;
  padding: .2rem .55rem;
  border-radius: 4px 4px 0 0;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-muted);
  font-size: .75rem;
  cursor: pointer;
  transition: background .12s, color .12s;
}
.wf-tab:hover { color: var(--text); background: var(--surface-2); }
.wf-tab-active {
  background: var(--surface-2);
  border-color: var(--border);
  border-bottom-color: var(--surface-2);
  color: var(--accent);
  font-weight: 600;
}

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
