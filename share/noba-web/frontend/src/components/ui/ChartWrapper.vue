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
  if (chart) chart.destroy()
  if (!canvas.value) return
  chart = new Chart(canvas.value.getContext('2d'), JSON.parse(JSON.stringify(props.config)))
}

onMounted(render)
watch(() => props.config, render, { deep: true })
onUnmounted(() => { if (chart) chart.destroy() })

defineExpose({ getChart: () => chart })
</script>

<template>
  <canvas ref="canvas"></canvas>
</template>
