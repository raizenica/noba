<script setup>
import { ref, reactive, watch } from 'vue'
import { useSettingsStore } from '../../../stores/settings'

const props = defineProps({
  intCat: {
    type: String,
    required: true,
  },
})

const settingsStore = useSettingsStore()

// Social provider state
const expandedProvider = ref('')
const socialProviders = reactive({
  google: { clientId: '', clientSecret: '' },
  facebook: { clientId: '', clientSecret: '' },
  github: { clientId: '', clientSecret: '' },
  microsoft: { clientId: '', clientSecret: '' },
})

// Sync social providers with settings store
watch(() => settingsStore.data.socialProviders, (sp) => {
  if (sp) {
    for (const key of ['google', 'facebook', 'github', 'microsoft']) {
      if (sp[key]) {
        socialProviders[key].clientId = sp[key].clientId || ''
        socialProviders[key].clientSecret = sp[key].clientSecret || ''
      }
    }
  }
}, { immediate: true })

// Write back to settings store on change
watch(socialProviders, (val) => {
  if (!settingsStore.data.socialProviders) settingsStore.data.socialProviders = {}
  for (const key of ['google', 'facebook', 'github', 'microsoft']) {
    settingsStore.data.socialProviders[key] = { ...val[key] }
  }
}, { deep: true })

function callbackUrl(provider) {
  const base = window.location.origin
  return `${base}/api/auth/social/${provider}/callback`
}

function toggleReveal(evt) {
  const input = evt.currentTarget.previousElementSibling
  if (input) input.type = input.type === 'password' ? 'text' : 'password'
}
</script>

