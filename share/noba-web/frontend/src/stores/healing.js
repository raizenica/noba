// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { defineStore } from 'pinia'
import { ref, shallowRef, computed } from 'vue'
import { useHealing } from '../composables/useHealing'

export const useHealingStore = defineStore('healing', () => {
  const api = useHealing()

  // State (using shallowRef for large arrays)
  const ledger = shallowRef([])
  const trust = shallowRef([])
  const suggestions = shallowRef([])
  const dependencies = shallowRef([])
  const maintenance = shallowRef([])
  const effectiveness = ref({})
  const loading = ref(false)
  const lastFetch = ref(0)

  // Computed
  const pendingApprovals = computed(() =>
    ledger.value.filter(e => e.trust_level === 'approve' && e.action_success == null)
  )
  const activeMaintenance = computed(() =>
    maintenance.value.filter(w => w.active)
  )
  const openCircuitBreakers = computed(() =>
    trust.value.filter(t => t.current_level === 'notify' && (t.demotion_count || 0) > 0)
  )
  const suggestionCount = computed(() => suggestions.value.length)
  const activeHealCount = computed(() =>
    ledger.value.filter(e =>
      e.action_success === null && e.trust_level === 'execute'
    ).length
  )

  // Actions
  async function fetchAll() {
    loading.value = true
    try {
      const results = await Promise.all([
        api.fetchLedger({ limit: 100 }),
        api.fetchTrust(),
        api.fetchSuggestions(),
        api.fetchDependencies(),
        api.fetchMaintenance(),
        api.fetchEffectiveness(),
      ])
      if (results[0]) ledger.value = results[0]
      if (results[1]) trust.value = results[1]
      if (results[2]) suggestions.value = results[2]
      if (results[3]) dependencies.value = results[3]
      if (results[4]) maintenance.value = results[4]
      if (results[5]) effectiveness.value = results[5]
      lastFetch.value = Date.now()
    } finally {
      loading.value = false
    }
  }

  async function fetchLedger(params = {}) {
    const data = await api.fetchLedger(params)
    if (data) ledger.value = data
  }

  async function fetchTrust() {
    const data = await api.fetchTrust()
    if (data) trust.value = data
  }

  async function fetchSuggestions() {
    const data = await api.fetchSuggestions()
    if (data) suggestions.value = data
  }

  async function fetchMaintenance() {
    const data = await api.fetchMaintenance()
    if (data) maintenance.value = data
  }

  async function promoteTrust(ruleId) {
    const result = await api.promoteTrust(ruleId)
    if (result) await fetchTrust()
    return result
  }

  async function dismissSuggestion(id) {
    const result = await api.dismissSuggestion(id)
    if (result) await fetchSuggestions()
    return result
  }

  async function createMaintenanceWindow(data) {
    const result = await api.createMaintenance(data)
    if (result) await fetchMaintenance()
    return result
  }

  async function endMaintenanceWindow(id) {
    const result = await api.endMaintenance(id)
    if (result) await fetchMaintenance()
    return result
  }

  async function rollbackAction(ledgerId) {
    return await api.rollback(ledgerId)
  }

  return {
    // State
    ledger, trust, suggestions, dependencies, maintenance,
    effectiveness, loading, lastFetch,
    // Computed
    pendingApprovals, activeMaintenance, openCircuitBreakers,
    suggestionCount, activeHealCount,
    // Actions
    fetchAll, fetchLedger, fetchTrust, fetchSuggestions, fetchMaintenance,
    promoteTrust, dismissSuggestion,
    createMaintenanceWindow, endMaintenanceWindow, rollbackAction,
  }
})
