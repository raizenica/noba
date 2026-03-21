<script setup>
import { onMounted, ref } from 'vue'
import { useSettingsStore } from '../../stores/settings'

const settingsStore = useSettingsStore()
const saving = ref(false)
const saveMsg = ref('')

onMounted(async () => {
  await settingsStore.fetchPreferences()
  // Ensure all vis keys exist — default to true (visible) when not explicitly set
  for (const item of visItems) {
    if (settingsStore.vis[item.key] === undefined) {
      settingsStore.vis[item.key] = true
    }
  }
})

const visItems = [
  { key: 'core',          label: 'Core System' },
  { key: 'health',        label: 'System Health' },
  { key: 'netio',         label: 'Network I/O' },
  { key: 'hw',            label: 'Hardware' },
  { key: 'truenas',       label: 'TrueNAS Integration' },
  { key: 'plex',          label: 'Media Stack' },
  { key: 'downloads',     label: 'Download Stack' },
  { key: 'battery',       label: 'Power State' },
  { key: 'pihole',        label: 'Pi-hole DNS' },
  { key: 'storage',       label: 'Storage' },
  { key: 'scrutiny',      label: 'Disk Health (Scrutiny)' },
  { key: 'tailscale',     label: 'Tailscale' },
  { key: 'frigate',       label: 'Cameras (Frigate)' },
  { key: 'recovery',      label: 'Recovery Actions' },
  { key: 'agents',        label: 'Remote Agents' },
  { key: 'radar',         label: 'Network Radar' },
  { key: 'kuma',          label: 'Uptime Kuma' },
  { key: 'procs',         label: 'Resource Hogs' },
  { key: 'containers',    label: 'Containers' },
  { key: 'services',      label: 'Services' },
  { key: 'logs',          label: 'System Logs' },
  { key: 'automations',   label: 'Automation Deck' },
  { key: 'actions',       label: 'Quick Actions' },
  { key: 'bookmarks',     label: 'Homelab Links' },
  { key: 'proxmox',       label: 'Proxmox VE' },
  { key: 'adguard',       label: 'AdGuard Home' },
  { key: 'jellyfin',      label: 'Jellyfin' },
  { key: 'hass',          label: 'Home Assistant' },
  { key: 'unifi',         label: 'UniFi' },
  { key: 'speedtest',     label: 'Speedtest' },
  { key: 'diskIo',        label: 'Disk I/O' },
  { key: 'weather',       label: 'Weather' },
  { key: 'tautulli',      label: 'Tautulli' },
  { key: 'overseerr',     label: 'Overseerr' },
  { key: 'prowlarr',      label: 'Prowlarr' },
  { key: 'nextcloud',     label: 'Nextcloud' },
  { key: 'traefik',       label: 'Traefik' },
  { key: 'npm',           label: 'Nginx Proxy Manager' },
  { key: 'authentik',     label: 'Authentik' },
  { key: 'cloudflare',    label: 'Cloudflare' },
  { key: 'omv',           label: 'OpenMediaVault' },
  { key: 'xcpng',         label: 'XCP-ng' },
  { key: 'homebridge',    label: 'Homebridge' },
  { key: 'z2m',           label: 'Zigbee2MQTT' },
  { key: 'esphome',       label: 'ESPHome' },
  { key: 'unifiProtect',  label: 'UniFi Protect' },
  { key: 'pikvm',         label: 'PiKVM' },
  { key: 'k8s',           label: 'Kubernetes' },
  { key: 'gitea',         label: 'Gitea' },
  { key: 'gitlab',        label: 'GitLab' },
  { key: 'github',        label: 'GitHub' },
  { key: 'paperless',     label: 'Paperless-ngx' },
  { key: 'vaultwarden',   label: 'Vaultwarden' },
  { key: 'vpn',           label: 'VPN' },
  { key: 'certExpiry',    label: 'Cert Expiry' },
  { key: 'lidarr',        label: 'Lidarr' },
  { key: 'readarr',       label: 'Readarr' },
  { key: 'bazarr',        label: 'Bazarr' },
  { key: 'dockerUpdates', label: 'Docker Updates' },
  { key: 'devicePresence',label: 'Device Presence' },
]

async function save() {
  saving.value = true
  saveMsg.value = ''
  try {
    await settingsStore.savePreferences()
    saveMsg.value = 'Saved.'
    setTimeout(() => { saveMsg.value = '' }, 2500)
  } catch {
    saveMsg.value = 'Save failed.'
  } finally {
    saving.value = false
  }
}

function selectAll() {
  for (const item of visItems) settingsStore.vis[item.key] = true
}
function selectNone() {
  for (const item of visItems) settingsStore.vis[item.key] = false
}
</script>

<template>
  <div>
    <div class="s-section">
      <span class="s-label">Module Visibility</span>
      <p class="help-text" style="margin-bottom:.75rem">
        Choose which dashboard cards are shown. Save to apply.
      </p>
      <div style="display:flex;gap:.4rem;margin-bottom:.75rem">
        <button class="btn btn-xs" @click="selectAll">Select All</button>
        <button class="btn btn-xs" @click="selectNone">Select None</button>
      </div>
      <div class="toggle-grid">
        <label v-for="item in visItems" :key="item.key" class="toggle-item">
          <input type="checkbox" v-model="settingsStore.vis[item.key]">
          {{ item.label }}
        </label>
      </div>
    </div>

    <div style="margin-top:1.25rem;display:flex;gap:.75rem;align-items:center">
      <button class="btn btn-primary" :disabled="saving" @click="save">
        <i class="fas" :class="saving ? 'fa-spinner fa-spin' : 'fa-check'"></i>
        {{ saving ? 'Saving…' : 'Save Visibility' }}
      </button>
      <span v-if="saveMsg" style="font-size:.8rem;color:var(--text-muted)">{{ saveMsg }}</span>
    </div>
  </div>
</template>
