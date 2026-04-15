<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi'
import DashboardCard from './DashboardCard.vue'
import ChartWrapper from '../ui/ChartWrapper.vue'

const { get } = useApi()
const capacityData = ref(null)
const loading = ref(true)
const error = ref(null)
let _iv = null

async function fetchCapacity() {
  try {
    error.value = null
    const data = await get('/api/predict/capacity?metrics=disk_percent')
    capacityData.value = data
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function formatRelativeTime(ts) {
  if (!ts) return null
  // ts may be ISO string or unix timestamp
  const targetMs = typeof ts === 'string' ? new Date(ts).getTime() : ts * 1000
  const diff = (targetMs - Date.now()) / 1000
  if (isNaN(diff)) return null
  if (diff <= 0) return 'already full'
  const days = Math.floor(diff / 86400)
  if (days < 1)  return 'less than a day'
  if (days < 7)  return `${days} day${days !== 1 ? 's' : ''}`
  const weeks = Math.floor(days / 7)
  if (weeks < 5) return `${weeks} week${weeks !== 1 ? 's' : ''}`
  const months = Math.floor(days / 30)
  return `${months} month${months !== 1 ? 's' : ''}`
}

function formatAbsDate(ts) {
  if (!ts) return ''
  const d = typeof ts === 'string' ? new Date(ts) : new Date(ts * 1000)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

const combined = computed(() => capacityData.value?.combined || null)

const fullAtRelative = computed(() => {
  const c = combined.value
  if (!c || !c.full_at) return null
  return formatRelativeTime(c.full_at)
})

const fullAtAbsolute = computed(() => {
  const c = combined.value
  if (!c || !c.full_at) return null
  return formatAbsDate(c.full_at)
})

const confidenceBadgeClass = computed(() => {
  const c = combined.value?.confidence
  if (c === 'high')   return 'bs'
  if (c === 'medium') return 'bw'
  return 'bd'
})

const confidenceReason = computed(() => {
  const c = combined.value
  if (!c) return ''
  const r2 = c.r_squared ?? 0
  const slope = c.slope_per_day ?? 0
  if (r2 < 0.5) {
    return `Low correlation (R²=${r2.toFixed(2)}) — usage pattern is irregular`
  }
  if (Math.abs(slope) < 0.001) {
    return 'Minimal growth detected — projection may not be meaningful'
  }
  return 'Sufficient data for projection'
})

const slopePerDay = computed(() => {
  const s = combined.value?.slope_per_day
  if (s == null) return null
  return s.toFixed(3)
})

// Build projection points array from first metric's projection
const projectionPoints = computed(() => {
  const metrics = capacityData.value?.metrics
  if (!metrics) return []
  const first = Object.values(metrics)[0]
  const proj = first?.projection
  return Array.isArray(proj) ? proj : []
})

const chartConfig = computed(() => {
  const points = projectionPoints.value
  if (!points.length) return null
  return {
    type: 'line',
    data: {
      labels: points.map(p => new Date(p.time * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })),
      datasets: [
        {
          label: 'Predicted',
          data: points.map(p => p.predicted),
          borderColor: 'var(--accent)',
          borderWidth: 3,
          pointRadius: 0,
          fill: false,
        },
        {
          label: '68% Upper',
          data: points.map(p => p.upper_68),
          borderColor: 'transparent',
          backgroundColor: 'rgba(0,200,255,0.18)',
          pointRadius: 0,
          fill: '+1',
        },
        {
          label: '68% Lower',
          data: points.map(p => p.lower_68),
          borderColor: 'transparent',
          pointRadius: 0,
          fill: false,
        },
        {
          label: '95% Upper',
          data: points.map(p => p.upper_95),
          borderDash: [5, 5],
          borderColor: 'rgba(0,200,255,0.5)',
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
        },
        {
          label: '95% Lower',
          data: points.map(p => p.lower_95),
          borderDash: [5, 5],
          borderColor: 'rgba(0,200,255,0.5)',
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      scales: {
        x: {
          type: 'category',
          ticks: { color: 'rgba(200,223,240,.6)', maxTicksLimit: 6 },
          grid: { display: false },
        },
        y: {
          min: 0,
          max: 100,
          ticks: {
            color: 'rgba(200,223,240,.6)',
            callback: v => v + '%',
          },
          grid: { color: 'rgba(255,255,255,.12)' },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: ${(ctx.parsed.y || 0).toFixed(1)}%`,
          },
        },
      },
    },
  }
})

onMounted(() => {
  fetchCapacity()
  _iv = setInterval(fetchCapacity, 5 * 60 * 1000)
})

onUnmounted(() => {
  if (_iv) clearInterval(_iv)
})
</script>

<template>
  <DashboardCard title="Capacity Forecast" icon="fas fa-chart-line" card-id="prediction">
    <template v-if="loading">
      <div class="empty-msg">Loading...</div>
    </template>

    <template v-else-if="error">
      <div class="empty-msg" style="color:var(--danger)">{{ error }}</div>
    </template>

    <template v-else-if="capacityData">
      <!-- Full-at row -->
      <div class="row" style="align-items:flex-start;gap:.4rem;flex-wrap:wrap">
        <span class="row-label">Full at</span>
        <span class="row-val" style="display:flex;flex-direction:column;align-items:flex-end;gap:.1rem">
          <template v-if="fullAtRelative">
            <span style="font-weight:600">{{ fullAtRelative }}</span>
            <span style="font-size:.68rem;color:var(--text-muted)">{{ fullAtAbsolute }}</span>
          </template>
          <span v-else style="color:var(--success);font-size:.8rem">No capacity issue detected</span>
        </span>
      </div>

      <!-- Confidence + slope -->
      <div class="row">
        <span class="row-label">Confidence</span>
        <span class="row-val">
          <span
            class="badge"
            :class="confidenceBadgeClass"
            style="text-transform:capitalize"
            :title="confidenceReason"
          >{{ combined?.confidence || 'n/a' }}</span>
        </span>
      </div>

      <div v-if="slopePerDay != null" class="row">
        <span class="row-label">Growth rate</span>
        <span class="row-val">{{ slopePerDay }}%/day</span>
      </div>

      <!-- Mini chart -->
      <div
        v-if="chartConfig"
        style="margin-top:.6rem;height:110px;position:relative"
      >
        <ChartWrapper :config="chartConfig" />
      </div>
    </template>

    <template v-else>
      <div class="empty-msg">No prediction data available.</div>
    </template>
  </DashboardCard>
</template>
