<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useApi }       from '../composables/useApi'
import { useAuthStore } from '../stores/auth'
import { useDashboardStore } from '../stores/dashboard'

const { get, post } = useApi()
const authStore      = useAuthStore()
const dashStore      = useDashboardStore()

const agents = computed(() => dashStore.live.agents || [])

// ── Active tab ────────────────────────────────────────────────────────────────
const activeTab = ref('syslog')

function setTab(tab) {
  activeTab.value = tab
  if (tab === 'syslog')   fetchLog()
  if (tab === 'history')  fetchCommandHistory()
  if (tab === 'audit')    fetchAuditLog()
  if (tab === 'journal')  { fetchJournalUnits(); fetchJournal() }
}

// ── System Log tab ────────────────────────────────────────────────────────────
const LOG_TYPES = ['syserr', 'syslog', 'auth', 'kern', 'daemon', 'dpkg', 'apt', 'nginx', 'docker']

const selectedLog   = ref('syserr')
const logContent    = ref('')
const logLoading    = ref(false)
const logAutoRefresh = ref(false)
let   _logTimer     = null

async function fetchLog() {
  logLoading.value = true
  try {
    const text = await get(`/api/log-viewer?type=${selectedLog.value}`)
    logContent.value = typeof text === 'string' ? text : ''
    await nextTick()
    const el = document.getElementById('syslog-pre')
    if (el) el.scrollTop = el.scrollHeight
  } catch (e) {
    logContent.value = 'Failed to fetch log: ' + e.message
  } finally {
    logLoading.value = false
  }
}

function toggleLogAutoRefresh() {
  logAutoRefresh.value = !logAutoRefresh.value
  if (_logTimer) { clearInterval(_logTimer); _logTimer = null }
  if (logAutoRefresh.value) {
    _logTimer = setInterval(fetchLog, 5000)
  }
}

// ── Command History tab ───────────────────────────────────────────────────────
const cmdHistory        = ref([])
const cmdHistoryLoading = ref(false)

async function fetchCommandHistory() {
  cmdHistoryLoading.value = true
  try {
    const data = await get('/api/agents/command-history?limit=50')
    cmdHistory.value = Array.isArray(data) ? data : []
  } catch { /* silent */ }
  finally { cmdHistoryLoading.value = false }
}

function historyStatusClass(status) {
  if (status === 'ok')     return 'bs'
  if (status === 'error')  return 'bd'
  if (status === 'queued') return 'bn'
  return 'bw'
}

// ── Audit Log tab ─────────────────────────────────────────────────────────────
const auditLog       = ref([])
const auditLoading   = ref(false)
const auditPage      = ref(1)
const auditPageSize  = ref(50)
const auditTotal     = ref(0)
const auditSortField = ref('time')
const auditSortDir   = ref('desc')

const auditSorted = computed(() => {
  const log = [...auditLog.value]
  const field = auditSortField.value
  const dir   = auditSortDir.value === 'asc' ? 1 : -1
  return log.sort((a, b) => {
    const va = a[field] ?? ''
    const vb = b[field] ?? ''
    if (typeof va === 'number') return (va - vb) * dir
    return String(va).localeCompare(String(vb)) * dir
  })
})

function toggleAuditSort(field) {
  if (auditSortField.value === field) {
    auditSortDir.value = auditSortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    auditSortField.value = field
    auditSortDir.value   = 'desc'
  }
}

async function fetchAuditLog(page) {
  if (page !== undefined) auditPage.value = page
  auditLoading.value = true
  try {
    const offset = (auditPage.value - 1) * auditPageSize.value
    const data = await get(
      `/api/audit?limit=${auditPageSize.value}&offset=${offset}&sort=${auditSortField.value}&dir=${auditSortDir.value}`
    )
    if (Array.isArray(data)) {
      auditLog.value   = data
      auditTotal.value = data.length < auditPageSize.value
        ? (auditPage.value - 1) * auditPageSize.value + data.length
        : auditTotal.value || data.length
    }
  } catch { /* silent */ }
  finally { auditLoading.value = false }
}

