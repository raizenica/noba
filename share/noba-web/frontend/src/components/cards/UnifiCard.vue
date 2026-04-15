<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const unifi = computed(() => dashboard.live.unifi)
</script>

<template>
  <DashboardCard title="UniFi Network" icon="fas fa-wifi" card-id="unifi">
    <template #header-actions>
      <span
        class="badge"
        :class="unifi && unifi.status === 'online' ? 'bs' : 'bn'"
        style="margin-left:auto;margin-right:.25rem"
      >{{ unifi ? unifi.status : 'offline' }}</span>
    </template>

    <template v-if="unifi">
      <div class="row">
        <span class="row-label">Devices</span>
        <span class="row-val">{{ (unifi.adopted || 0) }} / {{ (unifi.devices || 0) }}</span>
      </div>
      <div class="row">
        <span class="row-label">Clients</span>
        <span class="row-val">{{ unifi.clients || 0 }}</span>
      </div>
    </template>
    <div v-else class="empty-msg">UniFi data unavailable.</div>
  </DashboardCard>
</template>
