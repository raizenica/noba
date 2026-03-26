<script setup>
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useNotificationsStore } from '../stores/notifications'
import { useApi } from '../composables/useApi'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const notify = useNotificationsStore()
const api = useApi()

const hostname = computed(() => route.params.hostname)

const canvasEl = ref(null)
const status = ref('connecting')   // connecting | active | unavailable | error | closed
const statusMsg = ref('')
const frameCount = ref(0)
const frameW = ref(0)
const frameH = ref(0)
const quality = ref(70)
const fps = ref(10)
const clipboardStatus = ref('')   // '' | 'ok' | 'error'
let clipboardStatusTimeout = null
// Writable computed so it stays reactive to auth role (role loads async in new tabs)
const _inputToggle = ref(true)
const inputEnabled = computed({
  get: () => _inputToggle.value && auth.isOperator,
  set: (v) => { _inputToggle.value = v },
})
const showToolbar = ref(true)
const isPopup = !!window.opener

let ws = null
let connecting = false
let toolbarTimeout = null
let lastMoveTime = 0

// ── WebSocket connection ──────────────────────────────────────────────────────

function buildWsUrl(wsToken) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host = window.location.host
  const q = new URLSearchParams({
    token: wsToken,
    quality: quality.value,
    fps: fps.value,
  })
  return `${proto}://${host}/api/agents/${hostname.value}/rdp?${q}`
}

async function connect() {
  if (connecting) return
  connecting = true
  if (ws) {
    ws.close()
    ws = null
  }
  status.value = 'connecting'
  statusMsg.value = ''
  frameCount.value = 0

  let wsToken
  try {
    const res = await api.post('/api/ws-token')
    wsToken = res.token
  } catch {
    status.value = 'error'
    statusMsg.value = 'Failed to obtain connection token'
    connecting = false
    return
  }

  ws = new WebSocket(buildWsUrl(wsToken))
  connecting = false
  ws.binaryType = 'blob'

  ws.onopen = () => {
    status.value = 'active'
  }

  ws.onmessage = async (e) => {
    const msg = JSON.parse(e.data)

    if (msg.type === 'rdp_frame') {
      frameW.value = msg.w
      frameH.value = msg.h
      frameCount.value++
      await drawFrame(msg.data)

    } else if (msg.type === 'rdp_ready') {
      status.value = 'active'

    } else if (msg.type === 'rdp_unavailable') {
      status.value = 'unavailable'
      statusMsg.value = msg.reason || 'No display available on this agent'

    } else if (msg.type === 'rdp_clipboard') {
      navigator.clipboard.writeText(msg.text ?? '').then(() => {
        _setClipboardStatus('ok')
      }).catch(() => {
        _setClipboardStatus('error')
      })
    }
  }

  ws.onerror = () => {
    status.value = 'error'
    statusMsg.value = 'WebSocket error'
  }

  ws.onclose = (e) => {
    if (status.value !== 'unavailable') {
      status.value = 'closed'
      statusMsg.value = e.code === 4001 ? 'Authentication failed' : 'Connection closed'
    }
    ws = null
  }
}

async function drawFrame(b64data) {
  const canvas = canvasEl.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')

  // Use createImageBitmap for off-thread decode (non-blocking)
  const binary = atob(b64data)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  // Sniff format: JPEG starts with 0xFF 0xD8, everything else assumed PNG
  const mime = bytes[0] === 0xFF ? 'image/jpeg' : 'image/png'
  const blob = new Blob([bytes], { type: mime })

  try {
    const bitmap = await createImageBitmap(blob)
    // Resize canvas to match frame dimensions (only when they change)
    if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
      canvas.width = bitmap.width
      canvas.height = bitmap.height
    }
    ctx.drawImage(bitmap, 0, 0)
    bitmap.close()
  } catch {
    // Fallback: img element
    const img = new Image()
    img.onload = () => {
      if (canvas.width !== img.width || canvas.height !== img.height) {
        canvas.width = img.width
        canvas.height = img.height
      }
      ctx.drawImage(img, 0, 0)
      URL.revokeObjectURL(img.src)
    }
    img.src = URL.createObjectURL(blob)
  }
}

