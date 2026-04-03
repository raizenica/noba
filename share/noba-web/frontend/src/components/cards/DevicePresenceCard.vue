<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()

const devicePresence = computed(() => dashboard.live.devicePresence || [])
</script>

<template>
  <DashboardCard title="Device Presence" icon="fas fa-mobile-alt" card-id="device-presence">
    <template v-if="devicePresence.length > 0">
      <div
        v-for="d in devicePresence"
        :key="d.ip"
        class="row"
      >
        <span class="row-label">{{ d.name || d.ip }}</span>
        <span class="badge" :class="d.status === 'online' ? 'bs' : 'bd'">{{ d.status }}</span>
        <span
          v-if="d.ms > 0"
          class="row-val"
          style="margin-left:auto;font-size:.75rem;color:var(--text-dim)"
        >{{ d.ms }}ms</span>
      </div>
    </template>
    <div v-else class="empty-msg">No devices configured.</div>
  </DashboardCard>
</template>
