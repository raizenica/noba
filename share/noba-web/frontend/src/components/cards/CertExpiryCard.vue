<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()

const certExpiry = computed(() => dashboard.live.certExpiry || [])

function certBadgeClass(daysLeft) {
  if (daysLeft > 30) return 'bs'
  if (daysLeft > 7)  return 'bw'
  return 'bd'
}
</script>

<template>
  <DashboardCard title="Cert Expiry" icon="fas fa-certificate" card-id="certExpiry">
    <template v-if="certExpiry.length > 0">
      <div
        v-for="cert in certExpiry"
        :key="cert.host"
        class="row"
      >
        <span class="row-label">{{ cert.host }}</span>
        <span class="badge" :class="certBadgeClass(cert.days_left)">
          {{ cert.days_left }} days
        </span>
      </div>
    </template>
    <div v-else class="empty-msg">No certificates to monitor.</div>
  </DashboardCard>
</template>
