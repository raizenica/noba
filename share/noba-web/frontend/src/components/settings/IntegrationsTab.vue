<script setup>
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'
import IntegrationSetup from './IntegrationSetup.vue'

const settingsStore = useSettingsStore()
const { get, del: apiDel } = useApi()
const notifications = useNotificationsStore()

const intCat = ref('infra')
const saving = ref(false)
const saveMsg = ref('')

// Managed integrations
const instances = ref([])
const showSetup = ref(false)

async function fetchInstances() {
  try {
    instances.value = await get('/api/integrations/instances')
  } catch { /* silent */ }
}

async function deleteInstance(id) {
  if (!confirm(`Delete integration "${id}"?`)) return
  try {
    await apiDel('/api/integrations/instances/' + id)
    notifications.addToast('Integration deleted', 'success')
    await fetchInstances()
  } catch {
    notifications.addToast('Failed to delete integration', 'danger')
  }
}

function onInstanceSaved() {
  showSetup.value = false
  fetchInstances()
}

onMounted(async () => {
  if (!settingsStore.loaded) await settingsStore.fetchSettings()
  fetchInstances()
})

async function save() {
  saving.value = true
  saveMsg.value = ''
  try {
    await settingsStore.saveSettings()
    saveMsg.value = 'Saved.'
    setTimeout(() => { saveMsg.value = '' }, 2500)
  } catch {
    saveMsg.value = 'Save failed.'
  } finally {
    saving.value = false
  }
}

function toggleReveal(evt) {
  const input = evt.currentTarget.previousElementSibling
  if (input) input.type = input.type === 'password' ? 'text' : 'password'
}

const cats = [
  { key: 'infra',  label: 'Infrastructure', icon: 'fa-server' },
  { key: 'media',  label: 'Media',          icon: 'fa-film' },
  { key: 'network',label: 'Network',        icon: 'fa-network-wired' },
  { key: 'iot',    label: 'IoT & Home',     icon: 'fa-microchip' },
  { key: 'devops', label: 'DevOps',         icon: 'fa-code-branch' },
  { key: 'notify', label: 'Notifications',  icon: 'fa-bell' },
  { key: 'auth',   label: 'Auth & Security',icon: 'fa-lock' },
  { key: 'ai',     label: 'AI / LLM',       icon: 'fa-robot' },
]
</script>

