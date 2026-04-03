<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import AppModal from '../ui/AppModal.vue'
import ChartWrapper from '../ui/ChartWrapper.vue'
import RemoteTerminal from './RemoteTerminal.vue'
import { useApi } from '../../composables/useApi'

const props = defineProps({
  show: Boolean,
  hostname: { type: String, default: '' },
  agent: { type: Object, default: null },
})
const emit = defineEmits(['close'])

const { get } = useApi()

// ── Tabs ──────────────────────────────────────────────────────────────────────
const activeTab = ref('overview')

// ── History chart ─────────────────────────────────────────────────────────────
const historyMetric  = ref('cpu')
const historyData    = ref([])
const historyLoading = ref(false)

const CHART_COLORS = { cpu: '#00c8ff', mem: '#00e676', disk: '#ffb300' }

const historyChartConfig = computed(() => {
  if (!historyData.value.length) return null
  const labels = historyData.value.map(d => new Date(d.time * 1000).toLocaleTimeString())
  const values = historyData.value.map(d => d.value)
  const color  = CHART_COLORS[historyMetric.value] || '#00c8ff'
  return {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: `${props.hostname} ${historyMetric.value}%`,
        data: values,
        borderColor: color,
        borderWidth: 1.5,
        pointRadius: 0,
        fill: true,
        backgroundColor: color + '18',
      }],
    },
    options: {
      responsive: true,
      animation: { duration: 0 },
      scales: {
        y: { min: 0, max: 100, ticks: { color: '#c8dff0' }, grid: { color: 'rgba(200,223,240,.08)' } },
        x: { ticks: { color: '#c8dff0', maxTicksLimit: 8 }, grid: { display: false } },
      },
      plugins: { legend: { labels: { color: '#c8dff0' } } },
    },
  }
})

async function fetchHistory(metric) {
  if (!props.hostname) return
  historyMetric.value = metric
  historyLoading.value = true
  historyData.value = []
  try {
    const data = await get(`/api/agents/${encodeURIComponent(props.hostname)}/history?metric=${metric}&hours=24`)
    historyData.value = Array.isArray(data) ? data : []
  } catch { /* silent */ }
  finally { historyLoading.value = false }
}

// ── Healing outcomes ─────────────────────────────────────────────────────────
const healOutcomes = ref([])
const healLoading  = ref(false)

async function fetchHealOutcomes() {
  if (!props.hostname) return
  healLoading.value = true
  try {
    const data = await get(`/api/healing/ledger?target=${encodeURIComponent(props.hostname)}&limit=20`)
    healOutcomes.value = Array.isArray(data) ? data : []
  } catch { /* silent */ }
  finally { healLoading.value = false }
}

// ── Command results ───────────────────────────────────────────────────────────
const agentDetail   = ref(null)
const detailLoading = ref(false)

async function fetchDetail() {
  if (!props.hostname) return
  detailLoading.value = true
  agentDetail.value = null
  try {
    agentDetail.value = await get(`/api/agents/${encodeURIComponent(props.hostname)}`)
  } catch { /* silent */ }
  finally { detailLoading.value = false }
}

const cmdResults = computed(() => {
  const results = agentDetail.value?.cmd_results || []
  return [...results].reverse().slice(0, 20)
})

const topProcs = computed(() => agentDetail.value?.top_processes || [])

function formatResult(r) {
  if (r.stdout)  return r.stdout.trim()
  if (r.pong)    return `pong v${r.version || '?'}`
  if (r.message) return r.message
  if (r.error)   return `Error: ${r.error}`
  return JSON.stringify(r, null, 2)
}

// ── Disk usage ────────────────────────────────────────────────────────────────
const disks = computed(() => props.agent?.disks || agentDetail.value?.disks || [])

// ── OS icon ───────────────────────────────────────────────────────────────────
function osIcon(platform) {
  if (!platform) return 'fas fa-server'
  const p = platform.toLowerCase()
  if (p.includes('linux'))   return 'fab fa-linux'
  if (p.includes('windows')) return 'fab fa-windows'
  if (p.includes('darwin') || p.includes('macos')) return 'fab fa-apple'
  if (p.includes('freebsd')) return 'fas fa-server'
  return 'fas fa-server'
}

