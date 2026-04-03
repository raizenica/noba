<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const readarr = computed(() => dashboard.live.readarr)
</script>

<template>
  <DashboardCard title="Readarr" icon="fas fa-book" card-id="readarr">
    <template v-if="readarr">
      <div class="row">
        <span class="row-label">Status</span>
        <span class="badge" :class="readarr.status === 'online' ? 'bs' : 'bd'">{{ readarr.status }}</span>
      </div>
      <div class="row">
        <span class="row-label">Queue</span>
        <span class="row-val">{{ readarr.queue_count || 0 }}</span>
      </div>
    </template>
    <div v-else class="empty-msg">Readarr unreachable.</div>
  </DashboardCard>
</template>
