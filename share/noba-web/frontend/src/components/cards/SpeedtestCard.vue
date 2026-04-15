<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const speedtest = computed(() => dashboard.live.speedtest)
</script>

<template>
  <DashboardCard title="Speedtest" icon="fas fa-tachometer-alt" card-id="speedtest">
    <template #header-actions>
      <span
        class="badge"
        :class="speedtest && speedtest.status === 'online' ? 'bs' : 'bn'"
        style="margin-left:auto;margin-right:.25rem"
      >{{ speedtest ? speedtest.status : 'offline' }}</span>
    </template>

    <template v-if="speedtest">
      <div class="row">
        <span class="row-label">Download</span>
        <span class="row-val">{{ (speedtest.download || 0) }} Mbps</span>
      </div>
      <div class="row">
        <span class="row-label">Upload</span>
        <span class="row-val">{{ (speedtest.upload || 0) }} Mbps</span>
      </div>
      <div class="row">
        <span class="row-label">Ping</span>
        <span class="row-val">{{ (speedtest.ping || 0) }} ms</span>
      </div>
      <div v-if="speedtest.server" class="row">
        <span class="row-label">Server</span>
        <span class="row-val">{{ speedtest.server }}</span>
      </div>
    </template>
    <div v-else class="empty-msg">Speedtest data unavailable.</div>
  </DashboardCard>
</template>
