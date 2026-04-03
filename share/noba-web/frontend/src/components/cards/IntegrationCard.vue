<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<template>
  <DashboardCard :title="instance.id" :icon="template.icon || 'fas fa-plug'" :health="health">
    <div v-if="!data || !Object.keys(data).length" class="empty-msg">No data available</div>
    <template v-else>
      <template v-for="metric in template.metrics" :key="metric.key">
        <!-- VM / container list (full-width, breaks out of row layout) -->
        <div v-if="metric.type === 'vm_list'" class="ic-vm-list">
          <div
            v-for="vm in (data[metric.key] || [])"
            :key="vm.vmid || vm.name"
            class="ic-vm-row"
          >
            <span
              class="status-dot"
              :class="vm.status === 'running' ? 'dot-up' : 'dot-down'"
              aria-hidden="true"
            />
            <span class="ic-vm-name">{{ vm.name }}</span>
            <span class="ic-vm-type">{{ vm.type }}</span>
            <span class="ic-vm-cpu" v-if="vm.cpu != null">{{ vm.cpu }}%</span>
          </div>
          <div v-if="!(data[metric.key] || []).length" class="ic-vm-empty">No guests</div>
        </div>

        <!-- All other metrics: standard row -->
        <div v-else class="row">
          <span class="row-label">{{ metric.label }}</span>

          <!-- Status badge -->
          <span v-if="metric.type === 'status'" class="row-val">
            <span :class="['badge', statusClass(data[metric.key])]">
              {{ data[metric.key] || 'unknown' }}
            </span>
          </span>

          <!-- Percent bar -->
          <span v-else-if="metric.type === 'percent_bar'" class="row-val">
            <div class="prog" style="flex:1">
              <div class="prog-track" :style="{ width: Math.min(data[metric.key]||0, 100) + '%',
                background: percentColor(data[metric.key]||0) }" />
            </div>
            <span class="prog-meta">{{ data[metric.key]||0 }}%</span>
          </span>

          <!-- Temperature -->
          <span v-else-if="metric.type === 'temperature'" class="row-val"
            :style="{ color: tempColor(data[metric.key]) }">
            {{ data[metric.key] != null ? data[metric.key] + '°C' : '—' }}
          </span>

          <!-- Age (time since) -->
          <span v-else-if="metric.type === 'age'" class="row-val">
            {{ formatAge(data[metric.key]) }}
          </span>

          <!-- Number -->
          <span v-else-if="metric.type === 'number'" class="row-val">
            {{ data[metric.key] != null ? data[metric.key] : '—' }}
          </span>

          <!-- Bytes -->
          <span v-else-if="metric.type === 'bytes'" class="row-val">
            {{ formatBytes(data[metric.key]) }}
          </span>

          <!-- Default -->
          <span v-else class="row-val">{{ data[metric.key] ?? '—' }}</span>
        </div>
      </template>

      <!-- Site badge -->
      <div v-if="instance.site" class="row">
        <span class="row-label">Site</span>
        <span class="row-val"><span class="badge ba">{{ instance.site }}</span></span>
      </div>

      <!-- Health status -->
      <div v-if="instance.health_status && instance.health_status !== 'unknown'" class="row">
        <span class="row-label">Status</span>
        <span class="row-val">
          <span :class="['badge', statusClass(instance.health_status)]">{{ instance.health_status }}</span>
        </span>
      </div>
    </template>
  </DashboardCard>
</template>

<script setup>
import { computed } from 'vue'
import DashboardCard from './DashboardCard.vue'

const props = defineProps({
  instance: { type: Object, required: true },   // {id, category, platform, site, health_status, ...}
  template: { type: Object, required: true },    // {icon, metrics: [{key, label, type}]}
  data: { type: Object, default: () => ({}) },   // live metrics from collector
})

const health = computed(() => {
  const s = props.instance.health_status
  if (s === 'online') return 'ok'
  if (s === 'degraded') return 'warn'
  if (s === 'offline') return 'fail'
  return undefined
})

function statusClass(val) {
  if (!val) return 'ba'
  const v = String(val).toLowerCase()
  if (['online', 'healthy', 'ok', 'active', 'running'].includes(v)) return 'bs'
  if (['degraded', 'warning', 'slow'].includes(v)) return 'bw'
  if (['offline', 'error', 'failed', 'down', 'faulted'].includes(v)) return 'bd'
  return 'ba'
}

function percentColor(val) {
  if (val >= 90) return 'var(--danger)'
  if (val >= 75) return 'var(--warning)'
  return 'var(--accent)'
}

function tempColor(val) {
  if (val == null) return 'var(--text-muted)'
  if (val >= 80) return 'var(--danger)'
  if (val >= 60) return 'var(--warning)'
  return 'var(--success)'
}

function formatAge(val) {
  if (!val) return '—'
  const hours = typeof val === 'number' ? val : 0
  if (hours < 1) return 'just now'
  if (hours < 24) return `${Math.round(hours)}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function formatBytes(val) {
  if (val == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = val
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${units[i]}`
}
</script>

<style scoped>
.ic-vm-list { display: flex; flex-direction: column; gap: .2rem; margin: .25rem 0; }
.ic-vm-row  { display: flex; align-items: center; gap: .4rem; font-size: .75rem; }
.ic-vm-name { flex: 1; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ic-vm-type { font-size: .65rem; color: var(--text-muted); background: var(--surface); padding: .1rem .3rem; border-radius: 3px; }
.ic-vm-cpu  { font-size: .65rem; color: var(--text-muted); min-width: 2.5rem; text-align: right; }
.ic-vm-empty { font-size: .75rem; color: var(--text-muted); padding: .2rem 0; }
</style>
