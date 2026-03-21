<script setup>
const shortcuts = [
  { keys: ['S'],       description: 'Open Settings' },
  { keys: ['R'],       description: 'Refresh now' },
  { keys: ['Esc'],     description: 'Close modal / panel' },
  { keys: ['D'],       description: 'Go to Dashboard' },
  { keys: ['A'],       description: 'Go to Agents' },
  { keys: ['L'],       description: 'Go to Logs' },
  { keys: ['M'],       description: 'Go to Monitoring' },
  { keys: ['?'],       description: 'Show this shortcut reference' },
  { keys: ['Ctrl', 'K'], description: 'Command palette (if enabled)' },
]
</script>

<template>
  <div>
    <div class="s-section">
      <span class="s-label">Keyboard Shortcuts</span>
      <p class="help-text" style="margin-bottom:1rem">These shortcuts work anywhere in the dashboard.</p>
      <div style="display:flex;flex-direction:column;gap:.6rem">
        <div
          v-for="s in shortcuts" :key="s.description"
          style="display:flex;align-items:center;gap:.75rem"
        >
          <div style="display:flex;gap:.25rem;min-width:100px">
            <kbd
              v-for="k in s.keys" :key="k"
              style="display:inline-block;padding:.1rem .4rem;background:var(--surface-2);border:1px solid var(--border);border-radius:3px;font-family:var(--font-data);font-size:.75rem;line-height:1.5"
            >{{ k }}</kbd>
          </div>
          <span style="color:var(--text-muted);font-size:.82rem">{{ s.description }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
