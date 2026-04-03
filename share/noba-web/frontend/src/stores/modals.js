// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useModalsStore = defineStore('modals', () => {
  const historyModal = ref({ show: false, metric: '', range: 24 })
  const smartModal = ref(false)
  const profileModal = ref(false)
  const searchModal = ref(false)
  const terminalModal = ref(false)
  const sessionsModal = ref(false)
  const systemInfoModal = ref(false)
  const networkModal = ref(false)
  const processModal = ref(false)
  const backupExplorerModal = ref(false)
  const aiChat = ref(false)

  // ── Global confirm dialog ────────────────────────────────────────────────
  const confirmDialog = ref({ show: false, message: '', resolve: null })

  function confirm(message) {
    return new Promise((resolve) => {
      confirmDialog.value = { show: true, message, resolve }
    })
  }

  function confirmYes() {
    const r = confirmDialog.value.resolve
    confirmDialog.value = { show: false, message: '', resolve: null }
    if (r) r(true)
  }

  function confirmNo() {
    const r = confirmDialog.value.resolve
    confirmDialog.value = { show: false, message: '', resolve: null }
    if (r) r(false)
  }

  function showHistory(metric, range = 24) {
    historyModal.value = { show: true, metric, range }
  }

  function closeHistory() {
    historyModal.value = { show: false, metric: '', range: 24 }
  }

  return {
    historyModal,
    smartModal,
    profileModal,
    searchModal,
    terminalModal,
    sessionsModal,
    systemInfoModal,
    networkModal,
    processModal,
    backupExplorerModal,
    aiChat,
    confirmDialog,
    confirm,
    confirmYes,
    confirmNo,
    showHistory,
    closeHistory,
  }
})