<template>
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
        <input class="field-input" type="url" v-model="settingsStore.data.kumaUrl" placeholder="http://nas.example.com:3001">
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
      <div class="field-2" style="margin-top:.5rem">
        <div>
          <label class="field-label">Username (if no token)</label>
          <input class="field-input" v-model="settingsStore.data.graylogUser" placeholder="admin" autocomplete="off">
        </div>
        <div>
          <label class="field-label">Password</label>
          <div class="reveal-wrap">
            <input class="field-input" type="password" v-model="settingsStore.data.graylogPassword" autocomplete="off">
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
          <input class="field-input" type="url" v-model="settingsStore.data.plexUrl" placeholder="http://nas.example.com:32400">
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
      <div class="help-text" style="margin-bottom:.5rem;font-style:italic">
        <i class="fas fa-info-circle"></i> Pi-hole v5 uses API token. Pi-hole v6 uses App Password or auto-auth password.
      </div>
      <div class="field-2">
        <div>
          <label class="field-label">URL / IP</label>
          <input class="field-input" type="url" v-model="settingsStore.data.piholeUrl" placeholder="http://192.168.1.100">
        </div>
        <div>
          <label class="field-label">
            <span style="display:flex;align-items:center;gap:.3rem">
              API Token (v5)
              <span class="badge ba" style="font-size:.65rem">Pi-hole 5.x</span>
            </span>
          </label>
          <div class="reveal-wrap">
            <input class="field-input" type="password" v-model="settingsStore.data.piholeToken" autocomplete="off" placeholder="Pi-hole v5 API token">
            <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
          </div>
        </div>
        <div>
          <label class="field-label">
            <span style="display:flex;align-items:center;gap:.3rem">
              App Password (v6)
              <span class="badge bs" style="font-size:.65rem">Pi-hole 6.x</span>
            </span>
          </label>
          <div class="reveal-wrap">
            <input class="field-input" type="password" v-model="settingsStore.data.piholePassword" autocomplete="off" placeholder="Pi-hole v6 App Password">
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

    <!-- Social Login Providers -->
    <div class="s-section">
      <span class="s-label">Social Login</span>
      <p style="color:var(--text-muted);font-size:.8rem;margin:0 0 1rem">
        Let users sign in with their existing accounts. Each provider requires a free app registration — click the setup guide for step-by-step instructions.
      </p>

      <!-- Google -->
      <div class="social-provider-card">
        <div class="sp-header" role="button" tabindex="0" @click="expandedProvider = expandedProvider === 'google' ? '' : 'google'" @keydown.enter="expandedProvider = expandedProvider === 'google' ? '' : 'google'" @keydown.space.prevent="expandedProvider = expandedProvider === 'google' ? '' : 'google'">
          <i class="fab fa-google" style="color:#4285f4;font-size:1.2rem"></i>
          <span class="sp-name">Google</span>
          <span v-if="settingsStore.data.socialProviders?.google?.clientId" class="badge bs">Configured</span>
          <span v-else class="badge bw">Not configured</span>
          <i class="fas fa-chevron-down sp-chevron" :class="{rotated: expandedProvider === 'google'}"></i>
        </div>
        <div v-if="expandedProvider === 'google'" class="sp-body">
          <details class="setup-guide">
            <summary>Setup Guide (2 minutes)</summary>
            <ol>
              <li>Go to <a href="https://console.cloud.google.com/apis/credentials" target="_blank">Google Cloud Console → Credentials</a></li>
              <li>Click <strong>"Create Credentials"</strong> → <strong>"OAuth client ID"</strong></li>
              <li>If prompted, configure the OAuth consent screen first (External, add your email)</li>
              <li>Application type: <strong>Web application</strong></li>
              <li>Name: <code>NOBA</code></li>
              <li>Authorized redirect URI: <code>{{ callbackUrl('google') }}</code></li>
              <li>Click <strong>Create</strong> → copy the Client ID and Client Secret below</li>
            </ol>
          </details>
          <div class="field-2" style="margin-top:.75rem">
            <div>
              <label class="field-label">Client ID</label>
              <input class="field-input" type="text" v-model="socialProviders.google.clientId"
                placeholder="xxx.apps.googleusercontent.com">
            </div>
            <div>
              <label class="field-label">Client Secret</label>
              <div class="reveal-wrap">
                <input class="field-input" type="password" v-model="socialProviders.google.clientSecret" autocomplete="off">
                <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
              </div>
            </div>
          </div>
          <div class="sp-callback">
            <label class="field-label">Callback URL (copy this into Google Console)</label>
            <code class="callback-url">{{ callbackUrl('google') }}</code>
          </div>
        </div>
      </div>

      <!-- Facebook -->
      <div class="social-provider-card">
        <div class="sp-header" role="button" tabindex="0" @click="expandedProvider = expandedProvider === 'facebook' ? '' : 'facebook'" @keydown.enter="expandedProvider = expandedProvider === 'facebook' ? '' : 'facebook'" @keydown.space.prevent="expandedProvider = expandedProvider === 'facebook' ? '' : 'facebook'">
          <i class="fab fa-facebook" style="color:#1877f2;font-size:1.2rem"></i>
          <span class="sp-name">Facebook</span>
          <span v-if="settingsStore.data.socialProviders?.facebook?.clientId" class="badge bs">Configured</span>
          <span v-else class="badge bw">Not configured</span>
          <i class="fas fa-chevron-down sp-chevron" :class="{rotated: expandedProvider === 'facebook'}"></i>
        </div>
        <div v-if="expandedProvider === 'facebook'" class="sp-body">
          <details class="setup-guide">
            <summary>Setup Guide (5 minutes)</summary>
            <ol>
              <li>Go to <a href="https://developers.facebook.com/apps/" target="_blank">Facebook Developers</a> and click <strong>"Create App"</strong></li>
              <li>Choose <strong>"Consumer"</strong> or <strong>"None"</strong> as the app type</li>
              <li>Add the <strong>"Facebook Login"</strong> product</li>
              <li>Under Facebook Login → Settings, add Valid OAuth Redirect URI: <code>{{ callbackUrl('facebook') }}</code></li>
              <li>Go to Settings → Basic to find your <strong>App ID</strong> and <strong>App Secret</strong></li>
              <li>Copy them below</li>
            </ol>
            <p style="color:var(--warning);font-size:.75rem;margin-top:.5rem">
              <i class="fas fa-info-circle"></i> Facebook requires HTTPS for production. For homelab use, keep the app in "Development" mode and add yourself as a test user under Roles → Test Users.
            </p>
          </details>
          <div class="field-2" style="margin-top:.75rem">
            <div>
              <label class="field-label">App ID</label>
              <input class="field-input" type="text" v-model="socialProviders.facebook.clientId" placeholder="123456789012345">
            </div>
            <div>
              <label class="field-label">App Secret</label>
              <div class="reveal-wrap">
                <input class="field-input" type="password" v-model="socialProviders.facebook.clientSecret" autocomplete="off">
                <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
              </div>
            </div>
          </div>
          <div class="sp-callback">
            <label class="field-label">Callback URL</label>
            <code class="callback-url">{{ callbackUrl('facebook') }}</code>
          </div>
        </div>
      </div>

      <!-- GitHub -->
      <div class="social-provider-card">
        <div class="sp-header" role="button" tabindex="0" @click="expandedProvider = expandedProvider === 'github' ? '' : 'github'" @keydown.enter="expandedProvider = expandedProvider === 'github' ? '' : 'github'" @keydown.space.prevent="expandedProvider = expandedProvider === 'github' ? '' : 'github'">
          <i class="fab fa-github" style="color:#f0f6fc;font-size:1.2rem"></i>
          <span class="sp-name">GitHub</span>
          <span v-if="settingsStore.data.socialProviders?.github?.clientId" class="badge bs">Configured</span>
          <span v-else class="badge bw">Not configured</span>
          <i class="fas fa-chevron-down sp-chevron" :class="{rotated: expandedProvider === 'github'}"></i>
        </div>
        <div v-if="expandedProvider === 'github'" class="sp-body">
          <details class="setup-guide">
            <summary>Setup Guide (1 minute — easiest option)</summary>
            <ol>
              <li>Go to <a href="https://github.com/settings/developers" target="_blank">GitHub → Settings → Developer Settings → OAuth Apps</a></li>
              <li>Click <strong>"New OAuth App"</strong></li>
              <li>Application name: <code>NOBA</code></li>
              <li>Homepage URL: your NOBA URL (e.g., <code>http://noba.local:8080</code>)</li>
              <li>Authorization callback URL: <code>{{ callbackUrl('github') }}</code></li>
              <li>Click <strong>Register</strong>, then <strong>"Generate a new client secret"</strong></li>
              <li>Copy Client ID and Client Secret below</li>
            </ol>
            <p style="color:var(--success);font-size:.75rem;margin-top:.5rem">
              <i class="fas fa-check-circle"></i> GitHub works with HTTP and localhost — no review needed. Best option for quick setup.
            </p>
          </details>
          <div class="field-2" style="margin-top:.75rem">
            <div>
              <label class="field-label">Client ID</label>
              <input class="field-input" type="text" v-model="socialProviders.github.clientId" placeholder="Iv1.abc123def456">
            </div>
            <div>
              <label class="field-label">Client Secret</label>
              <div class="reveal-wrap">
                <input class="field-input" type="password" v-model="socialProviders.github.clientSecret" autocomplete="off">
                <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
              </div>
            </div>
          </div>
          <div class="sp-callback">
            <label class="field-label">Callback URL</label>
            <code class="callback-url">{{ callbackUrl('github') }}</code>
          </div>
        </div>
      </div>

      <!-- Microsoft -->
      <div class="social-provider-card">
        <div class="sp-header" role="button" tabindex="0" @click="expandedProvider = expandedProvider === 'microsoft' ? '' : 'microsoft'" @keydown.enter="expandedProvider = expandedProvider === 'microsoft' ? '' : 'microsoft'" @keydown.space.prevent="expandedProvider = expandedProvider === 'microsoft' ? '' : 'microsoft'">
          <i class="fab fa-microsoft" style="color:#00a4ef;font-size:1.2rem"></i>
          <span class="sp-name">Microsoft</span>
          <span v-if="settingsStore.data.socialProviders?.microsoft?.clientId" class="badge bs">Configured</span>
          <span v-else class="badge bw">Not configured</span>
          <i class="fas fa-chevron-down sp-chevron" :class="{rotated: expandedProvider === 'microsoft'}"></i>
        </div>
        <div v-if="expandedProvider === 'microsoft'" class="sp-body">
          <details class="setup-guide">
            <summary>Setup Guide (3 minutes)</summary>
            <ol>
              <li>Go to <a href="https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade" target="_blank">Azure Portal → App Registrations</a></li>
              <li>Click <strong>"New registration"</strong></li>
              <li>Name: <code>NOBA</code></li>
              <li>Supported account types: <strong>"Accounts in any organizational directory and personal Microsoft accounts"</strong></li>
              <li>Redirect URI: Web → <code>{{ callbackUrl('microsoft') }}</code></li>
              <li>Click <strong>Register</strong></li>
              <li>Copy the <strong>Application (client) ID</strong> from the overview page</li>
              <li>Go to <strong>Certificates &amp; secrets</strong> → <strong>"New client secret"</strong> → copy the <strong>Value</strong> (not the ID)</li>
            </ol>
          </details>
          <div class="field-2" style="margin-top:.75rem">
            <div>
              <label class="field-label">Application (Client) ID</label>
              <input class="field-input" type="text" v-model="socialProviders.microsoft.clientId"
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
            </div>
            <div>
              <label class="field-label">Client Secret Value</label>
              <div class="reveal-wrap">
                <input class="field-input" type="password" v-model="socialProviders.microsoft.clientSecret" autocomplete="off">
                <button type="button" class="reveal-btn" @click="toggleReveal"><i class="fas fa-eye"></i></button>
              </div>
            </div>
          </div>
          <div class="sp-callback">
            <label class="field-label">Callback URL</label>
            <code class="callback-url">{{ callbackUrl('microsoft') }}</code>
          </div>
        </div>
      </div>
    </div>

    <!-- Generic SSO / OIDC (advanced) -->
    <div class="s-section">
      <span class="s-label">Custom SSO / OIDC (Advanced)</span>
      <p style="color:var(--text-muted);font-size:.8rem;margin:0 0 .75rem">
        For Authentik, Keycloak, Authelia, or any OpenID Connect provider not listed above.
      </p>
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
          <input class="field-input" type="number" v-model.number="settingsStore.data.llmMaxTokens" min="256" max="32768" step="256" placeholder="4096">
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
</template>

<style scoped>
/* Social provider cards */
.social-provider-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: .5rem;
  overflow: hidden;
}
.sp-header {
  display: flex;
  align-items: center;
  gap: .75rem;
  padding: .75rem 1rem;
  cursor: pointer;
  transition: background .15s;
}
.sp-header:hover { background: var(--surface-2); }
.sp-name { font-weight: 600; flex: 1; }
.sp-chevron {
  font-size: .7rem;
  color: var(--text-muted);
  transition: transform .2s;
}
.sp-chevron.rotated { transform: rotate(180deg); }
.sp-body {
  padding: .75rem 1rem 1rem;
  background: var(--surface-2);
  border-top: 1px solid var(--border);
}
.setup-guide {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: .5rem .75rem;
}
.setup-guide summary {
  cursor: pointer;
  font-size: .85rem;
  color: var(--accent);
  font-weight: 600;
}
.setup-guide ol {
  margin: .5rem 0 0;
  padding-left: 1.2rem;
  font-size: .8rem;
  line-height: 1.7;
  color: var(--text);
}
.setup-guide ol code {
  background: var(--surface-2);
  padding: .1rem .3rem;
  border-radius: 3px;
  font-family: var(--font-data);
  font-size: .75rem;
  user-select: all;
}
.setup-guide a {
  color: var(--accent);
  text-decoration: underline;
}
.sp-callback {
  margin-top: .75rem;
}
.callback-url {
  display: block;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: .4rem .6rem;
  font-family: var(--font-data);
  font-size: .75rem;
  color: var(--accent);
  user-select: all;
  word-break: break-all;
}
</style>
