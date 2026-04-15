<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, onMounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useAuthStore }      from '../stores/auth'
import { useApi }            from '../composables/useApi'
import { useNotificationsStore } from '../stores/notifications'
import { useModalsStore } from '../stores/modals'

import AgentDetailModal from '../components/agents/AgentDetailModal.vue'
import CommandPalette   from '../components/agents/CommandPalette.vue'
import LogStreamModal   from '../components/agents/LogStreamModal.vue'
import DeployModal      from '../components/agents/DeployModal.vue'

const dashboardStore = useDashboardStore()
const authStore      = useAuthStore()
const { get, del }   = useApi()
const notify         = useNotificationsStore()
const modals         = useModalsStore()

// ── Agent list from SSE store ──────────────────────────────────────────────────
const agents = computed(() => dashboardStore.live.agents || [])

// ── Selection & Bulk Actions ──────────────────────────────────────────────────
const selectedAgents = ref(new Set())

function toggleSelect(hostname) {
  if (selectedAgents.value.has(hostname)) {
    selectedAgents.value.delete(hostname)
  } else {
    selectedAgents.value.add(hostname)
  }
}

function selectAll() {
  if (selectedAgents.value.size === agents.value.length) {
    selectedAgents.value.clear()
  } else {
    selectedAgents.value = new Set(agents.value.map(a => a.hostname))
  }
}

async function bulkUpdate() {
  const targets = Array.from(selectedAgents.value)
  if (!targets.length) return
  if (!await modals.confirm(`Queue agent update for ${targets.length} hosts?`)) return
  try {
    const { post } = useApi()
    await post('/api/agents/bulk-command', {
      hostnames: targets,
      type: 'update_agent',
      params: {}
    })
    notify.addToast(`Update queued for ${targets.length} agents`, 'success')
    selectedAgents.value.clear()
  } catch (e) {
    notify.addToast(`Bulk update failed: ${e.message}`, 'danger')
  }
}

async function bulkRemove() {
  const targets = Array.from(selectedAgents.value)
  if (!targets.length) return
  if (!await modals.confirm(`Remove ${targets.length} agents from the dashboard? This does not stop the services on the remote hosts.`)) return
  
  let success = 0
  let fail = 0
  for (const host of targets) {
    try {
      await del(`/api/agents/${host}`)
      success++
    } catch {
      fail++
    }
  }
  
  if (success) notify.addToast(`Removed ${success} agents`, 'success')
  if (fail) notify.addToast(`Failed to remove ${fail} agents`, 'danger')
  selectedAgents.value.clear()
}

// ── Command history ────────────────────────────────────────────────────────────
const cmdHistory        = ref([])
const cmdHistoryLoading = ref(false)

async function fetchCommandHistory() {
  cmdHistoryLoading.value = true
  try {
    const data = await get('/api/agents/command-history?limit=50')
    cmdHistory.value = Array.isArray(data) ? data : []
  } catch (e) { notify.addToast('Failed to load command history: ' + e.message, 'danger') }
  finally { cmdHistoryLoading.value = false }
}

// ── Agent detail modal ────────────────────────────────────────────────────────
const showDetailModal  = ref(false)
const detailHostname   = ref('')
const detailAgent      = ref(null)

function openDetail(agent) {
  detailHostname.value = agent.hostname
  detailAgent.value    = agent
  showDetailModal.value = true
}

// ── Log stream modal ──────────────────────────────────────────────────────────
const showLogStream    = ref(false)
const logStreamHost    = ref('')

function openLogStream(hostname) {
  logStreamHost.value = hostname
  showLogStream.value = true
}

async function deleteAgent(hostname) {
  if (!await modals.confirm(`Remove agent "${hostname}" from the dashboard? This only removes the record — the agent service on the remote host is not affected.`)) return
  try {
    await del(`/api/agents/${hostname}`)
    notify.addToast(`Agent "${hostname}" removed`, 'success')
  } catch (e) {
    notify.addToast(`Failed to remove agent: ${e.message}`, 'danger')
  }
}

// ── Deploy modal ──────────────────────────────────────────────────────────────
const showDeploy = ref(false)

// ── Helpers ───────────────────────────────────────────────────────────────────
function osIcon(platform) {
  if (!platform) return 'fas fa-server'
  const p = platform.toLowerCase()
  if (p.includes('linux'))   return 'fab fa-linux'
  if (p.includes('windows')) return 'fab fa-windows'
  if (p.includes('darwin') || p.includes('macos')) return 'fab fa-apple'
  return 'fas fa-server'
}

function lastSeenLabel(s) {
  if (s === undefined || s === null) return '--'
  if (s < 60)   return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

function historyStatusClass(status) {
  if (status === 'ok')     return 'bs'
  if (status === 'error')  return 'bd'
  if (status === 'queued') return 'bn'
  return 'bw'
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  fetchCommandHistory()
})
</script>

