<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()

const cpuPercent = computed(() => dashboard.live.cpuPercent || 0)
const memory     = computed(() => dashboard.live.memory || {})
const uptime     = computed(() => dashboard.live.uptime || '--')
const loadavg    = computed(() => {
  const la = dashboard.live.loadavg
  if (!la) return '--'
  if (typeof la === 'string') return la
  if (Array.isArray(la) && la.length) return la.map(v => (v || 0).toFixed(2)).join(' ')
  return '--'
})
const cpuTemp    = computed(() => dashboard.live.cpuTemp || '--')
const osName     = computed(() => dashboard.live.osName || '--')
const kernel     = computed(() => dashboard.live.kernel || '--')

const cpuTempClass = computed(() => {
  const t = parseFloat(cpuTemp.value)
  if (isNaN(t)) return 'bn'
  if (t > 85) return 'bd'
  if (t > 70) return 'bw'
  return 'bs'
})

const memPercent = computed(() => {
  const m = memory.value
  if (m && m.total) return Math.round(((m.used || 0) / m.total) * 100)
  return dashboard.live.memPercent || 0
})

const memLabel = computed(() => {
  const m = memory.value
  if (!m) return '--'
  if (typeof m === 'string') return m
  if (m.total) return `${fmtBytes(m.used || 0)} / ${fmtBytes(m.total)}`
  return '--'
})

const health = computed(() => {
  const c = cpuPercent.value
  if (c > 90) return 'fail'
  if (c > 70) return 'warn'
  return 'ok'
})

function fmtBytes(b) {
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++ }
  return b.toFixed(1) + ' ' + u[i]
}
</script>

<template>
  <DashboardCard title="Core System" icon="fas fa-microchip" card-id="core" :health="health">
    <div class="row">
      <span class="row-label">OS</span>
      <span class="row-val">{{ osName }}</span>
    </div>
    <div class="row">
      <span class="row-label">Kernel</span>
      <span class="row-val">{{ kernel }}</span>
    </div>
    <div class="row">
      <span class="row-label">Uptime</span>
      <span class="row-val">{{ uptime }}</span>
    </div>
    <div class="row">
      <span class="row-label">Load Avg</span>
      <span class="row-val">{{ loadavg }}</span>
    </div>
    <div class="row">
      <span class="row-label">CPU Temp</span>
      <span class="badge" :class="cpuTempClass">{{ cpuTemp }}</span>
    </div>

    <div style="margin-top:.875rem">
      <div style="font-size:.62rem;letter-spacing:.15em;text-transform:uppercase;color:var(--text-muted);margin-bottom:.35rem">
        CPU UTILIZATION
      </div>
      <div class="spark-wrap" :aria-label="'CPU utilization: ' + cpuPercent + '%'" role="img">
        <div class="spark-val" aria-hidden="true">{{ cpuPercent }}%</div>
      </div>
    </div>

    <div class="prog" style="margin-top:.65rem">
      <div class="prog-meta">
        <span>MEMORY</span>
        <span>{{ memPercent }}%</span>
      </div>
      <div
        class="prog-track"
        role="progressbar"
        :aria-valuenow="memPercent"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-label="'Memory usage ' + memPercent + '%'"
      >
        <div
          class="prog-fill"
          :class="memPercent > 90 ? 'f-danger' : memPercent > 75 ? 'f-warning' : 'f-accent'"
          :style="'width:' + memPercent + '%'"
        ></div>
      </div>
      <div style="font-family:var(--font-data);font-size:.72rem;color:var(--text-muted);margin-top:.2rem">
        {{ memLabel }}
      </div>
    </div>
  </DashboardCard>
</template>
