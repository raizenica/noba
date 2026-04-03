<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, nextTick, watch, onMounted, onUnmounted } from 'vue'
import Sortable from 'sortablejs'
import { useDashboardStore } from '../stores/dashboard'
import { useSettingsStore } from '../stores/settings'
import { useApi } from '../composables/useApi'
import WelcomeSetup from '../components/welcome/WelcomeSetup.vue'

// ── Dashboard sub-components ─────────────────────────────────────────────────
import HealthBar         from '../components/dashboard/HealthBar.vue'
import HealthScoreGauge  from '../components/dashboard/HealthScoreGauge.vue'
import DashboardToolbar  from '../components/dashboard/DashboardToolbar.vue'

// ── Card imports ──────────────────────────────────────────────────────────────
import CoreSystemCard     from '../components/cards/CoreSystemCard.vue'
import SystemHealthCard   from '../components/cards/SystemHealthCard.vue'
import UptimeCard         from '../components/cards/UptimeCard.vue'
import NetworkIoCard      from '../components/cards/NetworkIoCard.vue'
import HardwareCard       from '../components/cards/HardwareCard.vue'
import StorageCard        from '../components/cards/StorageCard.vue'
import DiskHealthCard     from '../components/cards/DiskHealthCard.vue'
import DiskIoCard         from '../components/cards/DiskIoCard.vue'
import NetworkRadarCard   from '../components/cards/NetworkRadarCard.vue'
import ProcessesCard      from '../components/cards/ProcessesCard.vue'
import BatteryCard        from '../components/cards/BatteryCard.vue'
import AgentsCard         from '../components/cards/AgentsCard.vue'
import CertExpiryCard     from '../components/cards/CertExpiryCard.vue'
import DevicePresenceCard from '../components/cards/DevicePresenceCard.vue'
import ContainersCard     from '../components/cards/ContainersCard.vue'
import AutomationsCard    from '../components/cards/AutomationsCard.vue'
import QuickActionsCard   from '../components/cards/QuickActionsCard.vue'
import BookmarksCard      from '../components/cards/BookmarksCard.vue'

// ── Integration card imports ──────────────────────────────────────────────────
import PiholeCard       from '../components/cards/PiholeCard.vue'
import AdguardCard      from '../components/cards/AdguardCard.vue'
import UnifiCard        from '../components/cards/UnifiCard.vue'
import SpeedtestCard    from '../components/cards/SpeedtestCard.vue'
import TailscaleCard    from '../components/cards/TailscaleCard.vue'
import TruenasCard      from '../components/cards/TruenasCard.vue'
import PlexCard         from '../components/cards/PlexCard.vue'
import DownloadsCard    from '../components/cards/DownloadsCard.vue'
import JellyfinCard     from '../components/cards/JellyfinCard.vue'
import LidarrCard       from '../components/cards/LidarrCard.vue'
import ReadarrCard      from '../components/cards/ReadarrCard.vue'
import BazarrCard       from '../components/cards/BazarrCard.vue'
import HassCard         from '../components/cards/HassCard.vue'
import FrigateCard      from '../components/cards/FrigateCard.vue'
import KumaCard         from '../components/cards/KumaCard.vue'
import ProxmoxCard      from '../components/cards/ProxmoxCard.vue'
import VaultwardenCard  from '../components/cards/VaultwardenCard.vue'
import VpnCard          from '../components/cards/VpnCard.vue'
import EnergyCard       from '../components/cards/EnergyCard.vue'
import CameraFeedsCard  from '../components/cards/CameraFeedsCard.vue'
import RecoveryCard     from '../components/cards/RecoveryCard.vue'
import N8nCard         from '../components/cards/N8nCard.vue'
import PredictionCard  from '../components/cards/PredictionCard.vue'
import IntegrationCard      from '../components/cards/IntegrationCard.vue'
import TruenasInstanceCard  from '../components/cards/TruenasInstanceCard.vue'
import { getTemplate } from '../data/cardTemplates'

const dashboardStore = useDashboardStore()
const settingsStore  = useSettingsStore()
const { get } = useApi()

// ── Sub-component refs ───────────────────────────────────────────────────────
const healthScoreRef = ref(null)
const toolbarRef     = ref(null)

