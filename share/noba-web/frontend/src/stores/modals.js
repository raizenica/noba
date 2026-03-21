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
    showHistory,
    closeHistory,
  }
})
