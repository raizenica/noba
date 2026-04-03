<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useApi } from '../../composables/useApi'
import ChartWrapper from '../ui/ChartWrapper.vue'

const { get } = useApi()

const predMetrics        = ref(['disk_percent'])
const predRange          = ref('30d')
const predProjection     = ref('90d')
const predCapacity       = ref(null)
const predHealth         = ref(null)
const predLoading        = ref(false)
const predHealthLoading  = ref(false)

const metricOptions = [
  { key: 'disk_percent',  label: 'Disk %' },
  { key: 'cpu_percent',   label: 'CPU %' },
  { key: 'mem_percent',   label: 'Memory %' },
]
const rangeOptions      = ['7d', '30d', '90d']
const projectionOptions = ['30d', '90d', '180d']

function togglePredMetric(key) {
  const idx = predMetrics.value.indexOf(key)
  if (idx === -1) {
    predMetrics.value = [...predMetrics.value, key]
  } else if (predMetrics.value.length > 1) {
    predMetrics.value = predMetrics.value.filter(k => k !== key)
  }
  fetchPredictions()
}

async function fetchPredictions() {
  predLoading.value = true
  try {
    const qs = predMetrics.value.map(m => `metrics=${encodeURIComponent(m)}`).join('&')
    predCapacity.value = await get(`/api/predict/capacity?${qs}`)
  } catch { predCapacity.value = null }
  finally { predLoading.value = false }
}

async function fetchPredictHealth() {
  predHealthLoading.value = true
  try {
    predHealth.value = await get('/api/predict/health')
  } catch { predHealth.value = null }
  finally { predHealthLoading.value = false }
}

function predScoreClass(score) {
  if (score == null) return ''
  if (score >= 80) return 'bs'
  if (score >= 60) return 'bw'
  return 'bd'
}

function predScoreColor(score) {
  if (score == null) return 'var(--text-muted)'
  if (score >= 80) return 'var(--success)'
  if (score >= 60) return 'var(--warning)'
  return 'var(--danger)'
}

function formatPct(v) {
  if (v == null) return '\u2014'
  return (v * 100).toFixed(1) + '%'
}

function formatMs(v) {
  if (v == null) return '\u2014'
  return v.toFixed(0) + ' ms'
}

const predChartConfig = computed(() => {
  if (!predCapacity.value?.metrics) return null
  const colors = ['var(--accent)', 'var(--success)', 'var(--warning)']
  const datasets = []
  let labels = null

  Object.entries(predCapacity.value.metrics).forEach(([key, info], i) => {
    const points = info.projection || []
    if (!points.length) return
    if (!labels) labels = points.map(p => new Date(p.time * 1000))
    const color = colors[i % colors.length]
    datasets.push(
      {
        label: key.replace(/_/g, ' '),
        data: points.map(p => p.predicted),
        borderColor: color,
        borderWidth: 3,
        pointRadius: 0,
        fill: false,
      },
      {
        label: `${key} 68% band`,
        data: points.map(p => p.upper_68),
        borderColor: 'transparent',
        backgroundColor: 'rgba(0,200,255,0.18)',
        pointRadius: 0,
        fill: '+1',
      },
      {
        label: `${key} 68% lower`,
        data: points.map(p => p.lower_68),
        borderColor: 'transparent',
        pointRadius: 0,
        fill: false,
      },
      {
        label: `${key} 95% upper`,
        data: points.map(p => p.upper_95),
        borderDash: [5, 5],
        borderColor: 'rgba(0,200,255,0.5)',
        borderWidth: 1.5,
        pointRadius: 0,
        fill: false,
      },
      {
        label: `${key} 95% lower`,
        data: points.map(p => p.lower_95),
        borderDash: [5, 5],
        borderColor: 'rgba(0,200,255,0.5)',
        borderWidth: 1.5,
        pointRadius: 0,
        fill: false,
      },
    )
  })

  if (!labels || !datasets.length) return null

  return {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      scales: {
        x: {
          type: 'category',
          ticks: { color: 'rgba(200,223,240,.6)', maxTicksLimit: 8 },
          grid: { display: false },
        },
        y: {
          min: 0,
          max: 100,
          ticks: { color: 'rgba(200,223,240,.6)', callback: v => v + '%' },
          grid: { color: 'rgba(255,255,255,.12)' },
        },
      },
      plugins: {
        legend: {
          display: true,
          labels: {
            color: 'rgba(200,223,240,.7)',
            filter: item => !item.text.includes('band') && !item.text.includes('lower') && !item.text.includes('upper'),
          },
        },
        tooltip: {
          callbacks: {
            label: ctx => {
              if (ctx.dataset.label?.includes('band') || ctx.dataset.label?.includes('lower') || ctx.dataset.label?.includes('upper')) return null
              return `${ctx.dataset.label}: ${(ctx.parsed.y || 0).toFixed(1)}%`
            },
          },
          filter: item => !item.dataset.label?.includes('band') && !item.dataset.label?.includes('95'),
        },
      },
    },
  }
})

defineExpose({ fetchPredictions, fetchPredictHealth })
</script>

