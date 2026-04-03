<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, nextTick } from 'vue'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'
import { Chart, registerables } from 'chart.js'

Chart.register(...registerables)

const { post } = useApi()
const notif    = useNotificationsStore()

const influxQuery   = ref('')
const influxLoading = ref(false)
const influxResults = ref([])
let   _influxChart  = null
const influxCanvas  = ref(null)

async function runInfluxQuery() {
  if (!influxQuery.value.trim()) return
  influxLoading.value = true
  try {
    const data = await post('/api/influxdb/query', { query: influxQuery.value })
    influxResults.value = Array.isArray(data) ? data : []
    await nextTick()
    renderInfluxChart()
  } catch (e) {
    notif.addToast('Query error: ' + e.message, 'error')
  } finally {
    influxLoading.value = false }
}

function influxTableKeys() {
  if (!influxResults.value.length) return []
  return Object.keys(influxResults.value[0] || {})
}

function renderInfluxChart() {
  if (!influxCanvas.value || !influxResults.value.length) return
  if (_influxChart) { _influxChart.destroy(); _influxChart = null }
  const rows = influxResults.value
  const valueKey = Object.keys(rows[0] || {}).find(k => k === '_value' || k === 'value') || null
  const timeKey  = Object.keys(rows[0] || {}).find(k => k === '_time'  || k === 'time')  || null
  if (!valueKey) return
  const labels = timeKey ? rows.map(r => r[timeKey]) : rows.map((_, i) => i)
  const values = rows.map(r => parseFloat(r[valueKey]) || 0)
  _influxChart = new Chart(influxCanvas.value.getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: valueKey,
        data: values,
        borderColor: '#00c8ff',
        backgroundColor: 'rgba(0,200,255,.1)',
        borderWidth: 1.5,
        pointRadius: 0,
        fill: true,
        tension: 0.3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      scales: {
        x: { ticks: { color: 'rgba(255,255,255,.5)', maxTicksLimit: 8 }, grid: { color: 'rgba(255,255,255,.05)' } },
        y: { ticks: { color: 'rgba(255,255,255,.5)' }, grid: { color: 'rgba(255,255,255,.05)' } },
      },
      plugins: { legend: { labels: { color: 'rgba(255,255,255,.7)' } } },
    },
  })
}

defineExpose({ renderInfluxChart })
</script>

<template>
  <div>
    <div style="display:flex;gap:.5rem;margin-bottom:.5rem;flex-wrap:wrap">
      <span style="font-size:.7rem;color:var(--text-muted);align-self:center">Quick Queries:</span>
      <button class="btn btn-xs btn-secondary" @click="influxQuery = 'from(bucket:\u0022default\u0022) |> range(start: -1h) |> filter(fn: (r) => r._measurement == \u0022cpu\u0022)'">CPU (1h)</button>
      <button class="btn btn-xs btn-secondary" @click="influxQuery = 'from(bucket:\u0022default\u0022) |> range(start: -24h) |> filter(fn: (r) => r._measurement == \u0022disk\u0022) |> filter(fn: (r) => r._field == \u0022used_percent\u0022)'">Disk Usage (24h)</button>
      <button class="btn btn-xs btn-secondary" @click="influxQuery = 'from(bucket:\u0022default\u0022) |> range(start: -15m) |> filter(fn: (r) => r._measurement == \u0022net\u0022) |> filter(fn: (r) => r._field == \u0022bytes_recv\u0022)'">Network Traffic (15m)</button>
    </div>
    <textarea
      v-model="influxQuery"
      class="field-input"
      rows="4"
      placeholder='from(bucket:"default") |> range(start: -1h) |> filter(fn: (r) => r._measurement == "cpu")'
      style="font-family:monospace;font-size:.8rem;resize:vertical;width:100%;box-sizing:border-box"
    ></textarea>
    <div style="margin-top:.5rem;display:flex;gap:.5rem;align-items:center">
      <button
        class="btn btn-primary btn-sm"
        :disabled="influxLoading || !influxQuery.trim()"
        @click="runInfluxQuery"
      >
        <i class="fas" :class="influxLoading ? 'fa-spinner fa-spin' : 'fa-play'"></i>
        {{ influxLoading ? 'Running...' : 'Run Query' }}
      </button>
      <span
        v-if="influxResults.length"
        style="font-size:.7rem;color:var(--text-muted)"
      >{{ influxResults.length }} rows</span>
    </div>

    <!-- Chart area -->
    <div style="margin-top:.8rem;position:relative;height:200px">
      <canvas ref="influxCanvas" style="width:100%;height:100%"></canvas>
    </div>

    <!-- Results table -->
    <div
      v-if="influxResults.length > 0"
      style="margin-top:.5rem;max-height:200px;overflow:auto;font-size:.7rem"
    >
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="border-bottom:1px solid var(--border)">
            <th
              v-for="key in influxTableKeys()"
              :key="key"
              style="padding:.2rem .4rem;text-align:left"
            >{{ key }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, i) in influxResults.slice(0, 50)"
            :key="i"
            style="border-bottom:1px solid var(--border)"
          >
            <td
              v-for="key in influxTableKeys()"
              :key="key"
              style="padding:.2rem .4rem"
            >{{ row[key] }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
