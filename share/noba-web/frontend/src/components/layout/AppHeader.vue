<script setup>
import { ref, inject, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useDashboardStore } from '../../stores/dashboard'
import { useSettingsStore } from '../../stores/settings'
import { useNotificationsStore } from '../../stores/notifications'
import { useAuthStore } from '../../stores/auth'
import { useModalsStore } from '../../stores/modals'
import { useApprovalsStore } from '../../stores/approvals'
import { useApi } from '../../composables/useApi'

const toggleSidebar = inject('toggleSidebar')
const router = useRouter()

const dashboardStore = useDashboardStore()
const settingsStore = useSettingsStore()
const notifStore = useNotificationsStore()
const auth = useAuthStore()
const modals = useModalsStore()
const approvalsStore = useApprovalsStore()
const { get } = useApi()

// ── Active maintenance windows ──────────────────────────────────────────────
const activeMaintenanceWindows = ref([])

async function fetchActiveMaintenanceWindows() {
  try {
    const data = await get('/api/maintenance-windows/active')
    activeMaintenanceWindows.value = Array.isArray(data) ? data : []
  } catch { /* silent */ }
}

const maintenanceTooltip = () =>
  activeMaintenanceWindows.value.map(w => w.name).join(', ')

let _approvalPollInterval   = null
let _maintenancePollInterval = null

onMounted(() => {
  approvalsStore.fetchCount()
  _approvalPollInterval = setInterval(() => approvalsStore.fetchCount(), 30_000)

  fetchActiveMaintenanceWindows()
  _maintenancePollInterval = setInterval(fetchActiveMaintenanceWindows, 60_000)
})

onUnmounted(() => {
  clearInterval(_approvalPollInterval)
  clearInterval(_maintenancePollInterval)
})

const themes = [
  { value: 'auto', label: 'System' },
  { value: 'default', label: 'Operator' },
  { value: 'catppuccin', label: 'Catppuccin' },
  { value: 'tokyo', label: 'Tokyo' },
  { value: 'gruvbox', label: 'Gruvbox' },
  { value: 'dracula', label: 'Dracula' },
  { value: 'nord', label: 'Nord' },
]

function onThemeChange(event) {
  const theme = event.target.value
  localStorage.setItem('noba-theme', theme)
  settingsStore.preferences.theme = theme
  settingsStore.savePreferences().catch(() => {})
}

function connLabel() {
  switch (dashboardStore.connStatus) {
    case 'sse': return 'Live'
    case 'polling': return 'Polling'
    default: return 'Offline'
  }
}

function openSearch() {
  modals.searchModal = true
}

function openProfile() {
  modals.profileModal = true
}
</script>

<template>
  <header class="app-header">
    <button class="icon-btn" title="Toggle sidebar" @click="toggleSidebar()">
      <i class="fas fa-bars"></i>
    </button>

    <div class="header-search" style="cursor:pointer" @click="openSearch" title="Search (Ctrl+K)">
      <i class="fas fa-search search-icon"></i>
      <input
        type="text"
        placeholder="Search commands, agents, settings..."
        readonly
        style="cursor:pointer"
      >
      <span class="search-kbd">Ctrl+K</span>
    </div>

    <div style="flex:1"></div>

    <button class="icon-btn" title="Refresh" @click="dashboardStore.refreshStats()">
      <i class="fas fa-sync-alt"></i>
    </button>

    <select
      class="field-select"
      style="width:auto;font-size:11px;padding:3px 6px"
      :value="settingsStore.preferences.theme || 'default'"
      @change="onThemeChange"
    >
      <option v-for="t in themes" :key="t.value" :value="t.value">{{ t.label }}</option>
    </select>

    <button class="icon-btn" title="Notifications" style="position:relative">
      <i class="fas fa-bell"></i>
      <span
        v-if="(notifStore.unreadCount || 0) > 0"
        class="notif-badge"
      >{{ notifStore.unreadCount }}</span>
    </button>

    <button
      v-if="(approvalsStore.count || 0) > 0"
      class="icon-btn"
      title="Pending Approvals"
      style="position:relative"
      @click="router.push('/automations')"
    >
      <i class="fas fa-check-circle" style="color:var(--warning, #f0a500)"></i>
      <span class="notif-badge" style="background:var(--warning, #f0a500);color:#000">
        {{ approvalsStore.count }}
      </span>
    </button>

    <span
      v-if="dashboardStore.offlineMode"
      class="offline-badge"
    ><i class="fas fa-wifi-slash" style="font-size:.6rem"></i> Offline</span>

    <!-- Active maintenance window indicator -->
    <span
      v-if="activeMaintenanceWindows.length > 0"
      class="live-pill"
      style="background:color-mix(in srgb, var(--warning, #f0a500) 15%, transparent);border:1px solid var(--warning, #f0a500);color:var(--warning, #f0a500);cursor:default"
      :title="maintenanceTooltip()"
    >
      <i class="fas fa-wrench" style="font-size:.6rem"></i>
      Maintenance
    </span>

    <span class="live-pill" :class="`conn-${dashboardStore.connStatus}`">
      <span class="live-dot" :class="dashboardStore.connStatus"></span>
      {{ connLabel() }}
    </span>

    <!-- User avatar — opens profile modal -->
    <button
      class="icon-btn"
      title="Profile"
      @click="openProfile"
      style="margin-left:.25rem"
    >
      <i class="fas fa-user-circle" style="font-size:1.1rem"></i>
    </button>
  </header>
</template>
