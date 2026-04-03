<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { Chart } from 'chart.js/auto'
import { useHealingStore } from '../../stores/healing'

const store = useHealingStore()

const successChart = ref(null)
const actionChart = ref(null)
const ruleChart = ref(null)

let successInstance = null
let actionInstance = null
let ruleInstance = null

function getCssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function getThemeColors() {
  return {
    success: getCssVar('--success') || '#4caf50',
    danger:  getCssVar('--danger')  || '#f44336',
    warning: getCssVar('--warning') || '#ff9800',
    accent:  getCssVar('--accent')  || '#2196f3',
    border:  getCssVar('--border')  || '#333',
    text:    getCssVar('--text')    || '#eee',
    muted:   getCssVar('--text-muted') || '#888',
  }
}

function buildSuccessChart(eff) {
  if (successInstance) { successInstance.destroy(); successInstance = null }
  if (!successChart.value) return

  const c = getThemeColors()
  const verified = eff.verified_count || 0
  const failed   = eff.failed_count   || 0
  const pending  = eff.pending_count  || 0

  successInstance = new Chart(successChart.value, {
    type: 'doughnut',
    data: {
      labels: ['Verified', 'Failed', 'Pending'],
      datasets: [{
        data: [verified, failed, pending],
        backgroundColor: [c.success, c.danger, c.warning],
        borderColor: c.border,
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: {
          labels: { color: c.text, font: { size: 12 } },
        },
        tooltip: {
          callbacks: {
            label: ctx => {
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0) || 1
              const pct = ((ctx.parsed / total) * 100).toFixed(1)
              return ` ${ctx.label}: ${ctx.parsed} (${pct}%)`
            },
          },
        },
      },
    },
  })
}

function buildActionChart(ledger) {
  if (actionInstance) { actionInstance.destroy(); actionInstance = null }
  if (!actionChart.value) return

  const c = getThemeColors()
  const counts = {}
  for (const e of ledger) {
    if (e.action_type) counts[e.action_type] = (counts[e.action_type] || 0) + 1
  }
  const labels = Object.keys(counts).sort()
  const data   = labels.map(l => counts[l])

  actionInstance = new Chart(actionChart.value, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Actions',
        data,
        backgroundColor: c.accent,
        borderColor: c.border,
        borderWidth: 1,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.y} actions` } },
      },
      scales: {
        x: {
          ticks: { color: c.muted },
          grid:  { color: c.border },
        },
        y: {
          beginAtZero: true,
          ticks: { color: c.muted, precision: 0 },
          grid:  { color: c.border },
        },
      },
    },
  })
}

function buildRuleChart(ledger) {
  if (ruleInstance) { ruleInstance.destroy(); ruleInstance = null }
  if (!ruleChart.value) return

  const c = getThemeColors()

  // Compute per-rule success %
  const ruleMap = {}
  for (const e of ledger) {
    if (!e.rule_id) continue
    if (!ruleMap[e.rule_id]) ruleMap[e.rule_id] = { total: 0, ok: 0 }
    ruleMap[e.rule_id].total++
    const v = e.verification_result ?? e.action_success
    if (v === true || v === 'verified') ruleMap[e.rule_id].ok++
  }

  const labels = Object.keys(ruleMap).sort()
  const data   = labels.map(r => {
    const { total, ok } = ruleMap[r]
    return total ? Math.round((ok / total) * 100) : 0
  })
  const colors = data.map(v => v >= 80 ? c.success : v >= 50 ? c.warning : c.danger)

  ruleInstance = new Chart(ruleChart.value, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Success %',
        data,
        backgroundColor: colors,
        borderColor: c.border,
        borderWidth: 1,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.x}% success` } },
      },
      scales: {
        x: {
          min: 0,
          max: 100,
          ticks: { color: c.muted, callback: v => v + '%' },
          grid:  { color: c.border },
        },
        y: {
          ticks: { color: c.muted },
          grid:  { color: c.border },
        },
      },
    },
  })
}

const hasData = computed(() => {
  const eff = store.effectiveness || {}
  const ledger = store.ledger || []
  if (ledger.length > 0) return true
  if (Array.isArray(eff)) return eff.some(e => (e.total || e.count || 0) > 0)
  return Object.values(eff).some(v => typeof v === 'object' && (v.total || v.count || 0) > 0)
})

function renderAll() {
  buildSuccessChart(store.effectiveness || {})
  buildActionChart(store.ledger || [])
  buildRuleChart(store.ledger || [])
}

onMounted(async () => {
  if (!store.effectiveness || Object.keys(store.effectiveness).length === 0) {
    await store.fetchAll()
  }
  renderAll()
})

// Re-render when data changes (e.g., after background refresh)
watch(
  [() => store.effectiveness, () => store.ledger],
  () => renderAll(),
  { deep: true }
)

onBeforeUnmount(() => {
  successInstance?.destroy()
  actionInstance?.destroy()
  ruleInstance?.destroy()
})
</script>

<template>
  <div v-if="hasData" class="effectiveness-grid">
    <div class="eff-card">
      <h4>Success Rate</h4>
      <canvas ref="successChart" />
    </div>
    <div class="eff-card">
      <h4>Actions by Type</h4>
      <canvas ref="actionChart" />
    </div>
    <div class="eff-card span-full">
      <h4>Per-Rule Effectiveness</h4>
      <canvas ref="ruleChart" />
    </div>
  </div>
  <div v-else style="text-align:center;padding:2rem;color:var(--text-muted)">
    <i class="fas fa-chart-pie" style="font-size:2rem;opacity:.2;display:block;margin-bottom:.75rem"></i>
    No healing data yet — charts will appear once the pipeline processes events.
  </div>
</template>

<style scoped>
.effectiveness-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.eff-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }
.eff-card h4 { margin: 0 0 .75rem; font-size: .9rem; color: var(--text-muted); text-transform: uppercase; }
.eff-card canvas { max-height: 250px; }
.span-full { grid-column: 1 / -1; }
</style>
