<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const auth = useAuthStore()
const notifications = useNotificationsStore()
const { post, get } = useApi()

const proxmox = computed(() => dashboard.live.proxmox)
const isOperator = computed(() => auth.isOperator)
const isAdmin = computed(() => auth.isAdmin)

async function fetchPmxSnapshots(node, vmid, type) {
  try {
    if (!isAdmin.value) {
      notifications.addToast('Admin access required for snapshots', 'warning')
      return
    }
    const snapname = `snapshot-${Date.now()}`
    await post(`/api/proxmox/nodes/${node}/vms/${vmid}/snapshot`, {
      name: snapname,
      description: `Auto snapshot by NOBA`,
      type: type || 'qemu'
    })
    notifications.addToast(`Snapshot created: ${snapname}`, 'success')
  } catch (e) {
    notifications.addToast('Snapshot failed: ' + (e.message || 'Unknown error'), 'danger')
  }
}

async function openPmxConsole(node, vmid, type) {
  try {
    if (!isOperator.value) {
      notifications.addToast('Operator access required for console', 'warning')
      return
    }
    const res = await get(`/api/proxmox/nodes/${node}/vms/${vmid}/console?type=${type || 'qemu'}`)
    if (res && res.url) {
      window.open(res.url, '_blank')
    } else {
      notifications.addToast('Console URL not returned', 'danger')
    }
  } catch (e) {
    notifications.addToast('Console failed: ' + (e.message || 'Unknown error'), 'danger')
  }
}
</script>

<template>
  <DashboardCard title="Proxmox VE" icon="fas fa-server" card-id="proxmox">
    <template #header-actions>
      <span
        v-if="proxmox && proxmox.vms && proxmox.vms.length > 0"
        class="card-count"
      >{{ (proxmox.vms.length || 0) }} guests</span>
      <span
        class="badge"
        :class="proxmox && proxmox.status === 'online' ? 'bs' : 'bn'"
        style="margin-left:auto;margin-right:.25rem"
      >{{ proxmox ? proxmox.status : 'offline' }}</span>
    </template>

    <template v-if="proxmox && proxmox.status === 'online'">
      <!-- Nodes -->
      <div
        v-for="node in (proxmox.nodes || [])"
        :key="node.name"
        class="row"
        style="margin-bottom:.35rem"
      >
        <div
          class="status-dot"
          :class="node.status === 'online' ? 'dot-up' : 'dot-down'"
          aria-hidden="true"
        ></div>
        <span class="row-label">{{ node.name }}</span>
        <span class="badge bn" style="font-size:.65rem">CPU {{ node.cpu }}%</span>
        <span class="badge bn" style="font-size:.65rem">MEM {{ node.mem_percent }}%</span>
      </div>

      <!-- VMs / LXC -->
      <div style="margin-top:.5rem;max-height:260px;overflow-y:auto;display:flex;flex-direction:column;gap:4px">
        <div
          v-for="vm in (proxmox.vms || [])"
          :key="vm.vmid + '-' + vm.node"
          class="ct-row"
          style="flex-shrink:0"
        >
          <div
            class="status-dot"
            :class="vm.status === 'running' ? 'dot-up' : 'dot-down'"
            :aria-label="vm.status"
          ></div>
          <span class="ct-name">{{ vm.name }}</span>
          <span class="ct-img">#{{ vm.vmid }} &middot; {{ (vm.type || 'unknown').toUpperCase() }}</span>
          <span
            class="badge"
            :class="vm.status === 'running' ? 'bs' : vm.status === 'stopped' ? 'bw' : 'bn'"
          >{{ vm.status }}</span>
          <span
            v-if="vm.status === 'running'"
            class="badge bn"
            style="font-size:.62rem"
          >{{ vm.cpu }}% cpu</span>
          <div v-if="isOperator" style="display:flex;gap:4px">
            <button
              class="svc-btn"
              title="Snapshots"
              @click="fetchPmxSnapshots(vm.node, vm.vmid, vm.type)"
            ><i class="fas fa-camera"></i></button>
            <button
              class="svc-btn"
              title="Console"
              @click="openPmxConsole(vm.node, vm.vmid, vm.type)"
            ><i class="fas fa-desktop"></i></button>
          </div>
        </div>
      </div>
      <div v-if="!proxmox.vms || proxmox.vms.length === 0" class="empty-msg">
        No VMs or containers found.
      </div>
    </template>
    <div v-else class="empty-msg">Proxmox unreachable — <router-link to="/settings?tab=integrations" class="empty-link">configure in Settings</router-link>.</div>
  </DashboardCard>
</template>
