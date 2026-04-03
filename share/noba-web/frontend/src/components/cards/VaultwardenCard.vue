<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const vaultwarden = computed(() => dashboard.live.vaultwarden)
</script>

<template>
  <DashboardCard title="Vaultwarden" icon="fas fa-lock" card-id="vaultwarden">
    <template v-if="vaultwarden">
      <div class="row">
        <span class="row-label">Status</span>
        <span class="badge" :class="vaultwarden.status === 'online' ? 'bs' : 'bd'">{{ vaultwarden.status }}</span>
      </div>
      <div v-if="vaultwarden.users != null" class="row">
        <span class="row-label">Users</span>
        <span class="row-val">{{ vaultwarden.users }}</span>
      </div>
      <div v-if="vaultwarden.orgs != null" class="row">
        <span class="row-label">Organisations</span>
        <span class="row-val">{{ vaultwarden.orgs }}</span>
      </div>
    </template>
    <div v-else class="empty-msg">Vaultwarden unreachable — <router-link to="/settings?tab=integrations" class="empty-link">configure in Settings</router-link>.</div>
  </DashboardCard>
</template>
