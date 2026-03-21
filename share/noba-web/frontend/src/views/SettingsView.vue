<script setup>
import { computed, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const tab = computed(() => route.params.tab || 'general')

const tabs = [
  { key: 'general',    label: 'General',     icon: 'fa-database' },
  { key: 'visibility', label: 'Visibility',  icon: 'fa-eye' },
  { key: 'integrations', label: 'Integrations', icon: 'fa-plug' },
  { key: 'backup',     label: 'Backup',      icon: 'fa-archive' },
  { key: 'users',      label: 'Users',       icon: 'fa-users',        admin: true },
  { key: 'alerts',     label: 'Alerts',      icon: 'fa-bell' },
  { key: 'statuspage', label: 'Status Page', icon: 'fa-signal',       admin: true },
  { key: 'shortcuts',  label: 'Shortcuts',   icon: 'fa-keyboard' },
  { key: 'plugins',    label: 'Plugins',     icon: 'fa-puzzle-piece', admin: true },
]

const tabComponents = {
  general:      defineAsyncComponent(() => import('../components/settings/GeneralTab.vue')),
  visibility:   defineAsyncComponent(() => import('../components/settings/VisibilityTab.vue')),
  integrations: defineAsyncComponent(() => import('../components/settings/IntegrationsTab.vue')),
  backup:       defineAsyncComponent(() => import('../components/settings/BackupTab.vue')),
  users:        defineAsyncComponent(() => import('../components/settings/UsersTab.vue')),
  alerts:       defineAsyncComponent(() => import('../components/settings/AlertsTab.vue')),
  statuspage:   defineAsyncComponent(() => import('../components/settings/StatusPageTab.vue')),
  shortcuts:    defineAsyncComponent(() => import('../components/settings/ShortcutsTab.vue')),
  plugins:      defineAsyncComponent(() => import('../components/settings/PluginsTab.vue')),
}

const tabComponent = computed(() => tabComponents[tab.value])

function navigateTab(key) {
  router.push({ name: 'settings', params: { tab: key } })
}

const currentTabDef = computed(() => tabs.find(t => t.key === tab.value) || tabs[0])
</script>

<template>
  <div>
    <!-- Page header -->
    <h2 style="margin-bottom:1rem">
      <i class="fas" :class="'fa-' + (currentTabDef.icon || 'cog')" style="margin-right:.5rem"></i>
      Settings &mdash; {{ currentTabDef.label }}
    </h2>

    <!-- Tab bar -->
    <div class="tab-bar" style="margin-bottom:1.25rem;display:flex;flex-wrap:wrap;gap:.3rem">
      <button
        v-for="t in tabs"
        :key="t.key"
        class="btn btn-xs"
        :class="{ 'btn-primary': tab === t.key }"
        @click="navigateTab(t.key)"
      >
        <i class="fas" :class="t.icon" style="margin-right:.3rem"></i>
        {{ t.label }}
        <span v-if="t.admin" style="font-size:.55rem;opacity:.6;margin-left:.2rem">(admin)</span>
      </button>
    </div>

    <!-- Tab content -->
    <Suspense>
      <component :is="tabComponent" />
      <template #fallback>
        <div style="padding:2rem;text-align:center;color:var(--text-muted)">
          <i class="fas fa-spinner fa-spin"></i> Loading...
        </div>
      </template>
    </Suspense>
  </div>
</template>