// ── First-run detection ──────────────────────────────────────────────────────
const welcomeDismissed = ref(localStorage.getItem('noba:welcome_dismissed') === '1')
const _INTEGRATION_KEYS = [
  'piholeUrl', 'hassUrl', 'unifiUrl', 'proxmoxUrl', 'truenasUrl',
  'plexUrl', 'jellyfinUrl', 'qbitUrl', 'adguardUrl', 'sonarrUrl',
  'radarrUrl', 'speedtestUrl', 'kumaUrl', 'monitoredServices',
]
const isFirstRun = computed(() => {
  if (welcomeDismissed.value) return false
  if (!settingsStore.loaded) return false
  const d = settingsStore.data
  return !_INTEGRATION_KEYS.some(k => d[k] && String(d[k]).trim())
    && managedInstances.value.length === 0
})
function dismissWelcome() {
  welcomeDismissed.value = true
  localStorage.setItem('noba:welcome_dismissed', '1')
  // Re-use the shared masonry observer after the grid renders
  setTimeout(() => nextTick(() => requestAnimationFrame(() => requestAnimationFrame(initMasonry))), 300)
}

// ── Managed integration instances ────────────────────────────────────────────
const managedInstances = ref([])
const showEmptyIntegrations = ref(false)

const activeInstances = computed(() =>
  managedInstances.value.filter(inst => {
    const d = getIntegrationData(inst.id)
    return d && Object.keys(d).length > 0
  })
)

const emptyInstances = computed(() =>
  managedInstances.value.filter(inst => {
    const d = getIntegrationData(inst.id)
    return !d || Object.keys(d).length === 0
  })
)

async function fetchManagedInstances() {
  try {
    managedInstances.value = await get('/api/integrations/instances')
  } catch { /* silent */ }
}

function getCardTemplate(platform) {
  return getTemplate(platform)
}

function getIntegrationData(instanceId) {
  return (dashboardStore.live.instances || {})[instanceId] || {}
}

// ── Glance mode ──────────────────────────────────────────────────────────────
const glanceMode = ref(false)
const gridRef = ref(null)

// Masonry observer kept at component scope so onUnmounted can clean it up
let _masonryObserver = null
let _masonryChildObserver = null

function initMasonry() {
  if (_masonryObserver) _masonryObserver.disconnect()
  _masonryObserver = new ResizeObserver(entries => {
    for (const entry of entries) {
      const card = entry.target
      if (card.offsetParent === null) continue
      const height = card.getBoundingClientRect().height
      const next = `span ${Math.ceil((height + 18) / 10)}`
      // Only write the DOM when the span actually changes — prevents the
      // style-write → reflow → observer-refires cascade.
      if (card.style.gridRowEnd !== next) card.style.gridRowEnd = next
    }
  })
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const grid = gridRef.value
    if (grid) grid.querySelectorAll('.card').forEach(c => _masonryObserver.observe(c))
  }))

  // Watch for new cards added by SSE data
  const grid = document.querySelector('.grid')
  if (grid) {
    if (_masonryChildObserver) _masonryChildObserver.disconnect()
    _masonryChildObserver = new MutationObserver(() => {
      requestAnimationFrame(() => {
        grid.querySelectorAll('.card').forEach(card => {
          if (!_masonryObserver) return
          _masonryObserver.observe(card)
        })
      })
    })
    _masonryChildObserver.observe(grid, { childList: true })
  }
}

// ── Card visibility helper ────────────────────────────────────────────────────
function showCard(key) {
  return settingsStore.vis[key] !== false
}

// ── Card order helpers ────────────────────────────────────────────────────────
function applyCardOrder(order) {
  const container = gridRef.value
  if (!container || !order || order.length === 0) return
  const items = Array.from(container.children)
  const itemMap = {}
  items.forEach(el => {
    const id = el.getAttribute('data-id')
    if (id) itemMap[id] = el
  })
  order.forEach(id => {
    if (itemMap[id]) { container.appendChild(itemMap[id]); delete itemMap[id] }
  })
  Object.values(itemMap).forEach(el => container.appendChild(el))
}

function onDashboardLoaded() {
  nextTick(() => {
    applyCardOrder(settingsStore.preferences.preferences?.cardOrder || [])
    // Recalculate masonry spans after reorder
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const grid = gridRef.value
      if (!grid) return
      grid.querySelectorAll('.card').forEach(c => {
        const height = c.getBoundingClientRect().height
        if (height > 0) { const s = `span ${Math.ceil((height + 18) / 10)}`; if (c.style.gridRowEnd !== s) c.style.gridRowEnd = s }
      })
    }))
  })
}

