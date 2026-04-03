<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const bazarr = computed(() => dashboard.live.bazarr)
</script>

<template>
  <DashboardCard title="Bazarr" icon="fas fa-closed-captioning" card-id="bazarr">
    <template v-if="bazarr">
      <div class="row">
        <span class="row-label">Status</span>
        <span class="badge" :class="bazarr.status === 'online' ? 'bs' : 'bd'">{{ bazarr.status }}</span>
      </div>
      <div class="row">
        <span class="row-label">Queue</span>
        <span class="row-val">{{ bazarr.queue_count || 0 }}</span>
      </div>
    </template>
    <div v-else class="empty-msg">Bazarr unreachable.</div>
  </DashboardCard>
</template>
