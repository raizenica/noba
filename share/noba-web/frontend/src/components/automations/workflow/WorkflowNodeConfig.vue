<script setup>
import { computed } from 'vue'

const props = defineProps({
  node: { type: Object, default: null },  // selected node data (null = nothing selected)
})

const emit = defineEmits(['update', 'delete', 'close'])

const nodeTypeLabel = computed(() => {
  const map = {
    action:        'Action',
    condition:     'Condition',
    approval_gate: 'Approval Gate',
    parallel:      'Parallel',
    delay:         'Delay',
    notification:  'Notification',
  }
  return props.node ? (map[props.node.type] || props.node.type) : ''
})

function onField(field, value) {
  if (!props.node) return
  emit('update', { ...props.node, [field]: value })
}

function onDelete() {
  if (!props.node) return
  emit('delete', props.node.id)
}
</script>

<template>
  <div v-if="node" class="wnc-panel">
    <!-- Header -->
    <div class="wnc-header">
      <span class="wnc-title">{{ nodeTypeLabel }}</span>
      <button class="wnc-close" title="Close panel" @click="emit('close')">
        <i class="fas fa-times"></i>
      </button>
    </div>

    <!-- Label field (all node types) -->
    <div class="wnc-field">
      <label class="wnc-label">Label</label>
      <input
        class="wnc-input"
        :value="node.label"
        placeholder="Node label"
        @input="onField('label', $event.target.value)"
      />
    </div>

    <!-- Condition expression -->
    <div v-if="node.type === 'condition'" class="wnc-field">
      <label class="wnc-label">Expression</label>
      <input
        class="wnc-input"
        :value="node.expression"
        placeholder="e.g. status == 'ok'"
        @input="onField('expression', $event.target.value)"
      />
      <span class="wnc-hint">Evaluated as a truthy/falsy condition.</span>
    </div>

    <!-- Delay seconds -->
    <div v-if="node.type === 'delay'" class="wnc-field">
      <label class="wnc-label">Delay (seconds)</label>
      <input
        class="wnc-input"
        type="number"
        min="1"
        :value="node.seconds || 30"
        @input="onField('seconds', parseInt($event.target.value) || 30)"
      />
    </div>

    <!-- Notification message -->
    <div v-if="node.type === 'notification'" class="wnc-field">
      <label class="wnc-label">Message</label>
      <input
        class="wnc-input"
        :value="node.message"
        placeholder="Notification message"
        @input="onField('message', $event.target.value)"
      />
    </div>

    <!-- Node ID (read-only) -->
    <div class="wnc-field">
      <label class="wnc-label">Node ID</label>
      <span class="wnc-id">{{ node.id }}</span>
    </div>

    <!-- Delete action -->
    <div class="wnc-footer">
      <button class="wnc-delete-btn" @click="onDelete">
        <i class="fas fa-trash"></i> Delete Node
      </button>
    </div>
  </div>
</template>

<style scoped>
.wnc-panel {
  display: flex;
  flex-direction: column;
  gap: .55rem;
  padding: .6rem .65rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-top: none;
  border-radius: 0 0 6px 0;
  min-width: 200px;
  max-width: 240px;
}

.wnc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  padding-bottom: .4rem;
}

.wnc-title {
  font-size: .72rem;
  font-weight: 700;
  color: var(--text);
  text-transform: uppercase;
  letter-spacing: .05em;
}

.wnc-close {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: .75rem;
  padding: 2px 4px;
  border-radius: 3px;
}
.wnc-close:hover { color: var(--danger); }

.wnc-field {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.wnc-label {
  font-size: .62rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: .05em;
}

.wnc-input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-size: .75rem;
  padding: .25rem .4rem;
  width: 100%;
  box-sizing: border-box;
}
.wnc-input:focus { outline: none; border-color: var(--accent); }

.wnc-hint {
  font-size: .6rem;
  color: var(--text-muted);
  font-style: italic;
}

.wnc-id {
  font-size: .68rem;
  color: var(--text-muted);
  font-family: var(--font-data);
}

.wnc-footer {
  margin-top: .25rem;
  border-top: 1px solid var(--border);
  padding-top: .4rem;
}

.wnc-delete-btn {
  display: inline-flex;
  align-items: center;
  gap: .3rem;
  background: var(--danger-dim);
  border: 1px solid var(--danger-border);
  border-radius: 4px;
  color: var(--danger);
  font-size: .7rem;
  padding: .25rem .5rem;
  cursor: pointer;
  width: 100%;
  justify-content: center;
}
.wnc-delete-btn:hover { background: var(--danger); color: #fff; }
</style>