onMounted(() => {
  healthScoreRef.value?.fetchHealthScore()
  toolbarRef.value?.fetchDashboards()
  fetchManagedInstances()
  // Initialize drag-to-reorder on card grid
  function initSortable() {
    if (!gridRef.value) return
    if (gridRef.value._sortable) return

    applyCardOrder(settingsStore.preferences.preferences?.cardOrder || [])

    gridRef.value._sortable = Sortable.create(gridRef.value, {
      animation: 150,
      handle: '.card-hdr',
      ghostClass: 'sortable-ghost',
      dragClass: 'sortable-drag',
      forceFallback: true,
      fallbackOnBody: true,
      dataIdAttr: 'data-id',
      store: {
        get: function () {
          return settingsStore.preferences.preferences?.cardOrder || []
        },
        set: function (sortable) {
          if (!settingsStore.preferences.preferences) settingsStore.preferences.preferences = {}
          settingsStore.preferences.preferences.cardOrder = sortable.toArray()
          settingsStore.savePreferences().catch(() => {})
        }
      }
    })
  }
  let attempts = 0
  const tryInit = () => {
    attempts++
    if (gridRef.value && gridRef.value.children.length > 0) {
      initSortable()
    } else if (attempts < 20) {
      setTimeout(tryInit, 250)
    }
  }
  setTimeout(tryInit, 300)

  nextTick(() => requestAnimationFrame(() => requestAnimationFrame(initMasonry)))
})

// Re-run masonry only when the SET of active instances changes (not on every SSE data tick).
// Watching the full reactive array fires on every SSE update because .filter() always
// returns a new array reference — watch a stable key derived from instance IDs instead.
watch(() => activeInstances.value.map(i => i.id).join(','), () => {
  nextTick(() => requestAnimationFrame(() => requestAnimationFrame(() => {
    const grid = gridRef.value
    if (!grid) return
    // Re-apply card order so late-arriving managed instance cards land in their saved position
    const savedOrder = settingsStore.preferences.preferences?.cardOrder
    if (savedOrder?.length) applyCardOrder(savedOrder)
    grid.querySelectorAll('.card').forEach(c => {
      const height = c.getBoundingClientRect().height
      if (height > 0) { const s = `span ${Math.ceil((height + 18) / 10)}`; if (c.style.gridRowEnd !== s) c.style.gridRowEnd = s }
    })
  })))
})

onUnmounted(() => {
  if (gridRef.value?._sortable) gridRef.value._sortable.destroy()
  if (_masonryObserver) { _masonryObserver.disconnect(); _masonryObserver = null }
  if (_masonryChildObserver) { _masonryChildObserver.disconnect(); _masonryChildObserver = null }
})
</script>

