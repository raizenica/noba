<script setup>
import { ref, provide, onMounted, watch } from 'vue'
import { useAuthStore } from './stores/auth'
import { useDashboardStore } from './stores/dashboard'
import { useSettingsStore } from './stores/settings'
import AppSidebar from './components/layout/AppSidebar.vue'
import AppHeader from './components/layout/AppHeader.vue'
import ToastContainer from './components/ui/ToastContainer.vue'

const auth = useAuthStore()
const dashboard = useDashboardStore()
const settings = useSettingsStore()

const sidebarCollapsed = ref(false)
provide('sidebarCollapsed', sidebarCollapsed)
provide('toggleSidebar', () => { sidebarCollapsed.value = !sidebarCollapsed.value })

onMounted(async () => {
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
    </template>
    <router-view v-else />
    <ToastContainer />
  </div>
</template>
