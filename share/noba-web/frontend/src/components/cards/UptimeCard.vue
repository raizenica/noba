<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi'
import DashboardCard from './DashboardCard.vue'
import { UPTIME_FETCH_INTERVAL_MS } from '../../constants'

const { get } = useApi()
const uptimeItems   = ref([])
const uptimePercent = ref(0)
let _iv = null

async function fetchUptime() {
  try {
    const data = await get('/api/uptime')
    uptimeItems.value   = data.items || data || []
    uptimePercent.value = data.percent ?? uptimePercent.value
  } catch { /* silent */ }
}

const downItems = computed(() =>
  uptimeItems.value.filter(i => i.status !== 'up').slice(0, 5)
)

const upCount = computed(() =>
  uptimeItems.value.filter(i => i.status === 'up').length
)

const percentColor = computed(() => {
  const p = uptimePercent.value
  if (p >= 95) return 'var(--success)'
  if (p >= 80) return 'var(--warning)'
  return 'var(--danger)'
})

onMounted(() => {
  fetchUptime()
  _iv = setInterval(fetchUptime, UPTIME_FETCH_INTERVAL_MS)
})

onUnmounted(() => {
  if (_iv) clearInterval(_iv)
})
</script>

<template>
  <DashboardCard title="Uptime Status" icon="fas fa-check-circle" card-id="uptime">
    <div style="text-align:center;margin:4px 0">
      <span
        style="font-size:1.8rem;font-weight:700"
        :style="'color:' + percentColor"
      >{{ uptimePercent }}%</span>
      <div style="font-size:.7rem;color:var(--text-dim)">
        {{ upCount }}/{{ uptimeItems.length }} services up
      </div>
    </div>
    <div
      v-for="item in downItems"
      :key="item.name"
      class="row"
      style="font-size:.8rem"
    >
      <span class="row-label">
        <i class="fas fa-times-circle" style="color:var(--danger);margin-right:4px"></i>
        {{ item.name }}
      </span>
      <span class="badge bd">down</span>
    </div>
  </DashboardCard>
</template>
