<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { useNotificationsStore } from '../../stores/notifications'
const notifs = useNotificationsStore()
</script>

<template>
  <div class="toast-container">
    <TransitionGroup name="slide">
      <div v-for="toast in notifs.toasts" :key="toast.id"
           class="toast-item" :class="'toast-' + toast.type"
           @click="notifs.removeToast(toast.id)">
        {{ toast.message }}
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-container {
  position: fixed;
  bottom: 1rem;
  right: 1rem;
  z-index: 9999;
  display: flex;
  flex-direction: column-reverse;
  gap: .5rem;
  pointer-events: none;
}
.toast-item {
  pointer-events: auto;
  padding: .6rem 1rem;
  border-radius: 6px;
  font-size: .85rem;
  cursor: pointer;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text);
  max-width: 360px;
  box-shadow: 0 4px 12px rgba(0,0,0,.3);
}
.toast-success { border-color: var(--success); background: var(--success-dim); }
.toast-warning { border-color: var(--warning); background: var(--warning-dim); }
.toast-danger { border-color: var(--danger); background: var(--danger-dim); }
.toast-info { border-color: var(--accent); background: var(--accent-dim); }
</style>
