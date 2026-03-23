<script setup>
import { ref, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const emit = defineEmits(['saved', 'cancel'])
const { get, post } = useApi()
const notifications = useNotificationsStore()

const step = ref(0)
const steps = ['Category', 'Platform', 'Configure', 'Test & Save']

// Step 1
const categories = ref([])

// Step 2
const selectedCategory = ref('')
const platforms = ref([])

// Step 3
const selectedPlatform = ref('')
const instanceId = ref('')
const instanceUrl = ref('')
const authMethod = ref('none')
const authToken = ref('')
const authUser = ref('')
const authPass = ref('')
const authApiKey = ref('')
const instanceSite = ref('')
const instanceTags = ref('')

// Step 4
const testing = ref(false)
const saving = ref(false)
const testResult = ref(null)

onMounted(async () => {
  try {
    categories.value = await get('/api/integrations/catalog/categories')
  } catch { /* silent */ }
})

function categoryIcon(cat) {
  const icons = {
    nas: 'fa-database', hypervisor: 'fa-server', container_runtime: 'fa-cubes',
    reverse_proxy: 'fa-random', dns: 'fa-shield-alt', media: 'fa-film',
    media_management: 'fa-tv', download_client: 'fa-download',
    vpn: 'fa-lock', monitoring: 'fa-heartbeat', smart_home: 'fa-home',
    identity_auth: 'fa-user-shield', backup: 'fa-archive',
    certificate: 'fa-certificate', database: 'fa-table',
    git_devops: 'fa-code-branch', mail: 'fa-envelope',
    document_wiki: 'fa-book', security: 'fa-shield-alt',
    cloud_cdn: 'fa-cloud', network_hardware: 'fa-wifi',
    power_ups: 'fa-bolt', surveillance: 'fa-video',
    logging: 'fa-scroll', metrics: 'fa-chart-line',
    message_queue: 'fa-stream', photo_management: 'fa-images',
    automation_workflow: 'fa-cogs', file_sync: 'fa-sync',
  }
  return icons[cat] || 'fa-plug'
}

function formatCat(cat) {
  return cat.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

async function selectCategory(cat) {
  selectedCategory.value = cat
  try {
    platforms.value = await get(`/api/integrations/catalog/categories/${cat}/platforms`)
  } catch {
    platforms.value = []
  }
  step.value = 1
}

function selectPlatform(p) {
  selectedPlatform.value = p
  instanceId.value = p + '-1'
  step.value = 2
}

function buildAuthConfig() {
  if (authMethod.value === 'token') return { method: 'token', token_env: authToken.value }
  if (authMethod.value === 'userpass') return { method: 'userpass', username: authUser.value, password_env: authPass.value }
  if (authMethod.value === 'apikey') return { method: 'apikey', apikey_env: authApiKey.value }
  return { method: 'none' }
}

async function testConnection() {
  testing.value = true
  testResult.value = null
  try {
    const res = await post('/api/integrations/instances/test-connection', {
      platform: selectedPlatform.value,
      url: instanceUrl.value,
      auth_config: buildAuthConfig(),
    })
    testResult.value = res
  } catch (e) {
    testResult.value = { success: false, error: e.message || 'Connection test failed' }
  } finally {
    testing.value = false
  }
}

async function saveInstance() {
  saving.value = true
  try {
    const tags = instanceTags.value
      ? instanceTags.value.split(',').map(t => t.trim()).filter(Boolean)
      : []
    await post('/api/integrations/instances', {
      id: instanceId.value || selectedPlatform.value + '-1',
      category: selectedCategory.value,
      platform: selectedPlatform.value,
      url: instanceUrl.value,
      auth_config: buildAuthConfig(),
      site: instanceSite.value || null,
      tags,
    })
    notifications.addToast('Integration saved successfully', 'success')
    emit('saved')
  } catch (e) {
    notifications.addToast('Failed to save: ' + (e.message || 'Unknown error'), 'danger')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="setup-wizard">
    <!-- Progress bar -->
    <div class="wizard-progress">
      <span v-for="(s, i) in steps" :key="i"
        :class="['wizard-step', { active: step === i, done: step > i }]">
        {{ s }}
      </span>
    </div>

    <!-- Step 1: Category -->
    <div v-if="step === 0" class="wizard-body">
      <h3>What type of integration?</h3>
      <div class="wizard-grid">
        <button v-for="cat in categories" :key="cat" class="wizard-card"
          @click="selectCategory(cat)">
          <i :class="['fas', categoryIcon(cat)]"></i>
          <span class="wizard-card-title">{{ formatCat(cat) }}</span>
        </button>
      </div>
      <button class="btn btn-xs" @click="emit('cancel')">Cancel</button>
    </div>

    <!-- Step 2: Platform -->
    <div v-if="step === 1" class="wizard-body">
      <h3>Which platform?</h3>
      <div class="wizard-grid">
        <button v-for="p in platforms" :key="p" class="wizard-card"
          @click="selectPlatform(p)">
          <span class="wizard-card-title">{{ p }}</span>
        </button>
      </div>
      <div style="display:flex;gap:.5rem;margin-top:.5rem">
        <button class="btn btn-xs" @click="step = 0">Back</button>
        <button class="btn btn-xs" @click="emit('cancel')">Cancel</button>
      </div>
    </div>

    <!-- Step 3: Configure -->
    <div v-if="step === 2" class="wizard-body">
      <h3>Configure {{ selectedPlatform }}</h3>
      <div class="wizard-form">
        <div>
          <label class="field-label">Instance ID</label>
          <input v-model="instanceId" class="field-input" :placeholder="`${selectedPlatform}-1`" />
        </div>
        <div>
          <label class="field-label">URL</label>
          <input v-model="instanceUrl" class="field-input" placeholder="https://host:port" />
        </div>
        <div>
          <label class="field-label">Authentication</label>
          <select v-model="authMethod" class="form-select">
            <option value="none">None</option>
            <option value="token">API Token (env var)</option>
            <option value="userpass">Username + Password (env var)</option>
            <option value="apikey">API Key (env var)</option>
          </select>
        </div>
        <div v-if="authMethod === 'token'">
          <label class="field-label">Token Environment Variable</label>
          <input v-model="authToken" class="field-input" placeholder="e.g., TRUENAS_TOKEN" />
        </div>
        <div v-if="authMethod === 'userpass'">
          <label class="field-label">Username</label>
          <input v-model="authUser" class="field-input" placeholder="admin" />
          <label class="field-label" style="margin-top:.5rem">Password Env Variable</label>
          <input v-model="authPass" class="field-input" placeholder="e.g., NAS_PASSWORD" />
        </div>
        <div v-if="authMethod === 'apikey'">
          <label class="field-label">API Key Environment Variable</label>
          <input v-model="authApiKey" class="field-input" placeholder="e.g., JELLYFIN_API_KEY" />
        </div>
        <div>
          <label class="field-label">Site (optional)</label>
          <input v-model="instanceSite" class="field-input" placeholder="e.g., site-a" />
        </div>
        <div>
          <label class="field-label">Tags (comma-separated, optional)</label>
          <input v-model="instanceTags" class="field-input" placeholder="e.g., production, media-storage" />
        </div>
      </div>
      <div style="display:flex;gap:.5rem;margin-top:1rem">
        <button class="btn btn-xs" @click="step = 1">Back</button>
        <button class="btn btn-primary" @click="step = 3">Next</button>
      </div>
    </div>

    <!-- Step 4: Test & Save -->
    <div v-if="step === 3" class="wizard-body">
      <h3>Test & Save</h3>
      <div class="wizard-summary">
        <div class="row"><span class="row-label">Platform</span><span class="row-val badge ba">{{ selectedPlatform }}</span></div>
        <div class="row"><span class="row-label">Instance ID</span><span class="row-val">{{ instanceId || `${selectedPlatform}-1` }}</span></div>
        <div class="row"><span class="row-label">URL</span><span class="row-val">{{ instanceUrl || '—' }}</span></div>
        <div class="row"><span class="row-label">Auth</span><span class="row-val">{{ authMethod }}</span></div>
        <div v-if="instanceSite" class="row"><span class="row-label">Site</span><span class="row-val">{{ instanceSite }}</span></div>
      </div>
      <div style="display:flex;gap:.5rem;margin-top:1rem">
        <button class="btn btn-xs" @click="step = 2">Back</button>
        <button class="btn" @click="testConnection" :disabled="testing">
          {{ testing ? 'Testing...' : 'Test Connection' }}
        </button>
        <button class="btn btn-primary" @click="saveInstance" :disabled="saving">
          {{ saving ? 'Saving...' : 'Save Integration' }}
        </button>
      </div>
      <!-- Test result -->
      <div v-if="testResult" class="wizard-test-result" :class="testResult.success ? 'test-ok' : 'test-fail'">
        {{ testResult.success ? 'Connection successful!' : `Connection failed: ${testResult.error}` }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.setup-wizard { max-width: 600px; }
.wizard-progress { display: flex; gap: .5rem; margin-bottom: 1.5rem; }
.wizard-step { font-size: .75rem; color: var(--text-muted); padding: .25rem .5rem; border-radius: 4px; background: var(--surface-2); }
.wizard-step.active { color: var(--accent); background: var(--surface); border: 1px solid var(--accent); }
.wizard-step.done { color: var(--success); }
.wizard-body h3 { margin: 0 0 1rem; font-size: 1.1rem; }
.wizard-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: .5rem; margin-bottom: 1rem; }
.wizard-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: .5rem; transition: border-color .15s; color: var(--text); }
.wizard-card:hover { border-color: var(--accent); }
.wizard-card i { font-size: 1.5rem; color: var(--accent); }
.wizard-card-title { font-size: .85rem; text-transform: capitalize; }
.wizard-form { display: flex; flex-direction: column; gap: .75rem; }
.wizard-summary { background: var(--surface-2); border-radius: 8px; padding: 1rem; }
.wizard-test-result { margin-top: .75rem; padding: .5rem .75rem; border-radius: 6px; font-size: .85rem; }
.test-ok { background: color-mix(in srgb, var(--success) 15%, transparent); color: var(--success); }
.test-fail { background: color-mix(in srgb, var(--danger) 15%, transparent); color: var(--danger); }
</style>
