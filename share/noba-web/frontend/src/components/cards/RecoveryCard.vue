<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref } from 'vue'
import { useApi } from '../../composables/useApi'
import DashboardCard from './DashboardCard.vue'

const { post } = useApi()
const recoveryLoading = ref(false)
const recoveryResult  = ref('')
const svcName = ref('')

async function runRecovery(action, params = {}) {
  recoveryLoading.value = true
  recoveryResult.value  = ''
  try {
    const res = await post('/api/recovery', { action, ...params })
    recoveryResult.value = res?.message || 'Done'
  } catch (e) {
    recoveryResult.value = 'Error: ' + e.message
  } finally {
    recoveryLoading.value = false
  }
}
</script>

<template>
  <DashboardCard title="Recovery" icon="fas fa-first-aid" card-id="recovery">
    <div style="display:flex;flex-wrap:wrap;gap:.4rem">
      <button
        class="btn btn-sm"
        :disabled="recoveryLoading"
        @click="runRecovery('tailscale-reconnect')"
      >
        <i class="fas fa-network-wired"></i> Reconnect Tailscale
      </button>
      <button
        class="btn btn-sm"
        :disabled="recoveryLoading"
        @click="runRecovery('dns-flush')"
      >
        <i class="fas fa-shield-alt"></i> Flush DNS
      </button>
    </div>
    <div style="margin-top:.5rem;display:flex;gap:.3rem">
      <input
        v-model="svcName"
        class="field-input"
        type="text"
        placeholder="service name"
        style="flex:1;font-size:.75rem"
      >
      <button
        class="btn btn-sm"
        :disabled="recoveryLoading || !svcName"
        @click="runRecovery('service-restart', { service: svcName })"
      ><i class="fas fa-redo"></i></button>
    </div>
    <div
      v-if="recoveryResult"
      style="margin-top:.4rem;font-size:.75rem;padding:.3rem .5rem;background:var(--surface-2);border-radius:4px"
    >{{ recoveryResult }}</div>
  </DashboardCard>
</template>
