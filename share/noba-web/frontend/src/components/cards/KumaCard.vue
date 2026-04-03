<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const kuma = computed(() => dashboard.live.kuma)
const monitors = computed(() => Array.isArray(kuma.value) ? kuma.value : [])
</script>

<template>
  <DashboardCard title="Uptime Kuma" icon="fas fa-heartbeat" card-id="kuma">
    <div v-if="monitors.length > 0" class="ct-list">
      <div
        v-for="m in monitors"
        :key="m.name"
        class="radar-row"
      >
        <div
          class="status-dot"
          :class="m.status === 'Up' ? 'dot-up' : m.status === 'Pending' ? 'dot-pending' : 'dot-down'"
          :aria-label="m.status"
        ></div>
        <span class="radar-ip">{{ m.name }}</span>
        <span class="badge" :class="m.status === 'Up' ? 'bs' : m.status === 'Pending' ? 'bw' : 'bd'">{{ m.status }}</span>
      </div>
    </div>
    <div v-else class="empty-msg">No Kuma monitors active or reachable.</div>
  </DashboardCard>
</template>