// ── Clipboard bridge ──────────────────────────────────────────────────────────

function _setClipboardStatus(s) {
  clipboardStatus.value = s
  clearTimeout(clipboardStatusTimeout)
  clipboardStatusTimeout = setTimeout(() => { clipboardStatus.value = '' }, 2000)
}

async function pasteToRemote() {
  if (!inputEnabled.value || !ws || ws.readyState !== WebSocket.OPEN) return
  try {
    const text = await navigator.clipboard.readText()
    if (!text) return
    ws.send(JSON.stringify({ type: 'rdp_clipboard_paste', text }))
    _setClipboardStatus('ok')
  } catch {
    _setClipboardStatus('error')
  }
}

function copyFromRemote() {
  if (!inputEnabled.value || !ws || ws.readyState !== WebSocket.OPEN) return
  ws.send(JSON.stringify({ type: 'rdp_clipboard_get' }))
}

function disconnect() {
  if (ws) {
    try { ws.send(JSON.stringify({ type: 'rdp_stop' })) } catch { /* ignore */ }
    ws.close()
    ws = null
  }
  if (window.opener) {
    window.close()
  } else {
    router.push({ name: 'remote' })
  }
}

// ── Input injection ───────────────────────────────────────────────────────────

function canvasCoords(e) {
  const canvas = canvasEl.value
  if (!canvas) return { x: 0, y: 0 }
  const rect = canvas.getBoundingClientRect()
  // object-fit: contain letterboxes the canvas content inside the CSS box.
  // Compute the actual content rect to get accurate coords.
  const canvasAspect = canvas.width / canvas.height
  const boxAspect = rect.width / rect.height
  let contentW, contentH, offsetX, offsetY
  if (canvasAspect > boxAspect) {
    contentW = rect.width
    contentH = rect.width / canvasAspect
    offsetX = 0
    offsetY = (rect.height - contentH) / 2
  } else {
    contentH = rect.height
    contentW = rect.height * canvasAspect
    offsetX = (rect.width - contentW) / 2
    offsetY = 0
  }
  return {
    x: Math.max(0, Math.min(1, (e.clientX - rect.left - offsetX) / contentW)),
    y: Math.max(0, Math.min(1, (e.clientY - rect.top - offsetY) / contentH)),
  }
}

function sendInput(payload) {
  if (!inputEnabled.value || !ws || ws.readyState !== WebSocket.OPEN) return
  ws.send(JSON.stringify({ type: 'rdp_input', ...payload }))
}

function onMouseMove(e) {
  showToolbarBriefly()
  const now = Date.now()
  if (now - lastMoveTime < 50) return  // ~20 Hz
  lastMoveTime = now
  const { x, y } = canvasCoords(e)
  sendInput({ event: 'mousemove', x, y })
}

function onMouseDown(e) {
  e.preventDefault()
  const { x, y } = canvasCoords(e)
  // Map browser button: 0=left→1, 1=middle→2, 2=right→3
  const btn = e.button === 2 ? 3 : e.button === 1 ? 2 : 1
  sendInput({ event: 'mousedown', x, y, button: btn })
}

function onMouseUp(e) {
  const { x, y } = canvasCoords(e)
  const btn = e.button === 2 ? 3 : e.button === 1 ? 2 : 1
  sendInput({ event: 'mouseup', x, y, button: btn })
}

function onWheel(e) {
  e.preventDefault()
  sendInput({ event: 'wheel', delta_y: e.deltaY })
}

function onKeyDown(e) {
  e.preventDefault()
  sendInput({ event: 'keydown', code: e.code, key: e.key, keycode: e.keyCode })
}

function onKeyUp(e) {
  e.preventDefault()
  sendInput({ event: 'keyup', code: e.code, key: e.key, keycode: e.keyCode })
}

function onContextMenu(e) {
  e.preventDefault()
}

