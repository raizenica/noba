<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref } from 'vue'

const props = defineProps({
  node: Object,      // {id, type, label, x, y, ...config}
  selected: Boolean,
  isEntry: Boolean,
})
const emit = defineEmits(['select', 'startConnect', 'endConnect', 'delete', 'update:position'])

// ── Node type meta ─────────────────────────────────────────────────────────
const NODE_META = {
  action:       { icon: 'fa-play',        borderColor: '#3b82f6', label: 'Action' },
  condition:    { icon: 'fa-code-branch',  borderColor: '#f59e0b', label: 'Condition' },
  approval_gate:{ icon: 'fa-lock',         borderColor: '#f97316', label: 'Approval' },
  parallel:     { icon: 'fa-code-branch',  borderColor: '#a855f7', label: 'Parallel', rotate: true },
  delay:        { icon: 'fa-clock',        borderColor: '#6b7280', label: 'Delay' },
  notification: { icon: 'fa-bell',         borderColor: '#22c55e', label: 'Notify' },
}

function meta(type) {
  return NODE_META[type] || { icon: 'fa-circle', borderColor: 'var(--border)', label: type }
}

// ── Output ports per type ──────────────────────────────────────────────────
function outputPorts(type) {
  if (type === 'condition')     return [{ id: 'true', label: 'True' }, { id: 'false', label: 'False' }]
  if (type === 'approval_gate') return [{ id: 'approved', label: 'Approved' }, { id: 'denied', label: 'Denied' }]
  return [{ id: 'default', label: '' }]
}

// ── Drag logic ─────────────────────────────────────────────────────────────
const dragging = ref(false)
let dragStartX = 0
let dragStartY = 0
let nodeStartX = 0
let nodeStartY = 0

function onMouseDown(e) {
  // Ignore clicks on port dots or delete button
  if (e.target.closest('.wn-port') || e.target.closest('.wn-delete')) return
  e.preventDefault()
  e.stopPropagation()
  emit('select', props.node.id)
  dragging.value = true
  dragStartX = e.clientX
  dragStartY = e.clientY
  nodeStartX = props.node.x
  nodeStartY = props.node.y

  function onMove(ev) {
    if (!dragging.value) return
    const dx = ev.clientX - dragStartX
    const dy = ev.clientY - dragStartY
    emit('update:position', { id: props.node.id, x: Math.max(0, nodeStartX + dx), y: Math.max(0, nodeStartY + dy) })
  }

  function onUp() {
    dragging.value = false
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }

  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

function onPortClick(e, portId, isInput) {
  e.stopPropagation()
  if (isInput) {
    emit('endConnect', props.node.id)
  } else {
    emit('startConnect', { nodeId: props.node.id, port: portId })
  }
}

function onDelete(e) {
  e.stopPropagation()
  emit('delete', props.node.id)
}

function onContextMenu(e) {
  e.preventDefault()
  emit('select', props.node.id)
}
</script>

<template>
  <div
    class="wn-wrapper"
    :class="{ 'wn-selected': selected, 'wn-dragging': dragging }"
    :data-node-id="node.id"
    :style="{
      position: 'absolute',
      left: node.x + 'px',
      top: node.y + 'px',
      borderLeftColor: meta(node.type).borderColor,
    }"
    @mousedown="onMouseDown"
    @contextmenu="onContextMenu"
  >
    <!-- Entry star -->
    <span v-if="isEntry" class="wn-entry-star" title="Entry node">
      <i class="fas fa-star"></i>
    </span>

    <!-- Delete button -->
    <button class="wn-delete" title="Delete node" aria-label="Delete node" @click="onDelete">
      <i class="fas fa-times"></i>
    </button>

    <!-- Type badge -->
    <span class="wn-badge">{{ meta(node.type).label }}</span>

    <!-- Input port (top center) -->
    <div
      class="wn-port wn-port-in"
      title="Input"
      @click="(e) => onPortClick(e, 'in', true)"
    ></div>

    <!-- Node body -->
    <div class="wn-body">
      <i
        class="fas wn-icon"
        :class="[meta(node.type).icon, meta(node.type).rotate ? 'wn-icon-rotated' : '']"
        :style="{ color: meta(node.type).borderColor }"
      ></i>
      <div class="wn-label-wrap">
        <span class="wn-label">{{ node.label || node.id }}</span>
        <span v-if="node.type === 'condition' && node.expression" class="wn-sub">
          {{ node.expression }}
        </span>
        <span v-if="node.type === 'delay' && node.seconds" class="wn-sub">
          {{ node.seconds }}s
        </span>
      </div>
    </div>

    <!-- Output ports (bottom) -->
    <div class="wn-ports-out">
      <div
        v-for="port in outputPorts(node.type)"
        :key="port.id"
        class="wn-port-out-wrap"
      >
        <span v-if="port.label" class="wn-port-label">{{ port.label }}</span>
        <div
          class="wn-port wn-port-out"
          :data-port="port.id"
          :title="port.label || 'Output'"
          @click="(e) => onPortClick(e, port.id, false)"
        ></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wn-wrapper {
  width: 170px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-left: 4px solid var(--border);
  border-radius: 6px;
  cursor: grab;
  user-select: none;
  box-shadow: 0 2px 8px rgba(0,0,0,.35);
  transition: box-shadow .15s, border-color .15s;
  z-index: 10;
}
.wn-wrapper:hover { box-shadow: 0 4px 16px rgba(0,0,0,.5); }
.wn-wrapper:hover .wn-delete { opacity: 1; }
.wn-selected { box-shadow: 0 0 0 2px var(--accent); }
.wn-dragging { cursor: grabbing; z-index: 20; }

