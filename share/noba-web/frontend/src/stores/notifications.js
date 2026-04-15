// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { defineStore } from 'pinia'
import { ref } from 'vue'

let _nextId = 0

export const useNotificationsStore = defineStore('notifications', () => {
  const toasts = ref([])

  function addToast(message, type = 'info', duration) {
    const id = ++_nextId
    // Errors/warnings stay longer so users can read them
    if (duration === undefined) {
      duration = (type === 'danger' || type === 'error') ? 8000
               : type === 'warning' ? 6000
               : 4000
    }
    toasts.value.push({ id, message, type })
    if (duration > 0) {
      setTimeout(() => removeToast(id), duration)
    }
  }

  function removeToast(id) {
    toasts.value = toasts.value.filter(t => t.id !== id)
  }

  return { toasts, addToast, removeToast }
})
