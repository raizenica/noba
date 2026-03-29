<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import AutonomySelector from '../automations/AutonomySelector.vue'

const authStore = useAuthStore()
const { get, put } = useApi()

const alertRules = ref([])
const loading = ref(false)
const saveMsg = ref('')

const editIdx = ref(-1)
const draft = reactive({})

const METRICS = ['cpuPercent', 'memPercent', 'cpuTemp', 'gpuTemp', 'disk_percent', 'ping_ms']
const CHANNELS = ['email', 'telegram', 'discord', 'slack', 'pushover', 'gotify']

onMounted(() => fetchRules())

async function fetchRules() {
  loading.value = true
  try {
    const d = await get('/api/alert-rules')
    alertRules.value = Array.isArray(d) ? d : (d.rules || [])
  } catch { /* silent */ }
  finally { loading.value = false }
}

async function saveRules() {
  saveMsg.value = ''
  try {
    await put('/api/alert-rules', { rules: alertRules.value })
    saveMsg.value = 'Saved.'
    setTimeout(() => { saveMsg.value = '' }, 2500)
  } catch (err) {
    saveMsg.value = err?.message || 'Save failed.'
  }
}

function startEdit(idx) {
  editIdx.value = idx
  Object.assign(draft, JSON.parse(JSON.stringify(alertRules.value[idx])))
  draft._actionType = draft.action?.type || ''
  draft._actionTarget = draft.action?.params?.container || draft.action?.params?.service || ''
  draft._actionAgent = draft.action?.target || ''
}

function cancelEdit() {
  editIdx.value = -1
}

function applyEdit(idx) {
  const r = { ...draft }
  if (r._actionType) {
    const paramKey = r._actionType === 'restart_service' ? 'service' : 'container'
    r.action = { type: r._actionType, target: r._actionAgent || '', params: { [paramKey]: r._actionTarget || '' } }
  } else {
    delete r.action
  }
  delete r._actionType
  delete r._actionTarget
  delete r._actionAgent
  alertRules.value[idx] = r
  editIdx.value = -1
}

function addRule() {
  const newRule = {
    id: 'rule-' + crypto.randomUUID().slice(0, 8),
    condition: '',
    severity: 'warning',
    message: '',
    channels: [],
    autonomy: 'execute',
    auto_approve_timeout: 15,
    max_retries: 3,
    circuit_break_after: 5,
  }
  alertRules.value.push(newRule)
  const idx = alertRules.value.length - 1
  startEdit(idx)
}

function removeRule(idx) {
  alertRules.value.splice(idx, 1)
  if (editIdx.value === idx) editIdx.value = -1
}

function toggleChannel(ch) {
  if (!draft.channels) draft.channels = []
  const i = draft.channels.indexOf(ch)
  if (i >= 0) draft.channels.splice(i, 1)
  else draft.channels.push(ch)
}

function hasChannel(ch) {
  return (draft.channels || []).includes(ch)
}

function copyMetric(m) {
  navigator.clipboard.writeText(m).catch(() => {})
}
</script>

