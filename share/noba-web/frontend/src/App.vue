<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, provide, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
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
import AiChatPanel from './components/modals/AiChatPanel.vue'
import AppModal from './components/ui/AppModal.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const isStandalone = computed(() => !!route.meta?.standalone)
const dashboard = useDashboardStore()
const settings = useSettingsStore()
const modals = useModalsStore()

const isMobile = () => window.innerWidth <= 640
const sidebarCollapsed = ref(isMobile())
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
  if (e.key === 'Enter' && modals.confirmDialog.show) {
    e.preventDefault()
    modals.confirmYes()
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKeyDown)

  // Handle OIDC callback: exchange one-time code for auth token
  const hash = window.location.hash
  if (hash && hash.includes('oidc_code=')) {
    const codeMatch = hash.match(/oidc_code=([^&]+)/)
    if (codeMatch) {
      try {
        const res = await fetch('/api/auth/oidc/exchange', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code: codeMatch[1] }),
        })
        if (res.ok) {
          const data = await res.json()
          auth.setToken(data.token)
        }
      } catch { /* OIDC exchange failed */ }
      window.history.replaceState({}, '', '/#/dashboard')
    }
  }

  if (auth.token) {
    await auth.fetchUserInfo()
    if (auth.authenticated) {
      await settings.fetchSettings()
      await settings.fetchPreferences()
      if (!isMobile() && settings.preferences.sidebarCollapsed !== undefined) {
        sidebarCollapsed.value = settings.preferences.sidebarCollapsed
      }
      dashboard.connectSse()
    }
  }
  if (!auth.authenticated) {
    router.push('/login')
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
})

watch(() => auth.authenticated, (val) => {
  if (!val) {
    dashboard.disconnectSse()
    router.push('/login')
  }
})

// Auto-collapse sidebar on navigation (mobile)
watch(() => router.currentRoute.value.path, () => {
  if (isMobile()) sidebarCollapsed.value = true
})

// Save sidebar state to preferences
watch(sidebarCollapsed, (val) => {
  if (!isMobile() && auth.authenticated && settings.preferences.sidebarCollapsed !== val) {
    settings.preferences.sidebarCollapsed = val
    settings.savePreferences().catch(() => {})
  }
})

// ── Theme persistence ─────────────────────────────────────────────────────────
const _lsTheme = localStorage.getItem('noba-theme') || 'default'
const activeTheme = computed(() =>
  settings.preferences?.theme || settings.preferences?.preferences?.theme || _lsTheme
)
watch(activeTheme, (t) => { localStorage.setItem('noba-theme', t) })
</script>

<template>
  <div
    class="app-layout"
    :class="{ 'sidebar-collapsed': sidebarCollapsed, 'no-sidebar': !auth.authenticated }"
    :data-theme="activeTheme"
  >
    <!-- Standalone routes (e.g. RDP viewer) — no chrome -->
    <template v-if="isStandalone && auth.authenticated">
      <router-view />
    </template>

    <template v-else-if="auth.authenticated">
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
      <AiChatPanel />

      <!-- Floating AI chat button — shown when AI is enabled -->
      <button
        v-if="settings.data.llmEnabled"
        class="ai-fab"
        title="AI Ops Assistant"
        @click="modals.aiChat = !modals.aiChat"
      >
        <i class="fas fa-robot"></i>
      </button>
    </template>
    <router-view v-else />
    <ToastContainer />

    <!-- Global confirm dialog — any component can call modals.confirm('...') -->
    <AppModal :show="modals.confirmDialog.show" title="Confirm" @close="modals.confirmNo()">
      <p style="padding:1rem">{{ modals.confirmDialog.message }}</p>
      <template #footer>
        <button class="btn" @click="modals.confirmNo()">Cancel</button>
        <button class="btn btn-danger" @click="modals.confirmYes()">Confirm</button>
      </template>
    </AppModal>
  </div>
</template>
