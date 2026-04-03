<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, watch } from 'vue'
import { useApi } from '../../composables/useApi'
import { CMD_POLL_FIRST_MS, CMD_POLL_SECOND_MS, CMD_POLL_THIRD_MS } from '../../constants'

const props = defineProps({
  agents: { type: Array, default: () => [] },
})
const emit = defineEmits(['result'])

const { post } = useApi()

// ── CMD_CATALOG ───────────────────────────────────────────────────────────────
const CMD_CATALOG = [
  // System
  { type: 'ping',              label: 'Ping',              icon: 'fa-heartbeat',        cat: 'system',     risk: 'low',    params: [] },
  { type: 'system_info',       label: 'System Info',       icon: 'fa-info-circle',      cat: 'system',     risk: 'low',    params: [] },
  { type: 'disk_usage',        label: 'Disk Usage',        icon: 'fa-hdd',              cat: 'system',     risk: 'low',    params: [{ key: 'path', label: 'Path', placeholder: '/' }] },
  { type: 'exec',              label: 'Run Command',       icon: 'fa-terminal',         cat: 'system',     risk: 'high',   params: [{ key: 'command', label: 'Shell command', placeholder: 'df -h', wide: true }, { key: 'timeout', label: 'Timeout (s)', placeholder: '30', numeric: true }] },
  { type: 'reboot',            label: 'Reboot',            icon: 'fa-power-off',        cat: 'system',     risk: 'high',   params: [{ key: 'delay', label: 'Delay (min)', placeholder: '0', numeric: true }] },
  { type: 'process_kill',      label: 'Kill Process',      icon: 'fa-skull-crossbones', cat: 'system',     risk: 'high',   params: [{ key: 'pid', label: 'PID', placeholder: '1234', numeric: true }, { key: 'name', label: 'Process name', placeholder: 'nginx' }, { key: 'signal', label: 'Signal', options: ['TERM','KILL','HUP','INT'] }] },
  // Services
  { type: 'list_services',     label: 'List Services',     icon: 'fa-list',             cat: 'services',   risk: 'low',    params: [] },
  { type: 'check_service',     label: 'Service Status',    icon: 'fa-stethoscope',      cat: 'services',   risk: 'low',    params: [{ key: 'service', label: 'Service name', placeholder: 'sshd' }] },
  { type: 'restart_service',   label: 'Restart Service',   icon: 'fa-redo',             cat: 'services',   risk: 'medium', params: [{ key: 'service', label: 'Service name', placeholder: 'nginx' }] },
  { type: 'service_control',   label: 'Service Control',   icon: 'fa-sliders-h',        cat: 'services',   risk: 'medium', params: [{ key: 'service', label: 'Service name', placeholder: 'nginx' }, { key: 'action', label: 'Action', options: ['start','stop','restart','enable','disable','status'] }] },
  // Network
  { type: 'network_test',      label: 'Ping / Trace',      icon: 'fa-network-wired',    cat: 'network',    risk: 'low',    params: [{ key: 'target', label: 'Target host', placeholder: '1.1.1.1' }, { key: 'mode', label: 'Mode', options: ['ping','trace'] }] },
  { type: 'network_config',    label: 'Network Config',    icon: 'fa-ethernet',         cat: 'network',    risk: 'low',    params: [] },
  { type: 'dns_lookup',        label: 'DNS Lookup',        icon: 'fa-globe',            cat: 'network',    risk: 'low',    params: [{ key: 'host', label: 'Hostname', placeholder: 'google.com' }, { key: 'type', label: 'Record', options: ['A','AAAA','MX','NS','TXT','CNAME'] }] },
  // Files
  { type: 'file_read',         label: 'Read File',         icon: 'fa-file-alt',         cat: 'files',      risk: 'low',    params: [{ key: 'path', label: 'File path', placeholder: '/etc/hostname', wide: true }, { key: 'lines', label: 'Max lines', placeholder: '100', numeric: true }] },
  { type: 'file_list',         label: 'List Directory',    icon: 'fa-folder-open',      cat: 'files',      risk: 'low',    params: [{ key: 'path', label: 'Directory', placeholder: '/var/log' }, { key: 'pattern', label: 'Glob', placeholder: '*.log' }] },
  { type: 'file_stat',         label: 'File Info',         icon: 'fa-file-invoice',     cat: 'files',      risk: 'low',    params: [{ key: 'path', label: 'File path', placeholder: '/etc/passwd' }] },
  { type: 'file_checksum',     label: 'Checksum',          icon: 'fa-fingerprint',      cat: 'files',      risk: 'low',    params: [{ key: 'path', label: 'File path', placeholder: '/usr/bin/python3' }, { key: 'algorithm', label: 'Algo', options: ['sha256','md5'] }] },
  { type: 'file_write',        label: 'Write File',        icon: 'fa-pen',              cat: 'files',      risk: 'high',   params: [{ key: 'path', label: 'Destination', placeholder: '/tmp/test.txt', wide: true }, { key: 'content', label: 'Content', placeholder: 'File contents...', textarea: true }] },
  { type: 'file_delete',       label: 'Delete File',       icon: 'fa-trash-alt',        cat: 'files',      risk: 'high',   params: [{ key: 'path', label: 'File path', placeholder: '/tmp/test.txt' }] },
  // Packages
  { type: 'package_updates',   label: 'Check Updates',     icon: 'fa-download',         cat: 'packages',   risk: 'low',    params: [] },
  // Users
  { type: 'list_users',        label: 'List Users',        icon: 'fa-users',            cat: 'users',      risk: 'low',    params: [] },
  { type: 'user_manage',       label: 'Manage User',       icon: 'fa-user-cog',         cat: 'users',      risk: 'high',   params: [{ key: 'action', label: 'Action', options: ['add','delete','modify'] }, { key: 'username', label: 'Username', placeholder: 'johndoe' }, { key: 'groups', label: 'Groups', placeholder: 'docker,sudo' }] },
  // Containers
  { type: 'container_list',    label: 'List Containers',   icon: 'fa-cubes',            cat: 'containers', risk: 'low',    params: [] },
  { type: 'container_control', label: 'Container Control', icon: 'fa-play-circle',      cat: 'containers', risk: 'medium', params: [{ key: 'container', label: 'Container name', placeholder: 'nginx' }, { key: 'action', label: 'Action', options: ['start','stop','restart'] }] },
  { type: 'container_logs',    label: 'Container Logs',    icon: 'fa-align-left',       cat: 'containers', risk: 'low',    params: [{ key: 'container', label: 'Container name', placeholder: 'nginx' }, { key: 'tail', label: 'Lines', placeholder: '100', numeric: true }] },
  // Logs
  { type: 'get_logs',          label: 'System Logs',       icon: 'fa-scroll',           cat: 'logs',       risk: 'low',    params: [{ key: 'unit', label: 'Unit (optional)', placeholder: 'nginx' }, { key: 'lines', label: 'Lines', placeholder: '50', numeric: true }, { key: 'priority', label: 'Priority', options: ['','emerg','alert','crit','err','warning','notice','info','debug'] }] },
  // Agent
  { type: 'set_interval',      label: 'Set Interval',      icon: 'fa-clock',            cat: 'agent',      risk: 'medium', params: [{ key: 'interval', label: 'Seconds (5-86400)', placeholder: '30', numeric: true }] },
  { type: 'update_agent',      label: 'Update Agent',      icon: 'fa-sync',             cat: 'agent',      risk: 'high',   params: [] },
  { type: 'uninstall_agent',   label: 'Uninstall',         icon: 'fa-times-circle',     cat: 'agent',      risk: 'high',   params: [] },
]

