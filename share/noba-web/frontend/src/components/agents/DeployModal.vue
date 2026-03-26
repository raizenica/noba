<script setup>
import { ref, computed } from 'vue'
import AppModal from '../ui/AppModal.vue'
import { useApi } from '../../composables/useApi'
import { useModalsStore } from '../../stores/modals'

const props = defineProps({
  show: Boolean,
})
const emit = defineEmits(['close', 'deployed'])

const { post, get } = useApi()
const modals = useModalsStore()

// ── State ─────────────────────────────────────────────────────────────────────
const deployTab   = ref('remote')

// SSH deploy
const deployHost  = ref('')
const deployUser  = ref('root')
const deployPass  = ref('')
const deployPort  = ref(22)
const deploying   = ref(false)
const deployResult = ref('')

// Install script
const scriptOS    = ref('linux')
const installCmd  = ref('')
const scriptLoading = ref(false)

// ── Derived ───────────────────────────────────────────────────────────────────
const canDeploy = computed(() => !!deployHost.value && !!deployUser.value && !deploying.value)

const resultIsError = computed(() =>
  deployResult.value.toLowerCase().includes('error') ||
  deployResult.value.toLowerCase().includes('fail')
)

// ── SSH deploy ────────────────────────────────────────────────────────────────
async function deploy() {
  if (!canDeploy.value) return
  if (!await modals.confirm(`Deploy agent to ${deployUser.value}@${deployHost.value}?`)) return
  deploying.value    = true
  deployResult.value = ''
  try {
    const data = await post('/api/agents/deploy', {
      host:      deployHost.value,
      ssh_user:  deployUser.value,
      ssh_pass:  deployPass.value,
      ssh_port:  deployPort.value,
    })
    if (data?.status === 'ok') {
      deployResult.value = `Success! Agent deployed to ${deployHost.value}`
      emit('deployed', deployHost.value)
    } else {
      deployResult.value = `Error: ${data?.error || data?.output || 'Deploy failed'}`
    }
  } catch (e) {
    deployResult.value = `Error: ${e.message}`
  } finally {
    deploying.value = false
  }
}

// ── Install script ────────────────────────────────────────────────────────────
async function generateScript(os) {
  scriptOS.value  = os
  scriptLoading.value = true
  installCmd.value = 'Generating...'
  try {
    const cfg = await get('/api/settings').catch(() => ({}))
    const key    = (cfg?.agentKeys || '').split(',')[0]?.trim() || 'YOUR_KEY'
    const server = window.location.origin
    if (os === 'linux') {
      installCmd.value = `curl -sf "${server}/api/agent/install-script?key=${key}" | sudo bash`
    } else {
      installCmd.value = `irm "${server}/api/agent/update" -Headers @{"X-Agent-Key"="${key}"} -OutFile agent.pyz; python agent.pyz --server ${server} --key ${key} --once`
    }
  } catch {
    installCmd.value = '# Could not generate script'
  } finally {
    scriptLoading.value = false
  }
}

async function copyScript() {
  try {
    await navigator.clipboard.writeText(installCmd.value)
  } catch { /* silent */ }
}

function switchTab(tab) {
  deployTab.value = tab
  if (tab === 'script' && !installCmd.value) generateScript('linux')
}
</script>

<template>
  <AppModal :show="show" title="Deploy Agent" width="520px" @close="emit('close')">

    <!-- Tab switcher -->
    <div style="display:flex;gap:.3rem;margin-bottom:.8rem">
      <button
        class="btn btn-xs"
        :class="deployTab === 'remote' ? 'btn-primary' : ''"
        @click="switchTab('remote')"
      ><i class="fas fa-satellite-dish" style="margin-right:.3rem"></i>SSH Deploy</button>
      <button
        class="btn btn-xs"
        :class="deployTab === 'script' ? 'btn-primary' : ''"
        @click="switchTab('script')"
      ><i class="fas fa-scroll" style="margin-right:.3rem"></i>Install Script</button>
    </div>

    <!-- SSH Deploy tab -->
    <div v-if="deployTab === 'remote'">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:.5rem;margin-bottom:.6rem">
        <div>
          <label class="field-label">Host / IP</label>
          <input v-model="deployHost" class="field-input" type="text" placeholder="192.168.1.100" style="font-size:.75rem">
        </div>
        <div>
          <label class="field-label">SSH User</label>
          <input v-model="deployUser" class="field-input" type="text" placeholder="root" style="font-size:.75rem">
        </div>
        <div>
          <label class="field-label">SSH Password</label>
          <input v-model="deployPass" class="field-input" type="password" style="font-size:.75rem">
        </div>
        <div>
          <label class="field-label">Port</label>
          <input v-model.number="deployPort" class="field-input" type="number" min="1" max="65535" style="font-size:.75rem">
        </div>
      </div>

      <button
        class="btn btn-primary btn-sm"
        style="width:100%"
        :disabled="!canDeploy"
        @click="deploy"
      >
        <i class="fas" :class="deploying ? 'fa-spinner fa-spin' : 'fa-satellite-dish'"></i>
        {{ deploying ? 'Deploying...' : 'Deploy Agent' }}
      </button>

      <div
        v-if="deployResult"
        style="margin-top:.5rem;font-size:.75rem;padding:.4rem .6rem;border-radius:4px"
        :style="resultIsError
          ? 'background:rgba(255,23,68,.1);color:var(--danger)'
          : 'background:rgba(0,230,118,.1);color:var(--success)'"
      >
        <i class="fas" :class="resultIsError ? 'fa-times-circle' : 'fa-check-circle'" style="margin-right:.3rem"></i>
        {{ deployResult }}
      </div>
    </div>

    <!-- Install Script tab -->
    <div v-if="deployTab === 'script'">
      <div style="display:flex;gap:.3rem;margin-bottom:.5rem">
        <button
          class="btn btn-xs"
          :class="scriptOS === 'linux' ? 'btn-primary' : ''"
          @click="generateScript('linux')"
        ><i class="fab fa-linux" style="margin-right:.25rem"></i>Linux</button>
        <button
          class="btn btn-xs"
          :class="scriptOS === 'windows' ? 'btn-primary' : ''"
          @click="generateScript('windows')"
        ><i class="fab fa-windows" style="margin-right:.25rem"></i>Windows</button>
      </div>

      <p style="font-size:.72rem;color:var(--text-muted);margin:.0 0 .4rem">
        {{ scriptOS === 'linux' ? 'Paste in any Linux terminal:' : 'Run in PowerShell (Admin):' }}
      </p>

      <div style="position:relative">
        <pre style="background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:.5rem;font-size:.65rem;overflow-x:auto;white-space:pre-wrap;word-break:break-all;max-height:100px;margin:0">{{ scriptLoading ? 'Generating...' : installCmd }}</pre>
        <button
          class="btn btn-xs"
          style="position:absolute;top:4px;right:4px"
          title="Copy to clipboard"
          @click="copyScript"
        ><i class="fas fa-copy"></i></button>
      </div>

      <p style="font-size:.68rem;color:var(--text-muted);margin-top:.5rem">
        The agent will connect back to this server automatically. Requires Python 3.8+.
      </p>
    </div>

    <template #footer>
      <button class="btn btn-xs" @click="emit('close')">Close</button>
    </template>
  </AppModal>
</template>
