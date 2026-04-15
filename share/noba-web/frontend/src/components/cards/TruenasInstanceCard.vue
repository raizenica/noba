<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import DashboardCard from './DashboardCard.vue'

const props = defineProps({
  instance: { type: Object, required: true },
})

const dashboard = useDashboardStore()
const auth = useAuthStore()
const { post } = useApi()

const truenas = computed(() => (dashboard.live.instances || {})[props.instance.id] || null)
const isOperator = computed(() => auth.isOperator)

async function vmAction(id, name, action) {
  try {
    await post(`/api/integrations/instances/${props.instance.id}/truenas/vm`, { id, name, action })
  } catch { /* silent */ }
}
</script>

<template>
  <DashboardCard :title="instance.id" icon="fas fa-server">
    <template v-if="truenas && truenas.status === 'online'">
      <div class="row">
        <span class="row-label">API Status</span>
        <span class="badge bs">ONLINE</span>
      </div>
      <div class="row">
        <span class="row-label">Active Apps</span>
        <span class="row-val">
          {{ (truenas.apps || []).filter(a => a.state === 'RUNNING').length }} / {{ (truenas.apps || []).length }}
        </span>
      </div>
      <div v-if="(truenas.alerts || []).length > 0" class="row">
        <span class="row-label">Hardware Alerts</span>
        <span class="badge bd">{{ (truenas.alerts || []).length }}</span>
      </div>
      <div v-if="instance.site" class="row">
        <span class="row-label">Site</span>
        <span class="row-val"><span class="badge ba">{{ instance.site }}</span></span>
      </div>

      <div
        v-if="truenas.vms && truenas.vms.length > 0"
        style="margin-top:.8rem;padding-top:.6rem;border-top:1px dashed var(--border)"
      >
        <span class="s-label" style="border:none;margin-bottom:.3rem">Virtual Machines</span>
        <div class="ct-list">
          <div
            v-for="vm in truenas.vms"
            :key="vm.id"
            class="ct-row"
            style="padding:.4rem .6rem"
          >
            <div
              class="status-dot"
              :class="vm.state === 'RUNNING' ? 'dot-up' : 'dot-down'"
              :aria-label="vm.state"
            ></div>
            <span class="ct-name">{{ vm.name }}</span>
            <div v-if="isOperator" class="svc-btns" role="group" :aria-label="vm.name + ' controls'">
              <button
                class="svc-btn"
                title="Start"
                aria-label="Start VM"
                :disabled="vm.state === 'RUNNING'"
                @click="vmAction(vm.id, vm.name, 'start')"
              ><i class="fas fa-play" aria-hidden="true"></i></button>
              <button
                class="svc-btn"
                title="Stop"
                aria-label="Stop VM"
                :disabled="vm.state !== 'RUNNING'"
                @click="vmAction(vm.id, vm.name, 'stop')"
              ><i class="fas fa-stop" aria-hidden="true"></i></button>
              <button
                class="svc-btn"
                title="Power Off (Force)"
                aria-label="Force power off VM"
                :disabled="vm.state !== 'RUNNING'"
                @click="vmAction(vm.id, vm.name, 'poweroff')"
              ><i class="fas fa-power-off" aria-hidden="true"></i></button>
            </div>
          </div>
        </div>
      </div>
    </template>
    <div v-else class="empty-msg">TrueNAS unreachable</div>
  </DashboardCard>
</template>