/* Entry star */
.wn-entry-star {
  position: absolute;
  top: -8px;
  left: -8px;
  color: var(--warning);
  font-size: .65rem;
  z-index: 5;
}

/* Delete button */
.wn-delete {
  position: absolute;
  top: 3px;
  right: 22px;
  width: 18px;
  height: 18px;
  background: var(--danger-dim);
  border: 1px solid var(--danger-border);
  border-radius: 3px;
  color: var(--danger);
  font-size: .6rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity .15s;
  z-index: 5;
}
.wn-delete:hover { background: var(--danger); color: #fff; }

/* Type badge */
.wn-badge {
  position: absolute;
  top: 3px;
  right: 44px;
  font-size: .5rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--text-muted);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 4px;
  pointer-events: none;
}

/* Input port */
.wn-port-in {
  position: absolute;
  top: -6px;
  left: 50%;
  transform: translateX(-50%);
  width: 12px;
  height: 12px;
  background: var(--surface-2);
  border: 2px solid var(--accent);
  border-radius: 50%;
  cursor: crosshair;
  z-index: 15;
  transition: background .12s;
}
.wn-port-in:hover { background: var(--accent); }

/* Body */
.wn-body {
  display: flex;
  align-items: flex-start;
  gap: .45rem;
  padding: .55rem .5rem .45rem .5rem;
  padding-top: .65rem;
}
.wn-icon { font-size: .85rem; margin-top: 2px; flex-shrink: 0; }
.wn-icon-rotated { transform: rotate(90deg); }
.wn-label-wrap { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.wn-label {
  font-size: .78rem;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.wn-sub {
  font-size: .62rem;
  color: var(--text-muted);
  font-family: var(--font-data);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Output ports */
.wn-ports-out {
  display: flex;
  justify-content: space-around;
  padding: 0 .5rem .35rem;
  gap: .25rem;
}
.wn-port-out-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.wn-port-label {
  font-size: .52rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: .05em;
  pointer-events: none;
}
.wn-port-out {
  width: 12px;
  height: 12px;
  background: var(--surface-2);
  border: 2px solid var(--text-muted);
  border-radius: 50%;
  cursor: crosshair;
  z-index: 15;
  transition: background .12s, border-color .12s;
}
.wn-port-out:hover { background: var(--accent); border-color: var(--accent); }
</style>
