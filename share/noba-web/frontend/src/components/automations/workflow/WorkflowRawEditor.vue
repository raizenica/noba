<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref } from 'vue'

const props = defineProps({
  modelValue: { type: Object, required: true },  // { nodes, edges, entry }
})
const emit = defineEmits(['apply', 'cancel'])

const rawJson = ref(JSON.stringify(props.modelValue, null, 2))
const rawError = ref('')

function apply() {
  try {
    const parsed = JSON.parse(rawJson.value)
    rawError.value = ''
    emit('apply', parsed)
  } catch (e) {
    rawError.value = 'Invalid JSON: ' + e.message
  }
}
</script>

<template>
  <div class="wre-container">
    <div class="wre-label">Edit the graph JSON directly, then click Apply.</div>
    <textarea v-model="rawJson" class="wre-textarea" spellcheck="false"></textarea>
    <div v-if="rawError" class="wre-error">{{ rawError }}</div>
    <div class="wre-actions">
      <button class="btn" @click="emit('cancel')">Cancel</button>
      <button class="btn btn-primary" @click="apply"><i class="fas fa-check"></i> Apply</button>
    </div>
  </div>
</template>

<style scoped>
.wre-container {
  border: 1px solid var(--border);
  border-top: none;
  border-radius: 0 0 6px 6px;
  padding: .75rem;
  background: var(--surface);
  display: flex;
  flex-direction: column;
  gap: .5rem;
}
.wre-label { font-size: .75rem; color: var(--text-muted); }
.wre-textarea {
  width: 100%;
  min-height: 240px;
  resize: vertical;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-family: var(--font-data);
  font-size: .75rem;
  padding: .5rem;
  box-sizing: border-box;
}
.wre-textarea:focus { outline: none; border-color: var(--accent); }
.wre-error { color: var(--danger); font-size: .75rem; }
.wre-actions { display: flex; justify-content: flex-end; gap: .5rem; }
</style>
