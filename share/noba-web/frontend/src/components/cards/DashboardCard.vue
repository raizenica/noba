<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref } from 'vue'

const props = defineProps({
  title:       { type: String, required: true },
  icon:        { type: String, default: 'fa-cube' },
  cardId:      { type: String, default: '' },
  collapsible: { type: Boolean, default: true },
  health:      { type: String, default: '' },   // 'ok' | 'warn' | 'fail'
})

const collapsed = ref(false)

function toggleCollapse() {
  if (props.collapsible) collapsed.value = !collapsed.value
}
</script>

<template>
  <div
    class="card"
    :data-id="cardId ? `card-${cardId}` : undefined"
    :data-health="health || undefined"
  >
    <div class="card-hdr">
      <i class="fas card-icon" :class="icon" aria-hidden="true"></i>
      <span class="card-title">{{ title }}</span>

      <slot name="header-actions" />

      <button
        v-if="collapsible"
        class="collapse-btn fas fa-chevron-down"
        :class="{ 'is-collapsed': collapsed }"
        :aria-expanded="!collapsed"
        :aria-controls="cardId ? `body-${cardId}` : undefined"
        type="button"
        @click="toggleCollapse"
      ></button>

      <i class="fas fa-grip-lines drag-handle" aria-hidden="true"></i>
    </div>

    <div
      v-show="!collapsed"
      class="card-body"
      :id="cardId ? `body-${cardId}` : undefined"
    >
      <slot />
    </div>
  </div>
</template>
