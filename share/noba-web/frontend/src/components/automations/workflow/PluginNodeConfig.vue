<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<!-- PluginNodeConfig.vue — renders a dynamic config form from a fields[] descriptor -->
<script setup>
const props = defineProps({
  // Array of field descriptors: { key, type, label, required?, default?, options? }
  fields:  { type: Array,  default: () => [] },
  // Current param values: { [key]: value }
  params:  { type: Object, default: () => ({}) },
})

const emit = defineEmits(['update'])

function val(key, defaultVal = '') {
  return props.params[key] ?? defaultVal
}

function set(key, value) {
  emit('update', { ...props.params, [key]: value })
}
</script>

<template>
  <div class="pnc-fields">
    <template v-for="field in fields" :key="field.key">
      <!-- String -->
      <div v-if="field.type === 'string' || !field.type" class="wnc-field">
        <label class="wnc-label">
          {{ field.label }}<span v-if="field.required" class="wnc-required">*</span>
        </label>
        <input
          class="wnc-input"
          type="text"
          :placeholder="field.label"
          :value="val(field.key, field.default ?? '')"
          @input="set(field.key, $event.target.value)"
        />
      </div>

      <!-- Number -->
      <div v-else-if="field.type === 'number'" class="wnc-field">
        <label class="wnc-label">{{ field.label }}</label>
        <input
          class="wnc-input"
          type="number"
          :value="val(field.key, field.default ?? 0)"
          @input="set(field.key, Number($event.target.value))"
        />
      </div>

      <!-- Boolean -->
      <div v-else-if="field.type === 'boolean'" class="wnc-field wnc-field--inline">
        <input
          type="checkbox"
          :id="`pnc-${field.key}`"
          :checked="val(field.key, field.default ?? false)"
          @change="set(field.key, $event.target.checked)"
        />
        <label :for="`pnc-${field.key}`" class="wnc-label">{{ field.label }}</label>
      </div>

      <!-- Select -->
      <div v-else-if="field.type === 'select'" class="wnc-field">
        <label class="wnc-label">{{ field.label }}</label>
        <select
          class="wnc-input"
          :value="val(field.key, field.default ?? '')"
          @change="set(field.key, $event.target.value)"
        >
          <option v-for="opt in (field.options || [])" :key="opt" :value="opt">{{ opt }}</option>
        </select>
      </div>

      <!-- List (comma-separated) -->
      <div v-else-if="field.type === 'list'" class="wnc-field">
        <label class="wnc-label">{{ field.label }} <span class="wnc-hint">(comma-separated)</span></label>
        <input
          class="wnc-input"
          type="text"
          :value="Array.isArray(val(field.key, [])) ? val(field.key, []).join(', ') : val(field.key, '')"
          @input="set(field.key, $event.target.value.split(',').map(s => s.trim()).filter(Boolean))"
        />
      </div>
    </template>

    <p v-if="!fields.length" class="wnc-hint">This node has no configurable parameters.</p>
  </div>
</template>

<style scoped>
.wnc-field { display: flex; flex-direction: column; gap: .25rem; margin-bottom: .5rem; }
.wnc-field--inline { flex-direction: row; align-items: center; gap: .5rem; }
.wnc-label { font-size: .7rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; }
.wnc-input { background: var(--surface); border: 1px solid var(--border); border-radius: 4px; color: var(--text); padding: .3rem .5rem; font-size: .8rem; width: 100%; box-sizing: border-box; }
.wnc-hint  { font-size: .65rem; color: var(--text-dim); }
.wnc-required { color: var(--danger); margin-left: 2px; }
</style>