const CMD_CATEGORIES = {
  system: 'System', services: 'Services', network: 'Network', files: 'Files',
  packages: 'Packages', users: 'Users', containers: 'Containers', logs: 'Logs', agent: 'Agent',
}

const RISK_PILL_CLASS = { low: 'pill-low', medium: 'pill-med', high: 'pill-high' }

// ── State ─────────────────────────────────────────────────────────────────────
const selectedType   = ref('ping')
const selectedTarget = ref('')
const params         = ref({})
const sending        = ref(false)
const outputTabs     = ref({})     // hostname -> output text
const pendingHosts   = ref(new Set()) // hosts currently waiting for result
const activeTab      = ref('')

// ── Derived ───────────────────────────────────────────────────────────────────
const activeCatalogEntry = computed(() => CMD_CATALOG.find(c => c.type === selectedType.value))
const activeCat          = computed(() => activeCatalogEntry.value?.cat || 'system')

const catalogInCat = computed(() =>
  CMD_CATALOG.filter(c => c.cat === activeCat.value)
)

const onlineAgents = computed(() => (props.agents || []).filter(a => a.online))

const canRun = computed(() =>
  !!selectedTarget.value && !!selectedType.value && !sending.value
)

// Reset params when type changes
watch(selectedType, () => { params.value = {} })

// ── Run ───────────────────────────────────────────────────────────────────────
async function run() {
  if (!canRun.value) return
  sending.value = true
  try {
    const entry      = activeCatalogEntry.value
    const cleanParams = {}
    if (entry) {
      for (const p of entry.params) {
        const val = (params.value[p.key] || '').toString().trim()
        if (val) cleanParams[p.key] = p.numeric ? (parseInt(val, 10) || val) : val
      }
    }
    const targets = selectedTarget.value === '__all__'
      ? onlineAgents.value.map(a => a.hostname)
      : [selectedTarget.value]

    for (const host of targets) {
      outputTabs.value[host] = 'Queued…'
      pendingHosts.value.add(host)
      if (!(activeTab.value)) activeTab.value = host
      await post(`/api/agents/${encodeURIComponent(host)}/command`, {
        type: selectedType.value,
        params: cleanParams,
      })
      // Poll for result
      setTimeout(() => pollResult(host), CMD_POLL_FIRST_MS)
      setTimeout(() => pollResult(host), CMD_POLL_SECOND_MS)
      setTimeout(() => pollResult(host), CMD_POLL_THIRD_MS)
    }
    emit('result', { targets, type: selectedType.value })
  } catch { /* non-fatal */
  } finally {
    sending.value = false
  }
}

