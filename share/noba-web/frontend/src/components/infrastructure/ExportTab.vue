<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useDashboardStore } from '../../stores/dashboard'
import { useNotificationsStore } from '../../stores/notifications'

const authStore      = useAuthStore()
const dashboardStore = useDashboardStore()
const notif          = useNotificationsStore()

const agents = computed(() => dashboardStore.live.agents || [])

const iacFormat   = ref('ansible')
const iacHostname = ref('')
const iacDiscover = ref(false)
const iacLoading  = ref(false)
const iacOutput   = ref('')
const iacWarning  = ref('')

async function generateIaC() {
  iacLoading.value = true
  iacOutput.value  = ''
  iacWarning.value = ''
  try {
    const fmt = iacFormat.value
    const ep = fmt === 'docker-compose' ? '/api/export/docker-compose'
             : fmt === 'shell' ? '/api/export/shell'
             : '/api/export/ansible'
    const discover = iacDiscover.value
    const fetchOpts = { headers: { 'Authorization': `Bearer ${authStore.token}` } }
    let resp
    if (discover) {
      // POST when discovery is needed (side-effect: sends commands to agents)
      fetchOpts.method = 'POST'
      fetchOpts.headers['Content-Type'] = 'application/json'
      fetchOpts.body = JSON.stringify({ hostname: iacHostname.value || null, discover: true })
      resp = await fetch(ep, fetchOpts)
    } else {
      // GET for read-only export from cached data
      const qs = new URLSearchParams()
      if (iacHostname.value) qs.set('hostname', iacHostname.value)
      const qstr = qs.toString()
      resp = await fetch(ep + (qstr ? `?${qstr}` : ''), fetchOpts)
    }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    iacWarning.value = resp.headers.get('X-Noba-Discovery-Warning') || ''
    iacOutput.value = await resp.text()
  } catch (e) {
    notif.addToast('Export failed: ' + e.message, 'error')
  }
  iacLoading.value = false
}

function downloadIaC() {
  if (!iacOutput.value) return
  const ext = iacFormat.value === 'docker-compose' ? 'yml' : iacFormat.value === 'ansible' ? 'yml' : 'sh'
  const blob = new Blob([iacOutput.value], { type: 'text/plain' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `noba-export.${ext}`
  a.click()
  URL.revokeObjectURL(url)
}

async function copyIaC() {
  if (!iacOutput.value) return
  try {
    await navigator.clipboard.writeText(iacOutput.value)
    notif.addToast('Copied to clipboard', 'success')
  } catch {
    notif.addToast('Copy failed', 'error')
  }
}
</script>

<template>
  <div>
    <div style="display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap;align-items:flex-end">
      <div style="display:flex;flex-direction:column;gap:.2rem;min-width:160px">
        <label style="font-size:.7rem;color:var(--text-dim)">Format</label>
        <select
          v-model="iacFormat"
          style="padding:.3rem .5rem;font-size:.8rem;border:1px solid var(--border);border-radius:4px;background:var(--surface-2);color:var(--text)"
        >
          <option value="ansible">Ansible Playbook</option>
          <option value="docker-compose">Docker Compose</option>
          <option value="shell">Shell Script</option>
        </select>
      </div>
      <div style="display:flex;flex-direction:column;gap:.2rem;min-width:160px">
        <label style="font-size:.7rem;color:var(--text-dim)">Agent</label>
        <select
          v-model="iacHostname"
          style="padding:.3rem .5rem;font-size:.8rem;border:1px solid var(--border);border-radius:4px;background:var(--surface-2);color:var(--text)"
        >
          <option value="">All Agents</option>
          <option v-for="a in agents" :key="a.hostname" :value="a.hostname">{{ a.hostname }}</option>
        </select>
      </div>
      <label style="display:flex;align-items:center;gap:.4rem;font-size:.75rem;color:var(--text-dim);cursor:pointer" title="Auto-discover containers and services from agent before export">
        <input type="checkbox" v-model="iacDiscover"> Discover
      </label>
      <button class="btn btn-sm btn-primary" @click="generateIaC" :disabled="iacLoading">
        <i class="fas fa-file-code" :class="iacLoading ? 'fa-spin' : ''"></i> Generate
      </button>
      <button class="btn btn-sm" @click="downloadIaC" :disabled="!iacOutput" title="Download file">
        <i class="fas fa-download"></i> Download
      </button>
      <button class="btn btn-sm" @click="copyIaC" :disabled="!iacOutput" title="Copy to clipboard">
        <i class="fas fa-copy"></i> Copy
      </button>
    </div>
    <div v-if="iacWarning" style="background:var(--warning-bg,#332b00);color:var(--warning,#ffcc00);padding:.5rem .8rem;border-radius:4px;font-size:.75rem;margin-bottom:.5rem">
      <i class="fas fa-exclamation-triangle" style="margin-right:.4rem"></i>{{ iacWarning }}
    </div>
    <div v-if="iacLoading" class="empty-msg">Generating...</div>
    <div v-else-if="!iacOutput" class="empty-msg">
      Select a format and agent, then click Generate to create an Infrastructure-as-Code export.
    </div>
    <div v-else style="position:relative">
      <pre style="background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:.8rem;font-size:.75rem;line-height:1.5;overflow-x:auto;max-height:600px;overflow-y:auto;font-family:'Fira Code','Cascadia Code',monospace;white-space:pre;tab-size:2;color:var(--text)">{{ iacOutput }}</pre>
    </div>
  </div>
</template>
