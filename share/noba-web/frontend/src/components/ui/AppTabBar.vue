<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
defineProps({
  tabs: { type: Array, required: true }, // [{ key, label, icon, badge }]
  active: { type: String, required: true },
})
const emit = defineEmits(['change'])

function onTabChange(key) {
  emit('change', key)
  const content = document.querySelector('.app-content')
  if (content) content.scrollTo({ top: 0, behavior: 'smooth' })
}
</script>

<template>
  <div class="app-tab-bar">
    <button
      v-for="t in tabs"
      :key="t.key"
      class="btn btn-xs"
      :class="active === t.key ? 'btn-primary' : 'btn-secondary'"
      @click="onTabChange(t.key)"
    >
      <i v-if="t.icon" class="fas" :class="[t.icon, 'mr-xs']"></i>
      {{ t.label }}
      <span v-if="t.badge" class="nav-badge ml-xs">{{ t.badge }}</span>
    </button>
  </div>
</template>

<style scoped>
.app-tab-bar {
  display: flex;
  flex-wrap: nowrap;
  gap: 0.4rem;
  margin-bottom: 1.25rem;
  overflow-x: auto;
  padding-bottom: 4px; /* Space for scrollbar if needed */
  -webkit-overflow-scrolling: touch;
}
/* Hide scrollbar for cleaner look, but keep functionality */
.app-tab-bar::-webkit-scrollbar { height: 3px; }
.app-tab-bar::-webkit-scrollbar-track { background: transparent; }
.app-tab-bar::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

.btn { white-space: nowrap; flex-shrink: 0; }

.nav-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  background: var(--accent);
  color: #fff;
  border-radius: 8px;
  font-size: 0.6rem;
  font-weight: 700;
  vertical-align: middle;
}
.btn-secondary .nav-badge {
  background: var(--surface-2);
  color: var(--text-muted);
}
.mr-xs { margin-right: 0.35rem; }
.ml-xs { margin-left: 0.35rem; }
</style>
