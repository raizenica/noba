<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const tabSearch = ref('')
const tab = computed(() => route.params.tab || 'general')

const tabs = [
  { key: 'general',    label: 'General',     icon: 'fa-database' },
  { key: 'visibility', label: 'Visibility',  icon: 'fa-eye' },
  { key: 'integrations', label: 'Integrations', icon: 'fa-plug' },
  { key: 'backup',     label: 'Backup',      icon: 'fa-archive' },
  { key: 'users',      label: 'Users',       icon: 'fa-users',        admin: true },
  { key: 'alerts',      label: 'Alerts',      icon: 'fa-bell' },
  { key: 'healing',     label: 'Healing',     icon: 'fa-heartbeat' },
  { key: 'maintenance', label: 'Maintenance', icon: 'fa-tools' },
  { key: 'statuspage', label: 'Status Page', icon: 'fa-signal',       admin: true },
  { key: 'shortcuts',  label: 'Shortcuts',   icon: 'fa-keyboard' },
  { key: 'plugins',    label: 'Plugins',     icon: 'fa-puzzle-piece', admin: true },
]

const filteredTabs = computed(() => {
  if (!tabSearch.value.trim()) return tabs
  const q = tabSearch.value.toLowerCase()
  return tabs.filter(t => 
    t.label.toLowerCase().includes(q) || 
    t.key.toLowerCase().includes(q)
  )
})

const tabComponents = {
  general:      defineAsyncComponent(() => import('../components/settings/GeneralTab.vue')),
  visibility:   defineAsyncComponent(() => import('../components/settings/VisibilityTab.vue')),
  integrations: defineAsyncComponent(() => import('../components/settings/IntegrationsTab.vue')),
  backup:       defineAsyncComponent(() => import('../components/settings/BackupTab.vue')),
  users:        defineAsyncComponent(() => import('../components/settings/UsersTab.vue')),
  alerts:       defineAsyncComponent(() => import('../components/settings/AlertsTab.vue')),
  healing:      defineAsyncComponent(() => import('../components/settings/HealingTab.vue')),
  maintenance:  defineAsyncComponent(() => import('../components/settings/MaintenanceTab.vue')),
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

    <!-- Tab bar with filter -->
    <div style="margin-bottom:1.25rem;display:flex;flex-direction:column;gap:.75rem">
      <div class="reveal-wrap" style="max-width:300px">
        <input
          v-model="tabSearch"
          type="text"
          class="field-input"
          placeholder="Filter settings..."
          style="padding-left:2.2rem"
        >
        <i class="fas fa-search" style="position:absolute;left:.8rem;opacity:.3;font-size:.85rem"></i>
        <button v-if="tabSearch" class="reveal-btn" @click="tabSearch = ''" style="right:.4rem" aria-label="Clear search">
          <i class="fas fa-times"></i>
        </button>
      </div>

      <div class="tab-bar" style="display:flex;flex-wrap:wrap;gap:.3rem">
        <button
          v-for="t in filteredTabs"
          :key="t.key"
          class="btn btn-xs"
          :class="{ 'btn-primary': tab === t.key }"
          @click="navigateTab(t.key)"
        >
          <i class="fas" :class="t.icon" style="margin-right:.3rem"></i>
          {{ t.label }}
          <span v-if="t.admin" style="font-size:.55rem;opacity:.6;margin-left:.2rem">(admin)</span>
        </button>
        <div v-if="filteredTabs.length === 0" style="padding:.4rem;color:var(--text-muted);font-size:.8rem;font-style:italic">
          No matching categories found.
        </div>
      </div>
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