async function pollResult(hostname) {
  try {
    const { get: getReq } = useApi()
    const results = await getReq(`/api/agents/${encodeURIComponent(hostname)}/results`)
    if (Array.isArray(results) && results.length > 0) {
      const last = results[results.length - 1]
      let output = ''
      if (last.stdout)  output = last.stdout
      else if (last.pong)    output = `pong v${last.version || '?'}`
      else if (last.message) output = last.message
      else if (last.error)   output = `Error: ${last.error}`
      else output = JSON.stringify(last, null, 2)
      outputTabs.value = { ...outputTabs.value, [hostname]: output.trim() }
      pendingHosts.value.delete(hostname)
    }
  } catch { /* silent */ }
}
</script>

<template>
  <div class="cmd-palette">
    <div class="cmd-palette-hdr">
      <i class="fas fa-terminal" style="margin-right:.4rem"></i>Command Palette
    </div>
    <div class="cmd-palette-body">

      <!-- Top bar: target + category tabs -->
      <div class="cmd-palette-topbar">
        <select v-model="selectedTarget" class="field-select cmd-palette-target">
          <option value="">Target agent...</option>
          <option v-for="a in onlineAgents" :key="a.hostname" :value="a.hostname">
            {{ a.hostname }}
          </option>
          <option value="__all__">All online agents</option>
        </select>

        <div class="cmd-cat-tabs">
          <button
            v-for="(label, key) in CMD_CATEGORIES"
            :key="key"
            class="cmd-cat-tab"
            :class="{ active: activeCat === key }"
            @click="selectedType = CMD_CATALOG.find(c => c.cat === key)?.type || selectedType; params = {}"
          >{{ label }}</button>
        </div>
      </div>

      <!-- Command type grid -->
      <div class="cmd-type-grid">
        <button
          v-for="c in catalogInCat"
          :key="c.type"
          class="cmd-type-btn"
          :class="{ active: selectedType === c.type, 'risk-high': c.risk === 'high' }"
          :title="`${c.label} (${c.risk} risk)`"
          @click="selectedType = c.type; params = {}"
        >
          <i class="fas" :class="c.icon"></i>
          <span class="cmd-type-label">{{ c.label }}</span>
          <span class="cmd-risk-dot" :class="`dot-${c.risk}`"></span>
        </button>
      </div>

      <!-- Params area -->
      <div v-if="(activeCatalogEntry?.params || []).length > 0" class="cmd-params-area">
        <div
          v-for="p in activeCatalogEntry.params"
          :key="p.key"
          class="cmd-param-field"
          :class="{ wide: p.wide, 'full-width': p.textarea }"
        >
          <label>{{ p.label }}</label>
          <select v-if="p.options" v-model="params[p.key]" class="field-select">
            <option value="">Select...</option>
            <option v-for="o in p.options" :key="o" :value="o">{{ o || '(any)' }}</option>
          </select>
          <textarea
            v-else-if="p.textarea"
            v-model="params[p.key]"
            class="field-input cmd-textarea"
            :placeholder="p.placeholder"
            rows="3"
          ></textarea>
          <input
            v-else
            v-model="params[p.key]"
            class="field-input"
            :type="p.numeric ? 'number' : 'text'"
            :placeholder="p.placeholder"
          >
        </div>
      </div>

      <!-- Footer: risk pill + run button -->
      <div class="cmd-palette-footer">
        <div v-if="selectedType" class="cmd-selected-info">
          <span
            class="cmd-risk-pill"
            :class="`pill-${activeCatalogEntry?.risk || 'low'}`"
          >{{ (activeCatalogEntry?.risk || '').toUpperCase() }} RISK</span>
          <span style="opacity:.5;font-size:.7rem">{{ selectedType }}</span>
        </div>
        <button
          class="btn btn-primary btn-sm"
          :disabled="!canRun"
          @click="run"
        >
          <i class="fas" :class="sending ? 'fa-spinner fa-spin' : 'fa-play'"></i>
          {{ sending ? 'Sending...' : 'Run' }}
        </button>
      </div>
    </div>

    <!-- Output panel -->
    <div v-if="Object.keys(outputTabs).length > 0" class="cmd-output-panel">
      <div class="cmd-output-tabs" style="display:flex;gap:.3rem;margin-bottom:.4rem">
        <button
          v-for="(_, host) in outputTabs"
          :key="host"
          class="btn btn-xs"
          :class="activeTab === host ? 'btn-primary' : 'btn-secondary'"
          @click="activeTab = host"
        >
          {{ host }}
          <i v-if="pendingHosts.has(host)" class="fas fa-spinner fa-spin" style="margin-left:.3rem;font-size:.65rem;opacity:.7"></i>
          <span style="margin-left:.4rem;opacity:.4" @click.stop="delete outputTabs[host]; if(activeTab===host) activeTab=Object.keys(outputTabs)[0]||''">&times;</span>
        </button>
      </div>
      <pre class="cmd-output-pre">{{ outputTabs[activeTab] || 'Waiting for result...' }}</pre>
    </div>
  </div>
</template>
