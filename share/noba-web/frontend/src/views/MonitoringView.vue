<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, nextTick, onMounted } from 'vue'
import { useApi } from '../composables/useApi'
import AppTabBar from '../components/ui/AppTabBar.vue'

import SlaTable        from '../components/monitoring/SlaTable.vue'
import IncidentList    from '../components/monitoring/IncidentList.vue'
import EndpointTable   from '../components/monitoring/EndpointTable.vue'
import CorrelationTab  from '../components/monitoring/CorrelationTab.vue'
import GraylogTab      from '../components/monitoring/GraylogTab.vue'
import InfluxDbTab     from '../components/monitoring/InfluxDbTab.vue'
import CustomChartsTab from '../components/monitoring/CustomChartsTab.vue'

const { get } = useApi()
const activeTab = ref('sla')

// Lightweight badge counts
const slaCount      = ref(0)
const incidentCount = ref(0)
const endpointCount = ref(0)

async function fetchBadgeCounts() {
  try {
    const sla = await get('/api/sla/summary?hours=720')
    slaCount.value = (sla && sla.rules) ? sla.rules.length : 0
  } catch { /* silent */ }
  try {
    const inc = await get('/api/incidents?limit=100')
    incidentCount.value = Array.isArray(inc) ? inc.filter(i => !i.resolved_at).length : 0
  } catch { /* silent */ }
  try {
    const ep = await get('/api/endpoints')
    endpointCount.value = Array.isArray(ep) ? ep.length : 0
  } catch { /* silent */ }
}

onMounted(fetchBadgeCounts)

const tabs = computed(() => [
  { key: 'sla',         label: 'SLA',           icon: 'fa-percentage',         badge: slaCount.value || undefined },
  { key: 'incidents',   label: 'Incidents',     icon: 'fa-exclamation-triangle', badge: incidentCount.value || undefined },
  { key: 'correlation', label: 'Correlation',   icon: 'fa-project-diagram' },
  { key: 'graylog',     label: 'Graylog',       icon: 'fa-search' },
  { key: 'influxdb',    label: 'InfluxDB',      icon: 'fa-chart-area' },
  { key: 'charts',      label: 'Custom Charts', icon: 'fa-chart-bar' },
  { key: 'endpoints',   label: 'Endpoints',     icon: 'fa-network-wired',      badge: endpointCount.value || undefined },
])

const correlationRef  = ref(null)
const influxRef       = ref(null)
const customChartsRef = ref(null)

function setTab(tab) {
  activeTab.value = tab
  if (tab === 'correlation') {
    nextTick(() => correlationRef.value?.renderCorrelationChart())
  }
  if (tab === 'charts') {
    customChartsRef.value?.fetchAvailableMetrics()
    customChartsRef.value?.fetchDashboards()
    customChartsRef.value?.fetchMultiMetricChart()
  }
  if (tab === 'influxdb') {
    nextTick(() => influxRef.value?.renderInfluxChart())
  }
}
</script>

<template>
  <div>
    <!-- Page header -->
    <h2 style="margin-bottom:1rem">
      <i class="fas fa-chart-line" style="margin-right:.5rem;color:var(--accent)"></i>
      Monitoring
    </h2>

    <!-- Tab bar -->
    <AppTabBar :tabs="tabs" :active="activeTab" @change="setTab" />

    <!-- Tab contents -->
    <div v-show="activeTab === 'sla'">
      <SlaTable />
    </div>

    <div v-show="activeTab === 'incidents'">
      <IncidentList />
    </div>

    <div v-show="activeTab === 'correlation'">
      <CorrelationTab ref="correlationRef" />
    </div>

    <div v-show="activeTab === 'graylog'">
      <GraylogTab />
    </div>

    <div v-show="activeTab === 'influxdb'">
      <InfluxDbTab ref="influxRef" />
    </div>

    <div v-show="activeTab === 'charts'">
      <CustomChartsTab ref="customChartsRef" />
    </div>

    <div v-show="activeTab === 'endpoints'">
      <EndpointTable />
    </div>
  </div>
</template>
