<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
defineProps({
  automation: Object,
  stat: Object,        // from autoStats[automation.id] — run counts
  selected: Boolean,
  isOperator: Boolean,
})

const emit = defineEmits(['run', 'edit', 'delete', 'trace', 'toggle-select'])
</script>

<template>
  <div
    style="padding:.8rem;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);position:relative"
    :style="selected ? 'border-color:var(--accent)' : ''"
  >
    <!-- Selection Checkbox -->
    <div style="position:absolute;top:-8px;left:-8px;z-index:10" @click.stop="emit('toggle-select', automation.id)">
      <div class="bulk-check" :class="{ active: selected }">
        <i class="fas fa-check" v-if="selected"></i>
      </div>
    </div>

    <!-- Header row -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.4rem">
      <span style="font-weight:600;font-size:.85rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0">
        {{ automation.name }}
      </span>
      <div style="display:flex;gap:.3rem;align-items:center;flex-shrink:0;margin-left:.4rem">
        <span class="badge" :class="automation.enabled ? 'bs' : 'bw'" style="font-size:.55rem">
          {{ automation.enabled ? 'on' : 'off' }}
        </span>
        <span class="badge bn" style="font-size:.55rem">{{ automation.type }}</span>
      </div>
    </div>

    <!-- Meta -->
    <div style="font-size:.7rem;color:var(--text-muted);margin-bottom:.4rem">
      <div v-if="automation.schedule">Schedule: {{ automation.schedule }}</div>
      <div v-if="automation.last_run">
        Last run: {{ new Date(automation.last_run * 1000).toLocaleString() }}
      </div>
      <div v-if="stat" style="display:flex;gap:.6rem;margin-top:.2rem">
        <span>Runs: {{ stat.total || 0 }}</span>
        <span style="color:var(--success)">OK: {{ stat.done || 0 }}</span>
        <span v-if="(stat.failed || 0) > 0" style="color:var(--danger)">Fail: {{ stat.failed }}</span>
      </div>
    </div>

    <!-- Actions (operator+) -->
    <div v-if="isOperator" style="display:flex;gap:.3rem;flex-wrap:wrap">
      <button
        class="btn btn-xs btn-primary"
        :disabled="!automation.enabled"
        title="Run now"
        @click="emit('run', automation)"
      >
        <i class="fas fa-play"></i>
      </button>
      <button class="btn btn-xs" title="Edit" @click="emit('edit', automation)">
        <i class="fas fa-pen"></i>
      </button>
      <button
        v-if="automation.type === 'workflow'"
        class="btn btn-xs"
        title="Workflow trace"
        @click="emit('trace', automation)"
      >
        <i class="fas fa-project-diagram"></i>
      </button>
      <button class="btn btn-xs btn-danger" title="Delete" @click="emit('delete', automation)">
        <i class="fas fa-trash"></i>
      </button>
    </div>
  </div>
</template>

<style scoped>
.bulk-check {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  background: var(--surface);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: .7rem;
  transition: all .15s ease;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
  cursor: pointer;
}
.bulk-check.active {
  background: var(--accent);
  border-color: var(--accent);
}
</style>
