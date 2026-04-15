<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { useDashboardStore } from '../../stores/dashboard'

const { get } = useApi()
const dashboardStore = useDashboardStore()

const healthScore         = ref(null)
const healthScoreExpanded = ref(false)

// --- Last updated ticker ---
const relativeTime = ref('')
let tickInterval = null
let lastSeenEpoch = 0
let lastSeenTimestamp = ''

function tickRelative() {
  const ts = dashboardStore.live?.timestamp
  if (ts && ts !== lastSeenTimestamp) {
    lastSeenTimestamp = ts
    lastSeenEpoch = Date.now()
  }
  if (!lastSeenEpoch) { relativeTime.value = ''; return }
  const diffSec = Math.floor((Date.now() - lastSeenEpoch) / 1000)
  if (diffSec < 5) relativeTime.value = 'just now'
  else if (diffSec < 60) relativeTime.value = `${diffSec}s ago`
  else if (diffSec < 3600) relativeTime.value = `${Math.floor(diffSec / 60)}m ago`
  else relativeTime.value = `${Math.floor(diffSec / 3600)}h ago`
}

// --- Endpoint count ---
const endpointCount = ref(null)

onMounted(async () => {
  tickRelative()
  tickInterval = setInterval(tickRelative, 1000)
  fetchHealthScore()
  try {
    const eps = await get('/api/endpoints')
    endpointCount.value = Array.isArray(eps) ? eps.length : null
  } catch { /* silent */ }
})

onUnmounted(() => {
  clearInterval(tickInterval)
})

async function fetchHealthScore() {
  try {
    const result = await get('/api/health-score')
    healthScore.value = result
  } catch (e) {
    console.warn('[HealthScoreGauge] fetch failed:', e.message || e)
  }
}

function infraScoreColor(score) {
  if (score == null) return 'var(--text-muted)'
  if (score > 80) return 'var(--success)'
  if (score > 50) return 'var(--warning)'
  return 'var(--danger)'
}

function infraScoreRing(score) {
  if (score == null) {
    return 'background: conic-gradient(var(--surface-2) 0deg, var(--surface-2) 360deg)'
  }
  const deg   = Math.round((score / 100) * 360)
  const color = infraScoreColor(score)
  return `background: conic-gradient(${color} 0deg, ${color} ${deg}deg, var(--surface-2) ${deg}deg, var(--surface-2) 360deg)`
}

function catBadgeClass(status) {
  if (status === 'ok')      return 'bs'
  if (status === 'warning') return 'bw'
  return 'bd'
}

defineExpose({ fetchHealthScore })
</script>

<template>
  <div
    v-if="healthScore"
    style="margin:0.75rem 0;cursor:pointer"
    @click="healthScoreExpanded = !healthScoreExpanded"
  >
    <!-- Summary row -->
    <div
      style="display:flex;align-items:center;gap:1rem;padding:.8rem 1rem;border:1px solid var(--border);border-radius:8px;background:var(--surface-2)"
      :style="healthScoreExpanded ? 'border-radius:8px 8px 0 0' : ''"
    >
      <!-- Ring gauge -->
      <div
        style="position:relative;width:64px;height:64px;border-radius:50%;flex-shrink:0"
        :style="infraScoreRing(healthScore.score)"
      >
        <div
          style="position:absolute;inset:6px;border-radius:50%;background:var(--surface);display:flex;align-items:center;justify-content:center"
        >
          <span
            style="font-size:1.2rem;font-weight:700"
            :style="`color:${infraScoreColor(healthScore.score)}`"
          >{{ healthScore.score }}</span>
        </div>
      </div>

      <!-- Label -->
      <div style="flex:1;min-width:120px">
        <div style="font-weight:600;font-size:.9rem">Infrastructure Health</div>
        <div style="font-size:.75rem;color:var(--text-muted)">
          Grade: {{ healthScore.grade }}
          &mdash;
          {{ Object.keys(healthScore.categories || {}).length }} categories
        </div>
        <div style="font-size:.7rem;color:var(--text-muted);text-align:center;margin-top:.15rem">
          <span v-if="relativeTime">Last updated: {{ relativeTime }}</span>
        </div>
        <div style="font-size:.7rem;color:var(--text-muted);text-align:center">
          {{ (dashboardStore.live?.agents || []).length }} agents
          <span v-if="endpointCount !== null">&middot; {{ endpointCount }} endpoints</span>
        </div>
      </div>

      <button
        class="btn btn-xs"
        type="button"
        title="Refresh"
        @click.stop="fetchHealthScore"
      ><i class="fas fa-sync-alt"></i></button>

      <i
        class="fas"
        :class="healthScoreExpanded ? 'fa-chevron-up' : 'fa-chevron-down'"
        style="color:var(--text-muted)"
      ></i>
    </div>

    <!-- Expanded categories -->
    <div
      v-show="healthScoreExpanded"
      style="border:1px solid var(--border);border-top:none;border-radius:0 0 8px 8px;padding:.8rem 1rem;background:var(--surface-2)"
    >
      <div
        v-for="(cat, key) in (healthScore.categories || {})"
        :key="key"
        style="margin-bottom:.6rem"
      >
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.2rem">
          <span style="font-size:.8rem;font-weight:500;text-transform:capitalize">
            {{ String(key).replace(/_/g, ' ') }}
          </span>
          <span class="badge" :class="catBadgeClass(cat.status)" style="font-size:.6rem">
            {{ cat.score }}/{{ cat.max }}
          </span>
        </div>
        <!-- Progress bar -->
        <div style="height:4px;background:var(--surface);border-radius:2px;overflow:hidden">
          <div
            style="height:100%;border-radius:2px;transition:width .3s"
            :style="`width:${(cat.score / cat.max) * 100}%;background:${cat.status === 'ok' ? 'var(--success)' : cat.status === 'warning' ? 'var(--warning)' : 'var(--danger)'}`"
          ></div>
        </div>
        <div v-if="cat.detail" style="font-size:.65rem;color:var(--text-muted);margin-top:.15rem">
          {{ cat.detail }}
        </div>
        <div
          v-for="rec in (cat.recommendations || [])"
          :key="rec"
          style="font-size:.65rem;color:var(--warning);padding-left:.5rem"
        >
          <i class="fas fa-exclamation-triangle" style="margin-right:.2rem;font-size:.55rem"></i>
          {{ rec }}
        </div>
      </div>
      <div
        v-if="healthScore.timestamp"
        style="font-size:.65rem;color:var(--text-muted);text-align:right;margin-top:.4rem"
      >
        Updated: {{ new Date(healthScore.timestamp * 1000).toLocaleTimeString() }}
      </div>
    </div>
  </div>
</template>
