<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const vpn = computed(() => dashboard.live.vpn)
</script>

<template>
  <DashboardCard title="VPN" icon="fas fa-shield-alt" card-id="vpn">
    <template v-if="vpn">
      <div class="row">
        <span class="row-label">Status</span>
        <span class="badge" :class="vpn.status === 'online' ? 'bs' : 'bd'">{{ vpn.status }}</span>
      </div>
      <div class="row">
        <span class="row-label">Peers</span>
        <span class="row-val">{{ vpn.peers || 0 }}</span>
      </div>
    </template>
    <div v-else class="empty-msg">VPN data unavailable.</div>
  </DashboardCard>
</template>
