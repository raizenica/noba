<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, nextTick, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'
import { useDashboardStore } from '../../stores/dashboard'
import { useNotificationsStore } from '../../stores/notifications'
import { STREAM_DEFAULT_BACKLOG, STREAM_BUFFER_MAX_LINES } from '../../constants'

const { get, post } = useApi()
const authStore      = useAuthStore()
const dashStore      = useDashboardStore()
const notif          = useNotificationsStore()

const agents = computed(() => dashStore.live.agents || [])

const streamHost       = ref('')
const streamUnit       = ref('')
const streamPriority   = ref('')
const streamBacklog    = ref(STREAM_DEFAULT_BACKLOG)
const streamId         = ref('')
const streamActive     = ref(false)
const streamPaused     = ref(false)
const streamLoading    = ref(false)
const streamLines      = ref([])
const streamCursor     = ref(0)
const streamAutoScroll = ref(true)
const streamShowJump   = ref(false)

let _streamInterval = null

const SEVERITY_PATTERNS = [
  { pattern: /emerg|alert|crit|fatal|panic/i,      cls: 'log-crit'  },
  { pattern: /error|err\b|exception|traceback/i,   cls: 'log-error' },
  { pattern: /warn/i,                              cls: 'log-warn'  },
  { pattern: /info\b|notice/i,                     cls: 'log-info'  },
  { pattern: /debug\b/i,                           cls: 'log-debug' },
]

function streamLineClass(line) {
  for (const s of SEVERITY_PATTERNS) {
    if (s.pattern.test(line)) return s.cls
  }
  return ''
}

async function startStream() {
  if (!streamHost.value) return
  streamLoading.value = true
  streamLines.value   = []
  streamCursor.value  = 0
  streamPaused.value  = false
  try {
    const data = await post(`/api/agents/${encodeURIComponent(streamHost.value)}/stream-logs`, {
      unit:     streamUnit.value || '',
      priority: streamPriority.value || '',
      lines:    parseInt(String(streamBacklog.value), 10) || STREAM_DEFAULT_BACKLOG,
    })
    if (data?.stream_id) {
      streamId.value     = data.stream_id
      streamActive.value = true
      _startStreamPoll()
    }
  } catch { /* non-fatal */
  } finally {
    streamLoading.value = false
  }
}

async function stopStream() {
  _stopStreamPoll()
  if (streamHost.value && streamId.value) {
    try {
      await fetch(`/api/agents/${encodeURIComponent(streamHost.value)}/stream-logs/${streamId.value}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${authStore.token}` },
      })
    } catch { /* silent */ }
  }
  streamActive.value = false
  streamPaused.value = false
  streamId.value     = ''
}

function _startStreamPoll() {
  _stopStreamPoll()
  _streamInterval = setInterval(_pollStreamLines, 1000)
}

function _stopStreamPoll() {
  if (_streamInterval) { clearInterval(_streamInterval); _streamInterval = null }
}

async function _pollStreamLines() {
  if (!streamHost.value || !streamId.value || streamPaused.value) return
  try {
    const data = await get(
      `/api/agents/${encodeURIComponent(streamHost.value)}/stream/${streamId.value}?after=${streamCursor.value}`
    )
    if (data?.lines?.length > 0) {
      streamLines.value  = streamLines.value.concat(data.lines).slice(-STREAM_BUFFER_MAX_LINES)
      streamCursor.value = data.cursor || 0
      if (streamAutoScroll.value) {
        nextTick(() => {
          const el = document.getElementById('logs-stream-output')
          if (el) el.scrollTop = el.scrollHeight
        })
      } else {
        streamShowJump.value = true
      }
    }
    if (!data?.active) {
      streamActive.value = false
      _stopStreamPoll()
    }
  } catch {
    _stopStreamPoll()
    streamActive.value = false
    notif.addToast('Log stream disconnected', 'warning')
  }
}

function handleStreamScroll(e) {
  const el = e.target
  const atBottom = Math.abs(el.scrollHeight - el.scrollTop - el.clientHeight) < 10
  if (!atBottom && streamAutoScroll.value) {
    streamAutoScroll.value = false
  }
  if (atBottom) {
    streamShowJump.value = false
  }
}

function jumpToBottom() {
  streamAutoScroll.value = true
  const el = document.getElementById('logs-stream-output')
  if (el) el.scrollTop = el.scrollHeight
  streamShowJump.value = false
}

onUnmounted(() => {
  _stopStreamPoll()
  if (streamActive.value) stopStream()
})
</script>

