<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, onMounted } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import AppModal from '../ui/AppModal.vue'
import IntegrationSetup from '../settings/IntegrationSetup.vue'
import DeployModal from '../agents/DeployModal.vue'
import NotificationSetup from './NotificationSetup.vue'
import UserSetup from './UserSetup.vue'

const emit = defineEmits(['dismiss'])
const settingsStore = useSettingsStore()
const authStore = useAuthStore()
const { get } = useApi()

// ── Completion state ────────────────────────────────────────────────────────
const agents = ref([])
const instances = ref([])
const userCount = ref(1)

const INTEGRATION_KEYS = [
  'piholeUrl', 'hassUrl', 'unifiUrl', 'proxmoxUrl', 'truenasUrl',
  'plexUrl', 'jellyfinUrl', 'qbitUrl', 'adguardUrl', 'sonarrUrl',
  'radarrUrl', 'speedtestUrl', 'kumaUrl',
]

const NOTIF_KEYS = [
  'pushoverAppToken', 'gotifyUrl', 'gotifyAppToken',
]

const steps = computed(() => [
  {
    key: 'monitor',
    icon: 'fa-desktop',
    title: 'Core Monitoring',
    desc: 'CPU, memory, disk, and network stats are collected automatically.',
    done: true, // always complete
    auto: true,
  },
  {
    key: 'integrations',
    icon: 'fa-plug',
    title: 'Connect Your Services',
    desc: 'Add the platforms you use — NAS, hypervisors, DNS, media, containers, and 120+ more.',
    done: hasIntegrations.value,
  },
  {
    key: 'notifications',
    icon: 'fa-bell',
    title: 'Set Up Notifications',
    desc: 'Get notified when something needs attention — via Pushover, Gotify, or email.',
    done: hasNotifications.value,
  },
  {
    key: 'agents',
    icon: 'fa-satellite-dish',
    title: 'Monitor Remote Hosts',
    desc: 'Deploy lightweight agents to other machines for full multi-site monitoring.',
    done: agents.value.length > 0,
  },
  ...(authStore.isAdmin ? [{
    key: 'users',
    icon: 'fa-user-plus',
    title: 'Invite Your Team',
    desc: 'Create accounts with viewer, operator, or admin roles.',
    done: userCount.value > 1,
  }] : []),
])

const hasIntegrations = computed(() => {
  const d = settingsStore.data
  const hasLegacy = INTEGRATION_KEYS.some(k => d[k] && String(d[k]).trim())
  return hasLegacy || instances.value.length > 0
})

const hasNotifications = computed(() => {
  const d = settingsStore.data
  return NOTIF_KEYS.some(k => d[k] && String(d[k]).trim())
})

const completedCount = computed(() => steps.value.filter(s => s.done).length)
const progress = computed(() => Math.round((completedCount.value / steps.value.length) * 100))

// ── Modals ──────────────────────────────────────────────────────────────────
const activeModal = ref('')

function openStep(key) {
  if (key === 'monitor') return // auto-complete, no action needed
  activeModal.value = key
}

function closeModal() {
  activeModal.value = ''
  // Refresh data to update checkmarks
  fetchData()
}

async function onIntegrationSaved() {
  closeModal()
}

// ── Data loading ────────────────────────────────────────────────────────────
async function fetchData() {
  try { agents.value = await get('/api/agents') || [] } catch { agents.value = [] }
  try { instances.value = await get('/api/integrations/instances') || [] } catch { instances.value = [] }
  try {
    const u = await get('/api/admin/users')
    userCount.value = Array.isArray(u) ? u.length : 1
  } catch { userCount.value = 1 }
  if (!settingsStore.loaded) await settingsStore.fetchSettings()
}

onMounted(fetchData)
</script>

