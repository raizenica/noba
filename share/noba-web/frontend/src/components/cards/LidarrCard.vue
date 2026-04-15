<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const lidarr = computed(() => dashboard.live.lidarr)
</script>

<template>
  <DashboardCard title="Lidarr" icon="fas fa-music" card-id="lidarr">
    <template v-if="lidarr">
      <div class="row">
        <span class="row-label">Status</span>
        <span class="badge" :class="lidarr.status === 'online' ? 'bs' : 'bd'">{{ lidarr.status }}</span>
      </div>
      <div class="row">
        <span class="row-label">Queue</span>
        <span class="row-val">{{ lidarr.queue_count || 0 }}</span>
      </div>
    </template>
    <div v-else class="empty-msg">Lidarr unreachable.</div>
  </DashboardCard>
</template>
