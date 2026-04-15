<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, watch } from 'vue'
import AppModal from '../ui/AppModal.vue'
import ChartWrapper from '../ui/ChartWrapper.vue'
import { useModalsStore } from '../../stores/modals'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const modals = useModalsStore()
const notif = useNotificationsStore()
const { get } = useApi()

const historyData = ref([])
const loading = ref(false)

const ranges = [
  { label: '1h',  hours: 1,   resolution: 30  },
  { label: '6h',  hours: 6,   resolution: 60  },
  { label: '24h', hours: 24,  resolution: 120 },
  { label: '7d',  hours: 168, resolution: 900 },
]

const activeRange = computed(() => modals.historyModal.range)

async function fetchHistory() {
  const { metric, range } = modals.historyModal
  if (!metric) return
  const resolution = ranges.find(r => r.hours === range)?.resolution ?? 60
  loading.value = true
  historyData.value = []
  try {
    const data = await get(`/api/history/${metric}?range=${range}&resolution=${resolution}`)
    historyData.value = Array.isArray(data) ? data : []
  } catch (e) {
    notif.addToast('Failed to load history: ' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

function setRange(hours) {
  modals.historyModal.range = hours
}

watch(
  () => [modals.historyModal.show, modals.historyModal.metric, modals.historyModal.range],
  ([show]) => { if (show) fetchHistory() },
  { immediate: true }
)

const chartConfig = computed(() => {
  if (!historyData.value.length) return null
  const labels = historyData.value.map(d =>
    new Date(d.time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  )
  const values = historyData.value.map(d => d.value)
  return {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: modals.historyModal.metric,
        data: values,
        borderColor: 'var(--accent, #00c8ff)',
        backgroundColor: 'rgba(0,200,255,0.08)',
        borderWidth: 1.5,
        pointRadius: 0,
        fill: true,
        tension: 0.2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      scales: {
        y: {
          beginAtZero: true,
          ticks: { color: 'rgba(200,223,240,.6)' },
          grid: { color: 'rgba(255,255,255,.06)' },
        },
        x: {
          ticks: { color: 'rgba(200,223,240,.6)', maxTicksLimit: 10 },
          grid: { display: false },
        },
      },
      plugins: {
        legend: { display: false },
      },
    },
  }
})

function exportCsv() {
  if (!historyData.value.length) return
  const metric = modals.historyModal.metric
  const rows = ['time,value', ...historyData.value.map(d =>
    `${new Date(d.time * 1000).toISOString()},${d.value}`
  )]
  const blob = new Blob([rows.join('\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${metric}_history.csv`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <AppModal
    :show="modals.historyModal.show"
    :title="`History: ${modals.historyModal.metric}`"
    width="720px"
    @close="modals.closeHistory()"
  >
    <div style="padding: 0 1rem 0.5rem">
      <!-- Range selector -->
      <div style="display:flex;gap:0.5rem;margin-bottom:1rem;align-items:center">
        <button
          v-for="r in ranges"
          :key="r.hours"
          class="btn btn-sm"
          :class="activeRange === r.hours ? 'btn-primary' : ''"
          @click="setRange(r.hours)"
        >{{ r.label }}</button>
        <button class="btn btn-sm" style="margin-left:auto" @click="exportCsv">
          <i class="fas fa-download" style="margin-right:4px"></i>CSV
        </button>
      </div>

      <!-- Chart area -->
      <div style="height:300px;position:relative">
        <div v-if="loading" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;opacity:.5;font-size:.85rem">
          Loading...
        </div>
        <div v-else-if="!chartConfig" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;opacity:.4;font-size:.85rem">
          No data available
        </div>
        <ChartWrapper v-else :config="chartConfig" style="width:100%;height:100%" />
      </div>
    </div>
  </AppModal>
</template>
