<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed, ref, watch } from 'vue'
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

// Once we've ever seen a valid GPU temperature, keep the row visible permanently
// (showing N/A when unavailable). This prevents masonry layout jumps caused by
// nvidia-smi transiently returning N/A between polling cycles.
const showGpuTemp = ref(false)
watch(gpuTemp, (v) => {
  if (v && v !== 'N/A') showGpuTemp.value = true
}, { immediate: true })
</script>

<template>
  <DashboardCard title="Hardware" icon="fas fa-memory" card-id="hw">
    <div class="row">
      <span class="row-label">CPU</span>
      <span class="row-val" style="font-size:.78rem;max-width:210px">{{ hwCpu }}</span>
    </div>
    <div class="row">
      <span class="row-label">GPU</span>
      <span class="row-val" style="font-size:.76rem;max-width:210px;white-space:pre-line">{{ hwGpu }}</span>
    </div>
    <div v-if="showGpuTemp" class="row">
      <span class="row-label">GPU Temp</span>
      <span class="badge" :class="gpuTempClass">{{ gpuTemp }}</span>
    </div>
  </DashboardCard>
</template>
