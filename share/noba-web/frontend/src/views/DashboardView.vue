<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import Sortable from 'sortablejs'
import { useDashboardStore } from '../stores/dashboard'
import { useSettingsStore } from '../stores/settings'
import { useApi } from '../composables/useApi'

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
import PredictionCard  from '../components/cards/PredictionCard.vue'
import IntegrationCard from '../components/cards/IntegrationCard.vue'
import { getTemplate } from '../data/cardTemplates'

const dashboardStore = useDashboardStore()
const settingsStore  = useSettingsStore()
const { get, post, del } = useApi()

// ── Managed integration instances ────────────────────────────────────────────
const managedInstances = ref([])

async function fetchManagedInstances() {
  try {
    managedInstances.value = await get('/api/integrations/instances')
  } catch { /* silent */ }
}

function getCardTemplate(platform) {
  return getTemplate(platform)
}

function getIntegrationData(instanceId) {
  return dashboardStore.live[instanceId] || {}
}

// ── Glance mode ──────────────────────────────────────────────────────────────
const glanceMode = ref(false)
const gridRef = ref(null)

// ── Alert dismissal ──────────────────────────────────────────────────────────
const dismissedAlerts = ref(new Set())

const visibleAlerts = computed(() =>
  (dashboardStore.live.alerts || []).filter(
    a => !dismissedAlerts.value.has(a.msg)
  )
)

function dismissAlert(msg) {
  dismissedAlerts.value = new Set([...dismissedAlerts.value, msg])
}

// ── Card visibility helper ────────────────────────────────────────────────────
function showCard(key) {
  return settingsStore.vis[key] !== false
}

// ── Health pips ───────────────────────────────────────────────────────────────
const healthPips = computed(() => {
  const live = dashboardStore.live

  const services   = live.services || []
  const containers = live.containers || []

  return [
    {
      key:   'services',
      title: 'Services',
      cls:   services.length
               ? (services.every(s => s.running) ? 'ok' : 'warn')
               : 'off',
    },
    {
      key:   'disks',
      title: 'Disks',
      cls:   live.disks && live.disks.length ? 'ok' : 'off',
    },
    {
      key:   'network',
      title: 'Network',
      cls:   live.unifi ? 'ok' : 'off',
    },
    {
      key:   'dns',
      title: 'DNS',
      cls:   live.pihole || live.adguard ? 'ok' : 'off',
    },
    {
      key:   'containers',
      title: 'Containers',
      cls:   containers.length ? 'ok' : 'off',
    },
    {
      key:   'media',
      title: 'Media',
      cls:   live.plex || live.jellyfin ? 'ok' : 'off',
    },
    {
      key:   'alerts',
      title: 'Alerts',
      cls:   (live.alerts || []).length ? 'warn' : 'ok',
    },
  ]
})

// ── Infrastructure health score ───────────────────────────────────────────────
const healthScore         = ref(null)
const healthScoreExpanded = ref(false)

async function fetchHealthScore() {
  try {
    healthScore.value = await get('/api/health-score')
  } catch { /* silent */ }
}

function infraScoreColor(score) {
  if (score == null) return 'var(--text-muted)'
  if (score > 80) return 'var(--success)'
  if (score > 50) return 'var(--warning)'
  return 'var(--danger)'
}

function infraScoreRing(score) {
  if (score == null) {
    return 'background: conic-gradient(var(--surface-2) 0deg, var(--surface-2) 360deg)'
  }
  const deg   = Math.round((score / 100) * 360)
  const color = infraScoreColor(score)
  return `background: conic-gradient(${color} 0deg, ${color} ${deg}deg, var(--surface-2) ${deg}deg, var(--surface-2) 360deg)`
}

function catBadgeClass(status) {
  if (status === 'ok')      return 'bs'
  if (status === 'warning') return 'bw'
  return 'bd'
}

// ── Custom dashboards ─────────────────────────────────────────────────────────
const savedDashboards     = ref([])
const saveDashboardName   = ref('')
const showSaveModal       = ref(false)

async function fetchDashboards() {
  try {
    savedDashboards.value = await get('/api/dashboards')
  } catch { /* silent */ }
}

async function saveDashboard() {
  const name = saveDashboardName.value.trim()
  if (!name) return
  try {
    const config = { vis: { ...settingsStore.vis } }
    await post('/api/dashboards', { name, config_json: JSON.stringify(config), shared: false })
    saveDashboardName.value = ''
    showSaveModal.value = false
    await fetchDashboards()
  } catch { /* silent */ }
}