<template>
  <div>
    <!-- First-run welcome -->
    <WelcomeSetup v-if="isFirstRun" @dismiss="dismissWelcome" />

    <!-- Dashboard -->
    <template v-else>
      <HealthBar />
      <HealthScoreGauge ref="healthScoreRef" />
      <DashboardToolbar ref="toolbarRef" @dashboard-loaded="onDashboardLoaded" />

      <!-- Card grid -->
      <div ref="gridRef" class="grid" :class="{ 'glance-mode': glanceMode }">
        <!-- System cards -->
        <CoreSystemCard     v-if="showCard('core')"                                        data-id="core" />
        <SystemHealthCard                                                                   data-id="health" />
        <UptimeCard                                                                         data-id="uptime" />
        <NetworkIoCard      v-if="showCard('netio')"                                       data-id="netio" />
        <HardwareCard       v-if="showCard('hw')"                                          data-id="hw" />
        <StorageCard        v-if="showCard('storage')"                                     data-id="storage" />
        <DiskHealthCard     v-if="showCard('scrutiny')"                                    data-id="scrutiny" />
        <DiskIoCard         v-if="showCard('diskIo')"                                      data-id="diskIo" />
        <NetworkRadarCard   v-if="showCard('radar')"                                       data-id="radar" />
        <ProcessesCard      v-if="showCard('procs')"                                       data-id="procs" />
        <BatteryCard        v-if="showCard('battery')"                                     data-id="battery" />
        <AgentsCard         v-if="showCard('agents')"                                      data-id="agents" />
        <CertExpiryCard     v-if="showCard('certExpiry')"                                  data-id="certExpiry" />
        <DevicePresenceCard                                                                 data-id="presence" />
        <ContainersCard     v-if="showCard('containers')"                                  data-id="containers" />
        <AutomationsCard    v-if="showCard('automations')"                                 data-id="automations" />
        <QuickActionsCard   v-if="showCard('actions')"                                     data-id="actions" />
        <BookmarksCard      v-if="showCard('bookmarks')"                                   data-id="bookmarks" />

        <!-- DNS / Network integrations -->
        <PiholeCard      v-if="showCard('pihole')      && settingsStore.data.piholeUrl"    data-id="pihole" />
        <AdguardCard     v-if="showCard('adguard')     && settingsStore.data.adguardUrl"   data-id="adguard" />
        <UnifiCard       v-if="showCard('unifi')       && settingsStore.data.unifiUrl"     data-id="unifi" />
        <SpeedtestCard   v-if="showCard('speedtest')   && settingsStore.data.speedtestUrl" data-id="speedtest" />
        <TailscaleCard   v-if="showCard('tailscale')   && dashboardStore.live.tailscale"   data-id="tailscale" />

        <!-- Storage integrations -->
        <TruenasCard     v-if="showCard('truenas')     && settingsStore.data.truenasUrl"   data-id="truenas" />

        <!-- Media integrations -->
        <PlexCard        v-if="showCard('plex')        && settingsStore.data.plexUrl"      data-id="plex" />
        <DownloadsCard   v-if="showCard('downloads')   && (settingsStore.data.qbitUrl || settingsStore.data.radarrUrl || settingsStore.data.sonarrUrl)" data-id="downloads" />
        <JellyfinCard    v-if="showCard('jellyfin')    && settingsStore.data.jellyfinUrl"  data-id="jellyfin" />
        <LidarrCard      v-if="showCard('lidarr')      && settingsStore.data.lidarrUrl"    data-id="lidarr" />
        <ReadarrCard     v-if="showCard('readarr')     && settingsStore.data.readarrUrl"   data-id="readarr" />
        <BazarrCard      v-if="showCard('bazarr')      && settingsStore.data.bazarrUrl"    data-id="bazarr" />

        <!-- Home automation -->
        <HassCard        v-if="showCard('hass')        && settingsStore.data.hassUrl"      data-id="hass" />
        <FrigateCard     v-if="showCard('frigate')     && settingsStore.data.frigateUrl"   data-id="frigate" />

        <!-- Infrastructure integrations -->
        <KumaCard        v-if="showCard('kuma')        && settingsStore.data.kumaUrl"      data-id="kuma" />
        <ProxmoxCard     v-if="showCard('proxmox')     && settingsStore.data.proxmoxUrl"   data-id="proxmox" />
        <VaultwardenCard v-if="showCard('vaultwarden') && settingsStore.data.vaultwardenUrl" data-id="vaultwarden" />
        <VpnCard         v-if="showCard('vpn')         && dashboardStore.live.vpn"         data-id="vpn" />

        <!-- Data-driven cards (no URL needed) -->
        <EnergyCard      v-if="(dashboardStore.live.energy || []).length > 0"              data-id="energy" />
        <CameraFeedsCard v-if="(dashboardStore.live.cameraFeeds || []).length > 0"         data-id="cameraFeeds" />
        <N8nCard         v-if="showCard('n8n') && dashboardStore.live.n8n"                 data-id="n8n" />

        <!-- Prediction -->
        <PredictionCard  v-if="showCard('prediction')"                                      data-id="prediction" />

        <!-- Admin-only -->
        <RecoveryCard    v-if="showCard('recovery')"                                        data-id="recovery" />

        <!-- Managed Integration Cards (with data) -->
        <template v-for="inst in activeInstances" :key="'int-'+inst.id">
          <TruenasInstanceCard
            v-if="inst.platform === 'truenas'"
            :instance="inst"
            class="card"
            :data-id="'int-'+inst.id"
          />
          <IntegrationCard
            v-else
            :instance="inst"
            :template="getCardTemplate(inst.platform)"
            :data="getIntegrationData(inst.id)"
            class="card"
            :data-id="'int-'+inst.id"
          />
        </template>
      </div>

      <!-- Unconfigured integrations collapsed section -->
      <div v-if="emptyInstances.length > 0" style="margin-top:1rem">
        <button
          class="btn btn-xs"
          style="width:100%;justify-content:center;gap:.5rem;padding:.5rem;opacity:.7"
          @click="showEmptyIntegrations = !showEmptyIntegrations"
        >
          <i class="fas" :class="showEmptyIntegrations ? 'fa-chevron-up' : 'fa-chevron-down'"></i>
          {{ emptyInstances.length }} unconfigured integration{{ emptyInstances.length !== 1 ? 's' : '' }}
          <span style="font-size:.7rem;opacity:.7">(no data)</span>
        </button>
        <div v-if="showEmptyIntegrations" style="margin-top:.75rem;display:flex;flex-wrap:wrap;gap:.875rem">
          <IntegrationCard
            v-for="inst in emptyInstances"
            :key="'int-'+inst.id"
            :instance="inst"
            :template="getCardTemplate(inst.platform)"
            :data="getIntegrationData(inst.id)"
            class="card"
            :data-id="'int-'+inst.id"
          />
        </div>
      </div>
    </template>
  </div>
</template>
