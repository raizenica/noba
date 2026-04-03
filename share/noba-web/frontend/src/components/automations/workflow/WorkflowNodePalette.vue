<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
defineProps({
  nodeTypes: {
    type: Array,
    default: () => [
      { type: 'action',        icon: 'fa-play',        label: 'Action',    css: 'wb-action' },
      { type: 'condition',     icon: 'fa-code-branch', label: 'Condition', css: 'wb-condition' },
      { type: 'approval_gate', icon: 'fa-lock',        label: 'Approval',  css: 'wb-approval' },
      { type: 'parallel',      icon: 'fa-code-branch', label: 'Parallel',  css: 'wb-parallel', rotate: true },
      { type: 'delay',         icon: 'fa-clock',       label: 'Delay',     css: 'wb-delay' },
      { type: 'notification',  icon: 'fa-bell',        label: 'Notify',    css: 'wb-notify' },
    ],
  },
})

const emit = defineEmits(['add-node'])
</script>

<template>
  <div class="wnp-palette">
    <span class="wnp-label">Add:</span>
    <button
      v-for="nt in nodeTypes"
      :key="nt.type"
      class="wnp-btn"
      :class="nt.css"
      @click="emit('add-node', nt.type)"
    >
      <i
        class="fas"
        :class="[nt.icon, nt.rotate ? 'wnp-rotated' : '']"
      ></i>
      {{ nt.label }}
    </button>
  </div>
</template>

<style scoped>
.wnp-palette {
  display: flex;
  align-items: center;
  gap: .3rem;
  flex-wrap: wrap;
}

.wnp-label {
  font-size: .62rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: .06em;
  white-space: nowrap;
  margin-right: .1rem;
}

.wnp-btn {
  display: inline-flex;
  align-items: center;
  gap: .25rem;
  padding: .2rem .45rem;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-muted);
  font-size: .68rem;
  cursor: pointer;
  transition: background .12s, border-color .12s, color .12s;
  white-space: nowrap;
}
.wnp-btn:hover { background: var(--surface); border-color: var(--border-hi); color: var(--text); }

.wb-action       { border-color: var(--accent); color: var(--accent); }
.wb-condition    { border-color: var(--warning); color: var(--warning); }
.wb-approval     { border-color: color-mix(in srgb, var(--warning) 80%, var(--danger)); color: color-mix(in srgb, var(--warning) 80%, var(--danger)); }
.wb-parallel     { border-color: var(--info, #a855f7); color: var(--info, #a855f7); }
.wb-delay        { border-color: var(--text-muted); color: var(--text-muted); }
.wb-notify       { border-color: var(--success); color: var(--success); }

.wnp-rotated { display: inline-block; transform: rotate(90deg); }
</style>
