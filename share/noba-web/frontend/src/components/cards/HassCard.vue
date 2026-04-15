<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const hass = computed(() => dashboard.live.hass)
</script>

<template>
  <DashboardCard title="Home Assistant" icon="fas fa-home" card-id="hass">
    <template #header-actions>
      <span
        class="badge"
        :class="hass && hass.status === 'online' ? 'bs' : 'bn'"
        style="margin-left:auto;margin-right:.25rem"
      >{{ hass ? hass.status : 'offline' }}</span>
    </template>

    <template v-if="hass">
      <div class="row">
        <span class="row-label">Entities</span>
        <span class="row-val">{{ hass.entities || 0 }}</span>
      </div>
      <div class="row">
        <span class="row-label">Automations</span>
        <span class="row-val">{{ hass.automations || 0 }}</span>
      </div>
      <div class="row">
        <span class="row-label">Lights On</span>
        <span class="row-val">{{ hass.lights_on || 0 }}</span>
      </div>
      <div class="row">
        <span class="row-label">Switches On</span>
        <span class="row-val">{{ hass.switches_on || 0 }}</span>
      </div>
    </template>
    <div v-else class="empty-msg">Home Assistant data unavailable.</div>
  </DashboardCard>
</template>
