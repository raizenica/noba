<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const cameraFeeds = computed(() => dashboard.live.cameraFeeds || [])
</script>

<template>
  <DashboardCard title="Camera Feeds" icon="fas fa-video" card-id="cameras">
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px">
      <div
        v-for="cam in cameraFeeds"
        :key="cam.url"
        style="text-align:center"
      >
        <img
          :src="cam.url"
          :alt="cam.name"
          style="width:100%;border-radius:4px;background:#000"
          loading="lazy"
          @error="$event.target.style.display='none'"
        >
        <div style="font-size:.75rem;color:var(--text-muted);margin-top:4px">{{ cam.name }}</div>
      </div>
    </div>
    <div v-if="cameraFeeds.length === 0" class="empty-msg">No camera feeds configured.</div>
  </DashboardCard>
</template>
