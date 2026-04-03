<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'

const dashboardStore = useDashboardStore()
const tailscale = computed(() => dashboardStore.live.tailscale)
</script>

<template>
  <div>
    <template v-if="tailscale">
      <div class="row" style="margin-bottom:.8rem">
        <span class="row-label">Tailnet</span>
        <span class="row-val">{{ tailscale.tailnet }}</span>
      </div>
      <div class="row" style="margin-bottom:.8rem">
        <span class="row-label">This Node</span>
        <span class="row-val">{{ (tailscale.self?.hostname || '') + ' (' + (tailscale.self?.ip || '') + ')' }}</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.6rem">
        <div
          v-for="p in [...(tailscale.peers || [])].sort((a, b) => (b.online ? 1 : 0) - (a.online ? 1 : 0))"
          :key="p.hostname + '-' + (p.ip || '')"
          style="padding:.6rem;border-radius:6px;border:1px solid var(--border);background:var(--surface-2)"
        >
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.3rem">
            <span style="font-weight:600;font-size:.85rem">{{ p.hostname }}</span>
            <span :class="p.online ? 'dot-up' : 'dot-down'" style="font-size:.5rem">&#9679;</span>
          </div>
          <div style="font-size:.7rem;color:var(--text-muted)">
            <div>{{ p.ip }}</div>
            <div>{{ p.os }}</div>
            <div v-if="p.online && p.curAddr">{{ p.direct ? 'Direct' : 'Relay' }}: {{ p.curAddr }}</div>
            <div v-if="p.subnets && p.subnets.length">Routes: {{ p.subnets.join(', ') }}</div>
            <div v-if="!p.online && p.lastSeen">Last seen: {{ new Date(p.lastSeen).toLocaleDateString() }}</div>
          </div>
        </div>
      </div>
    </template>
    <div v-else class="empty-msg">Tailscale not available</div>
  </div>
</template>
