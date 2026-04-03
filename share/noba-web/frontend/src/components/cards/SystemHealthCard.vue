<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi'
import DashboardCard from './DashboardCard.vue'

const { get } = useApi()
const systemHealth = ref(null)
let _iv = null

async function fetchSystemHealth() {
  try {
    systemHealth.value = await get('/api/system/health')
  } catch { /* silent */ }
}

function scoreColor(score) {
  if (score >= 90) return 'var(--success)'
  if (score >= 60) return 'var(--warning)'
  return 'var(--danger)'
}

function statusColor(status) {
  if (status === 'ok') return 'var(--success)'
  if (status === 'warning') return 'var(--warning)'
  return 'var(--danger)'
}

onMounted(() => {
  fetchSystemHealth()
  _iv = setInterval(fetchSystemHealth, 30000)
})

onUnmounted(() => {
  if (_iv) clearInterval(_iv)
})
</script>

<template>
  <DashboardCard title="System Health" icon="fas fa-heartbeat" card-id="health">
    <template v-if="systemHealth">
      <div style="text-align:center;margin:8px 0">
        <div
          style="font-size:2.5rem;font-weight:700"
          :style="'color:' + scoreColor(systemHealth.score)"
        >
          {{ systemHealth.score }}<span style="font-size:1rem;color:var(--text-dim)">%</span>
        </div>
        <div style="font-size:.75rem;color:var(--text-muted)">
          Health Score — Grade <strong>{{ systemHealth.grade }}</strong>
        </div>
      </div>
      <div
        v-for="c in systemHealth.checks"
        :key="c.name"
        class="row"
        style="font-size:.8rem"
      >
        <span class="row-label">
          <i
            class="fas fa-circle"
            style="font-size:.4rem;vertical-align:middle;margin-right:4px"
            :style="'color:' + statusColor(c.status)"
          ></i>
          {{ c.name }}
        </span>
        <span class="row-val">{{ c.value }}</span>
      </div>
    </template>
    <div v-else class="empty-msg">Loading...</div>
  </DashboardCard>
</template>
