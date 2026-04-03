<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, nextTick } from 'vue'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'
import { Chart, registerables } from 'chart.js'

Chart.register(...registerables)

const { get } = useApi()
const notif   = useNotificationsStore()

const correlateMetrics = ref('cpu_percent,mem_percent')
const correlateHours   = ref(24)
const correlateLoading = ref(false)
const correlateData    = ref(null)
let   _correlateChart  = null
const correlateCanvas  = ref(null)

async function fetchCorrelation() {
  if (!correlateMetrics.value.trim()) return
  correlateLoading.value = true
  try {
    const data = await get(
      `/api/metrics/correlate?metrics=${encodeURIComponent(correlateMetrics.value)}&hours=${correlateHours.value}`
    )
    correlateData.value = data
    await nextTick()
    renderCorrelationChart()
  } catch (e) {
    notif.addToast('Correlation error: ' + e.message, 'error')
  } finally {
    correlateLoading.value = false
  }
}

function renderCorrelationChart() {
  if (!correlateCanvas.value || !correlateData.value) return
  if (_correlateChart) { _correlateChart.destroy(); _correlateChart = null }
  const colors   = ['#00c8ff','#00e676','#ffb300','#ff1744','#ab47bc','#26c6da','#ff7043','#66bb6a']
  const datasets = []
  let i = 0
  for (const [name, points] of Object.entries(correlateData.value)) {
    datasets.push({
      label: name,
      data: points.map(p => ({ x: p.time * 1000, y: p.value })),
      borderColor: colors[i % colors.length],
      borderWidth: 1.5,
      pointRadius: 0,
      fill: false,
      tension: 0.3,
    })
    i++
  }
  _correlateChart = new Chart(correlateCanvas.value.getContext('2d'), {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      scales: {
        x: {
          type: 'linear',
          ticks: {
            color: 'rgba(255,255,255,.5)',
            maxTicksLimit: 8,
            callback: v => new Date(v).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
          grid: { color: 'rgba(255,255,255,.05)' },
        },
        y: {
          ticks: { color: 'rgba(255,255,255,.5)' },
          grid:  { color: 'rgba(255,255,255,.05)' },
        },
      },
      plugins: { legend: { labels: { color: 'rgba(255,255,255,.7)' } } },
    },
  })
}

defineExpose({ renderCorrelationChart })
</script>

<template>
  <div>
    <div style="display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap">
      <input
        v-model="correlateMetrics"
        class="field-input"
        placeholder="cpu_percent,mem_percent,net_rx_bytes (comma-separated)"
        style="flex:1;font-size:.8rem;min-width:200px"
      >
      <select
        v-model.number="correlateHours"
        class="field-select"
        style="width:80px"
      >
        <option :value="1">1h</option>
        <option :value="6">6h</option>
        <option :value="24">24h</option>
        <option :value="72">3d</option>
        <option :value="168">7d</option>
      </select>
      <button
        class="btn btn-primary btn-sm"
        :disabled="correlateLoading || !correlateMetrics.trim()"
        @click="fetchCorrelation"
      >
        <i class="fas" :class="correlateLoading ? 'fa-spinner fa-spin' : 'fa-play'"></i>
      </button>
    </div>
    <div style="position:relative;height:300px">
      <canvas ref="correlateCanvas" style="width:100%;height:100%"></canvas>
    </div>
    <div v-if="!correlateData" style="font-size:.75rem;color:var(--text-muted);text-align:center;margin-top:.5rem">
      Enter metric names and click run to render the correlation chart.
    </div>
  </div>
</template>
