<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
const model = defineModel({ type: String, default: 'execute' })
const levels = [
  { value: 'execute',  label: 'Execute',  desc: 'Run immediately',        icon: 'fa-bolt',  color: 'var(--success)' },
  { value: 'approve',  label: 'Approve',  desc: 'Queue for approval',     icon: 'fa-clock', color: 'var(--warning)' },
  { value: 'notify',   label: 'Notify',   desc: 'Notify only',            icon: 'fa-bell',  color: 'var(--accent)'  },
  { value: 'disabled', label: 'Disabled', desc: 'Rule inactive',          icon: 'fa-ban',   color: 'var(--text-dim)'},
]
</script>

<template>
  <select class="field-select" v-model="model">
    <option v-for="l in levels" :key="l.value" :value="l.value">
      {{ l.label }} — {{ l.desc }}
    </option>
  </select>
</template>
