<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed, ref } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'

const dashboardStore = useDashboardStore()

// ── Alert dismissal ──────────────────────────────────────────────────────────
const dismissedAlerts = ref(new Set(JSON.parse(sessionStorage.getItem('noba:dismissed-alerts') || '[]')))

const visibleAlerts = computed(() =>
  (dashboardStore.live.alerts || []).filter(
    a => !dismissedAlerts.value.has(a.msg)
  )
)

function dismissAlert(key) {
  dismissedAlerts.value.add(key)
  sessionStorage.setItem('noba:dismissed-alerts', JSON.stringify([...dismissedAlerts.value]))
  dismissedAlerts.value = new Set(dismissedAlerts.value)
}

// ── Health pips ──────────────────────────────────────────────────────────────
const healthPips = computed(() => {
  const live = dashboardStore.live

  const services   = live.services || []
  const containers = live.containers || []

  return [
    {
      key:   'services',
      title: 'Services',
      cls:   services.length
               ? (services.every(s => s.running) ? 'ok' : 'warn')
               : 'off',
    },
    {
      key:   'disks',
      title: 'Disks',
      cls:   live.disks && live.disks.length ? 'ok' : 'off',
    },
    {
      key:   'network',
      title: 'Network',
      cls:   live.unifi ? 'ok' : 'off',
    },
    {
      key:   'dns',
      title: 'DNS',
      cls:   live.pihole || live.adguard ? 'ok' : 'off',
    },
    {
      key:   'containers',
      title: 'Containers',
      cls:   containers.length ? 'ok' : 'off',
    },
    {
      key:   'media',
      title: 'Media',
      cls:   live.plex || live.jellyfin ? 'ok' : 'off',
    },
    {
      key:   'alerts',
      title: 'Alerts',
      cls:   (live.alerts || []).length ? 'warn' : 'ok',
    },
  ]
})
</script>

<template>
  <div>
    <!-- Health bar -->
    <div class="health-bar" title="Infrastructure health overview">
      <div
        v-for="pip in healthPips"
        :key="pip.key"
        class="health-pip"
        :class="pip.cls"
        :title="pip.title"
      ></div>
    </div>

    <!-- Alert banner -->
    <div v-if="visibleAlerts.length > 0" class="alerts" style="margin:0.75rem 0 0">
      <div
        v-for="alert in visibleAlerts"
        :key="alert.msg"
        class="alert"
        :class="alert.level"
      >
        <i
          class="fas"
          :class="alert.level === 'danger' ? 'fa-exclamation-circle' : 'fa-exclamation-triangle'"
          style="margin-right:.5rem;flex-shrink:0"
        ></i>
        <span style="flex:1">{{ alert.msg }}</span>
        <button
          class="alert-dismiss"
          type="button"
          title="Dismiss"
          @click="dismissAlert(alert.msg)"
        >&times;</button>
      </div>
    </div>
  </div>
</template>
