<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const frigate = computed(() => dashboard.live.frigate)
</script>

<template>
  <DashboardCard
    title="Cameras"
    icon="fas fa-video"
    card-id="frigate"
    :health="frigate ? (frigate.onlineCount === frigate.cameraCount ? 'ok' : 'fail') : ''"
  >
    <template v-if="frigate">
      <div class="row">
        <span class="row-label">Cameras</span>
        <span class="row-val">{{ (frigate.onlineCount || 0) }}/{{ (frigate.cameraCount || 0) }} online</span>
      </div>
      <div v-if="frigate.version" class="row">
        <span class="row-label">Version</span>
        <span class="row-val">{{ frigate.version }}</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:.4rem;margin-top:.5rem">
        <div
          v-for="cam in (frigate.cameras || [])"
          :key="cam.name"
          style="position:relative;border-radius:4px;overflow:hidden;border:1px solid var(--border)"
        >
          <img
            :src="'/api/cameras/snapshot/' + cam.name"
            loading="lazy"
            :alt="cam.name"
            style="width:100%;aspect-ratio:16/9;object-fit:cover;display:block"
            @error="$event.target.style.display='none'"
          >
          <div style="padding:.2rem .4rem;font-size:.65rem;display:flex;justify-content:space-between;background:var(--surface-2)">
            <span>{{ cam.name }}</span>
            <span :class="cam.status === 'online' ? 'dot-up' : 'dot-down'" style="font-size:.4rem">&#9679;</span>
          </div>
        </div>
      </div>
    </template>
    <div v-else class="empty-msg">Frigate data unavailable.</div>
  </DashboardCard>
</template>
