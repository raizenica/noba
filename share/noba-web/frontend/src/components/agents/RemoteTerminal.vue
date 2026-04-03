<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { TERMINAL_RECONNECT_MS } from '../../constants'

const props = defineProps({
  hostname: { type: String, required: true },
  visible: { type: Boolean, default: true },
})

const authStore = useAuthStore()
const api = useApi()

const termRef       = ref(null)
const connected     = ref(false)
const agentOnline   = ref(true)
let ws              = null
let connecting      = false
let term            = null
let fitAddon        = null
let reconnectTimer  = null
let sessionId       = ''

async function connect() {
  if (connecting) return
  connecting = true
  if (ws) disconnect()
  if (!props.hostname || !authStore.token) { connecting = false; return }

  sessionId = `term-${props.hostname}-${Date.now()}`

  let wsToken
  try {
    const res = await api.post('/api/ws-token')
    wsToken = res.token
  } catch {
    term?.write('\r\n\x1b[31mFailed to obtain connection token\x1b[0m\r\n')
    connecting = false
    return
  }

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${proto}//${location.host}/api/agents/${encodeURIComponent(props.hostname)}/terminal?token=${encodeURIComponent(wsToken)}`

  ws = new WebSocket(url)
  connecting = false

  ws.onopen = () => {
    connected.value = true
    // Request PTY session
    const dims = fitAddon ? fitAddon.proposeDimensions() : { cols: 80, rows: 24 }
    ws.send(JSON.stringify({
      type: 'pty_open',
      session: sessionId,
      cols: dims?.cols || 80,
      rows: dims?.rows || 24,
    }))
  }

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)

      if (msg.type === 'pty_output') {
        term?.write(msg.data)
        return
      }

      if (msg.type === 'pty_opened') {
        agentOnline.value = true
        term?.write('\x1b[32mConnected to ' + props.hostname + '\x1b[0m\r\n')
        return
      }

      if (msg.type === 'pty_exit') {
        term?.write('\r\n\x1b[33m[session ended, exit code: ' + (msg.code || 0) + ']\x1b[0m\r\n')
        connected.value = false
        return
      }

      if (msg.type === 'pty_error') {
        term?.write('\r\n\x1b[31m' + (msg.error || 'PTY error') + '\x1b[0m\r\n')
        agentOnline.value = false
        return
      }

      // Legacy command results (fallback)
      if (msg.type === 'result' || msg.type === 'stream') {
        const text = msg.stdout || msg.line || msg.message || msg.error || ''
        if (text) term?.write(text.replace(/\n/g, '\r\n'))
        return
      }

      if (msg.type === 'ack') return
    } catch {
      // ignore
    }
  }

  ws.onclose = (event) => {
    connected.value = false
    if (event.code !== 1000) {
      term?.write('\r\n\x1b[31mDisconnected (' + (event.reason || event.code) + ')\x1b[0m\r\n')
      reconnectTimer = setTimeout(connect, TERMINAL_RECONNECT_MS)
    }
  }

  ws.onerror = () => {
    connected.value = false
  }
}

function disconnect() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  if (ws && ws.readyState === WebSocket.OPEN && sessionId) {
    try { ws.send(JSON.stringify({ type: 'pty_close', session: sessionId })) } catch {}
  }
  if (ws) { try { ws.close(1000) } catch {} ws = null }
  connected.value = false
  sessionId = ''
}

function initTerminal() {
  if (term) return
  if (!termRef.value) return

  term = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
    theme: {
      background: '#0d1117',
      foreground: '#c9d1d9',
      cursor: '#58a6ff',
      cursorAccent: '#0d1117',
      selectionBackground: '#264f78',
      black: '#0d1117',
      red: '#f85149',
      green: '#3fb950',
      yellow: '#d29922',
      blue: '#58a6ff',
      magenta: '#bc8cff',
      cyan: '#39c5cf',
      white: '#c9d1d9',
      brightBlack: '#484f58',
      brightRed: '#ff7b72',
      brightGreen: '#56d364',
      brightYellow: '#e3b341',
      brightBlue: '#79c0ff',
      brightMagenta: '#d2a8ff',
      brightCyan: '#56d4dd',
      brightWhite: '#f0f6fc',
    },
    allowProposedApi: true,
  })

  fitAddon = new FitAddon()
  term.loadAddon(fitAddon)
  term.open(termRef.value)

  nextTick(() => {
    try { fitAddon.fit() } catch {}
  })

  // Send keystrokes to PTY
  term.onData((data) => {
    if (ws && ws.readyState === WebSocket.OPEN && sessionId) {
      ws.send(JSON.stringify({ type: 'pty_input', session: sessionId, data }))
    }
  })

  // Handle resize
  term.onResize(({ cols, rows }) => {
    if (ws && ws.readyState === WebSocket.OPEN && sessionId) {
      ws.send(JSON.stringify({ type: 'pty_resize', session: sessionId, cols, rows }))
    }
  })

  // Resize observer
  const ro = new ResizeObserver(() => {
    try { fitAddon.fit() } catch {}
  })
  ro.observe(termRef.value)
}

watch(() => props.visible, (val) => {
  if (val) {
    nextTick(() => {
      initTerminal()
      if (!connected.value) connect()
      try { fitAddon?.fit() } catch {}
      term?.focus()
    })
  } else {
    disconnect()
  }
})

watch(() => props.hostname, () => {
  disconnect()
  if (term) { term.clear(); term.reset() }
  if (props.visible) nextTick(() => connect())
})

onMounted(() => {
  if (props.visible) {
    nextTick(() => {
      initTerminal()
      connect()
    })
  }
})

onUnmounted(() => {
  disconnect()
  if (term) { term.dispose(); term = null }
})
</script>

<template>
  <div class="remote-terminal-wrap">
    <div class="term-header">
      <i class="fas fa-terminal" style="margin-right:.4rem;opacity:.6"></i>
      <span style="font-weight:600;font-size:.75rem">{{ hostname }}</span>
      <span
        class="term-status"
        :class="connected ? 'term-online' : 'term-offline'"
      >{{ connected ? 'connected' : 'disconnected' }}</span>
    </div>
    <div ref="termRef" class="term-container"></div>
  </div>
</template>

<style scoped>
.remote-terminal-wrap {
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  background: #0d1117;
}
.term-header {
  display: flex;
  align-items: center;
  padding: .4rem .6rem;
  background: #161b22;
  border-bottom: 1px solid #21262d;
  color: #8b949e;
  font-size: .7rem;
}
.term-status {
  margin-left: .5rem;
  font-size: .6rem;
  padding: .1rem .4rem;
  border-radius: 3px;
}
.term-online { background: #23863620; color: #3fb950; }
.term-offline { background: #f8514920; color: #f85149; }
.term-container {
  height: 400px;
  padding: 4px;
}
</style>
