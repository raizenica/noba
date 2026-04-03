<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { Chart, registerables } from 'chart.js'

Chart.register(...registerables)

const props = defineProps({
  config: { type: Object, required: true },
})

const canvas = ref(null)
let chart = null

function render() {
  if (!canvas.value) return
  const config = props.config
  if (chart) {
    chart.data = config.data
    chart.options = config.options
    chart.update('none') // update without animation for performance
  } else {
    chart = new Chart(canvas.value.getContext('2d'), {
      type: config.type,
      data: config.data,
      options: config.options,
      plugins: config.plugins,
    })
  }
}

onMounted(render)
watch(() => props.config, render, { deep: true })
onUnmounted(() => { if (chart) chart.destroy() })

defineExpose({ getChart: () => chart })
</script>

<template>
  <canvas ref="canvas"></canvas>
</template>
