<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()

const netRx        = computed(() => dashboard.live.netRx || '0 B/s')
const netTx        = computed(() => dashboard.live.netTx || '0 B/s')
const hostname     = computed(() => dashboard.live.hostname || '--')
const defaultIp    = computed(() => dashboard.live.defaultIp || '--')
const netInterfaces = computed(() => dashboard.live.netInterfaces || [])
</script>

<template>
  <DashboardCard title="Network I/O" icon="fas fa-network-wired" card-id="netio">
    <div class="io-grid" style="margin-bottom:.875rem">
      <div class="io-stat">
        <div class="io-val io-down">{{ netRx }}</div>
        <div class="io-label"><i class="fas fa-arrow-down" aria-hidden="true"></i> RX</div>
      </div>
      <div class="io-stat">
        <div class="io-val io-up">{{ netTx }}</div>
        <div class="io-label"><i class="fas fa-arrow-up" aria-hidden="true"></i> TX</div>
      </div>
    </div>

    <div class="row">
      <span class="row-label">Hostname</span>
      <span class="row-val">{{ hostname }}</span>
    </div>
    <div class="row">
      <span class="row-label">Default IP</span>
      <span class="row-val">{{ defaultIp }}</span>
    </div>

    <div
      v-if="netInterfaces.length > 0"
      style="margin-top:.5rem;padding-top:.5rem;border-top:1px dashed var(--border)"
    >
      <div
        v-for="nic in netInterfaces"
        :key="nic.name"
        class="row"
        style="font-size:.72rem"
      >
        <span class="row-label">{{ nic.name }}</span>
        <span class="row-val">
          <i class="fas fa-arrow-down" style="color:var(--accent);font-size:.55rem" aria-hidden="true"></i>
          {{ ((nic.rx_bps || 0) / 1024 / 1024).toFixed(2) }} MB/s
          <i class="fas fa-arrow-up" style="color:var(--warning);font-size:.55rem;margin-left:.3rem" aria-hidden="true"></i>
          {{ ((nic.tx_bps || 0) / 1024 / 1024).toFixed(2) }} MB/s
        </span>
      </div>
    </div>
  </DashboardCard>
</template>
