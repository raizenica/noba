<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const expanded = ref(false)

const scrutiny = computed(() => dashboard.live.scrutiny || null)

const health = computed(() => {
  const s = scrutiny.value
  if (!s) return ''
  if (s.failed > 0) return 'fail'
  if (s.warn > 0) return 'warn'
  return 'ok'
})

const deviceList = computed(() => scrutiny.value?.device_list || [])
const diskSummary = computed(() => {
  const s = scrutiny.value
  if (!s) return ''
  const parts = [`${s.devices || 0} drives`]
  if (s.healthy) parts.push(`${s.healthy} healthy`)
  if (s.warn) parts.push(`${s.warn} warning`)
  if (s.failed) parts.push(`${s.failed} failed`)
  return parts.join(', ')
})
</script>

<template>
  <DashboardCard title="Disk Health" icon="fas fa-hdd" card-id="scrutiny" :health="health">
    <template v-if="scrutiny">
      <div class="row">
        <span class="row-label">Disks</span>
        <span class="row-val">{{ scrutiny.devices }}</span>
      </div>
      <div class="row">
        <span class="row-label">Healthy</span>
        <span class="row-val" style="color:var(--success)">{{ scrutiny.healthy }}</span>
      </div>
      <div v-if="(scrutiny.warn || 0) > 0" class="row">
        <span class="row-label">Warning</span>
        <span class="row-val" style="color:var(--warning)">{{ scrutiny.warn }}</span>
      </div>
      <div v-if="(scrutiny.failed || 0) > 0" class="row">
        <span class="row-label">Failed</span>
        <span class="row-val" style="color:var(--danger)">{{ scrutiny.failed }}</span>
      </div>
      <div class="row">
        <span class="row-label">Total Capacity</span>
        <span class="row-val">{{ ((scrutiny.totalCapacityBytes || 0) / 1e12).toFixed(1) }} TB</span>
      </div>
      <div class="row">
        <span class="row-label">Max Temp</span>
        <span
          class="row-val"
          :style="(scrutiny.maxTemp || 0) > 50 ? 'color:var(--danger)' : ''"
        >{{ (scrutiny.maxTemp || 0) }}°C</span>
      </div>

      <div v-if="deviceList.length > 0" style="margin-top:.6rem">
        <button
          class="btn btn-xs"
          style="width:100%;justify-content:center;font-size:.65rem;padding:.25rem;opacity:.7"
          @click="expanded = !expanded"
        >
          <i class="fas" :class="expanded ? 'fa-chevron-up' : 'fa-chevron-down'" style="margin-right:4px"></i>
          {{ expanded ? 'Hide' : 'Show' }} {{ deviceList.length }} drives
        </button>
        <div v-if="expanded" style="max-height:200px;overflow-y:auto;margin-top:.4rem">
          <div
            v-for="d in deviceList"
            :key="d.serial || d.name"
            class="row"
            style="font-size:.75rem"
          >
            <span class="row-label">
              <i
                class="fas fa-circle"
                style="font-size:.4rem;margin-right:4px"
                :style="d.status === 0 ? 'color:var(--success)' : d.status === 1 ? 'color:var(--warning)' : 'color:var(--danger)'"
                aria-hidden="true"
              ></i>
              /dev/{{ d.name }}
            </span>
            <span class="row-val" style="font-size:.65rem;opacity:.8">
              {{ d.model }}{{ d.temperature ? ' · ' + d.temperature + '°C' : '' }}
            </span>
          </div>
        </div>
      </div>
    </template>
    <div v-else class="empty-msg">Scrutiny unreachable — <router-link to="/settings?tab=integrations" class="empty-link">configure in Settings</router-link>.</div>
  </DashboardCard>
</template>
