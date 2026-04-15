<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()

const battery = computed(() => dashboard.live.battery || null)

const statusClass = computed(() => {
  const s = battery.value?.status
  if (s === 'Charging' || s === 'Full') return 'bs'
  if (s === 'Discharging') return 'bw'
  return 'bn'
})

const chargeClass = computed(() => {
  const p = battery.value?.percent || 0
  return p > 20 ? 'f-success' : 'f-danger'
})
</script>

<template>
  <DashboardCard
    v-if="battery && !battery.desktop"
    title="Power State"
    icon="fas fa-battery-half"
    card-id="battery"
  >
    <div class="row">
      <span class="row-label">Status</span>
      <span class="badge" :class="statusClass">{{ battery.status }}</span>
    </div>
    <div v-if="battery.timeRemaining" class="row">
      <span class="row-label">Remaining</span>
      <span class="row-val">{{ battery.timeRemaining }}</span>
    </div>
    <div class="prog" style="margin-top:.75rem">
      <div class="prog-meta">
        <span>CHARGE</span>
        <span>{{ battery.percent }}%</span>
      </div>
      <div
        class="prog-track"
        role="progressbar"
        :aria-valuenow="battery.percent"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-label="'Battery charge ' + battery.percent + '%'"
      >
        <div
          class="prog-fill"
          :class="chargeClass"
          :style="'width:' + battery.percent + '%'"
        ></div>
      </div>
    </div>
  </DashboardCard>
</template>