<template>
  <div>
    <!-- Controls row -->
    <div style="display:flex;flex-wrap:wrap;gap:1rem;margin-bottom:1rem;align-items:flex-start">
      <!-- Metric checkboxes -->
      <div>
        <div style="font-size:.7rem;color:var(--text-dim);margin-bottom:.3rem">Metrics</div>
        <div style="display:flex;gap:.5rem;flex-wrap:wrap">
          <label
            v-for="m in metricOptions"
            :key="m.key"
            style="display:flex;align-items:center;gap:.3rem;font-size:.8rem;cursor:pointer;padding:.25rem .5rem;border:1px solid var(--border);border-radius:4px;background:var(--surface-2)"
            :style="predMetrics.includes(m.key) ? 'border-color:var(--accent);background:var(--accent-dim,rgba(0,200,255,.08))' : ''"
          >
            <input
              type="checkbox"
              :checked="predMetrics.includes(m.key)"
              @change="togglePredMetric(m.key)"
              style="accent-color:var(--accent)"
            >
            {{ m.label }}
          </label>
        </div>
      </div>

      <!-- Range buttons -->
      <div>
        <div style="font-size:.7rem;color:var(--text-dim);margin-bottom:.3rem">History range</div>
        <div style="display:flex;gap:.3rem">
          <button
            v-for="r in rangeOptions"
            :key="r"
            class="btn btn-xs"
            :class="predRange === r ? 'btn-primary' : ''"
            @click="predRange = r; fetchPredictions()"
          >{{ r }}</button>
        </div>
      </div>

      <!-- Projection buttons -->
      <div>
        <div style="font-size:.7rem;color:var(--text-dim);margin-bottom:.3rem">Projection</div>
        <div style="display:flex;gap:.3rem">
          <button
            v-for="p in projectionOptions"
            :key="p"
            class="btn btn-xs"
            :class="predProjection === p ? 'btn-primary' : ''"
            @click="predProjection = p; fetchPredictions()"
          >{{ p }}</button>
        </div>
      </div>

      <!-- Refresh -->
      <div style="align-self:flex-end">
        <button
          class="btn btn-xs btn-secondary"
          :disabled="predLoading"
          @click="fetchPredictions(); fetchPredictHealth()"
        >
          <i class="fas fa-sync-alt" :class="predLoading ? 'fa-spin' : ''"></i> Refresh
        </button>
      </div>
    </div>

    <!-- Full-size chart -->
    <div v-if="predLoading" class="empty-msg">Loading predictions...</div>
    <div v-else-if="predChartConfig" style="position:relative;height:320px;margin-bottom:1.5rem">
      <ChartWrapper :config="predChartConfig" style="width:100%;height:100%" />
    </div>
    <div v-else class="empty-msg" style="margin-bottom:1.5rem">
      No prediction data available. Ensure there is enough history to generate projections.
    </div>

    <!-- Per-service health table -->
    <div>
      <h3 style="font-size:.9rem;font-weight:600;margin-bottom:.6rem">
        <i class="fas fa-heartbeat" style="margin-right:.3rem;color:var(--accent)"></i>
        Service Health Scores
      </h3>

      <div v-if="predHealthLoading" class="empty-msg">Loading health scores...</div>

      <template v-else-if="predHealth && predHealth.services && predHealth.services.length">
        <!-- Overall score summary -->
        <div
          style="display:flex;align-items:center;gap:.75rem;padding:.6rem .8rem;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);margin-bottom:.75rem"
        >
          <span style="font-size:1.3rem;font-weight:700" :style="'color:' + predScoreColor(predHealth.overall)">
            {{ predHealth.overall != null ? predHealth.overall.toFixed(0) : '\u2014' }}
          </span>
          <div>
            <div style="font-size:.8rem;font-weight:600">Overall Health</div>
            <div style="font-size:.7rem;color:var(--text-muted)">
              Grade:
              <span class="badge" :class="predScoreClass(predHealth.overall)" style="font-size:.6rem">
                {{ predHealth.grade || '\u2014' }}
              </span>
            </div>
          </div>
        </div>

        <!-- Service rows -->
        <div style="overflow-x:auto">
          <table style="width:100%;font-size:.78rem;border-collapse:collapse">
            <thead style="position:sticky;top:0;background:var(--surface)">
              <tr style="border-bottom:2px solid var(--border)">
                <th class="td-left">Service</th>
                <th class="td-center">Score</th>
                <th class="td-right">Uptime</th>
                <th class="td-right">Latency</th>
                <th class="td-right">Error rate</th>
                <th class="td-right">Headroom</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="svc in predHealth.services"
                :key="svc.name"
                class="border-b"
              >
                <td class="td-cell" style="font-weight:600">{{ svc.name }}</td>
                <td class="td-center">
                  <span
                    class="badge"
                    :class="predScoreClass(svc.composite_score)"
                    style="font-size:.65rem;min-width:36px;display:inline-block;text-align:center"
                  >{{ svc.composite_score != null ? svc.composite_score.toFixed(0) : '\u2014' }}</span>
                  <span
                    v-if="svc.grade"
                    style="font-size:.65rem;color:var(--text-muted);margin-left:.3rem"
                  >{{ svc.grade }}</span>
                </td>
                <td class="td-right">{{ formatPct(svc.uptime_ratio) }}</td>
                <td class="td-right">{{ formatMs(svc.avg_latency_ms) }}</td>
                <td class="td-right">
                  <span :style="(svc.error_rate || 0) > 0.05 ? 'color:var(--danger)' : ''">
                    {{ formatPct(svc.error_rate) }}
                  </span>
                </td>
                <td class="td-right">
                  <span :style="(svc.headroom || 1) < 0.2 ? 'color:var(--warning)' : ''">
                    {{ formatPct(svc.headroom) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <div v-else class="empty-msg">No service health data available.</div>
    </div>
  </div>
</template>
