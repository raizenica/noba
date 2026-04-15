<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'
import { useModalsStore } from '../../stores/modals'

const dashboardStore = useDashboardStore()
const authStore      = useAuthStore()
const { post }       = useApi()
const notif          = useNotificationsStore()
const modals         = useModalsStore()

const services = computed(() => dashboardStore.live.services || [])

async function svcAction(svc, action) {
  if (!authStore.isOperator) return
  const label = svc.name.replace('.service', '')
  const run = async () => {
    try {
      await post('/api/service-control', {
        service: svc.name,
        action,
        is_user: svc.is_user || false,
      })
      notif.addToast(`${action}: ${label}`, 'success')
    } catch (e) {
      notif.addToast(e.message || `Failed: ${label}`, 'error')
    }
  }
  if (action === 'start') return run()
  if (!await modals.confirm(`${action} service "${label}"?`)) return
  run()
}

function statusClass(svc) {
  if (svc.status === 'active') return 'bs'
  if (svc.status === 'failed' || svc.status === 'error') return 'bd'
  return 'bw'
}

function statusLabel(svc) {
  return svc.status || 'unknown'
}
</script>

<template>
  <div>
    <div v-if="services.length === 0" class="empty-msg">
      No service data available. Ensure the NOBA agent is running.
    </div>
    <div v-else style="overflow-x:auto">
      <table style="width:100%;font-size:.8rem;border-collapse:collapse">
        <thead>
          <tr style="border-bottom:2px solid var(--border)">
            <th class="td-left">Service</th>
            <th class="td-center">Status</th>
            <th v-if="authStore.isOperator" class="td-center">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="svc in services"
            :key="svc.name"
            class="border-b"
          >
            <td class="td-cell" style="font-family:monospace;font-size:.78rem">
              {{ svc.name.replace('.service', '') }}
            </td>
            <td class="td-center">
              <span class="badge" :class="statusClass(svc)" style="font-size:.6rem">
                {{ statusLabel(svc) }}
              </span>
            </td>
            <td v-if="authStore.isOperator" class="td-center">
              <div style="display:flex;gap:.3rem;justify-content:center">
                <button
                  class="btn btn-xs"
                  title="Start"
                  @click="svcAction(svc, 'start')"
                  :disabled="svc.status === 'active'"
                >
                  <i class="fas fa-play"></i>
                </button>
                <button
                  class="btn btn-xs btn-danger"
                  title="Stop"
                  @click="svcAction(svc, 'stop')"
                  :disabled="svc.status !== 'active'"
                >
                  <i class="fas fa-stop"></i>
                </button>
                <button
                  class="btn btn-xs"
                  title="Restart"
                  @click="svcAction(svc, 'restart')"
                >
                  <i class="fas fa-redo"></i>
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
