<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
const props = defineProps({
  modelValue: {
    type: String,
    required: true,
  },
  categories: {
    type: Array,
    required: true,
  },
})

const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <div style="display:flex;flex-wrap:wrap;gap:.3rem;margin-bottom:1rem;border-bottom:1px solid var(--border);padding-bottom:.6rem">
    <button
      v-for="c in categories"
      :key="c.key"
      class="btn btn-xs"
      :class="{ 'btn-primary': modelValue === c.key }"
      @click="emit('update:modelValue', c.key)"
    >
      <i class="fas" :class="c.icon" style="margin-right:.3rem"></i>{{ c.label }}
    </button>
  </div>
</template>
