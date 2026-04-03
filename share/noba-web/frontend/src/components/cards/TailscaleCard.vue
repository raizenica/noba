<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const tailscale = computed(() => dashboard.live.tailscale)
const onlinePeers = computed(() =>
  (tailscale.value?.peers || []).filter(n => n.online).slice(0, 8)
)
</script>

<template>
  <DashboardCard
    title="Tailscale"
    icon="fas fa-network-wired"
    card-id="tailscale"
    :health="tailscale && tailscale.onlineCount === tailscale.totalCount ? 'ok' : tailscale ? 'warn' : ''"
  >
    <template v-if="tailscale">
      <div class="row">
        <span class="row-label">Tailnet</span>
        <span class="row-val">{{ tailscale.tailnet || '—' }}</span>
      </div>
      <div class="row">
        <span class="row-label">Nodes Online</span>
        <span class="row-val" style="color:var(--success)">
          {{ (tailscale.onlineCount || 0) }}/{{ (tailscale.totalCount || 0) }}
        </span>
      </div>
      <div style="margin-top:.5rem;max-height:150px;overflow-y:auto">
        <div
          v-for="p in onlinePeers"
          :key="p.hostname + '-' + (p.ip || '')"
          class="row"
          style="font-size:.75rem"
        >
          <span class="row-label">
            <i class="fas fa-circle dot-up" style="font-size:.35rem;margin-right:4px"></i>
            {{ p.hostname }}
          </span>
          <span class="row-val" style="opacity:.7">{{ p.ip }}</span>
        </div>
      </div>
    </template>
    <div v-else class="empty-msg">Tailscale data unavailable.</div>
  </DashboardCard>
</template>
