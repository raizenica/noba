<script setup>
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '../../stores/auth'

const props = defineProps({
  hostname: { type: String, required: true },
  visible: { type: Boolean, default: true },
})

const authStore = useAuthStore()

// ── State ────────────────────────────────────────────────────────────────────
const input        = ref('')
const lines        = ref([])
const connected    = ref(false)
const sending      = ref(false)
const cmdHistory   = ref([])
const historyIdx   = ref(-1)
const scrollEl     = ref(null)
const inputEl      = ref(null)
let ws             = null
let reconnectTimer = null

// ── Scroll to bottom ─────────────────────────────────────────────────────────
function scrollBottom() {
  nextTick(() => {
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  })
}

// ── Push a line ──────────────────────────────────────────────────────────────
function pushLine(text, type = 'output') {
  lines.value.push({ text, type, ts: Date.now() })
  if (lines.value.length > 500) lines.value = lines.value.slice(-500)
  scrollBottom()
}

// ── WebSocket connection ─────────────────────────────────────────────────────
function connect() {
  if (ws) disconnect()
  if (!props.hostname || !authStore.token) return

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${proto}//${location.host}/api/agents/${encodeURIComponent(props.hostname)}/terminal?token=${encodeURIComponent(authStore.token)}`

  ws = new WebSocket(url)

  ws.onopen = () => {
    connected.value = true
    pushLine(`Connected to ${props.hostname}`, 'system')
    pushLine('Type commands to execute on the remote agent. Use "help" for built-in commands.', 'system')
  }

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)

      if (msg.type === 'ack') {
        if (msg.delivery === 'queued') {
          pushLine('(queued — agent not on WebSocket, waiting for next heartbeat)', 'system')
        }
        return
      }

      if (msg.type === 'error') {
        pushLine(msg.error || 'Unknown error', 'error')
        sending.value = false
        return
      }

      if (msg.type === 'stream') {
        pushLine(msg.line || '', 'output')
        return
      }

      if (msg.type === 'result' || msg.status) {
        let output = ''
        if (msg.stdout) output = msg.stdout
        else if (msg.message) output = msg.message
        else if (msg.error) output = msg.error
        else output = JSON.stringify(msg, null, 2)

        const isError = msg.status === 'error' || (msg.exit_code !== undefined && msg.exit_code !== 0)
        output.split('\n').forEach(line => {
          if (line) pushLine(line, isError ? 'error' : 'output')
        })

        if (msg.exit_code !== undefined && msg.exit_code !== 0) {
          pushLine(`(exit code: ${msg.exit_code})`, 'system')
        }

        sending.value = false
        return
      }
    } catch {
      pushLine(event.data, 'output')
    }
  }

  ws.onclose = (event) => {
    connected.value = false
    sending.value = false
    if (event.code !== 1000) {
      pushLine(`Disconnected (${event.reason || event.code})`, 'error')
      reconnectTimer = setTimeout(connect, 3000)
    }
  }

  ws.onerror = () => {
    connected.value = false
    sending.value = false
  }
}

function disconnect() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  if (ws) { try { ws.close(1000) } catch {} ws = null }
  connected.value = false
}

// ── Execute command ──────────────────────────────────────────────────────────
function execute() {
  const cmd = input.value.trim()
  if (!cmd) return

  if (cmdHistory.value[cmdHistory.value.length - 1] !== cmd) {
    cmdHistory.value.push(cmd)
    if (cmdHistory.value.length > 100) cmdHistory.value.shift()
  }
  historyIdx.value = -1

  pushLine(`${props.hostname}$ ${cmd}`, 'input')
  input.value = ''

  if (cmd === 'clear') { lines.value = []; return }
  if (cmd === 'help') {
    pushLine('Built-in: clear, help, history, reconnect', 'system')
    pushLine('All other input executes as shell commands on the remote agent.', 'system')
    return
  }
  if (cmd === 'history') {
    cmdHistory.value.forEach((c, i) => pushLine(`  ${i + 1}  ${c}`, 'system'))
    return
  }
  if (cmd === 'reconnect') { disconnect(); connect(); return }

  if (!ws || ws.readyState !== WebSocket.OPEN) {
    pushLine('Not connected. Type "reconnect" to retry.', 'error')
    return
  }

  sending.value = true
  ws.send(JSON.stringify({ type: 'exec', command: cmd, timeout: 30 }))
}

