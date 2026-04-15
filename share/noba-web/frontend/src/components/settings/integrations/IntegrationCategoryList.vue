<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import IntegrationInstanceCard from './IntegrationInstanceCard.vue'

const props = defineProps({
  instances: {
    type: Array,
    required: true,
  },
})

const emit = defineEmits(['edit', 'delete'])
</script>

<template>
  <div class="instance-list">
    <IntegrationInstanceCard
      v-for="inst in instances"
      :key="inst.id"
      :instance="inst"
      @edit="emit('edit', $event)"
      @delete="emit('delete', $event)"
    />
  </div>
</template>

<style scoped>
.instance-list {
  display: flex;
  flex-direction: column;
  gap: .5rem;
}
</style>
