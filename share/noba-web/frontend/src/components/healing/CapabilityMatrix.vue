<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, onMounted } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'
import { useHealing } from '../../composables/useHealing'

const dashStore = useDashboardStore()
const authStore = useAuthStore()
const notify = useNotificationsStore()
const healing = useHealing()

const expanded = ref(null)
const manifests = ref({})   // hostname -> { manifest, probed_at }
const refreshing = ref({})  // hostname -> bool

const agents = computed(() => {
  return (dashStore.live.agents || []).map(agent => ({
    ...agent,
    manifest: manifests.value[agent.hostname]?.manifest ?? null,
    probed_at: manifests.value[agent.hostname]?.probed_at ?? null,
  }))
})

function toggleAgent(hostname) {
  expanded.value = expanded.value === hostname ? null : hostname
}

function capState(info) {
  if (!info) return 'cap-off'
  if (info.available === false || info.state === 'unavailable') return 'cap-off'
  if (info.degraded || info.state === 'degraded') return 'cap-degraded'
  return 'cap-ok'
}

function formatTime(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString()
}

async function loadCapabilities(hostname) {
  try {
    const data = await healing.fetchCapabilities(hostname)
    if (data) {
      manifests.value[hostname] = {
        manifest: data.manifest ?? data,
        probed_at: data.probed_at ?? null,
      }
    }
  } catch {
    // silently skip agents with no capability data
  }
}

async function refresh(hostname) {
  if (refreshing.value[hostname]) return
  refreshing.value[hostname] = true
  try {
    const data = await healing.refreshCapabilities(hostname)
    if (data) {
      manifests.value[hostname] = {
        manifest: data.manifest ?? data,
        probed_at: data.probed_at ?? null,
      }
      notify.addToast(`Capabilities refreshed for ${hostname}`, 'success')
    } else {
      notify.addToast(`Refresh failed for ${hostname}`, 'error')
    }
  } catch {
    notify.addToast(`Error refreshing capabilities for ${hostname}`, 'error')
  } finally {
    refreshing.value[hostname] = false
  }
}

onMounted(async () => {
  const hostnames = (dashStore.live.agents || []).map(a => a.hostname).filter(Boolean)
  await Promise.allSettled(hostnames.map(h => loadCapabilities(h)))
})
</script>

<template>
  <div class="capability-matrix">
    <div v-if="!agents.length" class="empty-msg">No agents connected.</div>
    <div v-for="agent in agents" :key="agent.hostname" class="cap-agent">
      <div class="cap-header" role="button" tabindex="0" @click="toggleAgent(agent.hostname)" @keydown.enter="toggleAgent(agent.hostname)" @keydown.space.prevent="toggleAgent(agent.hostname)">
        <span class="cap-hostname">{{ agent.hostname }}</span>
        <span v-if="agent.manifest" class="badge ba">
          {{ agent.manifest.os }} · {{ agent.manifest.distro }}
        </span>
        <span v-if="agent.manifest" class="text-muted">{{ agent.manifest.init_system }}</span>
        <span v-if="!agent.manifest" class="badge bw">No manifest</span>
        <button
          v-if="authStore.isOperator"
          class="btn btn-xs"
          :disabled="refreshing[agent.hostname]"
          @click.stop="refresh(agent.hostname)"
        >
          {{ refreshing[agent.hostname] ? 'Refreshing...' : 'Refresh' }}
        </button>
      </div>

      <!-- Expanded capability list -->
      <div v-if="expanded === agent.hostname && agent.manifest" class="cap-detail">
        <div class="cap-grid">
          <div
            v-for="(info, tool) in agent.manifest.capabilities"
            :key="tool"
            class="cap-item"
          >
            <span :class="['cap-dot', capState(info)]" />
            <span class="cap-name">{{ tool }}</span>
            <span v-if="info && info.version" class="text-muted">v{{ info.version }}</span>
          </div>
        </div>
        <div class="cap-meta">
          <span class="text-muted">
            Last probed: {{ agent.probed_at ? formatTime(agent.probed_at) : 'never' }}
          </span>
        </div>
      </div>

      <!-- Expanded but no manifest -->
      <div v-else-if="expanded === agent.hostname && !agent.manifest" class="cap-detail">
        <div class="empty-msg">No capability data available. Try refreshing.</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cap-agent {
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: .5rem;
  overflow: hidden;
}

.cap-header {
  display: flex;
  gap: .75rem;
  align-items: center;
  padding: .75rem 1rem;
  cursor: pointer;
  flex-wrap: wrap;
}

.cap-header:hover {
  background: var(--surface-2);
}

.cap-hostname {
  font-weight: 600;
  font-family: var(--font-data);
}

.cap-detail {
  padding: .75rem 1rem;
  background: var(--surface-2);
}

.cap-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: .5rem;
}

.cap-item {
  display: flex;
  align-items: center;
  gap: .5rem;
}

.cap-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.cap-ok { background: var(--success); }
.cap-degraded { background: var(--warning); }
.cap-off { background: var(--text-muted); }

.cap-name {
  font-family: var(--font-data);
  font-size: .85rem;
}

.cap-meta {
  margin-top: .75rem;
  font-size: .8rem;
}
</style>
