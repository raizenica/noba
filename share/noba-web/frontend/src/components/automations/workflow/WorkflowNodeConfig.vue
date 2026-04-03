<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed, onMounted } from 'vue'
import PluginNodeConfig from './PluginNodeConfig.vue'
import { useWorkflowNodes } from '../../../composables/useWorkflowNodes'

const { fetchNodeTypes, actionCatalog, ready } = useWorkflowNodes()
onMounted(fetchNodeTypes)

const props = defineProps({
  node: { type: Object, default: null },  // selected node data (null = nothing selected)
})

const emit = defineEmits(['update', 'delete', 'close'])

// ACTION_CATALOG is now fetched from /api/workflow-nodes via useWorkflowNodes().
// Falls back to empty array until the fetch completes (built-ins always included server-side).
const ACTION_CATALOG = actionCatalog

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

// Derived helpers for action node sub-type config
const actionType = computed(() => props.node?.config?.type || null)
const actionParams = computed(() => props.node?.config?.config || {})

function onField(field, value) {
  if (!props.node) return
  emit('update', { ...props.node, [field]: value })
}

function onActionType(type) {
  if (!props.node) return
  emit('update', { ...props.node, config: { type, config: {} } })
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

    <!-- Action node: sub-type picker + config -->
    <template v-if="node.type === 'action'">
      <div class="wnc-field">
        <label class="wnc-label">Action Type</label>
        <select
          class="wnc-input"
          :value="actionType || ''"
          @change="onActionType($event.target.value)"
        >
          <option value="" disabled>— select type —</option>
          <option v-for="cat in ACTION_CATALOG" :key="cat.type" :value="cat.type">
            {{ cat.label }}
          </option>
        </select>
        <span v-if="!ready" class="wnc-hint">Loading node types…</span>
      </div>

      <!-- Built-in action types: no extra config fields -->
      <template v-if="actionType && ['service','script','webhook','http','agent_command','remediation'].includes(actionType)">
        <span class="wnc-hint">Configure this action in the workflow runner.</span>
      </template>

      <!-- Plugin node config — renders dynamic fields from WORKFLOW_NODE descriptor -->
      <template v-else-if="actionType && !['service','script','webhook','http','agent_command','remediation'].includes(actionType)">
        <PluginNodeConfig
          :fields="ACTION_CATALOG.find(n => n.type === actionType)?.fields || []"
          :params="actionParams"
          @update="p => emit('update', { ...node, config: { type: actionType, config: p } })"
        />
      </template>
    </template>

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
