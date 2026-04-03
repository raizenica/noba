<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'
import { useModalsStore } from '../../stores/modals'
import IntegrationSetup from './IntegrationSetup.vue'
import IntegrationSearchFilter from './integrations/IntegrationSearchFilter.vue'
import IntegrationSettingsPanel from './integrations/IntegrationSettingsPanel.vue'
import IntegrationCategoryList from './integrations/IntegrationCategoryList.vue'
import IntegrationEmptyState from './integrations/IntegrationEmptyState.vue'

const settingsStore = useSettingsStore()
const { get, post, del: apiDel } = useApi()
const notifications = useNotificationsStore()
const modals = useModalsStore()

const intCat = ref('infra')
const saving = ref(false)
const saveMsg = ref('')

// Managed integrations
const instances = ref([])
const showSetup = ref(false)
const editingInstance = ref(null)

async function fetchInstances() {
  try {
    instances.value = await get('/api/integrations/instances')
  } catch { /* silent */ }
}

async function deleteInstance(id) {
  if (!await modals.confirm(`Delete integration "${id}"?`)) return
  try {
    await apiDel('/api/integrations/instances/' + id)
    notifications.addToast('Integration deleted', 'success')
    await fetchInstances()
  } catch {
    notifications.addToast('Failed to delete integration', 'danger')
  }
}

function editInstance(inst) {
  editingInstance.value = inst
  showSetup.value = true
}

function onInstanceSaved() {
  showSetup.value = false
  editingInstance.value = null
  fetchInstances()
}

function onSetupCancel() {
  showSetup.value = false
  editingInstance.value = null
}

onMounted(async () => {
  if (!settingsStore.loaded) await settingsStore.fetchSettings()
  fetchInstances()
})

async function save() {
  saving.value = true
  saveMsg.value = ''
  try {
    await settingsStore.saveSettings()
    saveMsg.value = 'Saved.'
    setTimeout(() => { saveMsg.value = '' }, 2500)
  } catch {
    saveMsg.value = 'Save failed.'
  } finally {
    saving.value = false
  }
}

const testingAi = ref(false)
const aiTestMsg = ref('')

async function testAiConnection() {
  testingAi.value = true
  aiTestMsg.value = ''
  try {
    const data = await post('/api/ai/test', {})
    aiTestMsg.value = '✓ ' + (data.response || 'Connected')
  } catch (e) {
    aiTestMsg.value = '✗ ' + (e.message || 'Connection failed')
  } finally {
    testingAi.value = false
    setTimeout(() => { aiTestMsg.value = '' }, 5000)
  }
}

const cats = [
  { key: 'infra',  label: 'Infrastructure', icon: 'fa-server' },
  { key: 'media',  label: 'Media',          icon: 'fa-film' },
  { key: 'network',label: 'Network',        icon: 'fa-network-wired' },
  { key: 'iot',    label: 'IoT & Home',     icon: 'fa-microchip' },
  { key: 'devops', label: 'DevOps',         icon: 'fa-code-branch' },
  { key: 'notify', label: 'Notifications',  icon: 'fa-bell' },
  { key: 'auth',   label: 'Auth & Security',icon: 'fa-lock' },
  { key: 'ai',     label: 'AI / LLM',       icon: 'fa-robot' },
]
</script>

<template>
  <div>
    <!-- Category bar -->
    <IntegrationSearchFilter v-model="intCat" :categories="cats" />

    <!-- Settings forms by category -->
    <IntegrationSettingsPanel :int-cat="intCat" />

    <!-- Save -->
    <div style="margin-top:1.25rem;display:flex;gap:.75rem;align-items:center;flex-wrap:wrap">
      <button class="btn btn-primary" :disabled="saving" @click="save">
        <i class="fas" :class="saving ? 'fa-spinner fa-spin' : 'fa-check'"></i>
        {{ saving ? 'Saving…' : 'Save & Apply' }}
      </button>
      <button
        v-if="intCat === 'ai' && settingsStore.data.llmEnabled"
        class="btn"
        :disabled="testingAi"
        @click="testAiConnection"
      >
        <i class="fas" :class="testingAi ? 'fa-spinner fa-spin' : 'fa-plug'"></i>
        {{ testingAi ? 'Testing…' : 'Test Connection' }}
      </button>
      <span v-if="saveMsg" style="font-size:.8rem;color:var(--text-muted)">{{ saveMsg }}</span>
      <span v-if="aiTestMsg" style="font-size:.8rem" :style="{ color: aiTestMsg.startsWith('✓') ? 'var(--success)' : 'var(--danger)' }">{{ aiTestMsg }}</span>
    </div>

    <hr style="border-color: var(--border); margin: 2rem 0;" />

    <!-- Managed Integration Instances -->
    <div class="s-section">
      <div class="s-label" style="display:flex;align-items:center;justify-content:space-between">
        <span>Managed Integrations</span>
        <button v-if="!showSetup" class="btn btn-xs btn-primary" @click="showSetup = true">
          <i class="fas fa-plus" style="margin-right:.3rem"></i> Add Integration
        </button>
      </div>

      <IntegrationSetup v-if="showSetup" :edit-instance="editingInstance" @saved="onInstanceSaved" @cancel="onSetupCancel" />

      <IntegrationCategoryList
        v-if="!showSetup && instances.length"
        :instances="instances"
        @edit="editInstance"
        @delete="deleteInstance"
      />
      <IntegrationEmptyState
        v-if="!showSetup && !instances.length"
        @add="showSetup = true"
      />
    </div>
  </div>
</template>

