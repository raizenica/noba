<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const adguard = computed(() => dashboard.live.adguard)
</script>

<template>
  <DashboardCard title="AdGuard Home" icon="fas fa-shield-alt" card-id="adguard">
    <template #header-actions>
      <span
        class="badge"
        :class="adguard && adguard.status === 'enabled' ? 'bs' : 'bn'"
        style="margin-left:auto;margin-right:.25rem"
      >{{ adguard ? adguard.status : 'offline' }}</span>
    </template>

    <template v-if="adguard">
      <div class="row">
        <span class="row-label">DNS Queries</span>
        <span class="row-val">{{ (adguard.queries || 0).toLocaleString() }}</span>
      </div>
      <div class="row">
        <span class="row-label">Blocked</span>
        <span class="row-val">{{ (adguard.blocked || 0).toLocaleString() }}</span>
      </div>
      <div class="row">
        <span class="row-label">Block Rate</span>
        <span class="row-val">{{ (adguard.percent || 0) }}%</span>
      </div>
    </template>
    <div v-else class="empty-msg">AdGuard data unavailable.</div>
  </DashboardCard>
</template>
