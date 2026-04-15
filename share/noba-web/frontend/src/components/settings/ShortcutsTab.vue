<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, onMounted } from 'vue'

const LS_KEY = 'noba-keybindings'

const defaults = [
  { id: 'settings',    keys: ['S'],         description: 'Open Settings' },
  { id: 'refresh',     keys: ['R'],         description: 'Refresh now' },
  { id: 'escape',      keys: ['Esc'],       description: 'Close modal / panel', fixed: true },
  { id: 'dashboard',   keys: ['D'],         description: 'Go to Dashboard' },
  { id: 'agents',      keys: ['A'],         description: 'Go to Agents' },
  { id: 'logs',        keys: ['L'],         description: 'Go to Logs' },
  { id: 'monitoring',  keys: ['M'],         description: 'Go to Monitoring' },
  { id: 'infra',       keys: ['I'],         description: 'Go to Infrastructure' },
  { id: 'security',    keys: ['E'],         description: 'Go to Security' },
  { id: 'automations', keys: ['W'],         description: 'Go to Automations' },
  { id: 'help',        keys: ['?'],         description: 'Show shortcut reference', fixed: true },
  { id: 'search',      keys: ['Ctrl', 'K'], description: 'Command palette', fixed: true },
]

const shortcuts = ref([])
const editingId = ref(null)
const capturedKey = ref('')

onMounted(() => {
  const saved = localStorage.getItem(LS_KEY)
  if (saved) {
    try {
      const custom = JSON.parse(saved)
      shortcuts.value = defaults.map(d => {
        const c = custom.find(x => x.id === d.id)
        return { ...d, keys: c ? c.keys : [...d.keys] }
      })
    } catch {
      shortcuts.value = defaults.map(d => ({ ...d, keys: [...d.keys] }))
    }
  } else {
    shortcuts.value = defaults.map(d => ({ ...d, keys: [...d.keys] }))
  }
})

function startEdit(s) {
  if (s.fixed) return
  editingId.value = s.id
  capturedKey.value = ''
}

function onCapture(e) {
  e.preventDefault()
  e.stopPropagation()
  const parts = []
  if (e.ctrlKey) parts.push('Ctrl')
  if (e.altKey) parts.push('Alt')
  if (e.shiftKey) parts.push('Shift')
  const key = e.key
  if (!['Control', 'Alt', 'Shift', 'Meta'].includes(key)) {
    parts.push(key.length === 1 ? key.toUpperCase() : key)
    const s = shortcuts.value.find(x => x.id === editingId.value)
    if (s) s.keys = parts
    editingId.value = null
    save()
  }
}

function resetKey(s) {
  const d = defaults.find(x => x.id === s.id)
  if (d) s.keys = [...d.keys]
  save()
}

function resetAll() {
  shortcuts.value = defaults.map(d => ({ ...d, keys: [...d.keys] }))
  save()
}

function save() {
  localStorage.setItem(LS_KEY, JSON.stringify(
    shortcuts.value.map(s => ({ id: s.id, keys: s.keys }))
  ))
}
</script>

<template>
  <div>
    <div class="s-section">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.5rem">
        <span class="s-label" style="margin:0">Keyboard Shortcuts</span>
        <button class="btn btn-sm" @click="resetAll">
          <i class="fas fa-undo"></i> Reset All
        </button>
      </div>
      <p class="help-text" style="margin-bottom:1rem">
        Click a keybinding to change it. Press the new key combination to assign.
      </p>
      <div style="display:flex;flex-direction:column;gap:.5rem">
        <div
          v-for="s in shortcuts" :key="s.id"
          style="display:flex;align-items:center;gap:.75rem;padding:.35rem .5rem;border-radius:4px"
          :style="editingId === s.id ? 'background:var(--accent-dim);border:1px solid var(--accent)' : 'border:1px solid transparent'"
        >
          <!-- Keybinding display / capture -->
          <div
            style="display:flex;gap:.25rem;min-width:110px;cursor:pointer"
            :style="s.fixed ? 'opacity:.5;cursor:default' : ''"
            @click="startEdit(s)"
            @keydown="editingId === s.id && onCapture($event)"
            :tabindex="editingId === s.id ? 0 : -1"
            :ref="el => { if (editingId === s.id && el) el.focus() }"
          >
            <template v-if="editingId === s.id">
              <kbd style="display:inline-block;padding:.1rem .5rem;background:var(--accent);color:var(--bg);border-radius:3px;font-family:var(--font-data);font-size:.75rem;animation:pulse 1s infinite">
                Press key...
              </kbd>
            </template>
            <template v-else>
              <kbd
                v-for="k in s.keys" :key="k"
                style="display:inline-block;padding:.1rem .4rem;background:var(--surface-2);border:1px solid var(--border);border-radius:3px;font-family:var(--font-data);font-size:.75rem;line-height:1.5"
              >{{ k }}</kbd>
            </template>
          </div>

          <!-- Description -->
          <span style="color:var(--text-muted);font-size:.82rem;flex:1">{{ s.description }}</span>

          <!-- Reset individual -->
          <button
            v-if="!s.fixed"
            class="icon-btn"
            style="font-size:.7rem;opacity:.3"
            @click="resetKey(s)"
            title="Reset to default"
          >
            <i class="fas fa-undo"></i>
          </button>
          <span v-if="s.fixed" style="font-size:.6rem;color:var(--text-dim)">fixed</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .5; }
}
</style>
