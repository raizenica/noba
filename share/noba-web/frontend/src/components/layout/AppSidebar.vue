<script setup>
import { ref, inject } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { useDashboardStore } from '../../stores/dashboard'

const route = useRoute()
const authStore = useAuthStore()
const dashboardStore = useDashboardStore()

const sidebarCollapsed = inject('sidebarCollapsed')
const toggleSidebar = inject('toggleSidebar')

const settingsExpanded = ref(false)

const settingsTabs = [
  { tab: 'general', label: 'General', adminOnly: false },
  { tab: 'visibility', label: 'Visibility', adminOnly: false },
  { tab: 'integrations', label: 'Integrations', adminOnly: false },
  { tab: 'backup', label: 'Backup', adminOnly: false },
  { tab: 'users', label: 'Users', adminOnly: true },
  { tab: 'alerts', label: 'Alerts', adminOnly: false },
  { tab: 'statuspage', label: 'Status Page', adminOnly: true },
  { tab: 'shortcuts', label: 'Shortcuts', adminOnly: false },
  { tab: 'plugins', label: 'Plugins', adminOnly: true },
]

function isSettingsActive() {
  return route.path.startsWith('/settings')
}

function onSettingsClick() {
  settingsExpanded.value = !settingsExpanded.value
}

function onlineAgentCount() {
  return (dashboardStore.live.agents || []).filter(a => a.online).length
}
</script>

<template>
  <aside class="app-sidebar" :class="{ 'mobile-open': !sidebarCollapsed }">
    <div class="app-sidebar-logo">
      <div class="logo-mark" aria-hidden="true"><i class="fas fa-terminal"></i></div>
      <div class="logo-text">
        <div class="logo-name">NOBA</div>
        <div class="logo-tagline">Command Center</div>
      </div>
    </div>

    <nav class="app-sidebar-nav">
      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'dashboard' }" to="/dashboard">
        <i class="fas fa-th-large nav-icon"></i>
        <span class="nav-label">Dashboard</span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'agents' }" to="/agents">
        <i class="fas fa-robot nav-icon"></i>
        <span class="nav-label">Agents</span>
        <span v-if="onlineAgentCount() > 0" class="nav-badge">{{ onlineAgentCount() }}</span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'monitoring' }" to="/monitoring">
        <i class="fas fa-chart-line nav-icon"></i>
        <span class="nav-label">Monitoring</span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'infrastructure' }" to="/infrastructure">
        <i class="fas fa-server nav-icon"></i>
        <span class="nav-label">Infrastructure</span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'automations' }" to="/automations">
        <i class="fas fa-bolt nav-icon"></i>
        <span class="nav-label">Automations</span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'logs' }" to="/logs">
        <i class="fas fa-scroll nav-icon"></i>
        <span class="nav-label">Logs</span>
      </router-link>

      <router-link class="sidebar-nav-item" :class="{ active: route.name === 'security' }" to="/security">
        <i class="fas fa-shield-alt nav-icon"></i>
        <span class="nav-label">Security</span>
      </router-link>

      <a
        v-if="authStore.isAdmin"
        class="sidebar-nav-item"
        href="/api/docs"
        target="_blank"
        title="API Documentation"
      >
        <i class="fas fa-book nav-icon"></i>
        <span class="nav-label">API Docs</span>
        <i class="fas fa-external-link-alt nav-label" style="font-size:9px;opacity:.3;margin-left:auto"></i>
      </a>

      <div class="sidebar-divider"></div>

      <div
        class="sidebar-nav-item"
        :class="{ active: isSettingsActive() }"
        @click="onSettingsClick"
      >
        <i class="fas fa-cog nav-icon"></i>
        <span class="nav-label">Settings</span>
        <i
          class="fas nav-label"
          :class="settingsExpanded ? 'fa-chevron-down' : 'fa-chevron-right'"
          style="font-size:9px;opacity:.4;margin-left:auto"
        ></i>
      </div>

      <div v-show="settingsExpanded" class="sidebar-sub-items">
        <template v-for="item in settingsTabs" :key="item.tab">
          <router-link
            v-if="!item.adminOnly || authStore.isAdmin"
            class="sidebar-sub-item"
            :class="{ active: route.path === `/settings/${item.tab}` }"
            :to="`/settings/${item.tab}`"
          >{{ item.label }}</router-link>
        </template>
      </div>
    </nav>

    <div class="sidebar-user">
      <div class="sidebar-user-avatar">
        {{ (authStore.username || '?')[0].toUpperCase() }}
      </div>
      <div class="sidebar-user-info">
        <div class="sidebar-user-name">{{ authStore.username }}</div>
        <div class="sidebar-user-role">{{ authStore.userRole }}</div>
      </div>
      <button class="icon-btn" style="opacity:.4" title="Logout" @click="authStore.logout()">
        <i class="fas fa-sign-out-alt"></i>
      </button>
    </div>

    <div
      class="sidebar-backdrop"
      v-show="!sidebarCollapsed"
      @click="toggleSidebar()"
    ></div>
  </aside>
</template>