<template>
  <div>
    <!-- Controls -->
    <div style="display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.5rem;align-items:flex-end">
      <div style="flex:1;min-width:120px">
        <label class="field-label" style="font-size:.65rem">Agent</label>
        <select class="field-select" v-model="streamHost" style="font-size:.75rem" :disabled="streamActive">
          <option value="">Select agent...</option>
          <option
            v-for="a in agents.filter(a => a.online)"
            :key="a.hostname"
            :value="a.hostname"
          >{{ a.hostname }}</option>
        </select>
      </div>
      <div style="min-width:100px">
        <label class="field-label" style="font-size:.65rem">Unit (optional)</label>
        <input
          v-model="streamUnit"
          class="field-input"
          type="text"
          placeholder="e.g. nginx"
          style="font-size:.75rem"
          :disabled="streamActive"
        >
      </div>
      <div style="min-width:80px">
        <label class="field-label" style="font-size:.65rem">Priority</label>
        <select class="field-select" v-model="streamPriority" style="font-size:.75rem" :disabled="streamActive">
          <option value="">All</option>
          <option v-for="p in ['emerg','alert','crit','err','warning','notice','info','debug']" :key="p" :value="p">{{ p }}</option>
        </select>
      </div>
      <div style="min-width:60px">
        <label class="field-label" style="font-size:.65rem">Backlog</label>
        <input
          v-model.number="streamBacklog"
          class="field-input"
          type="number"
          min="0"
          max="500"
          style="font-size:.75rem;width:60px"
          :disabled="streamActive"
        >
      </div>
      <div style="display:flex;gap:.3rem;align-items:flex-end;padding-bottom:1px">
        <button
          v-if="!streamActive"
          class="btn btn-primary btn-sm"
          :disabled="!streamHost || streamLoading"
          @click="startStream"
        >
          <i class="fas" :class="streamLoading ? 'fa-spinner fa-spin' : 'fa-play'"></i>
          {{ streamLoading ? 'Starting...' : 'Start' }}
        </button>
        <template v-else>
          <button
            class="btn btn-sm"
            :class="streamPaused ? 'btn-primary' : 'btn-secondary'"
            @click="streamPaused = !streamPaused"
            :title="streamPaused ? 'Resume' : 'Pause'"
          >
            <i class="fas" :class="streamPaused ? 'fa-play' : 'fa-pause'"></i>
          </button>
          <button
            class="btn btn-sm"
            style="border-color:var(--danger);color:var(--danger)"
            @click="stopStream"
          >
            <i class="fas fa-stop"></i> Stop
          </button>
        </template>
      </div>
    </div>

    <!-- Status bar -->
    <div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.4rem;font-size:.7rem;color:var(--text-muted)">
      <span>
        <i
          class="fas fa-circle"
          :style="`color:${streamActive ? (streamPaused ? 'var(--warning)' : 'var(--success)') : 'var(--text-muted)'};font-size:.45rem`"
        ></i>
        {{ streamActive ? (streamPaused ? `Paused from ${streamHost}` : `Streaming from ${streamHost}`) : 'Idle' }}
      </span>
      <span>{{ streamLines.length }} lines</span>
      <label style="margin-left:auto;display:flex;align-items:center;gap:.3rem;cursor:pointer">
        <input v-model="streamAutoScroll" type="checkbox" style="accent-color:var(--accent)">
        Auto-scroll
      </label>
      <button
        v-if="streamLines.length > 0"
        class="btn btn-xs"
        title="Clear"
        @click="streamLines = []; streamCursor = 0"
      ><i class="fas fa-trash"></i></button>
    </div>

    <!-- Output -->
    <div style="position:relative">
      <div
        id="logs-stream-output"
        style="background:var(--bg);border:1px solid var(--border);border-radius:4px;font-family:var(--font-data);font-size:.72rem;max-height:45vh;min-height:120px;overflow-y:auto;padding:.4rem .6rem;white-space:pre-wrap;word-break:break-all;line-height:1.5"
        @scroll="handleStreamScroll"
      >
        <div
          v-if="streamLines.length === 0 && !streamActive"
          style="color:var(--text-muted);text-align:center;padding:2rem 0"
        >Select an agent and click Start to begin live log streaming.</div>
        <div
          v-else-if="streamLines.length === 0 && streamActive"
          style="color:var(--text-muted);text-align:center;padding:2rem 0"
        >Waiting for log lines...</div>
        <div
          v-for="(line, i) in streamLines"
          :key="i"
          :class="streamLineClass(line)"
          style="white-space:pre-wrap;word-break:break-all"
        >{{ line }}</div>
      </div>

      <!-- Jump to bottom button -->
      <button
        v-if="streamShowJump"
        class="btn btn-xs btn-primary"
        style="position:absolute;bottom:10px;right:25px;border-radius:20px;padding:.2rem .6rem;box-shadow:0 2px 8px rgba(0,0,0,0.4)"
        @click="jumpToBottom"
      >
        <i class="fas fa-arrow-down" style="margin-right:4px"></i> New logs below
      </button>
    </div>
  </div>
</template>

<style scoped>
.log-crit  { color: #ff1744; }
.log-error { color: var(--danger); }
.log-warn  { color: var(--warning); }
.log-info  { color: var(--text-muted); }
.log-debug { color: color-mix(in srgb, var(--text-muted) 60%, transparent); }
</style>
