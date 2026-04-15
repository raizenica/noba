<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const plex = computed(() => dashboard.live.plex)
</script>

<template>
  <DashboardCard title="Media Stack" icon="fas fa-film" card-id="plex">
    <template v-if="plex">
      <div class="row">
        <span class="row-label">Server Status</span>
        <span class="badge" :class="plex.status === 'online' ? 'bs' : 'bd'">{{ plex.status }}</span>
      </div>
      <div class="ph-stats" style="margin-top:.875rem">
        <div class="ph-stat">
          <div class="ph-val" style="color:var(--accent)">{{ plex.sessions }}</div>
          <div class="ph-label">Active Streams</div>
        </div>
        <div class="ph-stat">
          <div class="ph-val" style="color:var(--warning)">{{ plex.activities }}</div>
          <div class="ph-label">Background Tasks</div>
        </div>
      </div>
      <div v-if="plex.activities > 0" class="empty-msg" style="color:var(--warning)">
        High activity: Metadata scanning in progress.
      </div>
      <div
        v-if="plex.now_playing && plex.now_playing.length > 0"
        style="margin-top:.75rem;border-top:1px solid var(--border);padding-top:.5rem"
      >
        <div style="font-size:.7rem;color:var(--text-dim);margin-bottom:.3rem">Now Playing</div>
        <div
          v-for="np in plex.now_playing"
          :key="np.title"
          class="row"
          style="font-size:.8rem"
        >
          <span class="row-label" style="color:var(--accent)">{{ np.user }}</span>
          <span class="row-val" style="flex:1;text-align:right">{{ np.title }}</span>
        </div>
      </div>
    </template>
    <div v-else class="empty-msg">Media stack unreachable — <router-link to="/settings?tab=integrations" class="empty-link">configure in Settings</router-link>.</div>
  </DashboardCard>
</template>
