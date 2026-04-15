// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
// share/noba-web/frontend/src/composables/useWorkflowNodes.js
import { ref, computed } from 'vue'
import { useApi } from './useApi'

// Module-level cache — shared across all component instances
const _cache = ref(null)   // null = not yet fetched; [] = fetched (may be empty)
const _fetching = ref(false)

export function useWorkflowNodes() {
  const { get } = useApi()

  async function fetchNodeTypes() {
    if (_cache.value !== null || _fetching.value) return
    _fetching.value = true
    try {
      const data = await get('/api/workflow-nodes')
      _cache.value = Array.isArray(data) ? data : []
    } catch {
      // Graceful degradation: built-ins still work without the API
      _cache.value = []
    } finally {
      _fetching.value = false
    }
  }

  // All action node subtypes — built-ins and plugins combined.
  // Built-ins appear first (category === 'builtin'), then plugins.
  const actionCatalog = computed(() =>
    (_cache.value || []).map(n => ({
      type:     n.type,
      icon:     n.icon,
      label:    n.label,
      desc:     n.description,
      fields:   n.fields  || [],
      category: n.category || 'builtin',
    }))
  )

  const ready = computed(() => _cache.value !== null)

  return { fetchNodeTypes, actionCatalog, ready }
}
