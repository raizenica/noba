<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import { useApi } from '../../composables/useApi'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const { post } = useApi()

const pihole = computed(() => dashboard.live.pihole)

async function togglePihole() {
  try {
    await post('/api/pihole/toggle', {})
  } catch { /* silent */ }
}
</script>

<template>
  <DashboardCard title="Pi-hole DNS" icon="fas fa-shield-alt" card-id="pihole">
    <template #header-actions>
      <button
        v-if="pihole"
        class="btn btn-xs"
        type="button"
        :title="pihole.status === 'enabled' ? 'Disable Pi-hole' : 'Enable Pi-hole'"
        @click.stop="togglePihole"
      >
        <i :class="pihole.status === 'enabled' ? 'fas fa-toggle-on' : 'fas fa-toggle-off'"></i>
      </button>
    </template>

    <template v-if="pihole && (pihole.status === 'unauthorized' || pihole.status === 'error')">
      <div style="text-align:center;padding:.5rem 0">
        <span class="badge bd" style="font-size:.7rem">{{ pihole.status === 'unauthorized' ? 'API Key Required' : 'Connection Error' }}</span>
        <p style="font-size:.72rem;color:var(--text-muted);margin:.6rem 0 0">
          <router-link to="/settings/integrations" class="empty-link">Configure in Settings → Integrations</router-link>
        </p>
      </div>
    </template>
    <template v-else-if="pihole">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.875rem">
        <span class="badge" :class="pihole.status === 'enabled' ? 'bs' : 'bd'">{{ pihole.status }}</span>
        <span style="font-size:.68rem;color:var(--text-muted)">{{ pihole.domains }} domains</span>
      </div>
      <div class="ph-stats">
        <div class="ph-stat">
          <div class="ph-val">{{ typeof pihole.queries === 'number' ? pihole.queries.toLocaleString() : pihole.queries }}</div>
          <div class="ph-label">Total Queries</div>
        </div>
        <div class="ph-stat">
          <div class="ph-val" style="color:var(--danger)">{{ typeof pihole.blocked === 'number' ? pihole.blocked.toLocaleString() : pihole.blocked }}</div>
          <div class="ph-label">Blocked</div>
        </div>
      </div>
      <div class="prog">
        <div class="prog-meta">
          <span>BLOCK RATE</span>
          <span>{{ pihole.percent }}%</span>
        </div>
        <div
          class="prog-track"
          role="progressbar"
          :aria-valuenow="pihole.percent"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-label="'Block rate ' + pihole.percent + '%'"
        >
          <div class="prog-fill f-accent" :style="'width:' + (pihole.percent || 0) + '%'"></div>
        </div>
      </div>
    </template>
    <div v-else class="empty-msg">Pi-hole unreachable — <router-link to="/settings/integrations" class="empty-link">configure in Settings</router-link>.</div>
  </DashboardCard>
</template>
