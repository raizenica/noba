<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, onMounted } from 'vue'
import { useApi }       from '../composables/useApi'
import { useAuthStore } from '../stores/auth'
import { useNotificationsStore } from '../stores/notifications'
import ChartWrapper from '../components/ui/ChartWrapper.vue'

const { get, post } = useApi()
const authStore  = useAuthStore()
const notif      = useNotificationsStore()

// ── Score & agents ────────────────────────────────────────────────────────────
const securityScore      = ref(null)
const securityAgentCount = ref(0)
const securityAgents     = ref([])
const securityScanning   = ref(false)
const scanningHosts      = ref(new Set())

// ── Findings ──────────────────────────────────────────────────────────────────
const securityFindings       = ref([])
const securityFilterSeverity = ref('')
const securityFilterHost     = ref('')

// ── History chart ─────────────────────────────────────────────────────────────
const securityHistory = ref([])

// ── Drill-down ────────────────────────────────────────────────────────────────
const selectedAgent      = ref(null)
const drillDownFindings  = computed(() => {
  if (!selectedAgent.value) return []
  return securityFindings.value.filter(f => f.hostname === selectedAgent.value)
})

function selectAgent(hostname) {
  selectedAgent.value = selectedAgent.value === hostname ? null : hostname
}

// ── Computed score gauge helpers ──────────────────────────────────────────────
const RADIUS   = 52
const CIRCUMF  = 2 * Math.PI * RADIUS

function scoreColor(score) {
  const s = score || 0
  if (s >= 80) return 'var(--success)'
  if (s >= 60) return 'var(--warning)'
  return 'var(--danger)'
}

function scoreDashOffset(score) {
  return CIRCUMF * (1 - ((score || 0) / 100))
}

function scoreGrade(score) {
  const s = score || 0
  if (s >= 90) return 'A'
  if (s >= 80) return 'B'
  if (s >= 70) return 'C'
  if (s >= 50) return 'D'
  return 'F'
}

function agentScoreClass(score) {
  if (score >= 80) return 'bs'
  if (score >= 60) return 'bw'
  return 'bd'
}

function severityClass(severity) {
  if (severity === 'high')   return 'bd'
  if (severity === 'medium') return 'bw'
  return 'bn'
}

// ── History chart config ──────────────────────────────────────────────────────
const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899']

const historyChartConfig = computed(() => {
  if (!securityHistory.value.length) return null

  const byHost = {}
  securityHistory.value.forEach(h => {
    if (!byHost[h.hostname]) byHost[h.hostname] = []
    byHost[h.hostname].push(h)
  })

  const datasets = Object.entries(byHost).map(([host, points], ci) => ({
    label: host,
    data: points
      .sort((a, b) => a.scanned_at - b.scanned_at)
      .map(p => ({ x: new Date(p.scanned_at * 1000), y: p.score })),
    borderColor: COLORS[ci % COLORS.length],
    backgroundColor: 'transparent',
    tension: 0.3,
    pointRadius: 3,
  }))

  return {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          type: 'category',
          time: { tooltipFormat: 'MMM d, HH:mm' },
          grid: { color: 'rgba(255,255,255,0.05)' },
        },
        y: {
          min: 0,
          max: 100,
          grid: { color: 'rgba(255,255,255,0.05)' },
        },
      },
      plugins: {
        legend: { labels: { color: 'rgba(255,255,255,0.7)', font: { size: 10 } } },
      },
    },
  }
})

// ── Data fetching ─────────────────────────────────────────────────────────────
async function fetchSecurityData() {
  try {
    const scoreData = await get('/api/security/score')
    if (scoreData && typeof scoreData === 'object') {
      securityScore.value      = scoreData.score ?? null
      securityAgentCount.value = scoreData.agent_count || 0
      securityAgents.value     = scoreData.agents || []
      scanningHosts.value.clear()
    }
  } catch (e) { notif.addToast('Failed to load security scores: ' + e.message, 'danger') }

  try {
    const params = new URLSearchParams()
    if (securityFilterSeverity.value) params.set('severity', securityFilterSeverity.value)
    if (securityFilterHost.value)     params.set('hostname', securityFilterHost.value)
    const findings = await get(`/api/security/findings?${params}`)
    securityFindings.value = Array.isArray(findings) ? findings : []
  } catch (e) { notif.addToast('Failed to load findings: ' + e.message, 'danger') }

  try {
    const hist = await get('/api/security/history?limit=50')
    securityHistory.value = Array.isArray(hist) ? hist : []
  } catch (e) { notif.addToast('Failed to load scan history: ' + e.message, 'danger') }
}

