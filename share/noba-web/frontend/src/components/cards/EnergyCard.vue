<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const energy = computed(() => dashboard.live.energy || [])
</script>

<template>
  <DashboardCard title="Energy" icon="fas fa-bolt" card-id="energy">
    <div
      v-for="e in energy"
      :key="e.name"
      class="row"
      style="flex-wrap:wrap"
    >
      <span class="row-label" style="min-width:80px">{{ e.name }}</span>
      <template v-if="e.status === 'online'">
        <span style="display:flex;gap:12px;font-size:.8rem">
          <span><strong>{{ e.power_w }}</strong> W</span>
          <span v-if="e.voltage_v > 0" style="color:var(--text-muted)">{{ e.voltage_v }} V</span>
          <span class="badge" :class="e.on ? 'bs' : 'bn'" style="font-size:.65rem">{{ e.on ? 'ON' : 'OFF' }}</span>
        </span>
      </template>
      <template v-else>
        <span class="badge bd">offline</span>
      </template>
    </div>
    <div v-if="energy.length === 0" class="empty-msg">No energy data available.</div>
  </DashboardCard>
</template>
