<script setup>
defineProps({
  tabs: { type: Array, required: true }, // [{ key, label, icon, badge }]
  active: { type: String, required: true },
})
const emit = defineEmits(['change'])
</script>

<template>
  <div class="app-tab-bar">
    <button
      v-for="t in tabs"
      :key="t.key"
      class="btn btn-xs"
      :class="active === t.key ? 'btn-primary' : 'btn-secondary'"
      @click="emit('change', t.key)"
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
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: 1.25rem;
}
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
