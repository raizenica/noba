<script setup>
import { ref, computed, onMounted } from 'vue'
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

const dashboardStore = useDashboardStore()
const settingsStore  = useSettingsStore()
const { get }        = useApi()

// ── Glance mode ──────────────────────────────────────────────────────────────
const glanceMode = ref(false)

// ── Alert dismissal ──────────────────────────────────────────────────────────
const dismissedAlerts = ref(new Set())

const visibleAlerts = computed(() =>
  (dashboardStore.live.alerts || []).filter(
    a => !dismissedAlerts.value.has(a.message)
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

onMounted(() => {
  fetchHealthScore()
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
        :key="alert.message"
        class="alert"
        :class="alert.level"
      >
        <i
          class="fas"
          :class="alert.level === 'danger' ? 'fa-exclamation-circle' : 'fa-exclamation-triangle'"
          style="margin-right:.5rem;flex-shrink:0"
        ></i>
        <span style="flex:1">{{ alert.message }}</span>
        <button
          class="alert-dismiss"
          type="button"
          title="Dismiss"
          @click="dismissAlert(alert.message)"
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
        <div style="flex:1;min-width:0">
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

    <!-- ── Card grid ───────────────────────────────────────────────────────── -->
    <!--
      Cards are added in Tasks 9-10.
      Usage pattern:
        <SystemHealthCard v-if="showCard('core')" />

      Row content pattern (uses existing CSS, no extra component needed):
        <div class="row">
          <span class="row-label">Label</span>
          <span class="row-val">Value</span>
        </div>
    -->
    <div class="grid" :class="{ 'glance-mode': glanceMode }">
      <CoreSystemCard     v-if="showCard('core')"          />
      <SystemHealthCard                                     />
      <UptimeCard                                           />
      <NetworkIoCard      v-if="showCard('netio')"         />
      <HardwareCard       v-if="showCard('hw')"            />
      <StorageCard        v-if="showCard('storage')"       />
      <DiskHealthCard     v-if="showCard('scrutiny')"      />
      <DiskIoCard         v-if="showCard('diskIo')"        />
      <NetworkRadarCard   v-if="showCard('radar')"         />
      <ProcessesCard      v-if="showCard('procs')"         />
      <BatteryCard        v-if="showCard('battery')"       />
      <AgentsCard         v-if="showCard('agents')"        />
      <CertExpiryCard     v-if="showCard('certExpiry')"    />
      <DevicePresenceCard                                   />
      <ContainersCard     v-if="showCard('containers')"    />
      <AutomationsCard    v-if="showCard('automations')"   />
      <QuickActionsCard   v-if="showCard('actions')"       />
      <BookmarksCard      v-if="showCard('bookmarks')"     />
    </div>

    <!-- Glance-mode toggle — floats over the header area via slot or direct button -->
    <!-- Exposed as a ref so AppHeader or a parent can bind to it if needed -->
  </div>
</template>