// ── Keyboard ─────────────────────────────────────────────────────────────────
function onKeydown(e) {
  if (e.key === 'Enter') { e.preventDefault(); execute() }
  else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (!cmdHistory.value.length) return
    if (historyIdx.value < 0) historyIdx.value = cmdHistory.value.length
    historyIdx.value = Math.max(0, historyIdx.value - 1)
    input.value = cmdHistory.value[historyIdx.value] || ''
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (historyIdx.value < 0) return
    historyIdx.value = Math.min(cmdHistory.value.length, historyIdx.value + 1)
    input.value = historyIdx.value >= cmdHistory.value.length ? '' : cmdHistory.value[historyIdx.value]
  } else if (e.key === 'l' && e.ctrlKey) {
    e.preventDefault()
    lines.value = []
  }
}

function focusInput() { inputEl.value?.focus() }

// ── Lifecycle ────────────────────────────────────────────────────────────────
watch(() => props.visible, (val) => {
  if (val) { connect(); nextTick(() => inputEl.value?.focus()) }
  else disconnect()
})

watch(() => props.hostname, () => {
  lines.value = []
  if (props.visible) connect()
})

onMounted(() => { if (props.visible && props.hostname) connect() })
onUnmounted(() => disconnect())
</script>

<template>
  <div class="remote-terminal" @click="focusInput">
    <div class="term-header">
      <i class="fas fa-terminal" style="margin-right:.4rem;opacity:.6"></i>
      <span style="font-weight:600;font-size:.75rem">{{ hostname }}</span>
      <span
        class="term-status"
        :class="connected ? 'term-online' : 'term-offline'"
      >{{ connected ? 'connected' : 'disconnected' }}</span>
      <span v-if="sending" style="margin-left:.5rem;font-size:.65rem;color:var(--warning)">
        <i class="fas fa-circle-notch fa-spin"></i>
      </span>
      <button
        class="btn btn-xs"
        style="margin-left:auto;opacity:.5"
        title="Clear terminal"
        @click.stop="lines = []"
      ><i class="fas fa-eraser"></i></button>
    </div>

    <div ref="scrollEl" class="term-output">
      <div
        v-for="(line, i) in lines"
        :key="i"
        class="term-line"
        :class="`term-${line.type}`"
      >{{ line.text }}</div>
    </div>

    <div class="term-input-row">
      <span class="term-prompt">{{ hostname }}$</span>
      <input
        ref="inputEl"
        v-model="input"
        class="term-input"
        :disabled="!authStore.isOperator"
        :placeholder="authStore.isOperator ? (connected ? 'Type a command...' : 'Connecting...') : 'Operator access required'"
        spellcheck="false"
        autocomplete="off"
        @keydown="onKeydown"
      >
    </div>
  </div>
</template>

<style scoped>
.remote-terminal {
  display: flex;
  flex-direction: column;
  background: #0d1117;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: .75rem;
  min-height: 300px;
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
.term-output {
  flex: 1;
  overflow-y: auto;
  padding: .5rem .6rem;
  min-height: 200px;
  max-height: 400px;
}
.term-line {
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
  padding: 0 .2rem;
}
.term-input { color: #58a6ff; }
.term-output-line, .term-output { color: #c9d1d9; }
.term-error { color: #f85149; }
.term-system { color: #8b949e; font-style: italic; }
.term-input-row {
  display: flex;
  align-items: center;
  padding: .3rem .6rem;
  background: #0d1117;
  border-top: 1px solid #21262d;
}
.term-prompt {
  color: #3fb950;
  margin-right: .4rem;
  white-space: nowrap;
  font-weight: 600;
}
.term-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #c9d1d9;
  font-family: inherit;
  font-size: inherit;
  caret-color: #58a6ff;
}
.term-input::placeholder { color: #484f58; }
.term-input:disabled { cursor: not-allowed; opacity: .5; }
</style>
