<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useHealingStore } from '../../stores/healing'
import { useDashboardStore } from '../../stores/dashboard'

const store = useHealingStore()
const dashboardStore = useDashboardStore()

const pipelineStatus = computed(() => {
  if (store.activeMaintenance.length) return 'Maintenance'
  if (store.openCircuitBreakers.length > 2) return 'Degraded'
  return 'Active'
})

const pipelineClass = computed(() => {
  if (store.activeMaintenance.length) return 'bw'
  if (store.openCircuitBreakers.length > 2) return 'bd'
  return 'bs'
})
</script>

<template>
  <div class="heal-overview">
    <div class="heal-stat">
      <span class="heal-stat-label">Pipeline</span>
      <span :class="['badge', pipelineClass]">{{ pipelineStatus }}</span>
      <span style="font-size:.7rem;color:var(--text-muted);margin-left:.5rem">up {{ dashboardStore.live.uptime || '--' }}</span>
    </div>
    <div class="heal-stat">
      <span class="heal-stat-label">Active Heals</span>
      <span class="heal-stat-val">{{ store.activeHealCount }}</span>
    </div>
    <div class="heal-stat" v-if="store.pendingApprovals.length">
      <span class="heal-stat-label">Pending Approvals</span>
      <span class="badge bd">{{ store.pendingApprovals.length }}</span>
    </div>
    <div class="heal-stat" v-if="store.openCircuitBreakers.length">
      <span class="heal-stat-label">Circuit Breakers</span>
      <span class="badge bw">{{ store.openCircuitBreakers.length }} open</span>
    </div>
    <div class="heal-stat" v-if="store.activeMaintenance.length">
      <span class="heal-stat-label">Maintenance</span>
      <span class="badge ba">{{ store.activeMaintenance.length }} active</span>
    </div>
    <div class="heal-stat">
      <span class="heal-stat-label">Suggestions</span>
      <span :class="['badge', store.suggestionCount ? 'ba' : 'bs']">{{ store.suggestionCount }}</span>
    </div>
  </div>
</template>

<style scoped>
.heal-overview {
  display: flex;
  gap: 1.5rem;
  padding: .75rem 1rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 1rem;
  flex-wrap: wrap;
  align-items: center;
}
.heal-stat {
  display: flex;
  align-items: center;
  gap: .5rem;
}
.heal-stat-label {
  font-size: .8rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: .03em;
}
.heal-stat-val {
  font-family: var(--font-data);
  font-size: 1rem;
  color: var(--text);
}
</style>
