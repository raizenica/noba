<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()

const radar = computed(() => dashboard.live.radar || [])
</script>

<template>
  <DashboardCard title="Network Radar" icon="fas fa-satellite-dish" card-id="radar">
    <template v-if="radar.length > 0">
      <div
        v-for="t in radar"
        :key="t.ip"
        class="radar-row"
      >
        <div
          class="status-dot"
          :class="t.status === 'Up' ? 'dot-up' : t.status === 'Pending' ? 'dot-pending' : 'dot-down'"
          :aria-label="t.status"
        ></div>
        <span class="radar-ip">{{ t.ip }}</span>
        <span
          class="badge"
          :class="t.status === 'Up' ? 'bs' : t.status === 'Pending' ? 'bw' : 'bd'"
        >{{ t.status }}</span>
        <span v-if="t.status === 'Up' && t.ms > 0" class="radar-ms">{{ t.ms }}ms</span>
      </div>
    </template>
    <div v-else class="empty-msg">No radar IPs configured.</div>
  </DashboardCard>
</template>
