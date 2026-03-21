<script setup>
import { ref, provide, onMounted, onUnmounted, watch } from 'vue'
import { useAuthStore } from './stores/auth'
import { useDashboardStore } from './stores/dashboard'
import { useSettingsStore } from './stores/settings'
import { useModalsStore } from './stores/modals'
import AppSidebar from './components/layout/AppSidebar.vue'
import AppHeader from './components/layout/AppHeader.vue'
import ToastContainer from './components/ui/ToastContainer.vue'
import HistoryModal from './components/modals/HistoryModal.vue'
import SmartModal from './components/modals/SmartModal.vue'
import ProfileModal from './components/modals/ProfileModal.vue'
import SearchModal from './components/modals/SearchModal.vue'
import TerminalModal from './components/modals/TerminalModal.vue'
import SessionsModal from './components/modals/SessionsModal.vue'
import SystemInfoModal from './components/modals/SystemInfoModal.vue'
import NetworkModal from './components/modals/NetworkModal.vue'
import ProcessModal from './components/modals/ProcessModal.vue'
import BackupExplorerModal from './components/modals/BackupExplorerModal.vue'

const auth = useAuthStore()
const dashboard = useDashboardStore()
const settings = useSettingsStore()
const modals = useModalsStore()

const sidebarCollapsed = ref(false)
provide('sidebarCollapsed', sidebarCollapsed)
provide('toggleSidebar', () => { sidebarCollapsed.value = !sidebarCollapsed.value })

// ── Ctrl+K global shortcut ────────────────────────────────────────────────────
function onKeyDown(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault()
    modals.searchModal = !modals.searchModal
  }
  if (e.key === 'Escape') {
    modals.searchModal = false
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKeyDown)

  // Handle OIDC callback token from URL hash
  const hash = window.location.hash
  if (hash && hash.includes('token=')) {
    const params = new URLSearchParams(hash.substring(hash.indexOf('?')))
    const token = params.get('token')
    if (token) {
      auth.setToken(token)
      window.history.replaceState({}, '', '/#/dashboard')
    }
  }

  if (auth.token) {
    await auth.fetchUserInfo()
    if (auth.authenticated) {
      await settings.fetchSettings()
      await settings.fetchPreferences()
      dashboard.connectSse()
    }
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
})

watch(() => auth.authenticated, (val) => {
  if (!val) dashboard.disconnectSse()
})
</script>

<template>
  <div
    class="app-layout"
    :class="{ 'sidebar-collapsed': sidebarCollapsed }"
    :data-theme="settings.preferences.theme || 'default'"
  >
    <template v-if="auth.authenticated">
      <AppSidebar />
      <AppHeader />
      <main class="app-content">
        <router-view />
      </main>

      <!-- Global modals — mounted once, opened via modals store -->
      <HistoryModal />
      <SmartModal />
      <ProfileModal />
      <SearchModal />
      <TerminalModal />
      <SessionsModal />
      <SystemInfoModal />
      <NetworkModal />
      <ProcessModal />
      <BackupExplorerModal />
    </template>
    <router-view v-else />
    <ToastContainer />
  </div>
</template>
