<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
const props = defineProps({
  instance: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['edit', 'delete'])
</script>

<template>
  <div class="instance-row">
    <span class="badge ba">{{ instance.platform }}</span>
    <span class="instance-id">{{ instance.id }}</span>
    <span class="text-muted">{{ instance.url }}</span>
    <span v-if="instance.site" class="badge bs">{{ instance.site }}</span>
    <span :class="['badge', instance.health_status === 'online' ? 'bs' : instance.health_status === 'offline' ? 'bd' : 'bw']">
      {{ instance.health_status || 'unknown' }}
    </span>
    <div style="display:flex;gap:.25rem">
      <button class="btn btn-xs" @click="emit('edit', instance)" title="Edit integration">
        <i class="fas fa-edit"></i>
      </button>
      <button class="btn btn-xs btn-danger" @click="emit('delete', instance.id)" title="Delete integration">
        <i class="fas fa-trash"></i>
      </button>
    </div>
  </div>
</template>

<style scoped>
.instance-row {
  display: flex;
  align-items: center;
  gap: .75rem;
  padding: .5rem .75rem;
  background: var(--surface-2);
  border-radius: 6px;
  flex-wrap: wrap;
}
.instance-id { font-weight: 600; }
.text-muted { color: var(--text-muted); font-size: .85rem; }
</style>
