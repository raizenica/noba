<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()

const scrutiny = computed(() => dashboard.live.scrutiny || null)

const health = computed(() => {
  const s = scrutiny.value
  if (!s) return ''
  if (s.failed > 0) return 'fail'
  if (s.warn > 0) return 'warn'
  return 'ok'
})
</script>

<template>
  <DashboardCard title="Disk Health" icon="fas fa-hdd" card-id="scrutiny" :health="health">
    <template v-if="scrutiny">
      <div class="row">
        <span class="row-label">Disks</span>
        <span class="row-val">{{ scrutiny.devices }}</span>
      </div>
      <div class="row">
        <span class="row-label">Healthy</span>
        <span class="row-val" style="color:var(--success)">{{ scrutiny.healthy }}</span>
      </div>
      <div v-if="(scrutiny.warn || 0) > 0" class="row">
        <span class="row-label">Warning</span>
        <span class="row-val" style="color:var(--warning)">{{ scrutiny.warn }}</span>
      </div>
      <div v-if="(scrutiny.failed || 0) > 0" class="row">
        <span class="row-label">Failed</span>
        <span class="row-val" style="color:var(--danger)">{{ scrutiny.failed }}</span>
      </div>
      <div class="row">
        <span class="row-label">Total Capacity</span>
        <span class="row-val">{{ ((scrutiny.totalCapacityBytes || 0) / 1e12).toFixed(1) }} TB</span>
      </div>
      <div class="row">
        <span class="row-label">Max Temp</span>
        <span
          class="row-val"
          :style="(scrutiny.maxTemp || 0) > 50 ? 'color:var(--danger)' : ''"
        >{{ (scrutiny.maxTemp || 0) }}°C</span>
      </div>

      <div style="margin-top:.6rem;max-height:200px;overflow-y:auto">
        <div
          v-for="d in (scrutiny.device_list || [])"
          :key="d.serial || d.name"
          class="row"
          style="font-size:.75rem"
        >
          <span class="row-label">
            <i
              class="fas fa-circle"
              style="font-size:.4rem;margin-right:4px"
              :style="d.status === 0 ? 'color:var(--success)' : d.status === 1 ? 'color:var(--warning)' : 'color:var(--danger)'"
              aria-hidden="true"
            ></i>
            /dev/{{ d.name }}
          </span>
          <span class="row-val" style="font-size:.65rem;opacity:.8">
            {{ d.model }}{{ d.temperature ? ' · ' + d.temperature + '°C' : '' }}
          </span>
        </div>
      </div>
    </template>
    <div v-else class="empty-msg">Scrutiny not configured or unreachable.</div>
  </DashboardCard>
</template>
