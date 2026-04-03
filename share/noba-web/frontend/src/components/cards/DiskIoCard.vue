<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()

const diskIo = computed(() => dashboard.live.diskIo || [])
</script>

<template>
  <DashboardCard title="Disk I/O" icon="fas fa-hdd" card-id="diskio">
    <template v-if="diskIo.length > 0">
      <div
        v-for="d in diskIo"
        :key="d.device"
        class="row"
      >
        <span class="row-label">{{ d.device }}</span>
        <span class="row-val" style="font-size:.72rem">
          <i class="fas fa-arrow-down" style="color:var(--accent);font-size:.6rem" aria-hidden="true"></i>
          {{ ((d.read_bps || 0) / 1024 / 1024).toFixed(1) }} MB/s
          <i class="fas fa-arrow-up" style="color:var(--warning);font-size:.6rem;margin-left:.4rem" aria-hidden="true"></i>
          {{ ((d.write_bps || 0) / 1024 / 1024).toFixed(1) }} MB/s
        </span>
      </div>
    </template>
    <div v-else class="empty-msg">No disk I/O data.</div>
  </DashboardCard>
</template>
