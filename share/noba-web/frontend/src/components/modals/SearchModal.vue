<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import AppModal from '../ui/AppModal.vue'
import { useModalsStore } from '../../stores/modals'
import { useDashboardStore } from '../../stores/dashboard'

const modals = useModalsStore()
const dashboardStore = useDashboardStore()
const router = useRouter()

const searchQuery = ref('')
const searchInput = ref(null)

// ── Pages catalog ─────────────────────────────────────────────────────────────
const PAGES = [
  { id: 'p-dashboard',      label: 'Dashboard',       icon: 'fa-th-large',      category: 'page',    action: () => router.push('/dashboard') },
  { id: 'p-agents',         label: 'Agents',          icon: 'fa-robot',         category: 'page',    action: () => router.push('/agents') },
  { id: 'p-monitoring',     label: 'Monitoring',      icon: 'fa-chart-line',    category: 'page',    action: () => router.push('/monitoring') },
  { id: 'p-infrastructure', label: 'Infrastructure',  icon: 'fa-server',        category: 'page',    action: () => router.push('/infrastructure') },
  { id: 'p-automations',    label: 'Automations',     icon: 'fa-bolt',          category: 'page',    action: () => router.push('/automations') },
  { id: 'p-logs',           label: 'Logs',            icon: 'fa-file-alt',      category: 'page',    action: () => router.push('/logs') },
  { id: 'p-security',       label: 'Security',        icon: 'fa-shield-alt',    category: 'page',    action: () => router.push('/security') },
  { id: 'p-settings',       label: 'Settings',        icon: 'fa-cog',           category: 'page',    action: () => router.push('/settings') },
]

// ── Modal shortcuts ───────────────────────────────────────────────────────────
const MODAL_SHORTCUTS = [
  { id: 'm-profile',   label: 'Profile',          icon: 'fa-user',       category: 'modal', action: () => { modals.profileModal = true } },
  { id: 'm-smart',     label: 'SMART Disk Health', icon: 'fa-hdd',        category: 'modal', action: () => { modals.smartModal = true } },
  { id: 'm-terminal',  label: 'Terminal',          icon: 'fa-terminal',   category: 'modal', action: () => { modals.terminalModal = true } },
  { id: 'm-sessions',  label: 'Active Sessions',   icon: 'fa-users',      category: 'modal', action: () => { modals.sessionsModal = true } },
  { id: 'm-network',   label: 'Network Connections', icon: 'fa-network-wired', category: 'modal', action: () => { modals.networkModal = true } },
  { id: 'm-process',   label: 'Process List',      icon: 'fa-microchip',  category: 'modal', action: () => { modals.processModal = true } },
  { id: 'm-sysinfo',   label: 'System Info',       icon: 'fa-info-circle', category: 'modal', action: () => { modals.systemInfoModal = true } },
  { id: 'm-backup',    label: 'Backup Explorer',   icon: 'fa-archive',    category: 'modal', action: () => { modals.backupExplorerModal = true } },
]

// ── Agent results ─────────────────────────────────────────────────────────────
const agentResults = computed(() => {
  const agents = dashboardStore.live.agents || []
  return agents.map(a => ({
    id: `agent-${a.hostname}`,
    label: a.hostname,
    icon: 'fa-robot',
    category: 'agent',
    action: () => { router.push('/agents') },
  }))
})

// ── All searchable items ──────────────────────────────────────────────────────
const allItems = computed(() => [
  ...PAGES,
  ...MODAL_SHORTCUTS,
  ...agentResults.value,
])

const searchResults = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return PAGES.slice(0, 8)
  return allItems.value
    .filter(item => item.label.toLowerCase().includes(q) || item.category.toLowerCase().includes(q))
    .slice(0, 15)
})

function selectResult(item) {
  item.action()
  close()
}

function close() {
  modals.searchModal = false
  searchQuery.value = ''
}

watch(() => modals.searchModal, (val) => {
  if (val) {
    nextTick(() => searchInput.value?.focus())
  }
})
</script>

<template>
  <!-- Custom full-screen overlay — not using AppModal to have tight control over layout -->
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="modals.searchModal"
        class="modal-overlay"
        style="z-index:2000;align-items:flex-start;padding-top:15vh"
        @click.self="close"
        @keydown.escape="close"
      >
        <div class="modal-box" style="max-width:540px;width:100%;margin:0 1rem">
          <div style="display:flex;align-items:center;gap:.5rem;padding:.75rem 1rem;border-bottom:1px solid var(--border)">
            <i class="fas fa-search" style="opacity:.4"></i>
            <input
              ref="searchInput"
              v-model="searchQuery"
              type="text"
              class="field-input"
              style="flex:1;border:none;background:transparent;padding:.25rem;font-size:1rem;outline:none"
              placeholder="Search commands, pages, agents..."
              @keydown.escape="close"
            />
            <kbd style="font-size:.7rem;opacity:.35;padding:.15rem .4rem;border:1px solid var(--border);border-radius:3px">Esc</kbd>
          </div>

          <div style="max-height:340px;overflow-y:auto;padding:.25rem 0">
            <div
              v-for="result in searchResults"
              :key="result.id"
              style="display:flex;align-items:center;gap:.75rem;padding:.55rem 1rem;cursor:pointer;transition:background .1s"
              @mouseenter="$event.currentTarget.style.background = 'var(--surface-2)'"
              @mouseleave="$event.currentTarget.style.background = ''"
              @click="selectResult(result)"
            >
              <i class="fas nav-icon" :class="result.icon" style="width:16px;text-align:center;opacity:.6"></i>
              <span style="flex:1;font-size:.9rem">{{ result.label }}</span>
              <span style="font-size:.7rem;opacity:.35;text-transform:uppercase;letter-spacing:.06em">{{ result.category }}</span>
            </div>

            <div
              v-if="searchQuery && searchResults.length === 0"
              style="padding:1.5rem;text-align:center;opacity:.4;font-size:.85rem"
            >
              No results for "{{ searchQuery }}"
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
