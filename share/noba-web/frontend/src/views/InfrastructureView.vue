<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useAuthStore } from '../stores/auth'
import AppTabBar from '../components/ui/AppTabBar.vue'

import ServiceMapTab    from '../components/infrastructure/ServiceMapTab.vue'
import ServiceList      from '../components/infrastructure/ServiceList.vue'
import TopologyTab      from '../components/infrastructure/TopologyTab.vue'
import K8sBrowser       from '../components/infrastructure/K8sBrowser.vue'
import TailscaleTab     from '../components/infrastructure/TailscaleTab.vue'
import CrossSiteSyncTab from '../components/infrastructure/CrossSiteSyncTab.vue'
import ConfigDrift      from '../components/infrastructure/ConfigDrift.vue'
import ExportTab        from '../components/infrastructure/ExportTab.vue'
import TrafficTab       from '../components/infrastructure/TrafficTab.vue'
import NetworkDevices   from '../components/infrastructure/NetworkDevices.vue'
import PredictionsTab   from '../components/infrastructure/PredictionsTab.vue'

const authStore = useAuthStore()

const activeTab = ref('servicemap')

const tabs = computed(() => {
  const t = [
    { key: 'servicemap',  label: 'Service Map', icon: 'fa-project-diagram' },
    { key: 'services',    label: 'Services',    icon: 'fa-list' },
    { key: 'topology',    label: 'Topology',    icon: 'fa-network-wired' },
    { key: 'k8s',         label: 'Kubernetes',  icon: 'fa-dharmachakra' },
    { key: 'tailscale',   label: 'Tailscale',   icon: 'fa-shield-alt' },
    { key: 'sync',        label: 'Cross-Site Sync', icon: 'fa-sync' },
    { key: 'drift',       label: 'Config Drift', icon: 'fa-file-medical-alt' },
  ]
  if (authStore.isOperator) {
    t.push({ key: 'export', label: 'Export', icon: 'fa-file-export' })
  }
  t.push(
    { key: 'traffic',     label: 'Traffic',     icon: 'fa-chart-area' },
    { key: 'networkmap',  label: 'Network Map', icon: 'fa-route' },
    { key: 'predictions', label: 'Predictions', icon: 'fa-chart-line' },
  )
  return t
})

const serviceMapRef = ref(null)
const topologyRef   = ref(null)
const syncRef       = ref(null)
const trafficRef    = ref(null)
const predictRef    = ref(null)

function setTab(tab) {
  activeTab.value = tab
  if (tab === 'servicemap')  serviceMapRef.value?.fetchServiceMap()
  if (tab === 'topology')    topologyRef.value?.fetchTopology()
  if (tab === 'sync')        syncRef.value?.fetchSyncStatus()
  if (tab === 'traffic')     trafficRef.value?.fetchNetworkStats()
  if (tab === 'predictions') { predictRef.value?.fetchPredictions(); predictRef.value?.fetchPredictHealth() }
}
</script>

<template>
  <div style="padding:1rem">
    <h2 style="margin-bottom:1rem">
      <i class="fas fa-server" style="margin-right:.5rem;color:var(--accent)"></i>
      Infrastructure
    </h2>

    <!-- Tab bar -->
    <AppTabBar :tabs="tabs" :active="activeTab" @change="setTab" />

    <!-- Tab contents -->
    <div v-show="activeTab === 'servicemap'">
      <ServiceMapTab ref="serviceMapRef" />
    </div>

    <div v-show="activeTab === 'services'">
      <ServiceList />
    </div>

    <div v-show="activeTab === 'topology'">
      <TopologyTab ref="topologyRef" />
    </div>

    <div v-show="activeTab === 'k8s'">
      <K8sBrowser />
    </div>

    <div v-show="activeTab === 'tailscale'">
      <TailscaleTab />
    </div>

    <div v-show="activeTab === 'sync'">
      <CrossSiteSyncTab ref="syncRef" />
    </div>

    <div v-show="activeTab === 'drift'">
      <ConfigDrift />
    </div>

    <div v-show="activeTab === 'export'">
      <ExportTab />
    </div>

    <div v-show="activeTab === 'traffic'">
      <TrafficTab ref="trafficRef" />
    </div>

    <div v-show="activeTab === 'networkmap'">
      <NetworkDevices />
    </div>

    <div v-show="activeTab === 'predictions'">
      <PredictionsTab ref="predictRef" />
    </div>
  </div>
</template>
