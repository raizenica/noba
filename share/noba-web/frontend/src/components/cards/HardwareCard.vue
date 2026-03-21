<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()

const hwCpu   = computed(() => dashboard.live.hwCpu || '--')
const hwGpu   = computed(() => dashboard.live.hwGpu || '--')
const gpuTemp = computed(() => dashboard.live.gpuTemp || null)

const gpuTempClass = computed(() => {
  const t = parseFloat(gpuTemp.value)
  if (isNaN(t)) return 'bn'
  if (t > 85) return 'bd'
  if (t > 70) return 'bw'
  return 'bs'
})

const showGpuTemp = computed(() =>
  gpuTemp.value && gpuTemp.value !== 'N/A'
)
</script>

<template>
  <DashboardCard title="Hardware" icon="fas fa-memory" card-id="hw">
    <div class="row">
      <span class="row-label">CPU</span>
      <span class="row-val" style="font-size:.78rem;max-width:210px">{{ hwCpu }}</span>
    </div>
    <div class="row">
      <span class="row-label">GPU</span>
      <span class="row-val" style="font-size:.76rem;max-width:210px">{{ hwGpu }}</span>
    </div>
    <div v-if="showGpuTemp" class="row">
      <span class="row-label">GPU Temp</span>
      <span class="badge" :class="gpuTempClass">{{ gpuTemp }}</span>
    </div>
  </DashboardCard>
</template>
