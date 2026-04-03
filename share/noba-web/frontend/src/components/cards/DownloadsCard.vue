<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const qbit   = computed(() => dashboard.live.qbit)
const radarr = computed(() => dashboard.live.radarr)
const sonarr = computed(() => dashboard.live.sonarr)

function humanBps(bps) {
  if (!bps) return '0 B/s'
  if (bps < 1024) return bps + ' B/s'
  if (bps < 1048576) return (bps / 1024).toFixed(1) + ' KB/s'
  return (bps / 1048576).toFixed(1) + ' MB/s'
}
</script>

<template>
  <DashboardCard title="Download Stack" icon="fas fa-download" card-id="downloads">
    <!-- qBittorrent section -->
    <div style="margin-bottom:1rem">
      <div class="row" style="border-bottom:none;padding-bottom:0">
        <span class="row-label" style="color:var(--text)">qBittorrent</span>
        <span
          class="badge"
          :class="qbit && qbit.status === 'online' ? 'bs' : 'bn'"
        >{{ qbit ? (qbit.status || 'offline').toUpperCase() : 'OFFLINE' }}</span>
      </div>
      <div v-if="qbit && qbit.status === 'online'" class="io-grid" style="margin-top:.5rem">
        <div class="io-stat">
          <div class="io-val io-down">{{ humanBps(qbit.dl_speed) }}</div>
          <div class="io-label"><i class="fas fa-arrow-down" aria-hidden="true"></i> DL</div>
        </div>
        <div class="io-stat">
          <div class="io-val io-up">{{ humanBps(qbit.up_speed) }}</div>
          <div class="io-label"><i class="fas fa-arrow-up" aria-hidden="true"></i> UP</div>
        </div>
      </div>
      <div v-if="qbit && qbit.status === 'online'" class="row">
        <span class="row-label" style="font-size:.65rem">Active Torrents</span>
        <span class="row-val">{{ qbit.active_torrents }}</span>
      </div>
    </div>

    <!-- Radarr -->
    <div class="row">
      <span class="row-label" style="color:var(--text)">Radarr Queue</span>
      <span class="row-val">{{ radarr && radarr.status === 'online' ? radarr.queue_count : '--' }}</span>
    </div>

    <!-- Sonarr -->
    <div class="row">
      <span class="row-label" style="color:var(--text)">Sonarr Queue</span>
      <span class="row-val">{{ sonarr && sonarr.status === 'online' ? sonarr.queue_count : '--' }}</span>
    </div>
  </DashboardCard>
</template>