<template>
  <div class="welcome-setup">
    <div class="welcome-header">
      <div class="welcome-logo"><i class="fas fa-terminal"></i></div>
      <h1 class="welcome-title">Welcome to NOBA</h1>
      <p class="welcome-subtitle">COMMAND CENTER</p>
      <p class="welcome-desc">
        Your system is already being monitored. Complete the steps below to
        unlock the full platform — or skip ahead to the dashboard.
      </p>
    </div>

    <!-- Progress bar -->
    <div class="welcome-progress">
      <div class="progress-bar">
        <div class="progress-fill" :style="{ width: progress + '%' }"></div>
      </div>
      <span class="progress-label">{{ completedCount }} of {{ steps.length }} complete</span>
    </div>

    <!-- Step cards -->
    <div class="welcome-steps">
      <div
        v-for="step in steps"
        :key="step.key"
        class="step-card"
        :class="{ done: step.done, auto: step.auto }"
        @click="!step.auto && openStep(step.key)"
      >
        <div class="step-check">
          <i v-if="step.done" class="fas fa-check-circle"></i>
          <span v-else class="step-circle"></span>
        </div>
        <div class="step-icon"><i class="fas" :class="step.icon"></i></div>
        <div class="step-body">
          <div class="step-title">{{ step.title }}</div>
          <div class="step-desc">{{ step.desc }}</div>
        </div>
        <div v-if="!step.done && !step.auto" class="step-action">
          <button class="btn btn-sm btn-primary">Set Up</button>
        </div>
        <div v-else-if="step.done && !step.auto" class="step-action">
          <button class="btn btn-xs">Edit</button>
        </div>
      </div>
    </div>

    <div class="welcome-footer">
      <button class="btn btn-secondary" @click="emit('dismiss')">
        <i class="fas fa-arrow-right"></i> Continue to Dashboard
      </button>
      <p class="welcome-hint">
        You can always access these settings later from the sidebar.
      </p>
    </div>

    <!-- ── Integration Setup Modal ──────────────────────────────────────── -->
    <AppModal :show="activeModal === 'integrations'" title="Connect a Service" width="640px" @close="closeModal">
      <IntegrationSetup @saved="onIntegrationSaved" @cancel="closeModal" />
    </AppModal>

    <!-- ── Notification Setup Modal ─────────────────────────────────────── -->
    <AppModal :show="activeModal === 'notifications'" title="Set Up Notifications" width="540px" @close="closeModal">
      <NotificationSetup @done="closeModal" @cancel="closeModal" />
    </AppModal>

    <!-- ── Agent Deploy Modal ───────────────────────────────────────────── -->
    <DeployModal :show="activeModal === 'agents'" @close="closeModal" @deployed="closeModal" />

    <!-- ── User Setup Modal ─────────────────────────────────────────────── -->
    <AppModal :show="activeModal === 'users'" title="Add a Team Member" width="480px" @close="closeModal">
      <UserSetup @done="closeModal" @cancel="closeModal" />
    </AppModal>
  </div>
</template>

<style scoped>
.welcome-setup {
  max-width: 620px;
  margin: 0 auto;
  padding: 2rem 1rem;
}

.welcome-header {
  text-align: center;
  margin-bottom: 2rem;
}

.welcome-logo {
  font-size: 2.5rem;
  color: var(--accent);
  margin-bottom: .75rem;
}

.welcome-title {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--text);
  margin: 0;
  letter-spacing: 0.04em;
}

.welcome-subtitle {
  font-size: .75rem;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.2em;
  margin: .25rem 0 1rem;
}

.welcome-desc {
  color: var(--text-muted);
  font-size: .9rem;
  line-height: 1.5;
  max-width: 480px;
  margin: 0 auto;
}

/* Progress */
.welcome-progress {
  display: flex;
  align-items: center;
  gap: .75rem;
  margin-bottom: 1.5rem;
}

.progress-bar {
  flex: 1;
  height: 6px;
  background: var(--surface-2);
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
  transition: width .4s ease;
}

.progress-label {
  font-size: .75rem;
  color: var(--text-muted);
  white-space: nowrap;
}

/* Steps */
.welcome-steps {
  display: flex;
  flex-direction: column;
  gap: .6rem;
  margin-bottom: 2rem;
}

.step-card {
  display: flex;
  align-items: center;
  gap: .75rem;
  padding: .9rem 1rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color .2s, background .2s, opacity .2s;
}

.step-card:hover:not(.auto) {
  border-color: var(--accent);
  background: var(--surface-2);
}

.step-card.done {
  opacity: .65;
}

.step-card.auto {
  cursor: default;
  border-style: dashed;
}

.step-check {
  flex-shrink: 0;
  width: 1.5rem;
  text-align: center;
}

.step-check .fa-check-circle {
  color: var(--success);
  font-size: 1.1rem;
}

.step-circle {
  display: inline-block;
  width: 1.1rem;
  height: 1.1rem;
  border: 2px solid var(--border);
  border-radius: 50%;
}

.step-icon {
  flex-shrink: 0;
  width: 2rem;
  height: 2rem;
  border-radius: 6px;
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
  font-size: .85rem;
}

.step-body {
  flex: 1;
  min-width: 0;
}

.step-title {
  font-weight: 600;
  font-size: .9rem;
  color: var(--text);
  margin-bottom: .15rem;
}

.step-desc {
  font-size: .78rem;
  color: var(--text-muted);
  line-height: 1.3;
}

.step-action {
  flex-shrink: 0;
}

.step-done-label {
  font-size: .75rem;
  color: var(--success);
  font-weight: 600;
}

/* Footer */
.welcome-footer {
  text-align: center;
}

.welcome-hint {
  font-size: .75rem;
  color: var(--text-muted);
  margin-top: .75rem;
}
</style>