// ── Quality / settings ────────────────────────────────────────────────────────

function applyQuality() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return
  ws.send(JSON.stringify({ type: 'rdp_quality', quality: quality.value, fps: fps.value }))
}

// ── Toolbar auto-hide ─────────────────────────────────────────────────────────

function showToolbarBriefly() {
  showToolbar.value = true
  clearTimeout(toolbarTimeout)
  toolbarTimeout = setTimeout(() => { showToolbar.value = false }, 3000)
}

function toggleToolbar() {
  showToolbar.value = !showToolbar.value
  if (showToolbar.value) showToolbarBriefly()
}

// ── Fullscreen ────────────────────────────────────────────────────────────────

function toggleFullscreen() {
  const el = document.querySelector('.rdp-viewport')
  if (!el) return
  if (!document.fullscreenElement) {
    el.requestFullscreen().catch(() => {})
  } else {
    document.exitFullscreen()
  }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────

onMounted(() => {
  connect()
  showToolbarBriefly()
})

onUnmounted(() => {
  clearTimeout(toolbarTimeout)
  clearTimeout(clipboardStatusTimeout)
  if (ws) {
    try { ws.send(JSON.stringify({ type: 'rdp_stop' })) } catch { /* ignore */ }
    ws.close()
    ws = null
  }
})
</script>

<template>
  <div
    class="rdp-viewport"
    @mousemove="showToolbarBriefly"
    @keydown.stop
  >
    <!-- Status overlay (shown until first frame or on error) -->
    <div v-if="status !== 'active' || frameCount === 0" class="rdp-overlay">
      <div class="rdp-status-card">
        <i
          class="fas"
          :class="{
            'fa-spinner fa-spin': status === 'connecting' || (status === 'active' && frameCount === 0),
            'fa-exclamation-triangle': status === 'error' || status === 'unavailable',
            'fa-times-circle': status === 'closed',
          }"
        ></i>
        <div class="rdp-status-label">
          <template v-if="status === 'connecting'">Connecting to {{ hostname }}…</template>
          <template v-else-if="status === 'active' && frameCount === 0">Waiting for first frame…</template>
          <template v-else-if="status === 'unavailable'">{{ statusMsg }}</template>
          <template v-else-if="status === 'error'">{{ statusMsg }}</template>
          <template v-else-if="status === 'closed'">{{ statusMsg }}</template>
        </div>
        <button v-if="status !== 'connecting'" class="btn btn-primary" style="margin-top:1rem" @click="connect">
          Reconnect
        </button>
        <button class="btn" style="margin-top:.5rem" @click="disconnect()">
          {{ isPopup ? 'Close window' : 'Back to list' }}
        </button>
      </div>
    </div>

    <!-- Canvas (hidden until first frame arrives) -->
    <canvas
      v-show="status === 'active' && frameCount > 0"
      ref="canvasEl"
      class="rdp-canvas"
      tabindex="0"
      @mousemove="onMouseMove"
      @mousedown="onMouseDown"
      @mouseup="onMouseUp"
      @wheel.prevent="onWheel"
      @keydown="onKeyDown"
      @keyup="onKeyUp"
      @contextmenu="onContextMenu"
      @click.left="canvasEl && canvasEl.focus()"
    />

    <!-- Toolbar (auto-hides after 3s of no mouse movement) -->
    <div
      class="rdp-toolbar"
      :class="{ 'rdp-toolbar--visible': showToolbar }"
    >
      <button class="icon-btn" title="Back" @click="disconnect">
        <i class="fas fa-arrow-left"></i>
      </button>

      <span class="rdp-toolbar-host">{{ hostname }}</span>

      <span class="rdp-toolbar-info" v-if="frameCount > 0">
        {{ frameW }}×{{ frameH }}
      </span>

      <div class="rdp-toolbar-group">
        <label class="rdp-toolbar-label">Q</label>
        <input
          v-model.number="quality"
          type="range" min="10" max="100" step="5"
          class="rdp-slider"
          @change="applyQuality"
        />
        <span class="rdp-toolbar-val">{{ quality }}</span>
      </div>

      <div class="rdp-toolbar-group">
        <label class="rdp-toolbar-label">FPS</label>
        <input
          v-model.number="fps"
          type="range" min="1" max="15" step="1"
          class="rdp-slider"
          @change="applyQuality"
        />
        <span class="rdp-toolbar-val">{{ fps }}</span>
      </div>

      <button
        v-if="auth.isOperator"
        class="icon-btn"
        :title="inputEnabled ? 'Input: on (click to disable)' : 'Input: off (click to enable)'"
        :style="inputEnabled ? 'color:var(--accent)' : ''"
        @click="inputEnabled = !inputEnabled"
      >
        <i class="fas fa-mouse-pointer"></i>
      </button>

      <button
        v-if="auth.isOperator"
        class="icon-btn"
        :title="clipboardStatus === 'ok' ? 'Pasted!' : clipboardStatus === 'error' ? 'Clipboard error' : 'Paste local clipboard into remote'"
        :style="clipboardStatus === 'ok' ? 'color:var(--accent)' : clipboardStatus === 'error' ? 'color:#f7768e' : ''"
        @click="pasteToRemote"
      >
        <i class="fas fa-clipboard-check" v-if="clipboardStatus === 'ok'"></i>
        <i class="fas fa-clipboard" v-else></i>
      </button>

      <button
        v-if="auth.isOperator"
        class="icon-btn"
        :title="clipboardStatus === 'ok' ? 'Copied!' : clipboardStatus === 'error' ? 'Clipboard error' : 'Copy remote clipboard to local'"
        :style="clipboardStatus === 'ok' ? 'color:var(--accent)' : clipboardStatus === 'error' ? 'color:#f7768e' : ''"
        @click="copyFromRemote"
      >
        <i class="fas fa-copy"></i>
      </button>

      <button class="icon-btn" title="Fullscreen" @click="toggleFullscreen">
        <i class="fas fa-expand"></i>
      </button>

      <button class="icon-btn" title="Disconnect" @click="disconnect">
        <i class="fas fa-times"></i>
      </button>
    </div>
  </div>
