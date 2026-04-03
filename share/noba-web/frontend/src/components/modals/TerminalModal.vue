<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, watch, onUnmounted } from 'vue'
import AppModal from '../ui/AppModal.vue'
import { useModalsStore } from '../../stores/modals'
import { useApi } from '../../composables/useApi'

const modals = useModalsStore()
const api = useApi()

// ── WebSocket state ───────────────────────────────────────────────────────────
let ws = null
const lines = ref([])
const inputLine = ref('')
const terminalEl = ref(null)
const connected = ref(false)
const connecting = ref(false)
const maximized = ref(false)

async function connect() {
  if (ws) return
  connecting.value = true
  lines.value = []

  let wsToken
  try {
    const res = await api.post('/api/ws-token')
    wsToken = res.token
  } catch {
    lines.value.push({ type: 'error', text: 'Failed to obtain connection token' })
    connecting.value = false
    return
  }

  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${proto}://${location.host}/api/terminal?token=${encodeURIComponent(wsToken)}`
  ws = new WebSocket(url)

  ws.onopen = () => {
    connected.value = true
    connecting.value = false
    lines.value.push({ type: 'info', text: 'Connected to terminal.' })
    scrollBottom()
  }

  ws.onmessage = (evt) => {
    lines.value.push({ type: 'output', text: evt.data })
    scrollBottom()
  }

  ws.onerror = () => {
    lines.value.push({ type: 'error', text: 'WebSocket error.' })
    connected.value = false
    connecting.value = false
  }

  ws.onclose = () => {
    lines.value.push({ type: 'info', text: 'Connection closed.' })
    connected.value = false
    ws = null
  }
}

function disconnect() {
  if (ws) {
    ws.close()
    ws = null
  }
  connected.value = false
  connecting.value = false
}

function sendInput() {
  if (!ws || ws.readyState !== WebSocket.OPEN || !inputLine.value) return
  ws.send(inputLine.value + '\n')
  lines.value.push({ type: 'input', text: '$ ' + inputLine.value })
  inputLine.value = ''
  scrollBottom()
}

function scrollBottom() {
  setTimeout(() => {
    if (terminalEl.value) {
      terminalEl.value.scrollTop = terminalEl.value.scrollHeight
    }
  }, 10)
}

function toggleMaximize() {
  maximized.value = !maximized.value
  scrollBottom()
}

function handleGlobalKey(e) {
  if (e.altKey && e.key === 'Enter') {
    e.preventDefault()
    toggleMaximize()
  }
}

function close() {
  disconnect()
  modals.terminalModal = false
  maximized.value = false
}

watch(() => modals.terminalModal, (val) => {
  if (val) {
    connect()
    window.addEventListener('keydown', handleGlobalKey)
  } else {
    disconnect()
    window.removeEventListener('keydown', handleGlobalKey)
  }
})

onUnmounted(() => {
  disconnect()
  window.removeEventListener('keydown', handleGlobalKey)
})
</script>

<template>
  <AppModal
    :show="modals.terminalModal"
    title=""
    :width="maximized ? '98vw' : '90vw'"
    @close="close"
  >
    <!-- Custom header with status -->
    <div style="display:flex;align-items:center;gap:.75rem;padding:.75rem 1rem;border-bottom:1px solid var(--border);flex-shrink:0">
      <i class="fas fa-terminal" style="opacity:.6"></i>
      <span style="font-weight:500">Terminal</span>
      <span class="live-pill" :class="connected ? 'conn-sse' : 'conn-offline'" style="margin-left:auto;font-size:.7rem">
        <span class="live-dot" :class="connected ? 'sse' : 'offline'"></span>
        {{ connecting ? 'Connecting...' : connected ? 'Connected' : 'Disconnected' }}
      </span>
      <button class="btn btn-sm" @click="connect" :disabled="connected || connecting" v-if="!connected && !connecting">
        <i class="fas fa-plug" style="margin-right:4px"></i>Reconnect
      </button>
      <button class="icon-btn" @click="toggleMaximize" :title="maximized ? 'Restore' : 'Maximize (Alt+Enter)'">
        <i class="fas" :class="maximized ? 'fa-compress-alt' : 'fa-expand-alt'"></i>
      </button>
      <button class="modal-close" @click="close" aria-label="Close">&times;</button>
    </div>

    <!-- Output area -->
    <div
      ref="terminalEl"
      style="
        background: #0d1117;
        color: #c9d1d9;
        font-family: 'Courier New', monospace;
        font-size: .82rem;
        line-height: 1.5;
        padding: .75rem 1rem;
        overflow-y: auto;
        white-space: pre-wrap;
        word-break: break-all;
        transition: height 0.2s ease;
      "
      :style="{ height: maximized ? 'calc(100vh - 180px)' : '460px' }"
    >
      <div
        v-for="(line, i) in lines"
        :key="i"
        :style="{
          color: line.type === 'error' ? '#f85149'
               : line.type === 'info'  ? '#8b949e'
               : line.type === 'input' ? '#79c0ff'
               : '#c9d1d9'
        }"
      >{{ line.text }}</div>
      <div v-if="!lines.length" style="opacity:.3">Connecting to terminal WebSocket...</div>
    </div>

    <!-- Input row -->
    <div style="display:flex;gap:.5rem;padding:.75rem 1rem;border-top:1px solid var(--border)">
      <span style="font-family:monospace;font-size:.85rem;opacity:.5;align-self:center">$</span>
      <input
        v-model="inputLine"
        type="text"
        class="field-input"
        style="flex:1;font-family:monospace;font-size:.85rem"
        placeholder="Enter command..."
        :disabled="!connected"
        @keydown.enter="sendInput"
      />
      <button class="btn btn-primary" :disabled="!connected || !inputLine" @click="sendInput">
        <i class="fas fa-paper-plane"></i>
      </button>
    </div>
  </AppModal>
</template>
