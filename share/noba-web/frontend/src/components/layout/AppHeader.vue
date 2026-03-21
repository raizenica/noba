<script setup>
import { inject } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import { useSettingsStore } from '../../stores/settings'
import { useNotificationsStore } from '../../stores/notifications'

const toggleSidebar = inject('toggleSidebar')

const dashboardStore = useDashboardStore()
const settingsStore = useSettingsStore()
const notifStore = useNotificationsStore()

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
</script>

<template>
  <header class="app-header">
    <button class="icon-btn" title="Toggle sidebar" @click="toggleSidebar()">
      <i class="fas fa-bars"></i>
    </button>

    <div class="header-search">
      <i class="fas fa-search search-icon"></i>
      <input
        type="text"
        placeholder="Search commands, agents, settings..."
        readonly
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

    <span
      v-if="dashboardStore.offlineMode"
      class="offline-badge"
    ><i class="fas fa-wifi-slash" style="font-size:.6rem"></i> Offline</span>

    <span class="live-pill" :class="`conn-${dashboardStore.connStatus}`">
      <span class="live-dot" :class="dashboardStore.connStatus"></span>
      {{ connLabel() }}
    </span>
  </header>
</template>
