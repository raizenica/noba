<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const jellyfin = computed(() => dashboard.live.jellyfin)
</script>

<template>
  <DashboardCard title="Jellyfin" icon="fas fa-film" card-id="jellyfin">
    <template #header-actions>
      <span
        class="badge"
        :class="jellyfin && jellyfin.status === 'online' ? 'bs' : 'bn'"
        style="margin-left:auto;margin-right:.25rem"
      >{{ jellyfin ? jellyfin.status : 'offline' }}</span>
    </template>

    <template v-if="jellyfin">
      <div class="row">
        <span class="row-label">Active Streams</span>
        <span class="row-val">{{ jellyfin.streams || 0 }}</span>
      </div>
      <div class="row">
        <span class="row-label">Movies</span>
        <span class="row-val">{{ (jellyfin.movies || 0).toLocaleString() }}</span>
      </div>
      <div class="row">
        <span class="row-label">Series</span>
        <span class="row-val">{{ jellyfin.series || 0 }}</span>
      </div>
      <div class="row">
        <span class="row-label">Episodes</span>
        <span class="row-val">{{ (jellyfin.episodes || 0).toLocaleString() }}</span>
      </div>
      <div
        v-if="jellyfin.now_playing && jellyfin.now_playing.length > 0"
        style="margin-top:.75rem;border-top:1px solid var(--border);padding-top:.5rem"
      >
        <div style="font-size:.7rem;color:var(--text-dim);margin-bottom:.3rem">Now Playing</div>
        <div
          v-for="np in jellyfin.now_playing"
          :key="np.title"
          class="row"
          style="font-size:.8rem"
        >
          <span class="row-label" style="color:var(--accent)">{{ np.user }}</span>
          <span class="row-val" style="flex:1;text-align:right">{{ np.title }}</span>
        </div>
      </div>
    </template>
    <div v-else class="empty-msg">Jellyfin data unavailable.</div>
  </DashboardCard>
</template>