<template>
  <div>
    <!-- Page header -->
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem">
      <h2 style="margin:0">
        <i class="fas fa-satellite" style="margin-right:.5rem;color:var(--accent)"></i>
        Remote Agents
      </h2>
      <div style="display:flex;gap:.4rem">
        <button
          v-if="authStore.isAdmin"
          class="btn btn-xs btn-secondary"
          title="Deploy new agent"
          @click="showDeploy = true"
        >
          <i class="fas fa-satellite-dish" style="margin-right:.3rem"></i>Deploy
        </button>
      </div>
    </div>

    <!-- Selection Bar (Safety & Contextual actions) -->
    <div
      v-if="selectedAgents.size > 0 || agents.length > 0"
      class="selection-bar"
      :style="selectedAgents.size > 0 ? '' : 'border-color:transparent;background:transparent;box-shadow:none;padding:0;margin-bottom:.75rem'"
    >
      <div style="display:flex;align-items:center;gap:.8rem;flex:1">
        <button
          class="btn btn-xs"
          :class="selectedAgents.size === agents.length ? 'btn-primary' : 'btn-secondary'"
          @click="selectAll"
        >
          <i class="fas" :class="selectedAgents.size === agents.length ? 'fa-check-square' : 'fa-square'"></i>
          {{ selectedAgents.size === agents.length ? 'Deselect All' : 'Select All' }}
        </button>
        
        <template v-if="selectedAgents.size > 0">
          <div style="width:1px;height:16px;background:var(--border);margin:0 .2rem"></div>
          <span style="font-weight:600;font-size:.85rem">
            {{ selectedAgents.size }} agent{{ selectedAgents.size > 1 ? 's' : '' }} selected
          </span>
        </template>
      </div>

      <div v-if="selectedAgents.size > 0" style="display:flex;gap:.5rem;align-items:center">
        <button class="btn btn-xs btn-primary" @click="bulkUpdate">
          <i class="fas fa-sync-alt"></i> Update
        </button>
        <div style="width:1px;height:16px;background:var(--border);margin:0 .2rem"></div>
        <button v-if="authStore.isAdmin" class="btn btn-xs btn-danger" @click="bulkRemove">
          <i class="fas fa-trash"></i> Remove
        </button>
      </div>
    </div>

    <!-- Agent grid -->
    <div
      v-if="agents.length > 0"
      style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:.8rem;margin-bottom:1rem"
    >
      <div
        v-for="a in agents"
        :key="a.hostname"
        class="agent-card"
        :class="[a.online ? 'agent-online' : 'agent-offline', { 'selected-card': selectedAgents.has(a.hostname) }]"
        style="padding:.8rem;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);cursor:pointer;position:relative"
        @click="openDetail(a)"
      >
        <!-- Selection Checkbox -->
        <div
          style="position:absolute;top:-8px;left:-8px;z-index:10"
          @click.stop="toggleSelect(a.hostname)"
        >
          <div
            class="bulk-check"
            :class="{ active: selectedAgents.has(a.hostname) }"
          >
            <i class="fas fa-check" v-if="selectedAgents.has(a.hostname)"></i>
          </div>
        </div>

        <!-- Header row -->
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.4rem">
          <div style="display:flex;align-items:center;gap:.4rem;min-width:0">
            <i :class="osIcon(a.platform)" style="color:var(--accent);font-size:.85rem;flex-shrink:0"></i>
            <span style="font-weight:700;font-size:.88rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
              {{ a.hostname }}
            </span>
          </div>
          <span class="badge" :class="a.online ? 'bs' : 'bd'" style="font-size:.55rem;flex-shrink:0;margin-left:.4rem">
            {{ a.online ? 'online' : 'offline' }}
          </span>
        </div>

        <!-- Meters -->
        <div class="agent-meters" style="margin-bottom:.35rem">
          <div class="agent-meter">
            <span class="agent-meter-label">CPU</span>
            <div class="prog-track" style="flex:1;height:5px">
              <div
                class="prog-fill"
                :class="(a.cpu_percent||0)>90?'f-danger':(a.cpu_percent||0)>70?'f-warning':'f-accent'"
                :style="`width:${a.cpu_percent||0}%`"
              ></div>
            </div>
            <span class="agent-meter-val">{{ a.cpu_percent || 0 }}%</span>
          </div>
          <div class="agent-meter">
            <span class="agent-meter-label">RAM</span>
            <div class="prog-track" style="flex:1;height:5px">
              <div
                class="prog-fill"
                :class="(a.mem_percent||0)>90?'f-danger':(a.mem_percent||0)>70?'f-warning':'f-success'"
                :style="`width:${a.mem_percent||0}%`"
              ></div>
            </div>
            <span class="agent-meter-val">{{ a.mem_percent || 0 }}%</span>
          </div>
        </div>

        <!-- Meta -->
        <div style="font-size:.7rem;color:var(--text-muted)">
          <div>{{ a.platform }} &middot; {{ a.arch || '' }}</div>
          <div v-if="a.uptime_s">Uptime: {{ Math.floor((a.uptime_s||0)/3600) }}h</div>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>Last seen: {{ lastSeenLabel(a.last_seen_s) }}</span>
            <span
              v-if="a.agent_version"
              class="badge bw"
              style="font-size:.55rem;font-family:monospace;padding:.1rem .3rem"
              title="Agent version"
            >v{{ a.agent_version }}</span>
          </div>
        </div>

        <!-- Quick action buttons -->
        <div
          v-if="authStore.isOperator"
          style="margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.3rem"
          @click.stop
        >
          <button
            class="btn btn-xs"
            title="View details"
            @click="openDetail(a)"
          ><i class="fas fa-info-circle"></i></button>
          <button
            v-if="a.online"
            class="btn btn-xs"
            title="Stream logs"
            @click="openLogStream(a.hostname)"
          ><i class="fas fa-scroll"></i></button>
          <button
            v-if="authStore.isAdmin"
            class="btn btn-xs"
            style="margin-left:auto;color:var(--danger)"
            title="Remove agent"
            @click="deleteAgent(a.hostname)"
          ><i class="fas fa-trash"></i></button>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="agents.length === 0" class="empty-msg" style="margin-bottom:1rem;padding:2rem;text-align:center">
      <i class="fas fa-satellite-dish" style="font-size:2rem;opacity:.3;display:block;margin-bottom:.5rem"></i>
      No agents reporting yet.
      <br><small style="opacity:.6">Deploy an agent to a remote host to start monitoring it.</small>
      <br v-if="authStore.isAdmin">
      <button v-if="authStore.isAdmin" class="btn btn-primary" style="margin-top:.75rem" @click="showDeploy = true">
        <i class="fas fa-paper-plane"></i> Deploy Agent
      </button>
    </div>

    <!-- Command Palette (operator+) -->
    <CommandPalette
      v-if="agents.length > 0 && authStore.isOperator"
      :agents="agents"
      style="margin-bottom:1rem"
      @result="fetchCommandHistory"
    />

    <!-- Command History -->
    <div v-if="agents.length > 0" style="margin-top:.5rem">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.4rem">
        <span style="font-size:.75rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--text-muted)">
          <i class="fas fa-history" style="margin-right:.3rem"></i>Command History
        </span>
        <button
          class="btn btn-xs"
          :disabled="cmdHistoryLoading"
          @click="fetchCommandHistory"
        >
          <i class="fas" :class="cmdHistoryLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i>
        </button>
      </div>

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
              <td>
                <a
                  href="#"
                  class="agent-hostname-link"
                  @click.prevent="detailHostname = h.hostname; showDetailModal = true"
                >{{ h.hostname }}</a>
              </td>
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
    </div>

    <!-- Admin: Deploy section (inline, outside modal too) -->
    <div
      v-if="authStore.isAdmin && agents.length === 0"
      style="margin-top:1rem;padding:.8rem;border:1px solid var(--accent);border-radius:6px;background:color-mix(in srgb, var(--accent) 5%, var(--surface))"
    >
      <div style="font-size:.75rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);margin-bottom:.6rem">
        <i class="fas fa-rocket" style="margin-right:.4rem"></i>Get Started — Deploy your first agent
      </div>
      <button class="btn btn-primary btn-sm" @click="showDeploy = true">
        <i class="fas fa-satellite-dish" style="margin-right:.4rem"></i>Deploy Agent
      </button>
    </div>

    <!-- ── Modals ─────────────────────────────────────────────────────────── -->
    <AgentDetailModal
      :show="showDetailModal"
      :hostname="detailHostname"
      :agent="detailAgent"
      @close="showDetailModal = false; detailAgent = null"
    />

    <LogStreamModal
      :show="showLogStream"
      :hostname="logStreamHost"
      @close="showLogStream = false"
    />

    <DeployModal
      :show="showDeploy"
      @close="showDeploy = false"
      @deployed="showDeploy = false"
    />
  </div>
</template>

<style scoped>
.selection-bar {
  display: flex;
  align-items: center;
  padding: .6rem 1rem;
  background: var(--surface);
  border: 1px solid var(--accent);
  border-radius: 6px;
  margin-bottom: 1rem;
  box-shadow: 0 4px 12px rgba(0,0,0,0.2), 0 0 8px var(--accent-glow);
  animation: slide-down 0.2s ease-out;
}
.btn-link {
  background: none;
  border: none;
  color: var(--accent);
  text-decoration: underline;
  cursor: pointer;
  padding: 0;
}
.btn-link:hover {
  color: var(--text);
}
@keyframes slide-down {
  from { transform: translateY(-10px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}
.bulk-check {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  background: var(--surface);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content:center;
  color: #fff;
  font-size: .7rem;
  transition: all .15s ease;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
}
.bulk-check.active {
  background: var(--accent);
  border-color: var(--accent);
}
.selected-card {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 1px var(--accent);
}
.agent-card:hover .bulk-check {
  border-color: var(--accent);
}
</style>
