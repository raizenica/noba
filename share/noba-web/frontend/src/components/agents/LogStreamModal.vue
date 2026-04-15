<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, watch, nextTick, onUnmounted } from 'vue'
import AppModal from '../ui/AppModal.vue'
import { useApi } from '../../composables/useApi'

const props = defineProps({
  show:     Boolean,
  hostname: { type: String, default: '' },
})
const emit = defineEmits(['close'])

const { post, get, del } = useApi()

// ── State ─────────────────────────────────────────────────────────────────────
const unit       = ref('')
const priority   = ref('')
const backlog    = ref(50)
const streamId   = ref('')
const active     = ref(false)
const loading    = ref(false)
const lines      = ref([])
const cursor     = ref(0)
const autoScroll = ref(true)
const hasNewLogs = ref(false)

let _interval = null

// ── Log line severity classification ──────────────────────────────────────────
const SEVERITY_PATTERNS = [
  { pattern: /emerg|alert|crit|fatal|panic/i, cls: 'log-crit' },
  { pattern: /error|err\b|exception|traceback/i, cls: 'log-error' },
  { pattern: /warn/i, cls: 'log-warn' },
  { pattern: /info\b|notice/i, cls: 'log-info' },
  { pattern: /debug\b/i, cls: 'log-debug' },
]

function lineClass(line) {
  for (const s of SEVERITY_PATTERNS) {
    if (s.pattern.test(line)) return s.cls
  }
  return ''
}

// ── UI Helpers ────────────────────────────────────────────────────────────────
function onScroll(e) {
  const el = e.target
  const isAtBottom = el.scrollHeight - el.scrollTop <= el.clientHeight + 10
  if (isAtBottom) {
    autoScroll.value = true
    hasNewLogs.value = false
  } else {
    autoScroll.value = false
  }
}

function jumpToBottom() {
  const el = document.getElementById('log-stream-output')
  if (el) {
    el.scrollTop = el.scrollHeight
    autoScroll.value = true
    hasNewLogs.value = false
  }
}

// ── Stream controls ───────────────────────────────────────────────────────────
async function startStream() {
  if (!props.hostname) return
  loading.value = true
  lines.value   = []
  cursor.value  = 0
  try {
    const data = await post(`/api/agents/${encodeURIComponent(props.hostname)}/stream-logs`, {
      unit:     unit.value || '',
      priority: priority.value || '',
      lines:    parseInt(String(backlog.value), 10) || 50,
    })
    if (data?.stream_id) {
      streamId.value = data.stream_id
      active.value   = true
      _startPoll()
    }
  } catch { /* silent */
  } finally {
    loading.value = false
  }
}

async function stopStream() {
  _stopPoll()
  if (props.hostname && streamId.value) {
    try {
      await del(`/api/agents/${encodeURIComponent(props.hostname)}/stream-logs/${streamId.value}`)
    } catch { /* silent */ }
  }
  active.value   = false
  streamId.value = ''
}

function _startPoll() {
  _stopPoll()
  _interval = setInterval(_pollLines, 1000)
}

function _stopPoll() {
  if (_interval) { clearInterval(_interval); _interval = null }
}

async function _pollLines() {
  if (!props.hostname || !streamId.value) return
  try {
    const data = await get(
      `/api/agents/${encodeURIComponent(props.hostname)}/stream/${streamId.value}?after=${cursor.value}`
    )
    if (data?.lines?.length > 0) {
      lines.value = lines.value.concat(data.lines).slice(-2000)
      cursor.value = data.cursor || 0
      
      if (autoScroll.value) {
        nextTick(() => {
          const el = document.getElementById('log-stream-output')
          if (el) el.scrollTop = el.scrollHeight
        })
      } else {
        hasNewLogs.value = true
      }
    }
    if (!data?.active) {
      active.value = false
      _stopPoll()
    }
  } catch { /* silent */ }
}

// ── Cleanup ───────────────────────────────────────────────────────────────────
watch(() => props.show, (val) => {
  if (!val) {
    _stopPoll()
    if (active.value) stopStream()
  }
})

onUnmounted(() => {
  _stopPoll()
})

function handleClose() {
  if (active.value) stopStream()
  emit('close')
}
</script>