async function loadDashboard(dashboard) {
  try {
    const config = JSON.parse(dashboard.config_json)
    if (config.vis) Object.assign(settingsStore.vis, config.vis)
  } catch { /* silent */ }
}

async function deleteDashboard(id) {
  if (!confirm('Delete this saved dashboard?')) return
  try {
    await del('/api/dashboards/' + id)
    await fetchDashboards()
  } catch { /* silent */ }
}

onMounted(() => {
  fetchHealthScore()
  fetchDashboards()
  fetchManagedInstances()
  // Initialize drag-to-reorder on card grid
  function initSortable() {
    if (!gridRef.value) return
    // Avoid double-init
    if (gridRef.value._sortable) return
    gridRef.value._sortable = Sortable.create(gridRef.value, {
      animation: 150,
      handle: '.card-hdr',
      ghostClass: 'sortable-ghost',
      dragClass: 'sortable-drag',
      forceFallback: true,
      fallbackOnBody: true,
    })
  }
  // Retry until grid is in DOM and has children
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

  // Masonry — exact v2 approach: observe each .card, set grid-row-end: span N
  let _masonryObserver = null
  function initMasonry() {
    if (_masonryObserver) _masonryObserver.disconnect()
    _masonryObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        const card = entry.target
        if (card.offsetParent === null) continue  // skip hidden cards
        const height = card.getBoundingClientRect().height
        const rowSpan = Math.ceil((height + 18) / 10)
        card.style.gridRowEnd = `span ${rowSpan}`
      }
    })
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const grid = gridRef.value
      if (grid) {
        grid.querySelectorAll('.card').forEach(c => _masonryObserver.observe(c))
      }
    }))
  }

  // Start masonry after cards render
  setTimeout(initMasonry, 500)
})

onUnmounted(() => {
  if (gridRef.value?._sortable) gridRef.value._sortable.destroy()
})
</script>