</template>

<style scoped>
.rdp-viewport {
  position: fixed;
  inset: 0;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  cursor: none;
}

.rdp-viewport:hover {
  cursor: default;
}

.rdp-canvas {
  width: 100%;
  height: 100%;
  object-fit: contain;
  outline: none;
  cursor: crosshair;
}

/* Status overlay */
.rdp-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.85);
  z-index: 10;
}

.rdp-status-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: .5rem;
  color: var(--text, #e0e0e0);
  font-size: 1rem;
}

.rdp-status-card .fas {
  font-size: 2rem;
  color: var(--accent, #7aa2f7);
  margin-bottom: .5rem;
}

.rdp-status-label {
  color: var(--text-muted, #9aa0b0);
  max-width: 320px;
  text-align: center;
}

/* Toolbar */
.rdp-toolbar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  gap: .5rem;
  padding: .4rem .75rem;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  color: #e0e0e0;
  font-size: .82rem;
  opacity: 0;
  transform: translateY(-100%);
  transition: opacity .2s, transform .2s;
  z-index: 20;
  pointer-events: none;
}

.rdp-toolbar--visible {
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
}

.rdp-toolbar-host {
  font-weight: 600;
  margin-right: .25rem;
}

.rdp-toolbar-info {
  color: #888;
  font-size: .78rem;
  margin-right: auto;
}

.rdp-toolbar-group {
  display: flex;
  align-items: center;
  gap: .3rem;
}

.rdp-toolbar-label {
  color: #888;
  font-size: .75rem;
  min-width: 14px;
}

.rdp-toolbar-val {
  font-size: .75rem;
  min-width: 22px;
  text-align: right;
}

.rdp-slider {
  width: 72px;
  accent-color: var(--accent, #7aa2f7);
  cursor: pointer;
}

</style>