async function securityScanAll() {
  securityScanning.value = true
  try {
    await post('/api/security/scan-all', {})
    notif.addToast('Security scan started for all agents', 'info')
    setTimeout(fetchSecurityData, 3000)
  } catch (e) {
    notif.addToast('Scan request failed: ' + e.message, 'error')
  } finally {
    securityScanning.value = false
  }
}

async function securityScanHost(hostname) {
  scanningHosts.value.add(hostname)
  try {
    await post(`/api/security/scan/${encodeURIComponent(hostname)}`, {})
    notif.addToast(`Scan started for ${hostname}`, 'info')
    setTimeout(fetchSecurityData, 3000)
  } catch (e) {
    notif.addToast(`Scan failed for ${hostname}: ` + e.message, 'error')
    scanningHosts.value.delete(hostname)
  }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(fetchSecurityData)
</script>

<template>
  <div>
    <!-- Page header -->
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.5rem;margin-bottom:1rem">
      <h2 style="margin:0">
        <i class="fas fa-shield-alt" style="margin-right:.5rem;color:var(--accent)"></i>
        Security Posture
      </h2>
      <div style="display:flex;gap:.5rem">
        <button
          v-if="authStore.isOperator"
          class="btn btn-sm btn-primary"
          :disabled="securityScanning"
          @click="securityScanAll"
        >
          <i class="fas" :class="securityScanning ? 'fa-spinner fa-spin' : 'fa-search'"></i>
          Scan All Agents
        </button>
        <button class="btn btn-xs" @click="fetchSecurityData">
          <i class="fas fa-sync-alt"></i>
        </button>
      </div>
    </div>

    <!-- ── Overall Score Gauge ──────────────────────────────────────────── -->
    <div class="card" style="margin-bottom:1rem;text-align:center;padding:1.5rem">
      <div style="font-size:.75rem;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted);margin-bottom:.5rem">
        Aggregate Security Score
      </div>
      <div style="position:relative;display:inline-block;width:120px;height:120px">
        <svg viewBox="0 0 120 120" style="transform:rotate(-90deg)">
          <circle cx="60" cy="60" r="52" fill="none" stroke="var(--surface-2)" stroke-width="10"/>
          <circle
            cx="60" cy="60" r="52"
            fill="none"
            :stroke="scoreColor(securityScore)"
            stroke-width="10"
            stroke-linecap="round"
            :stroke-dasharray="CIRCUMF"
            :stroke-dashoffset="scoreDashOffset(securityScore)"
          />
        </svg>
        <div
          style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:2rem;font-weight:700;font-family:var(--font-data)"
          :style="`color:${scoreColor(securityScore)}`"
        >
          {{ securityScore !== null ? securityScore : '--' }}
        </div>
      </div>
      <div style="margin-top:.4rem">
        <span
          class="badge"
          :class="securityScore !== null ? agentScoreClass(securityScore) : 'bw'"
          style="font-size:.8rem;padding:.2rem .6rem"
        >Grade {{ securityScore !== null ? scoreGrade(securityScore) : '?' }}</span>
      </div>
      <div style="font-size:.7rem;color:var(--text-muted);margin-top:.3rem">
        {{ securityAgentCount }} agent(s) scanned
      </div>
    </div>

    <!-- ── Per-Agent Score Cards ─────────────────────────────────────────── -->
    <div
      v-if="securityAgents.length > 0"
      style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.75rem;margin-bottom:1rem"
    >
      <div
        v-for="agent in securityAgents"
        :key="agent.hostname"
        class="card"
        style="padding:1rem;cursor:pointer;transition:border-color .15s"
        :style="selectedAgent === agent.hostname ? 'border-color:var(--accent)' : ''"
        @click="selectAgent(agent.hostname)"
      >
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem">
          <span style="font-weight:600;font-size:.85rem">{{ agent.hostname }}</span>
          <span class="badge" :class="agentScoreClass(agent.score)">{{ agent.score }}</span>
        </div>
        <div style="font-size:.65rem;color:var(--text-muted)">
          {{ agent.scanned_at ? new Date(agent.scanned_at * 1000).toLocaleString() : 'Never scanned' }}
        </div>
        <div v-if="authStore.isOperator" style="margin-top:.5rem;display:flex;gap:.5rem" @click.stop>
          <button
            class="btn btn-xs"
            :disabled="scanningHosts.has(agent.hostname)"
            @click="securityScanHost(agent.hostname)"
          >
            <i class="fas" :class="scanningHosts.has(agent.hostname) ? 'fa-spinner fa-spin' : 'fa-search'"></i>
          </button>

        </div>
      </div>
    </div>

    <!-- ── Score drill-down ──────────────────────────────────────────────── -->
    <div
      v-if="selectedAgent"
      class="card"
      style="margin-bottom:1rem;padding:1rem;border-color:var(--accent)"
    >
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem">
        <h3 style="margin:0;font-size:.9rem">
          <i class="fas fa-search" style="color:var(--accent);margin-right:.3rem"></i>
          Findings for <strong>{{ selectedAgent }}</strong>
        </h3>
        <button class="btn btn-xs" @click="selectedAgent = null">
          <i class="fas fa-times"></i>
        </button>
      </div>
      <div v-if="drillDownFindings.length > 0" style="overflow-x:auto">
        <table style="width:100%;font-size:.75rem;border-collapse:collapse">
          <thead>
            <tr style="border-bottom:1px solid var(--border)">
              <th style="padding:.4rem;text-align:left">Severity</th>
              <th style="padding:.4rem;text-align:left">Category</th>
              <th style="padding:.4rem;text-align:left">Description</th>
              <th style="padding:.4rem;text-align:left">Remediation</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="f in drillDownFindings"
              :key="f.id"
              style="border-bottom:1px solid var(--border)"
            >
              <td style="padding:.4rem">
                <span class="badge" :class="severityClass(f.severity)" style="font-size:.55rem">{{ f.severity }}</span>
              </td>
              <td style="padding:.4rem;white-space:nowrap">{{ f.category }}</td>
              <td style="padding:.4rem">{{ f.description }}</td>
              <td style="padding:.4rem;font-size:.7rem;color:var(--text-muted)">{{ f.remediation }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else style="text-align:center;color:var(--text-muted);padding:1rem;font-size:.8rem">
        No findings for this agent.
      </div>
    </div>

    <!-- ── Findings Table ────────────────────────────────────────────────── -->
    <div class="card" style="padding:1rem;margin-bottom:1rem">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem;margin-bottom:.75rem">
        <h3 style="margin:0;font-size:.95rem">
          <i class="fas fa-exclamation-triangle" style="color:var(--warning);margin-right:.3rem"></i>
          Findings
        </h3>
        <div style="display:flex;gap:.4rem;flex-wrap:wrap">
          <select
            v-model="securityFilterSeverity"
            style="font-size:.7rem;padding:.2rem .4rem;background:var(--surface-2);border:1px solid var(--border);color:var(--text);border-radius:4px"
            @change="fetchSecurityData"
          >
            <option value="">All Severities</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <select
            v-model="securityFilterHost"
            style="font-size:.7rem;padding:.2rem .4rem;background:var(--surface-2);border:1px solid var(--border);color:var(--text);border-radius:4px"
            @change="fetchSecurityData"
          >
            <option value="">All Hosts</option>
            <option
              v-for="agent in securityAgents"
              :key="agent.hostname"
              :value="agent.hostname"
            >{{ agent.hostname }}</option>
          </select>
        </div>
      </div>

      <div style="overflow-x:auto">
        <table class="data-table" style="width:100%;font-size:.75rem">
          <thead>
            <tr>
              <th>Host</th>
              <th>Severity</th>
              <th>Category</th>
              <th>Description</th>
              <th>Remediation</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="f in securityFindings" :key="f.id">
              <td style="white-space:nowrap">{{ f.hostname }}</td>
              <td>
                <span class="badge" :class="severityClass(f.severity)" style="font-size:.55rem">
                  {{ f.severity }}
                </span>
              </td>
              <td style="white-space:nowrap">{{ f.category }}</td>
              <td>{{ f.description }}</td>
              <td style="font-size:.7rem;color:var(--text-muted)">{{ f.remediation }}</td>
            </tr>
            <tr v-if="securityFindings.length === 0">
              <td colspan="5" style="text-align:center;color:var(--text-muted);padding:2rem">
                No findings. Run a scan to check your security posture.
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ── Score History Chart ───────────────────────────────────────────── -->
    <div class="card" style="padding:1rem">
      <h3 style="margin:0 0 .5rem;font-size:.95rem">
        <i class="fas fa-chart-line" style="color:var(--accent);margin-right:.3rem"></i>
        Score History
      </h3>
      <div v-if="securityHistory.length > 0 && historyChartConfig" style="position:relative;height:160px">
        <ChartWrapper :config="historyChartConfig" />
      </div>
      <div
        v-else
        style="text-align:center;color:var(--text-muted);padding:1.5rem;font-size:.75rem"
      >
        No historical data yet. Scores will appear here after scans.
      </div>
    </div>
  </div>
</template>