<template>
  <div>
    <!-- New: Managed Integration Instances -->
    <div class="s-section" style="margin-bottom: 2rem;">
      <div class="s-label" style="display:flex;align-items:center;justify-content:space-between">
        <span>Managed Integrations</span>
        <button v-if="!showSetup" class="btn btn-xs btn-primary" @click="showSetup = true">
          <i class="fas fa-plus" style="margin-right:.3rem"></i> Add Integration
        </button>
      </div>

      <!-- Setup wizard -->
      <IntegrationSetup v-if="showSetup" @saved="onInstanceSaved" @cancel="showSetup = false" />

      <!-- Instance list -->
      <div v-if="!showSetup && instances.length" class="instance-list">
        <div v-for="inst in instances" :key="inst.id" class="instance-row">
          <span class="badge ba">{{ inst.platform }}</span>
          <span class="instance-id">{{ inst.id }}</span>
          <span class="text-muted">{{ inst.url }}</span>
          <span v-if="inst.site" class="badge bs">{{ inst.site }}</span>
          <span :class="['badge', inst.health_status === 'online' ? 'bs' : inst.health_status === 'offline' ? 'bd' : 'bw']">
            {{ inst.health_status || 'unknown' }}
          </span>
          <button class="btn btn-xs btn-danger" @click="deleteInstance(inst.id)">
            <i class="fas fa-trash"></i>
          </button>
        </div>
      </div>
      <div v-if="!showSetup && !instances.length" class="empty-msg">
        No managed integrations yet. Click "Add Integration" to set one up.
      </div>
    </div>

    <hr style="border-color: var(--border); margin: 1.5rem 0;" />

    <!-- Category bar -->
    <div style="display:flex;flex-wrap:wrap;gap:.3rem;margin-bottom:1rem;border-bottom:1px solid var(--border);padding-bottom:.6rem">
      <button
        v-for="c in cats" :key="c.key"
        class="btn btn-xs"
        :class="{ 'btn-primary': intCat === c.key }"
        @click="intCat = c.key"
      >
        <i class="fas" :class="c.icon" style="margin-right:.3rem"></i>{{ c.label }}
      </button>
    </div>

    <!-- ── INFRA ── -->
    <template v-if="intCat === 'infra'">
      <div class="s-section">
        <span class="s-label">Proxmox VE</span>
        <div class="field-2">
          <div>
            <label class="field-label">Base URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.proxmoxUrl" placeholder="https://192.168.1.100:8006">
          </div>
          <div>
            <label class="field-label">User (user@realm)</label>
            <input class="field-input" type="text" v-model="settingsStore.data.proxmoxUser" placeholder="root@pam">
          </div>
        </div>
        <div class="field-2" style="margin-top:.4rem">
          <div>
            <label class="field-label">API Token Name</label>
            <input class="field-input" type="text" v-model="settingsStore.data.proxmoxTokenName" placeholder="noba">
          </div>
          <div>
            <label class="field-label">API Token Value</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.proxmoxTokenValue" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">TrueNAS SCALE</span>
        <div class="field-2">
          <div>
            <label class="field-label">API URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.truenasUrl" placeholder="http://192.168.1.50">
          </div>
          <div>
            <label class="field-label">API Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.truenasKey" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Tailscale</span>
        <div class="field-2">
          <div>
            <label class="field-label">API Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.tailscaleApiKey" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
          <div>
            <label class="field-label">Tailnet</label>
            <input class="field-input" type="text" v-model="settingsStore.data.tailscaleTailnet" placeholder="yourname.github">
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Docker</span>
        <div>
          <label class="field-label">Docker Host Socket / TCP URL</label>
          <input class="field-input" type="text" v-model="settingsStore.data.dockerHost" placeholder="unix:///var/run/docker.sock">
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Uptime Kuma (Prometheus)</span>
        <div>
          <label class="field-label">Base URL</label>
          <input class="field-input" type="url" v-model="settingsStore.data.kumaUrl" placeholder="http://vnnas.example.org:3001">
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Speedtest Tracker</span>
        <div>
          <label class="field-label">URL</label>
          <input class="field-input" type="url" v-model="settingsStore.data.speedtestUrl" placeholder="http://192.168.1.50:8765">
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Scrutiny (Disk Health)</span>
        <div>
          <label class="field-label">URL</label>
          <input class="field-input" type="url" v-model="settingsStore.data.scrutinyUrl" placeholder="http://truenas:8080">
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Frigate (NVR)</span>
        <div>
          <label class="field-label">URL</label>
          <input class="field-input" type="url" v-model="settingsStore.data.frigateUrl" placeholder="http://frigate:5000">
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">InfluxDB</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.influxdbUrl" placeholder="http://influxdb:8086">
          </div>
          <div>
            <label class="field-label">Organization</label>
            <input class="field-input" type="text" v-model="settingsStore.data.influxdbOrg" placeholder="my-org">
          </div>
        </div>
        <div style="margin-top:.4rem">
          <label class="field-label">Token</label>
          <div class="reveal-wrap">
            <input class="field-input" type="password" v-model="settingsStore.data.influxdbToken" autocomplete="off">
            <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Graylog</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.graylogUrl" placeholder="http://graylog:9000">
          </div>
          <div>
            <label class="field-label">API Token</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.graylogToken" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Hardware Watchdog (BMC Mapping)</span>
        <div>
          <label class="field-label">Map OS IP to IPMI/BMC IP</label>
          <input class="field-input" type="text" v-model="settingsStore.data.bmcMap" placeholder="10.0.0.50|10.0.0.51">
        </div>
      </div>
    </template>

    <!-- ── MEDIA ── -->
    <template v-if="intCat === 'media'">
      <div class="s-section">
        <span class="s-label">Plex</span>
        <div class="field-2">
          <div>
            <label class="field-label">Base URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.plexUrl" placeholder="http://vnnas.example.org:32400">
          </div>
          <div>
            <label class="field-label">X-Plex-Token</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.plexToken" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Tautulli</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.tautulliUrl" placeholder="http://tautulli:8181">
          </div>
          <div>
            <label class="field-label">API Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.tautulliKey" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Download Stack (qBittorrent)</span>
        <div class="field-2">
          <div>
            <label class="field-label">qBittorrent URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.qbitUrl" placeholder="http://192.168.1.50:8080">
          </div>
          <div style="display:flex;gap:.5rem">
            <div style="flex:1">
              <label class="field-label">User</label>
              <input class="field-input" type="text" v-model="settingsStore.data.qbitUser" autocomplete="username">
            </div>
            <div style="flex:1">
              <label class="field-label">Pass</label>
              <div class="reveal-wrap">
                <input class="field-input" type="password" v-model="settingsStore.data.qbitPass" autocomplete="off">
                <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Radarr</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.radarrUrl" placeholder="http://192.168.1.50:7878">
          </div>
          <div>
            <label class="field-label">API Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.radarrKey" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Sonarr</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.sonarrUrl" placeholder="http://192.168.1.50:8989">
          </div>
          <div>
            <label class="field-label">API Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.sonarrKey" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Lidarr</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.lidarrUrl" placeholder="http://lidarr:8686">
          </div>
          <div>
            <label class="field-label">API Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.lidarrKey" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Readarr</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.readarrUrl" placeholder="http://readarr:8787">
          </div>
          <div>
            <label class="field-label">API Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.readarrKey" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Bazarr</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.bazarrUrl" placeholder="http://bazarr:6767">
          </div>
          <div>
            <label class="field-label">API Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.bazarrKey" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Overseerr</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.overseerrUrl" placeholder="http://overseerr:5055">
          </div>
          <div>
            <label class="field-label">API Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.overseerrKey" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Prowlarr</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.prowlarrUrl" placeholder="http://prowlarr:9696">
          </div>
          <div>
            <label class="field-label">API Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.prowlarrKey" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Jellyfin</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.jellyfinUrl" placeholder="http://192.168.1.50:8096">
          </div>
          <div>
            <label class="field-label">API Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.jellyfinKey" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ── NETWORK ── -->
    <template v-if="intCat === 'network'">
      <div class="s-section">
        <span class="s-label">Pi-hole DNS</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL / IP</label>
            <input class="field-input" type="url" v-model="settingsStore.data.piholeUrl" placeholder="http://192.168.100.111">
          </div>
          <div>
            <label class="field-label">App Password (v6)</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.piholeToken" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
          <div>
            <label class="field-label">Password (v6 auto-auth)</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.piholePassword" placeholder="Pi-hole v6 password" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">AdGuard Home</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.adguardUrl" placeholder="http://192.168.1.1:3000">
          </div>
          <div style="display:flex;gap:.5rem">
            <div style="flex:1">
              <label class="field-label">Username</label>
              <input class="field-input" type="text" v-model="settingsStore.data.adguardUser" autocomplete="username">
            </div>
            <div style="flex:1">
              <label class="field-label">Password</label>
              <div class="reveal-wrap">
                <input class="field-input" type="password" v-model="settingsStore.data.adguardPass" autocomplete="off">
                <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">UniFi Controller</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.unifiUrl" placeholder="https://192.168.1.1:8443">
          </div>
          <div style="display:flex;gap:.5rem">
            <div style="flex:1">
              <label class="field-label">Username</label>
              <input class="field-input" type="text" v-model="settingsStore.data.unifiUser" autocomplete="username">
            </div>
            <div style="flex:1">
              <label class="field-label">Password</label>
              <div class="reveal-wrap">
                <input class="field-input" type="password" v-model="settingsStore.data.unifiPass" autocomplete="off">
                <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
              </div>
            </div>
          </div>
        </div>
        <div style="margin-top:.5rem">
          <label class="field-label">Site</label>
          <input class="field-input" type="text" v-model="settingsStore.data.unifiSite" placeholder="default" style="max-width:200px">
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Nextcloud</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.nextcloudUrl" placeholder="https://cloud.example.com">
          </div>
          <div style="display:flex;gap:.5rem">
            <div style="flex:1">
              <label class="field-label">Username</label>
              <input class="field-input" type="text" v-model="settingsStore.data.nextcloudUser" autocomplete="username">
            </div>
            <div style="flex:1">
              <label class="field-label">Password</label>
              <div class="reveal-wrap">
                <input class="field-input" type="password" v-model="settingsStore.data.nextcloudPass" autocomplete="off">
                <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Traefik</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.traefikUrl" placeholder="http://traefik:8080">
          </div>
          <div>
            <span class="field-label">API (no auth needed)</span>
            <span style="font-size:.75rem;color:var(--text-dim)">Enable the API in your traefik config.</span>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Nginx Proxy Manager</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.npmUrl" placeholder="http://npm:81">
          </div>
          <div>
            <label class="field-label">API Token</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.npmToken" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Authentik</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.authentikUrl" placeholder="https://auth.example.com">
          </div>
          <div>
            <label class="field-label">API Token</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.authentikToken" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Cloudflare</span>
        <div class="field-2">
          <div>
            <label class="field-label">API Token</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.cloudflareToken" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
          <div>
            <label class="field-label">Zone ID</label>
            <input class="field-input" type="text" v-model="settingsStore.data.cloudflareZoneId" placeholder="Zone ID">
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Weather (OpenWeatherMap)</span>
        <div class="field-2">
          <div>
            <label class="field-label">API Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.weatherApiKey" autocomplete="off" placeholder="Your OWM API key">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
          <div>
            <label class="field-label">City</label>
            <input class="field-input" type="text" v-model="settingsStore.data.weatherCity" placeholder="London,UK">
          </div>
        </div>
      </div>
    </template>

    <!-- ── IOT / HOME ── -->
    <template v-if="intCat === 'iot'">
      <div class="s-section">
        <span class="s-label">Home Assistant</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.hassUrl" placeholder="http://192.168.1.50:8123">
          </div>
          <div>
            <label class="field-label">Long-Lived Access Token</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.hassToken" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Homebridge</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.homebridgeUrl" placeholder="http://homebridge:8581">
          </div>
          <div style="display:flex;gap:.5rem">
            <div style="flex:1">
              <label class="field-label">Username</label>
              <input class="field-input" type="text" v-model="settingsStore.data.homebridgeUser" autocomplete="username">
            </div>
            <div style="flex:1">
              <label class="field-label">Password</label>
              <div class="reveal-wrap">
                <input class="field-input" type="password" v-model="settingsStore.data.homebridgePass" autocomplete="off">
                <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Zigbee2MQTT</span>
        <div>
          <label class="field-label">URL</label>
          <input class="field-input" type="url" v-model="settingsStore.data.z2mUrl" placeholder="http://z2m:8080">
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">ESPHome</span>
        <div>
          <label class="field-label">URL</label>
          <input class="field-input" type="url" v-model="settingsStore.data.esphomeUrl" placeholder="http://esphome:6052">
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Frigate (IoT / Cameras)</span>
        <div>
          <label class="field-label">URL</label>
          <input class="field-input" type="url" v-model="settingsStore.data.frigateUrl" placeholder="http://frigate:5000">
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">UniFi Protect</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.unifiProtectUrl" placeholder="https://unvr.example.com">
          </div>
          <div style="display:flex;gap:.5rem">
            <div style="flex:1">
              <label class="field-label">Username</label>
              <input class="field-input" type="text" v-model="settingsStore.data.unifiProtectUser" autocomplete="username">
            </div>
            <div style="flex:1">
              <label class="field-label">Password</label>
              <div class="reveal-wrap">
                <input class="field-input" type="password" v-model="settingsStore.data.unifiProtectPass" autocomplete="off">
                <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">PiKVM</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.pikvmUrl" placeholder="https://pikvm.local">
          </div>
          <div style="display:flex;gap:.5rem">
            <div style="flex:1">
              <label class="field-label">Username</label>
              <input class="field-input" type="text" v-model="settingsStore.data.pikvmUser" autocomplete="username">
            </div>
            <div style="flex:1">
              <label class="field-label">Password</label>
              <div class="reveal-wrap">
                <input class="field-input" type="password" v-model="settingsStore.data.pikvmPass" autocomplete="off">
                <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ── DEVOPS ── -->
    <template v-if="intCat === 'devops'">
      <div class="s-section">
        <span class="s-label">Kubernetes</span>
        <div class="field-2">
          <div>
            <label class="field-label">API URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.k8sUrl" placeholder="https://k8s.example.com:6443">
          </div>
          <div>
            <label class="field-label">Bearer Token</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.k8sToken" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Gitea</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.giteaUrl" placeholder="https://gitea.example.com">
          </div>
          <div>
            <label class="field-label">API Token</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.giteaToken" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">GitLab</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.gitlabUrl" placeholder="https://gitlab.example.com">
          </div>
          <div>
            <label class="field-label">Personal Access Token</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.gitlabToken" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">GitHub</span>
        <div>
          <label class="field-label">Personal Access Token</label>
          <div class="reveal-wrap">
            <input class="field-input" type="password" v-model="settingsStore.data.githubToken" autocomplete="off" placeholder="ghp_xxxx...">
            <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Paperless-ngx</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.paperlessUrl" placeholder="http://paperless:8000">
          </div>
          <div>
            <label class="field-label">API Token</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.paperlessToken" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Vaultwarden</span>
        <div>
          <label class="field-label">URL</label>
          <input class="field-input" type="url" v-model="settingsStore.data.vaultwardenUrl" placeholder="https://vault.example.com">
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">OpenMediaVault</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.omvUrl" placeholder="http://omv:80">
          </div>
          <div style="display:flex;gap:.5rem">
            <div style="flex:1">
              <label class="field-label">Username</label>
              <input class="field-input" type="text" v-model="settingsStore.data.omvUser" autocomplete="username">
            </div>
            <div style="flex:1">
              <label class="field-label">Password</label>
              <div class="reveal-wrap">
                <input class="field-input" type="password" v-model="settingsStore.data.omvPass" autocomplete="off">
                <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">XCP-ng (Xen Orchestra)</span>
        <div class="field-2">
          <div>
            <label class="field-label">URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.xcpngUrl" placeholder="https://xo.example.com">
          </div>
          <div style="display:flex;gap:.5rem">
            <div style="flex:1">
              <label class="field-label">Username</label>
              <input class="field-input" type="text" v-model="settingsStore.data.xcpngUser" autocomplete="username">
            </div>
            <div style="flex:1">
              <label class="field-label">Password</label>
              <div class="reveal-wrap">
                <input class="field-input" type="password" v-model="settingsStore.data.xcpngPass" autocomplete="off">
                <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ── NOTIFICATIONS ── -->
    <template v-if="intCat === 'notify'">
      <div class="s-section">
        <span class="s-label">Pushover Notifications</span>
        <div class="field-2">
          <div>
            <label class="field-label">App Token</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.pushoverAppToken" autocomplete="off" placeholder="aTokenxxxx">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
          <div>
            <label class="field-label">User Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.pushoverUserKey" autocomplete="off" placeholder="uUserKeyxxx">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
        <label class="toggle-item" style="margin-top:.4rem">
          <input type="checkbox" v-model="settingsStore.data.pushoverEnabled">
          Enable Pushover alerts
        </label>
      </div>

      <div class="s-section">
        <span class="s-label">Gotify Notifications</span>
        <div class="field-2">
          <div>
            <label class="field-label">Server URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.gotifyUrl" placeholder="http://gotify.example.com">
          </div>
          <div>
            <label class="field-label">App Token</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.gotifyAppToken" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
        <label class="toggle-item" style="margin-top:.4rem">
          <input type="checkbox" v-model="settingsStore.data.gotifyEnabled">
          Enable Gotify alerts
        </label>
      </div>

      <div class="s-section">
        <span class="s-label">Telegram</span>
        <div class="field-2">
          <div>
            <label class="field-label">Bot Token</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.telegramBotToken" autocomplete="off" placeholder="123456:ABCxxxx">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
          <div>
            <label class="field-label">Chat ID</label>
            <input class="field-input" type="text" v-model="settingsStore.data.telegramChatId" placeholder="-1001234567890">
          </div>
        </div>
        <label class="toggle-item" style="margin-top:.4rem">
          <input type="checkbox" v-model="settingsStore.data.telegramEnabled">
          Enable Telegram alerts
        </label>
      </div>

      <div class="s-section">
        <span class="s-label">Discord</span>
        <div>
          <label class="field-label">Webhook URL</label>
          <div class="reveal-wrap">
            <input class="field-input" type="password" v-model="settingsStore.data.discordWebhook" autocomplete="off" placeholder="https://discord.com/api/webhooks/...">
            <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
          </div>
        </div>
        <label class="toggle-item" style="margin-top:.4rem">
          <input type="checkbox" v-model="settingsStore.data.discordEnabled">
          Enable Discord alerts
        </label>
      </div>

      <div class="s-section">
        <span class="s-label">Slack</span>
        <div>
          <label class="field-label">Webhook URL</label>
          <div class="reveal-wrap">
            <input class="field-input" type="password" v-model="settingsStore.data.slackWebhook" autocomplete="off" placeholder="https://hooks.slack.com/services/...">
            <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
          </div>
        </div>
        <label class="toggle-item" style="margin-top:.4rem">
          <input type="checkbox" v-model="settingsStore.data.slackEnabled">
          Enable Slack alerts
        </label>
      </div>
    </template>

    <!-- ── AUTH & SECURITY ── -->
    <template v-if="intCat === 'auth'">
      <div class="s-section">
        <span class="s-label">Agent Keys</span>
        <div>
          <label class="field-label">Comma-separated API keys for agent auth</label>
          <div class="reveal-wrap">
            <input class="field-input" type="password" v-model="settingsStore.data.agentKeys" placeholder="key1,key2" autocomplete="off">
            <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">SSO / OIDC</span>
        <div class="field-2">
          <div>
            <label class="field-label">Provider URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.oidcProviderUrl" placeholder="https://auth.example.com/realms/main">
          </div>
          <div>
            <label class="field-label">Client ID</label>
            <input class="field-input" type="text" v-model="settingsStore.data.oidcClientId" placeholder="noba">
          </div>
        </div>
        <div style="margin-top:.4rem">
          <label class="field-label">Client Secret</label>
          <div class="reveal-wrap">
            <input class="field-input" type="password" v-model="settingsStore.data.oidcClientSecret" autocomplete="off">
            <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">LDAP / Active Directory</span>
        <div class="field-2">
          <div>
            <label class="field-label">LDAP URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.ldapUrl" placeholder="ldap://dc.example.com:389">
          </div>
          <div>
            <label class="field-label">Base DN</label>
            <input class="field-input" type="text" v-model="settingsStore.data.ldapBaseDn" placeholder="dc=example,dc=com">
          </div>
        </div>
        <div class="field-2" style="margin-top:.4rem">
          <div>
            <label class="field-label">Bind DN</label>
            <input class="field-input" type="text" v-model="settingsStore.data.ldapBindDn" placeholder="cn=admin,dc=example,dc=com">
          </div>
          <div>
            <label class="field-label">Bind Password</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.ldapBindPassword" autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Security &amp; Monitoring</span>
        <div style="display:flex;flex-direction:column;gap:.7rem">
          <div>
            <label class="field-label">Cert Expiry Hosts (comma-separated)</label>
            <input class="field-input" type="text" v-model="settingsStore.data.certHosts" placeholder="example.com,cloud.example.com">
          </div>
          <div>
            <label class="field-label">Domain List (comma-separated)</label>
            <input class="field-input" type="text" v-model="settingsStore.data.domainList" placeholder="example.com,example.org">
          </div>
          <div>
            <label class="field-label">IP Whitelist (comma-separated)</label>
            <input class="field-input" type="text" v-model="settingsStore.data.ipWhitelist" placeholder="192.168.1.0/24,10.0.0.0/8">
          </div>
        </div>
      </div>
    </template>

    <!-- ── AI / LLM ── -->
    <template v-if="intCat === 'ai'">
      <div class="s-section">
        <span class="s-label">AI / LLM Configuration</span>
        <p class="help-text" style="margin-bottom:.8rem">
          Connect an LLM to enable the AI Ops Assistant. Supports Anthropic, OpenAI, local Ollama, or any OpenAI-compatible endpoint.
        </p>
        <div style="display:flex;align-items:center;gap:.8rem;margin-bottom:1rem">
          <label class="toggle-item">
            <input type="checkbox" v-model="settingsStore.data.llmEnabled">
            Enable AI Assistant
          </label>
        </div>
        <div class="field-2">
          <div>
            <label class="field-label">Provider</label>
            <select class="field-input field-select" v-model="settingsStore.data.llmProvider">
              <option value="">-- Select --</option>
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="openai">OpenAI</option>
              <option value="ollama">Ollama (local)</option>
              <option value="custom">Custom (OpenAI-compatible)</option>
            </select>
          </div>
          <div>
            <label class="field-label">Model</label>
            <input class="field-input" type="text" v-model="settingsStore.data.llmModel" placeholder="e.g. claude-sonnet-4-20250514, gpt-4o, llama3">
          </div>
        </div>
        <div class="field-2" style="margin-top:.75rem">
          <div>
            <label class="field-label">API Key</label>
            <div class="reveal-wrap">
              <input class="field-input" type="password" v-model="settingsStore.data.llmApiKey" placeholder="sk-ant-... or sk-..." autocomplete="off">
              <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
            </div>
            <span class="help-text" style="font-size:.7rem">Not needed for Ollama</span>
          </div>
          <div>
            <label class="field-label">Base URL</label>
            <input class="field-input" type="url" v-model="settingsStore.data.llmBaseUrl" placeholder="http://localhost:11434 (Ollama)">
            <span class="help-text" style="font-size:.7rem">Only needed for Ollama or custom endpoints</span>
          </div>
        </div>
        <div class="field-2" style="margin-top:.75rem">
          <div>
            <label class="field-label">Max Tokens</label>
            <input class="field-input" type="number" v-model.number="settingsStore.data.llmMaxTokens" min="256" max="32768" step="256">
          </div>
          <div>
            <label class="field-label">Temperature</label>
            <div style="display:flex;align-items:center;gap:.5rem">
              <input type="range" v-model.number="settingsStore.data.llmTemperature" min="0" max="1" step="0.1" style="flex:1">
              <span style="font-family:var(--font-data);font-size:.85rem;min-width:2rem;text-align:right">
                {{ settingsStore.data.llmTemperature ?? 0.7 }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- Save -->
    <div style="margin-top:1.25rem;display:flex;gap:.75rem;align-items:center">
      <button class="btn btn-primary" :disabled="saving" @click="save">
        <i class="fas" :class="saving ? 'fa-spinner fa-spin' : 'fa-check'"></i>
        {{ saving ? 'Saving…' : 'Save & Apply' }}
      </button>
      <span v-if="saveMsg" style="font-size:.8rem;color:var(--text-muted)">{{ saveMsg }}</span>
    </div>
  </div>
</template>

<style scoped>
.instance-list { display: flex; flex-direction: column; gap: .5rem; }
.instance-row { display: flex; align-items: center; gap: .75rem; padding: .5rem .75rem; background: var(--surface-2); border-radius: 6px; flex-wrap: wrap; }
.instance-id { font-weight: 600; }
.text-muted { color: var(--text-muted); font-size: .85rem; }
</style>