<template>
  <div>
    <!-- ── Health bar ──────────────────────────────────────────────────────── -->
    <div class="health-bar" title="Infrastructure health overview">
      <div
        v-for="pip in healthPips"
        :key="pip.key"
        class="health-pip"
        :class="pip.cls"
        :title="pip.title"
      ></div>
    </div>

    <!-- ── Alert banner ───────────────────────────────────────────────────── -->
    <div v-if="visibleAlerts.length > 0" class="alerts" style="margin:0.75rem 0 0">
      <div
        v-for="alert in visibleAlerts"
        :key="alert.msg"
        class="alert"
        :class="alert.level"
      >
        <i
          class="fas"
          :class="alert.level === 'danger' ? 'fa-exclamation-circle' : 'fa-exclamation-triangle'"
          style="margin-right:.5rem;flex-shrink:0"
        ></i>
        <span style="flex:1">{{ alert.msg }}</span>
        <button
          class="alert-dismiss"
          type="button"
          title="Dismiss"
          @click="dismissAlert(alert.msg)"
        >&times;</button>
      </div>
    </div>

    <!-- ── Infrastructure health score gauge ──────────────────────────────── -->
    <div
      v-if="healthScore"
      style="margin:0.75rem 0;cursor:pointer"
      @click="healthScoreExpanded = !healthScoreExpanded"
    >
      <!-- Summary row -->
      <div
        style="display:flex;align-items:center;gap:1rem;padding:.8rem 1rem;border:1px solid var(--border);border-radius:8px;background:var(--surface-2)"
        :style="healthScoreExpanded ? 'border-radius:8px 8px 0 0' : ''"
      >
        <!-- Ring gauge -->
        <div
          style="position:relative;width:64px;height:64px;border-radius:50%;flex-shrink:0"
          :style="infraScoreRing(healthScore.score)"
        >
          <div
            style="position:absolute;inset:6px;border-radius:50%;background:var(--surface);display:flex;align-items:center;justify-content:center"
          >
            <span
              style="font-size:1.2rem;font-weight:700"
              :style="`color:${infraScoreColor(healthScore.score)}`"
            >{{ healthScore.score }}</span>
          </div>
        </div>

        <!-- Label -->
        <div style="flex:1;min-width:120px">
          <div style="font-weight:600;font-size:.9rem">Infrastructure Health</div>
          <div style="font-size:.75rem;color:var(--text-muted)">
            Grade: {{ healthScore.grade }}
            &mdash;
            {{ Object.keys(healthScore.categories || {}).length }} categories
          </div>
        </div>

        <button
          class="btn btn-xs"
          type="button"
          title="Refresh"
          @click.stop="fetchHealthScore"
        ><i class="fas fa-sync-alt"></i></button>

        <i
          class="fas"
          :class="healthScoreExpanded ? 'fa-chevron-up' : 'fa-chevron-down'"
          style="color:var(--text-muted)"
        ></i>
      </div>

      <!-- Expanded categories -->
      <div
        v-show="healthScoreExpanded"
        style="border:1px solid var(--border);border-top:none;border-radius:0 0 8px 8px;padding:.8rem 1rem;background:var(--surface-2)"
      >
        <div
          v-for="(cat, key) in (healthScore.categories || {})"
          :key="key"
          style="margin-bottom:.6rem"
        >
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.2rem">
            <span style="font-size:.8rem;font-weight:500;text-transform:capitalize">
              {{ String(key).replace(/_/g, ' ') }}
            </span>
            <span class="badge" :class="catBadgeClass(cat.status)" style="font-size:.6rem">
              {{ cat.score }}/{{ cat.max }}
            </span>
          </div>
          <!-- Progress bar -->
          <div style="height:4px;background:var(--surface);border-radius:2px;overflow:hidden">
            <div
              style="height:100%;border-radius:2px;transition:width .3s"
              :style="`width:${(cat.score / cat.max) * 100}%;background:${cat.status === 'ok' ? 'var(--success)' : cat.status === 'warning' ? 'var(--warning)' : 'var(--danger)'}`"
            ></div>
          </div>
          <div v-if="cat.detail" style="font-size:.65rem;color:var(--text-muted);margin-top:.15rem">
            {{ cat.detail }}
          </div>
          <div
            v-for="rec in (cat.recommendations || [])"
            :key="rec"
            style="font-size:.65rem;color:var(--warning);padding-left:.5rem"
          >
            <i class="fas fa-exclamation-triangle" style="margin-right:.2rem;font-size:.55rem"></i>
            {{ rec }}
          </div>
        </div>
        <div
          v-if="healthScore.timestamp"
          style="font-size:.65rem;color:var(--text-muted);text-align:right;margin-top:.4rem"
        >
          Updated: {{ new Date(healthScore.timestamp * 1000).toLocaleTimeString() }}
        </div>
      </div>
    </div>

    <!-- ── Custom dashboards toolbar ──────────────────────────────────────── -->
    <div style="display:flex;align-items:center;gap:.5rem;margin:.75rem 0;flex-wrap:wrap">
      <select
        v-if="savedDashboards.length > 0"
        class="theme-select"
        style="font-size:.75rem;padding:.3rem .5rem"
        @change="e => { const d = savedDashboards.find(x => String(x.id) === e.target.value); if (d) loadDashboard(d); e.target.value = '' }"
      >
        <option value="">Load dashboard…</option>
        <option
          v-for="d in savedDashboards"
          :key="d.id"
          :value="d.id"
        >{{ d.name }}</option>
      </select>

      <button
        class="btn btn-xs btn-secondary"
        type="button"
        title="Save current layout"
        @click="showSaveModal = !showSaveModal"
      >
        <i class="fas fa-save"></i> Save Layout
      </button>

      <template v-if="showSaveModal">
        <input
          v-model="saveDashboardName"
          class="field-input"
          type="text"
          placeholder="Dashboard name…"
          style="font-size:.75rem;padding:.3rem .5rem;max-width:180px"
          @keyup.enter="saveDashboard"
        >
        <button
          class="btn btn-xs"
          type="button"
          :disabled="!saveDashboardName.trim()"
          @click="saveDashboard"
        >Save</button>
      </template>

      <button
        v-if="savedDashboards.length > 0"
        class="btn btn-xs btn-secondary"
        type="button"
        style="margin-left:.25rem"
        title="Manage saved dashboards"
        @click="showSaveModal = false"
      >
        <i class="fas fa-trash"></i>
      </button>
      <template v-if="savedDashboards.length > 0">
        <span
          v-for="d in savedDashboards"
          :key="'del-' + d.id"
          style="display:none"
        ></span>
      </template>
    </div>

    <!-- ── Card grid ───────────────────────────────────────────────────────── -->
    <div ref="gridRef" class="grid" :class="{ 'glance-mode': glanceMode }">
      <!-- System cards -->
      <CoreSystemCard     v-if="showCard('core')"                                        />
      <SystemHealthCard                                                                   />
      <UptimeCard                                                                         />
      <NetworkIoCard      v-if="showCard('netio')"                                       />
      <HardwareCard       v-if="showCard('hw')"                                          />
      <StorageCard        v-if="showCard('storage')"                                     />
      <DiskHealthCard     v-if="showCard('scrutiny')"                                    />
      <DiskIoCard         v-if="showCard('diskIo')"                                      />
      <NetworkRadarCard   v-if="showCard('radar')"                                       />
      <ProcessesCard      v-if="showCard('procs')"                                       />
      <BatteryCard        v-if="showCard('battery')"                                     />
      <AgentsCard         v-if="showCard('agents')"                                      />
      <CertExpiryCard     v-if="showCard('certExpiry')"                                  />
      <DevicePresenceCard                                                                 />
      <ContainersCard     v-if="showCard('containers')"                                  />
      <AutomationsCard    v-if="showCard('automations')"                                 />
      <QuickActionsCard   v-if="showCard('actions')"                                     />
      <BookmarksCard      v-if="showCard('bookmarks')"                                   />

      <!-- DNS / Network integrations -->
      <PiholeCard      v-if="showCard('pihole')      && settingsStore.data.piholeUrl"    />
      <AdguardCard     v-if="showCard('adguard')     && settingsStore.data.adguardUrl"   />
      <UnifiCard       v-if="showCard('unifi')       && settingsStore.data.unifiUrl"     />
      <SpeedtestCard   v-if="showCard('speedtest')   && settingsStore.data.speedtestUrl" />
      <TailscaleCard   v-if="showCard('tailscale')   && dashboardStore.live.tailscale"   />

      <!-- Storage integrations -->
      <TruenasCard     v-if="showCard('truenas')     && settingsStore.data.truenasUrl"   />

      <!-- Media integrations -->
      <PlexCard        v-if="showCard('plex')        && settingsStore.data.plexUrl"      />
      <DownloadsCard   v-if="showCard('downloads')   && (settingsStore.data.qbitUrl || settingsStore.data.radarrUrl || settingsStore.data.sonarrUrl)" />
      <JellyfinCard    v-if="showCard('jellyfin')    && settingsStore.data.jellyfinUrl"  />
      <LidarrCard      v-if="showCard('lidarr')      && settingsStore.data.lidarrUrl"    />
      <ReadarrCard     v-if="showCard('readarr')     && settingsStore.data.readarrUrl"   />
      <BazarrCard      v-if="showCard('bazarr')      && settingsStore.data.bazarrUrl"    />

      <!-- Home automation -->
      <HassCard        v-if="showCard('hass')        && settingsStore.data.hassUrl"      />
      <FrigateCard     v-if="showCard('frigate')     && settingsStore.data.frigateUrl"   />

      <!-- Infrastructure integrations -->
      <KumaCard        v-if="showCard('kuma')        && settingsStore.data.kumaUrl"      />
      <ProxmoxCard     v-if="showCard('proxmox')     && settingsStore.data.proxmoxUrl"   />
      <VaultwardenCard v-if="showCard('vaultwarden') && settingsStore.data.vaultwardenUrl" />
      <VpnCard         v-if="showCard('vpn')         && dashboardStore.live.vpn"         />

      <!-- Data-driven cards (no URL needed) -->
      <EnergyCard      v-if="(dashboardStore.live.energy || []).length > 0"              />
      <CameraFeedsCard v-if="(dashboardStore.live.cameraFeeds || []).length > 0"         />

      <!-- Prediction -->
      <PredictionCard  v-if="showCard('prediction')"                                      />

      <!-- Admin-only -->
      <RecoveryCard    v-if="showCard('recovery')"                                        />

      <!-- Managed Integration Cards -->
      <IntegrationCard
        v-for="inst in managedInstances"
        :key="'int-'+inst.id"
        :instance="inst"
        :template="getCardTemplate(inst.platform)"
        :data="getIntegrationData(inst.id)"
        class="card"
      />
    </div>

    <!-- Glance-mode toggle — floats over the header area via slot or direct button -->
    <!-- Exposed as a ref so AppHeader or a parent can bind to it if needed -->
  </div>
</template>
