// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { useApi } from './useApi'

export function useHealing() {
  const { get, post, del } = useApi()

  return {
    // Ledger
    fetchLedger: (params = {}) => {
      const qs = new URLSearchParams(params).toString()
      return get(`/api/healing/ledger${qs ? '?' + qs : ''}`)
    },
    // Effectiveness
    fetchEffectiveness: () => get('/api/healing/effectiveness'),
    // Trust
    fetchTrust: () => get('/api/healing/trust'),
    promoteTrust: (ruleId) => post(`/api/healing/trust/${encodeURIComponent(ruleId)}/promote`),
    // Suggestions
    fetchSuggestions: () => get('/api/healing/suggestions'),
    dismissSuggestion: (id) => post(`/api/healing/suggestions/${id}/dismiss`),
    // Dependencies
    fetchDependencies: () => get('/api/healing/dependencies'),
    validateDependencies: (config) => post('/api/healing/dependencies/validate', config),
    // Maintenance
    fetchMaintenance: () => get('/api/healing/maintenance'),
    createMaintenance: (data) => post('/api/healing/maintenance', data),
    endMaintenance: (id) => del(`/api/healing/maintenance/${id}`),
    // Capabilities
    fetchCapabilities: (hostname) => get(`/api/healing/capabilities/${encodeURIComponent(hostname)}`),
    refreshCapabilities: (hostname) => post(`/api/healing/capabilities/${encodeURIComponent(hostname)}/refresh`),
    // Rollback
    rollback: (ledgerId) => post(`/api/healing/rollback/${ledgerId}`),
    // Trust demotion
    demoteTrust: (ruleId) => post(`/api/healing/trust/${encodeURIComponent(ruleId)}/demote`),
    // Dry-run
    dryRun: (event) => post('/api/healing/dry-run', { event }),
    // Chaos
    fetchChaosScenarios: () => get('/api/healing/chaos/scenarios'),
    runChaos: (scenario, dryRun = true) => post('/api/healing/chaos/run', { scenario, dry_run: dryRun }),
    // Health
    fetchHealth: () => get('/api/healing/health'),
  }
}
