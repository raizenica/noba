import { defineStore } from 'pinia'
import { ref } from 'vue'

let _nextId = 0

export const useNotificationsStore = defineStore('notifications', () => {
  const toasts = ref([])

  function addToast(message, type = 'info', duration = 4000) {
    const id = ++_nextId
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