<template>
  <div>
    <div class="s-section">
      <span class="s-label">Alert Rules</span>
      <p style="font-size:.78rem;color:var(--text-muted);margin-bottom:1rem">
        Create rules that trigger notifications and optional self-healing actions when metric conditions are met.
      </p>

      <!-- Rules list -->
      <div
        v-for="(rule, idx) in alertRules" :key="idx"
        style="background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:.85rem 1rem;margin-bottom:.65rem"
      >
        <!-- View mode -->
        <template v-if="editIdx !== idx">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.4rem">
            <div style="display:flex;align-items:center;gap:.5rem">
              <span class="badge" :class="(rule.severity === 'danger' || rule.severity === 'critical') ? 'bd' : 'bw'" style="font-size:.6rem">
                {{ rule.severity || 'warning' }}
              </span>
              <strong style="font-size:.82rem">{{ rule.id || 'Unnamed Rule' }}</strong>
            </div>
            <div v-if="authStore.isAdmin" style="display:flex;gap:.35rem">
              <button class="btn btn-sm" style="padding:.3rem .6rem;width:auto" @click="startEdit(idx)">
                <i class="fas fa-pen"></i>
              </button>
              <button class="btn btn-sm btn-danger" style="padding:.3rem .6rem;width:auto" @click="removeRule(idx)">
                <i class="fas fa-trash"></i>
              </button>
            </div>
          </div>
          <div style="font-size:.75rem;color:var(--text-muted);font-family:var(--font-data)">{{ rule.condition }}</div>
          <div v-if="rule.message" style="font-size:.75rem;color:var(--text-muted);margin-top:.2rem">{{ rule.message }}</div>
          <div v-if="rule.action && rule.action.type" style="font-size:.7rem;color:var(--accent);margin-top:.3rem">
            <i class="fas fa-wrench" style="margin-right:.3rem"></i>
            {{ rule.action.type }}<template v-if="rule.action.target"> on <strong>{{ rule.action.target }}</strong></template>: {{ rule.action.params?.container || rule.action.params?.service || '' }}
          </div>
        </template>

        <!-- Edit mode -->
        <template v-else>
          <div class="field-2">
            <div>
              <label class="field-label">Rule ID</label>
              <input class="field-input" v-model="draft.id" placeholder="e.g. cpu-high">
            </div>
            <div>
              <label class="field-label">Severity</label>
              <select class="field-input field-select" v-model="draft.severity">
                <option value="warning">Warning</option>
                <option value="danger">Danger</option>
                <option value="critical">Critical</option>
              </select>
            </div>
          </div>
          <div style="margin-bottom:.75rem;margin-top:.5rem">
            <label class="field-label">Condition</label>
            <input class="field-input" v-model="draft.condition" placeholder="e.g. cpuPercent > 90">
          </div>
          <div style="margin-bottom:.75rem">
            <label class="field-label">Notification Message</label>
            <input class="field-input" v-model="draft.message" placeholder="e.g. CPU usage is critically high!">
          </div>
          <!-- Autonomy -->
          <div class="field-2" style="margin-bottom:.75rem">
            <div>
              <label class="field-label">Autonomy Level</label>
              <AutonomySelector v-model="draft.autonomy" />
            </div>
            <div v-if="draft.autonomy === 'approve'">
              <label class="field-label">Auto-approve timeout (minutes)</label>
              <input
                class="field-input"
                type="number"
                min="1"
                max="1440"
                v-model.number="draft.auto_approve_timeout"
                placeholder="15"
              >
            </div>
          </div>

          <div style="margin-bottom:.75rem">
            <label class="field-label">Notification Channels</label>
            <div class="toggle-grid">
              <label v-for="ch in CHANNELS" :key="ch" class="toggle-item">
                <input type="checkbox" :checked="hasChannel(ch)" @change="toggleChannel(ch)">
                <span style="text-transform:capitalize">{{ ch }}</span>
              </label>
            </div>
          </div>

          <!-- Self-healing action -->
          <div class="s-section" style="margin-top:.75rem">
            <span class="s-label" style="font-size:.58rem">Self-Healing Action (optional)</span>
            <div class="field-2">
              <div>
                <label class="field-label">Action Type</label>
                <select class="field-input field-select" v-model="draft._actionType">
                  <option value="">None</option>
                  <option value="restart_service">Restart Service</option>
                  <option value="restart_container">Restart Container</option>
                  <option value="run">Run Command</option>
                  <option value="webhook">Trigger Webhook</option>
                  <option value="automation">Run Automation</option>
                </select>
              </div>
              <div v-if="draft._actionType">
                <label class="field-label">{{ draft._actionType === 'restart_service' ? 'Service Name' : draft._actionType === 'restart_container' ? 'Container Name' : 'Target' }}</label>
                <input class="field-input" v-model="draft._actionTarget"
                  :placeholder="draft._actionType === 'restart_service' ? 'nginx.service' :
                    draft._actionType === 'restart_container' ? 'noba-test-nginx' :
                    draft._actionType === 'run' ? '/usr/local/bin/fix.sh' :
                    draft._actionType === 'webhook' ? 'webhook-id' : 'automation-id'">
              </div>
            </div>
            <div v-if="draft._actionType && (draft._actionType === 'restart_container' || draft._actionType === 'restart_service')" style="margin-top:.5rem">
              <label class="field-label">Remote Agent (optional — leave empty for local)</label>
              <input class="field-input" v-model="draft._actionAgent" placeholder="e.g. server-01, db-host">
            </div>
            <div v-if="draft._actionType" class="field-2" style="margin-top:.5rem">
              <div>
                <label class="field-label">Max Retries</label>
                <input class="field-input" type="number" min="1" max="10" v-model.number="draft.max_retries" placeholder="3">
              </div>
              <div>
                <label class="field-label">Circuit Break After</label>
                <input class="field-input" type="number" min="2" max="20" v-model.number="draft.circuit_break_after" placeholder="5">
              </div>
            </div>
          </div>

          <div style="display:flex;gap:.4rem;justify-content:flex-end;margin-top:.75rem">
            <button class="btn btn-sm" style="width:auto" @click="cancelEdit">Cancel</button>
            <button class="btn btn-sm btn-primary" style="width:auto" @click="applyEdit(idx)">
              <i class="fas fa-check"></i> Apply
            </button>
          </div>
        </template>
      </div>

      <div v-if="alertRules.length === 0" style="text-align:center;color:var(--text-muted);font-size:.8rem;padding:1.5rem 0">
        No alert rules configured. Click "Add Rule" to get started.
      </div>

      <div style="display:flex;gap:.5rem;margin-top:.5rem;flex-wrap:wrap;align-items:center">
        <button v-if="authStore.isAdmin" class="btn btn-sm btn-primary" style="width:auto" @click="addRule">
          <i class="fas fa-plus"></i> Add Rule
        </button>
        <button class="btn btn-sm" style="width:auto" :disabled="loading" @click="fetchRules">
          <i class="fas fa-sync" :class="loading ? 'fa-spin' : ''"></i> Refresh
        </button>
        <button class="btn btn-sm btn-primary" style="width:auto;margin-left:auto" @click="saveRules">
          <i class="fas fa-check"></i> Save Rules
        </button>
        <span v-if="saveMsg" style="font-size:.8rem;color:var(--text-muted)">{{ saveMsg }}</span>
      </div>
    </div>

    <!-- Available Metrics reference -->
    <div class="s-section">
      <span class="s-label">Available Metrics</span>
      <div style="font-size:.75rem;color:var(--text-muted);font-family:var(--font-data);display:flex;flex-wrap:wrap;gap:.4rem">
        <span
          v-for="m in METRICS" :key="m"
          class="badge bn" style="font-size:.65rem;cursor:pointer"
          @click="copyMetric(m)" title="Click to copy"
        >{{ m }}</span>
      </div>
      <p style="font-size:.7rem;color:var(--text-muted);margin-top:.5rem">
        Conditions use the format: <code>metric &gt; value</code>.
        Supported operators: <code>&gt; &lt; &gt;= &lt;= == !=</code>.
      </p>
    </div>
  </div>
</template>
