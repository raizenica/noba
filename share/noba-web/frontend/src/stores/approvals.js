// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useApi } from '../composables/useApi'

export const useApprovalsStore = defineStore('approvals', () => {
  const pending = ref([])
  const count = ref(0)

  async function fetchPending() {
    const { get } = useApi()
    try {
      const data = await get('/api/approvals?status=pending')
      pending.value = data || []
      count.value = pending.value.length
    } catch { /* ignore */ }
  }

  async function fetchCount() {
    const { get } = useApi()
    try {
      const data = await get('/api/approvals/count')
      count.value = data?.count || 0
    } catch { /* ignore */ }
  }

  async function decide(approvalId, decision) {
    const { post } = useApi()
    await post(`/api/approvals/${approvalId}/decide`, { decision })
    await fetchPending()
  }

  return { pending, count, fetchPending, fetchCount, decide }
})
