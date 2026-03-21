<script setup>
defineProps({
  type: { type: String, default: 'info' },
})
const classMap = { success: 'bs', info: 'bi', warning: 'bw', danger: 'bd' }
</script>

<template>
  <span class="badge" :class="classMap[type] || 'bi'"><slot /></span>
</template>
