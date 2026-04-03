<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
const emit = defineEmits(['add'])
</script>

<template>
  <div class="empty-msg" style="padding:2rem;text-align:center;background:var(--surface);border:1px dashed var(--border);border-radius:6px">
    <i class="fas fa-plug" style="font-size:2rem;display:block;margin-bottom:.75rem;opacity:.3"></i>
    No managed integrations yet.
    <br>
    <button class="btn btn-primary" style="margin-top:1rem" @click="emit('add')">
      <i class="fas fa-plus"></i> Add First Integration
    </button>
  </div>
</template>
