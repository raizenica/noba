<script setup>
const props = defineProps({
  status: String, // 'queued' | 'running' | 'done' | 'failed' | 'disabled' | 'pending' | 'cancelled' | 'timeout'
})

function statusClass(s) {
  if (s === 'done')      return 'bs'
  if (s === 'failed')    return 'bd'
  if (s === 'running')   return 'ba'
  if (s === 'cancelled') return 'bw'
  if (s === 'timeout')   return 'bd'
  return 'bn'
}
</script>

<template>
  <span class="badge" :class="statusClass(status)" style="font-size:.55rem">
    {{ status || 'pending' }}
  </span>
</template>