// ── Watch ─────────────────────────────────────────────────────────────────────
watch(() => props.show, (val) => {
  if (val) {
    activeTab.value = 'overview'
    fetchDetail()
    fetchHistory('cpu')
  }
})

watch(activeTab, (tab) => {
  if (tab === 'history') {
    nextTick(() => fetchHistory(historyMetric.value))
  }
  if (tab === 'healing') fetchHealOutcomes()
})
</script>

<template>
  <AppModal :show="show" :title="hostname" width="860px" @close="emit('close')">
    <div v-if="!agent && detailLoading" style="text-align:center;padding:2rem;color:var(--text-muted)">
      <i class="fas fa-spinner fa-spin"></i> Loading...
    </div>

    <div v-else>
      <!-- Header strip -->
      <div style="display:flex;align-items:center;gap:.8rem;padding:.6rem 0;border-bottom:1px solid var(--border);margin-bottom:.8rem">
        <i :class="osIcon(agent?.platform)" style="font-size:1.5rem;color:var(--accent)"></i>
        <div style="flex:1;min-width:0">
          <div style="font-weight:700;font-size:.95rem">{{ agent?.hostname || hostname }}</div>
          <div style="font-size:.7rem;color:var(--text-muted)">
            {{ agent?.platform }} &middot; {{ agent?.arch }} &middot; v{{ agent?.agent_version || '?' }}
          </div>
        </div>
        <button
          class="btn btn-xs"
          title="Refresh current tab"
          :disabled="detailLoading || historyLoading || healLoading"
          @click="activeTab === 'overview' ? fetchDetail() : activeTab === 'history' ? fetchHistory(historyMetric) : activeTab === 'healing' ? fetchHealOutcomes() : fetchDetail()"
        >
          <i class="fas fa-sync-alt" :class="{ 'fa-spin': detailLoading || historyLoading || healLoading }"></i>
        </button>
        <span
          class="badge"
          :class="agent?.online ? 'bs' : 'bd'"
          style="font-size:.6rem"
        >{{ agent?.online ? 'online' : 'offline' }}</span>
      </div>

      <!-- Tabs -->
      <div style="display:flex;gap:.3rem;margin-bottom:.8rem">
        <button
          v-for="tab in ['overview', 'processes', 'results', 'history', 'healing', 'terminal']"
          :key="tab"
          class="btn btn-xs"
          :class="activeTab === tab ? 'btn-primary' : ''"
          style="text-transform:capitalize"
          @click="activeTab = tab"
        >{{ tab }}</button>
      </div>

      <!-- Overview tab -->
      <div v-if="activeTab === 'overview'">
        <!-- Meters -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:.6rem;margin-bottom:.8rem">
          <!-- CPU -->
          <div style="padding:.6rem;border:1px solid var(--border);border-radius:6px;background:var(--surface-2)" :title="`Current CPU usage: ${agent?.cpu_percent || 0}%`">
            <div style="font-size:.65rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:.3rem">CPU</div>
            <div style="font-size:1.4rem;font-weight:700" :style="`color:${(agent?.cpu_percent||0)>90?'var(--danger)':(agent?.cpu_percent||0)>70?'var(--warning)':'var(--accent)'}`">
              {{ agent?.cpu_percent || 0 }}%
            </div>
            <div class="prog-track" style="height:4px;margin-top:.3rem">
              <div class="prog-fill" :class="(agent?.cpu_percent||0)>90?'f-danger':(agent?.cpu_percent||0)>70?'f-warning':'f-accent'" :style="`width:${agent?.cpu_percent||0}%`"></div>
            </div>
          </div>
          <!-- Memory -->
          <div style="padding:.6rem;border:1px solid var(--border);border-radius:6px;background:var(--surface-2)" :title="`Current memory usage: ${agent?.mem_percent || 0}% (${Math.round((agent?.mem_total_mb||0)/1024*10)/10} GB total)`">
            <div style="font-size:.65rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:.3rem">Memory</div>
            <div style="font-size:1.4rem;font-weight:700" :style="`color:${(agent?.mem_percent||0)>90?'var(--danger)':(agent?.mem_percent||0)>70?'var(--warning)':'var(--success)'}`">
              {{ agent?.mem_percent || 0 }}%
            </div>
            <div class="prog-track" style="height:4px;margin-top:.3rem">
              <div class="prog-fill" :class="(agent?.mem_percent||0)>90?'f-danger':(agent?.mem_percent||0)>70?'f-warning':'f-success'" :style="`width:${agent?.mem_percent||0}%`"></div>
            </div>
          </div>
        </div>

        <!-- Disks -->
        <div v-if="disks.length > 0" style="margin-bottom:.8rem">
          <div style="font-size:.65rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:.3rem">
            <i class="fas fa-hdd" style="margin-right:.3rem"></i>Disks
          </div>
          <div v-for="disk in disks" :key="disk.mount" style="margin-bottom:.3rem">
            <div style="display:flex;justify-content:space-between;font-size:.75rem;margin-bottom:.15rem">
              <span>{{ disk.mount }}</span>
              <span :style="`color:${disk.percent>90?'var(--danger)':disk.percent>70?'var(--warning)':'var(--text-muted)'}`">{{ disk.percent }}%</span>
            </div>
            <div class="prog-track" style="height:3px">
              <div class="prog-fill" :class="disk.percent>90?'f-danger':disk.percent>70?'f-warning':'f-accent'" :style="`width:${disk.percent}%`"></div>
            </div>
          </div>
        </div>

        <!-- Meta info -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:.3rem;font-size:.75rem">
          <div v-if="agent?.uptime_s" class="row">
            <span class="row-label">Uptime</span>
            <span class="row-val">{{ Math.floor((agent.uptime_s||0)/3600) }}h {{ Math.floor(((agent.uptime_s||0)%3600)/60) }}m</span>
          </div>
          <div v-if="agent?.last_seen_s !== undefined" class="row">
            <span class="row-label">Last seen</span>
            <span class="row-val">{{ agent.last_seen_s }}s ago</span>
          </div>
          <div v-if="agent?.load_avg" class="row">
            <span class="row-label">Load avg</span>
            <span class="row-val">{{ Array.isArray(agent.load_avg) ? agent.load_avg.map(v=>v.toFixed(2)).join(' / ') : agent.load_avg }}</span>
          </div>
          <div v-if="agent?.mem_total_mb" class="row">
            <span class="row-label">Total RAM</span>
            <span class="row-val">{{ Math.round((agent.mem_total_mb||0)/1024*10)/10 }} GB</span>
          </div>
        </div>
      </div>

      <!-- Processes tab -->
      <div v-if="activeTab === 'processes'">
        <div v-if="detailLoading" class="empty-msg"><i class="fas fa-spinner fa-spin"></i> Loading...</div>
        <div v-else-if="topProcs.length === 0" class="empty-msg">No process data. Run "Top Processes" command.</div>
        <div v-else style="overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;font-size:.75rem">
            <thead>
              <tr style="color:var(--text-muted);text-align:left;border-bottom:1px solid var(--border)">
                <th style="padding:.3rem .5rem">PID</th>
                <th style="padding:.3rem .5rem">Name</th>
                <th style="padding:.3rem .5rem">CPU%</th>
                <th style="padding:.3rem .5rem">MEM%</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in topProcs" :key="p.pid" style="border-bottom:1px solid var(--border)">
                <td style="padding:.25rem .5rem;color:var(--text-muted)">{{ p.pid }}</td>
                <td style="padding:.25rem .5rem;font-weight:500">{{ p.name }}</td>
                <td style="padding:.25rem .5rem" :style="`color:${(p.cpu||0)>50?'var(--warning)':'inherit'}`">{{ (p.cpu||0).toFixed(1) }}%</td>
                <td style="padding:.25rem .5rem" :style="`color:${(p.mem||0)>30?'var(--warning)':'inherit'}`">{{ (p.mem||0).toFixed(1) }}%</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Results tab -->
      <div v-if="activeTab === 'results'">
        <div v-if="detailLoading" class="empty-msg"><i class="fas fa-spinner fa-spin"></i> Loading...</div>
        <div v-else-if="cmdResults.length === 0" class="empty-msg">No command results yet.</div>
        <div v-else style="display:flex;flex-direction:column;gap:.4rem;max-height:360px;overflow-y:auto">
          <div
            v-for="r in cmdResults"
            :key="r.id || r.queued_at"
            style="border:1px solid var(--border);border-radius:4px;padding:.4rem .6rem;background:var(--surface-2)"
          >
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.2rem">
              <span class="badge ba" style="font-size:.55rem">{{ r.type }}</span>
              <span style="font-size:.65rem;color:var(--text-muted)">{{ r.finished_at ? new Date(r.finished_at * 1000).toLocaleString() : '--' }}</span>
            </div>
            <pre style="margin:0;font-size:.65rem;white-space:pre-wrap;word-break:break-all;max-height:100px;overflow-y:auto;color:var(--text)">{{ formatResult(r) }}</pre>
          </div>
        </div>
      </div>

      <!-- History tab -->
      <div v-if="activeTab === 'history'">
        <div style="display:flex;gap:.3rem;margin-bottom:.6rem">
          <button
            v-for="m in ['cpu', 'mem', 'disk']"
            :key="m"
            class="btn btn-xs"
            :class="historyMetric === m ? 'btn-primary' : ''"
            :style="historyMetric === m ? '' : `color:${CHART_COLORS[m]};border-color:${CHART_COLORS[m]}30`"
            @click="fetchHistory(m)"
          >{{ m.toUpperCase() }}</button>
          <span v-if="historyLoading" style="font-size:.75rem;color:var(--text-muted);align-self:center;margin-left:.3rem">
            <i class="fas fa-spinner fa-spin"></i>
          </span>
        </div>
        <div v-if="historyChartConfig" style="height:280px;position:relative">
          <ChartWrapper :config="historyChartConfig" />
        </div>
        <div v-else-if="!historyLoading" class="empty-msg">No history data for last 24h.</div>
      </div>

      <!-- healing tab -->
      <div v-if="activeTab === 'healing'">
        <div v-if="healLoading" class="empty-msg"><i class="fas fa-spinner fa-spin"></i> Loading...</div>
        <div v-else-if="healOutcomes.length === 0" class="empty-msg">No healing activity for this agent.</div>
        <div v-else style="display:flex;flex-direction:column;gap:.4rem;max-height:360px;overflow-y:auto">
          <div
            v-for="o in healOutcomes"
            :key="o.id"
            style="border:1px solid var(--border);border-radius:4px;padding:.5rem .6rem;background:var(--surface-2)"
          >
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.3rem">
              <div style="display:flex;gap:.3rem;align-items:center">
                <span class="badge ba" style="font-size:.55rem">{{ o.action_type }}</span>
                <span class="badge" :class="o.verified === 1 ? 'bs' : o.action_success === 0 ? 'bd' : 'bw'" style="font-size:.55rem">
                  {{ o.verified === 1 ? 'verified' : o.action_success === 1 ? 'unverified' : o.action_success === 0 ? 'failed' : 'notify' }}
                </span>
                <span v-if="o.trust_level" style="font-size:.6rem;color:var(--text-muted)">{{ o.trust_level }}</span>
              </div>
              <span style="font-size:.6rem;color:var(--text-muted)">{{ o.created_at ? new Date(o.created_at * 1000).toLocaleString() : '--' }}</span>
            </div>
            <div style="font-size:.7rem;color:var(--text-muted)">
              <span style="margin-right:.5rem"><b>Rule:</b> {{ o.rule_id || '--' }}</span>
              <span style="margin-right:.5rem"><b>Step:</b> {{ o.escalation_step||0 }}</span>
              <span><b>Duration:</b> {{ (o.duration_s||0).toFixed(1) }}s</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Terminal tab -->
      <div v-if="activeTab === 'terminal'">
        <RemoteTerminal :hostname="hostname" :visible="activeTab === 'terminal'" />
      </div>
    </div>

    <template #footer>
      <button class="btn btn-xs" @click="emit('close')">Close</button>
    </template>
  </AppModal>
</template>