<template>
  <AppModal :show="show" :title="`Log Stream — ${hostname}`" width="760px" @close="handleClose">

    <!-- Controls -->
    <div style="display:grid;grid-template-columns:1fr 1fr 80px auto;gap:.4rem;align-items:end;margin-bottom:.6rem">
      <div>
        <label class="field-label">Unit (optional)</label>
        <input v-model="unit" class="field-input" type="text" placeholder="nginx, sshd, ..." :disabled="active" style="font-size:.75rem">
      </div>
      <div>
        <label class="field-label">Priority</label>
        <select v-model="priority" class="field-select" :disabled="active" style="font-size:.75rem">
          <option value="">Any</option>
          <option v-for="p in ['emerg','alert','crit','err','warning','notice','info','debug']" :key="p" :value="p">{{ p }}</option>
        </select>
      </div>
      <div>
        <label class="field-label">Backlog</label>
        <input v-model.number="backlog" class="field-input" type="number" min="10" max="500" :disabled="active" style="font-size:.75rem">
      </div>
      <div style="display:flex;gap:.3rem">
        <button
          v-if="!active"
          class="btn btn-primary btn-sm"
          :disabled="loading || !hostname"
          @click="startStream"
        >
          <i class="fas" :class="loading ? 'fa-spinner fa-spin' : 'fa-play'"></i>
          {{ loading ? 'Starting...' : 'Start' }}
        </button>
        <button v-else class="btn btn-sm" style="border-color:var(--danger);color:var(--danger)" @click="stopStream">
          <i class="fas fa-stop"></i> Stop
        </button>
      </div>
    </div>

    <!-- Status bar -->
    <div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.4rem;font-size:.7rem;color:var(--text-muted)">
      <span>
        <i class="fas fa-circle" :style="`color:${active ? 'var(--success)' : 'var(--text-muted)'};font-size:.45rem`"></i>
        {{ active ? 'Streaming' : 'Idle' }}
      </span>
      <span>{{ lines.length }} lines</span>
      <label style="margin-left:auto;display:flex;align-items:center;gap:.3rem;cursor:pointer">
        <input v-model="autoScroll" type="checkbox" style="accent-color:var(--accent)">
        Auto-scroll
      </label>
      <button
        v-if="lines.length > 0"
        class="btn btn-xs"
        title="Clear"
        @click="lines = []; cursor = 0"
      ><i class="fas fa-trash"></i></button>
    </div>

    <!-- Log output -->
    <div style="position:relative">
      <div
        id="log-stream-output"
        style="height:360px;overflow-y:auto;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:.4rem .6rem;font-family:monospace;font-size:.68rem;line-height:1.45"
        @scroll="onScroll"
      >
        <div v-if="lines.length === 0 && !active" style="color:var(--text-muted);padding:.5rem 0">
          Press Start to begin streaming logs from <strong>{{ hostname }}</strong>.
        </div>
        <div
          v-for="(line, i) in lines"
          :key="i"
          :class="lineClass(line)"
          style="white-space:pre-wrap;word-break:break-all"
        >{{ line }}</div>
      </div>

      <!-- Jump to Bottom button -->
      <button
        v-if="hasNewLogs"
        class="btn btn-xs jump-btn"
        @click="jumpToBottom"
      >
        <i class="fas fa-arrow-down" style="margin-right:.3rem"></i> New logs below
      </button>
    </div>

    <template #footer>
      <button class="btn btn-xs" @click="handleClose">Close</button>
    </template>
  </AppModal>
</template>

<style scoped>
.log-crit  { color: #ff1744; }
.log-error { color: var(--danger); }
.log-warn  { color: var(--warning); }
.log-info  { color: var(--text-muted); }
.log-debug { color: color-mix(in srgb, var(--text-muted) 60%, transparent); }

.jump-btn {
  position: absolute;
  bottom: 10px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--accent);
  color: #fff;
  border: none;
  box-shadow: 0 2px 8px rgba(0,0,0,0.4);
  z-index: 10;
  animation: slide-up .2s ease-out;
}

@keyframes slide-up {
  from { transform: translate(-50%, 10px); opacity: 0; }
  to   { transform: translate(-50%, 0); opacity: 1; }
}
</style>