async function exportAuditCsv() {
  try {
    const res = await post('/api/audit/export', {
      sort: auditSortField.value,
      dir:  auditSortDir.value,
    })
    // If the endpoint returns a download URL or blob-like text
    const blob = new Blob([typeof res === 'string' ? res : JSON.stringify(res)], { type: 'text/csv' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url; a.download = 'noba-audit.csv'; a.click()
    URL.revokeObjectURL(url)
  } catch {
    // Fallback: build CSV from current page
    const header = 'timestamp,username,action,details,ip'
    const lines  = auditLog.value.map(r => {
      const ts      = new Date((r.time || r.timestamp || 0) * 1000).toISOString()
      const details = (r.detail || r.details || '').replace(/"/g, '""')
      return `${ts},"${r.username || r.user || ''}","${r.action || ''}","${details}","${r.ip || ''}"`
    })
    const csv = [header, ...lines].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url; a.download = 'noba-audit.csv'; a.click()
    URL.revokeObjectURL(url)
  }
}

// ── Journal tab ───────────────────────────────────────────────────────────────
const journalUnit     = ref('')
const journalPriority = ref('')
const journalLines    = ref(100)
const journalGrep     = ref('')
const journalOutput   = ref('')
const journalLoading  = ref(false)
const journalUnits    = ref([])

async function fetchJournalUnits() {
  try {
    const data = await get('/api/journal/units')
    journalUnits.value = Array.isArray(data) ? data : []
  } catch { /* silent */ }
}

async function fetchJournal() {
  journalLoading.value = true
  try {
    const params = new URLSearchParams({ lines: String(journalLines.value) })
    if (journalUnit.value)     params.set('unit',     journalUnit.value)
    if (journalPriority.value) params.set('priority', journalPriority.value)
    if (journalGrep.value)     params.set('grep',     journalGrep.value)
    const text = await get(`/api/journal?${params}`)
    journalOutput.value = typeof text === 'string' ? text : JSON.stringify(text, null, 2)
  } catch (e) {
    journalOutput.value = 'Error: ' + e.message
  } finally {
    journalLoading.value = false
  }
}

// ── Live Stream tab ───────────────────────────────────────────────────────────
const streamHost     = ref('')
const streamUnit     = ref('')
const streamPriority = ref('')
const streamBacklog  = ref(50)
const streamId       = ref('')
const streamActive   = ref(false)
const streamLoading  = ref(false)
const streamLines    = ref([])
const streamCursor   = ref(0)
const streamAutoScroll = ref(true)

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
  try {
    const data = await post(`/api/agents/${encodeURIComponent(streamHost.value)}/stream-logs`, {
      unit:     streamUnit.value || '',
      priority: streamPriority.value || '',
      lines:    parseInt(String(streamBacklog.value), 10) || 50,
    })
    if (data?.stream_id) {
      streamId.value     = data.stream_id
      streamActive.value = true
      _startStreamPoll()
    }
  } catch (e) {
    console.error('stream start error', e)
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
  if (!streamHost.value || !streamId.value) return
  try {
    const data = await get(
      `/api/agents/${encodeURIComponent(streamHost.value)}/stream/${streamId.value}?after=${streamCursor.value}`
    )
    if (data?.lines?.length > 0) {
      streamLines.value  = streamLines.value.concat(data.lines).slice(-2000)
      streamCursor.value = data.cursor || 0
      if (streamAutoScroll.value) {
        nextTick(() => {
          const el = document.getElementById('logs-stream-output')
          if (el) el.scrollTop = el.scrollHeight
        })
      }
    }
    if (!data?.active) {
      streamActive.value = false
      _stopStreamPoll()
    }
  } catch { /* silent */ }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  fetchLog()
})

import { onUnmounted } from 'vue'
onUnmounted(() => {
  _stopStreamPoll()
  if (_logTimer) { clearInterval(_logTimer); _logTimer = null }
  if (streamActive.value) stopStream()
})
</script>

<template>
  <div>
    <!-- Page header -->
    <h2 style="margin-bottom:1rem">
      <i class="fas fa-scroll" style="margin-right:.5rem"></i>Logs
    </h2>

    <!-- Tab bar -->
    <div class="tab-bar" style="margin-bottom:1rem;display:flex;flex-wrap:wrap;gap:.3rem">
      <button
        class="btn btn-xs"
        :class="{ 'btn-primary': activeTab === 'syslog' }"
        @click="setTab('syslog')"
      >System Log</button>
      <button
        class="btn btn-xs"
        :class="{ 'btn-primary': activeTab === 'history' }"
        @click="setTab('history')"
      >Command History</button>
      <button
        class="btn btn-xs"
        :class="{ 'btn-primary': activeTab === 'audit' }"
        @click="setTab('audit')"
      >Audit Log</button>
      <button
        class="btn btn-xs"
        :class="{ 'btn-primary': activeTab === 'journal' }"
        @click="setTab('journal')"
      >Journal</button>
      <button
        v-if="agents.length > 0 && authStore.isAdmin"
        class="btn btn-xs"
        :class="{ 'btn-primary': activeTab === 'stream' }"
        @click="setTab('stream')"
      >
        <i class="fas fa-satellite-dish" style="margin-right:.3rem"></i>Live Stream
      </button>
    </div>

    <!-- ── System Log tab ───────────────────────────────────────────────── -->
    <div v-show="activeTab === 'syslog'">
      <div style="display:flex;gap:.4rem;flex-wrap:wrap;align-items:center;margin-bottom:.5rem">
        <select
          v-model="selectedLog"
          style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);padding:3px 8px;border-radius:4px;font-size:.8rem"
          @change="fetchLog"
        >
          <option v-for="t in LOG_TYPES" :key="t" :value="t">{{ t }}</option>
        </select>
        <button class="btn btn-xs" :disabled="logLoading" @click="fetchLog">
          <i class="fas" :class="logLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i> Refresh
        </button>
        <button
          class="btn btn-xs"
          :class="{ 'btn-primary': logAutoRefresh }"
          @click="toggleLogAutoRefresh"
        >
          <i class="fas fa-clock"></i> Auto-refresh
        </button>
        <span v-if="logAutoRefresh" style="font-size:.7rem;color:var(--text-muted)">every 5s</span>
      </div>
      <pre
        id="syslog-pre"
        class="log-pre"
        style="max-height:55vh;overflow:auto;margin:0;padding:12px;font-size:.75rem;white-space:pre-wrap;word-break:break-all"
      >{{ logContent || 'No content.' }}</pre>
    </div>

    <!-- ── Command History tab ──────────────────────────────────────────── -->
    <div v-show="activeTab === 'history'">
      <div v-if="cmdHistory.length > 0" class="cmd-history-table-wrap">
        <table class="cmd-history-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Host</th>
              <th>Command</th>
              <th>User</th>
              <th>Status</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="h in cmdHistory" :key="h.id">
              <td style="white-space:nowrap">{{ new Date((h.queued_at||0)*1000).toLocaleString() }}</td>
              <td>{{ h.hostname }}</td>
              <td><span class="badge ba" style="font-size:.55rem">{{ h.cmd_type }}</span></td>
              <td>{{ h.queued_by }}</td>
              <td>
                <span class="badge" :class="historyStatusClass(h.status)" style="font-size:.55rem">
                  {{ h.status }}
                </span>
              </td>
              <td>{{ h.finished_at ? (h.finished_at - h.queued_at) + 's' : '--' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else-if="!cmdHistoryLoading" class="empty-msg">No command history yet.</div>
      <button
        class="btn btn-xs"
        style="margin-top:.5rem"
        :disabled="cmdHistoryLoading"
        @click="fetchCommandHistory"
      >
        <i class="fas" :class="cmdHistoryLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i> Refresh
      </button>
    </div>

    <!-- ── Audit Log tab ────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'audit'">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem;flex-wrap:wrap;gap:.4rem">
        <span style="font-size:.75rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.08em">
          <i class="fas fa-clipboard-list" style="margin-right:.3rem"></i>Audit Log
        </span>
        <div style="display:flex;gap:.3rem">
          <button class="btn btn-xs" :disabled="auditLoading" @click="fetchAuditLog()">
            <i class="fas" :class="auditLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i> Refresh
          </button>
          <button class="btn btn-xs" @click="exportAuditCsv">
            <i class="fas fa-download"></i> CSV
          </button>
        </div>
      </div>

      <div style="max-height:55vh;overflow-y:auto">
        <table style="width:100%;font-size:.8rem;border-collapse:collapse">
          <thead>
            <tr style="border-bottom:1px solid var(--border)">
              <th
                style="padding:.4rem;text-align:left;cursor:pointer;user-select:none;white-space:nowrap"
                @click="toggleAuditSort('time')"
              >
                Time
                <i v-if="auditSortField==='time'" class="fas" :class="auditSortDir==='asc'?'fa-sort-up':'fa-sort-down'" style="font-size:.6rem"></i>
              </th>
              <th
                style="padding:.4rem;text-align:left;cursor:pointer;user-select:none"
                @click="toggleAuditSort('action')"
              >
                Action
                <i v-if="auditSortField==='action'" class="fas" :class="auditSortDir==='asc'?'fa-sort-up':'fa-sort-down'" style="font-size:.6rem"></i>
              </th>
              <th
                style="padding:.4rem;text-align:left;cursor:pointer;user-select:none"
                @click="toggleAuditSort('username')"
              >
                User
                <i v-if="auditSortField==='username'" class="fas" :class="auditSortDir==='asc'?'fa-sort-up':'fa-sort-down'" style="font-size:.6rem"></i>
              </th>
              <th style="padding:.4rem;text-align:left">Detail</th>
              <th
                style="padding:.4rem;text-align:left;cursor:pointer;user-select:none"
                @click="toggleAuditSort('ip')"
              >
                IP
                <i v-if="auditSortField==='ip'" class="fas" :class="auditSortDir==='asc'?'fa-sort-up':'fa-sort-down'" style="font-size:.6rem"></i>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="e in auditSorted"
              :key="e.id || e.timestamp || e.time"
              style="border-bottom:1px solid var(--border)"
            >
              <td style="padding:.4rem;white-space:nowrap">
                {{ new Date((e.time || e.timestamp || 0) * 1000).toLocaleString() }}
              </td>
              <td style="padding:.4rem">
                <span class="badge ba" style="font-size:.55rem">{{ e.action }}</span>
              </td>
              <td style="padding:.4rem">{{ e.username || e.user }}</td>
              <td style="padding:.4rem;font-size:.7rem;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                {{ e.detail || e.details }}
              </td>
              <td style="padding:.4rem;font-size:.7rem;color:var(--text-muted)">{{ e.ip }}</td>
            </tr>
            <tr v-if="auditSorted.length === 0 && !auditLoading">
              <td colspan="5" style="text-align:center;padding:2rem;color:var(--text-muted)">No audit log entries.</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div style="display:flex;gap:.3rem;align-items:center;margin-top:.5rem;font-size:.75rem">
        <button class="btn btn-xs" :disabled="auditPage <= 1" @click="fetchAuditLog(auditPage - 1)">
          <i class="fas fa-chevron-left"></i>
        </button>
        <span>Page {{ auditPage }}</span>
        <button class="btn btn-xs" :disabled="auditLog.length < auditPageSize" @click="fetchAuditLog(auditPage + 1)">
          <i class="fas fa-chevron-right"></i>
        </button>
      </div>
    </div>

    <!-- ── Journal tab ──────────────────────────────────────────────────── -->
    <div v-show="activeTab === 'journal'">
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:1rem;font-size:.8rem;align-items:flex-end">
        <select
          v-model="journalUnit"
          style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);padding:3px 6px;border-radius:4px"
        >
          <option value="">All units</option>
          <option v-for="u in journalUnits" :key="u.name || u" :value="u.name || u">
            {{ u.name || u }}
          </option>
        </select>
        <select
          v-model="journalPriority"
          style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);padding:3px 6px;border-radius:4px"
        >
          <option value="">All priorities</option>
          <option value="0">Emergency</option>
          <option value="1">Alert</option>
          <option value="2">Critical</option>
          <option value="3">Error</option>
          <option value="4">Warning</option>
          <option value="5">Notice</option>
          <option value="6">Info</option>
          <option value="7">Debug</option>
        </select>
        <input
          v-model="journalGrep"
          type="text"
          placeholder="grep..."
          style="width:120px;padding:3px 6px;background:var(--surface-2);border:1px solid var(--border);color:var(--text);border-radius:4px"
        >
        <select
          v-model.number="journalLines"
          style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);padding:3px 6px;border-radius:4px"
        >
          <option :value="50">50 lines</option>
          <option :value="100">100</option>
          <option :value="200">200</option>
          <option :value="500">500</option>
        </select>
        <button class="btn btn-xs" :disabled="journalLoading" @click="fetchJournal">
          <i class="fas" :class="journalLoading ? 'fa-spinner fa-spin' : 'fa-search'"></i> Query
        </button>
      </div>
      <pre
        class="log-pre"
        style="max-height:50vh;overflow:auto;margin:0;padding:12px;font-size:.75rem;white-space:pre-wrap;word-break:break-all"
      >{{ journalOutput || 'No output. Press Query to fetch journal entries.' }}</pre>
    </div>

    <!-- ── Live Stream tab ──────────────────────────────────────────────── -->
    <div v-show="activeTab === 'stream'">
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
          <button
            v-else
            class="btn btn-sm"
            style="border-color:var(--danger);color:var(--danger)"
            @click="stopStream"
          >
            <i class="fas fa-stop"></i> Stop
          </button>
        </div>
      </div>

      <!-- Status bar -->
      <div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.4rem;font-size:.7rem;color:var(--text-muted)">
        <span>
          <i
            class="fas fa-circle"
            :style="`color:${streamActive ? 'var(--success)' : 'var(--text-muted)'};font-size:.45rem`"
          ></i>
          {{ streamActive ? `Streaming from ${streamHost}` : 'Idle' }}
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
      <div
        id="logs-stream-output"
        style="background:var(--bg);border:1px solid var(--border);border-radius:4px;font-family:var(--font-data);font-size:.72rem;max-height:45vh;min-height:120px;overflow-y:auto;padding:.4rem .6rem;white-space:pre-wrap;word-break:break-all;line-height:1.5"
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
