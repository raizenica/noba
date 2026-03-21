<script setup>
import { computed } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import DashboardCard from './DashboardCard.vue'

const settings = useSettingsStore()

const DEF_BOOKMARKS = 'Router|http://192.168.1.1|fa-network-wired, Pi-hole|http://pi.hole/admin|fa-shield-alt'

const bookmarksStr = computed(() =>
  settings.data.bookmarks || localStorage.getItem('noba-bookmarks') || DEF_BOOKMARKS
)

const parsedBookmarks = computed(() =>
  (bookmarksStr.value || '').split(',').filter(b => b.trim()).map(b => {
    const p = b.split('|')
    return {
      name: (p[0] || 'Link').trim(),
      url:  (p[1] || '#').trim(),
      icon: (p[2] || 'fa-link').trim(),
    }
  })
)
</script>

<template>
  <DashboardCard title="Homelab Links" icon="fas fa-bookmark" card-id="bookmarks">
    <div class="bm-grid">
      <a
        v-for="b in parsedBookmarks"
        :key="b.name"
        :href="b.url"
        target="_blank"
        rel="noopener noreferrer"
        class="bm-link"
      >
        <i class="fas" :class="b.icon" aria-hidden="true"></i>
        <span>{{ b.name }}</span>
      </a>
    </div>
    <div v-if="parsedBookmarks.length === 0" class="empty-msg">No bookmarks configured.</div>
  </DashboardCard>
</template>
