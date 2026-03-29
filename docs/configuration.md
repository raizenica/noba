# NOBA Configuration Reference

All configuration lives in a single YAML file:

- **Bare-metal:** `~/.config/noba/config.yaml`
- **Docker:** `/app/config/config.yaml` (mounted from `./data/config/`)
- **Override via env:** `NOBA_CONFIG=/path/to/config.yaml`

Settings can be edited directly in the file or via the web UI (**Settings → Integrations**). The web UI writes changes back to `config.yaml` automatically.

---

## Top-Level Structure

```yaml
email: ""
backup: {}
cloud: {}
downloads: {}
disk: {}
logs: {}
services: {}
update: {}
notifications: {}
web: {}
```

---

## `email`

The default email address used for alerts from automation scripts.

```yaml
email: "admin@example.com"
```

---

## `backup`

Controls `backup-to-nas.sh`.

```yaml
backup:
  # List of directories to back up
  sources:
    - ~/Documents
    - ~/Pictures
    - ~/Projects

  # Destination — local path or NAS mount point
  dest: /mnt/nas/backups

  # How many days to keep incremental snapshots
  retention_days: 30

  # Maximum number of snapshots to keep regardless of age
  keep_count: 10

  # Log file location
  log_file: ~/.local/share/backup-to-nas.log

  # Extra rsync flags (appended to the default set)
  rsync_opts: "--exclude=*.tmp --exclude=.DS_Store"
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `sources` | list | `[]` | Paths to back up |
| `dest` | string | `""` | Backup destination directory |
| `retention_days` | int | `30` | Delete snapshots older than this |
| `keep_count` | int | `10` | Hard cap on snapshot count |
| `log_file` | string | `~/.local/share/backup-to-nas.log` | Log output path |
| `rsync_opts` | string | `""` | Extra flags passed to rsync |

---

## `cloud`

Controls `cloud-backup.sh` (rclone-based).

```yaml
cloud:
  # rclone remote name (as configured with `rclone config`)
  remote: "gdrive:"

  # Local directory to sync to the cloud
  source: /mnt/nas/backups

  # Bandwidth limit (e.g. "10M" for 10 MB/s, "" for unlimited)
  bwlimit: ""

  log_file: ~/.local/share/cloud-backup.log
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `remote` | string | `""` | rclone remote name (include trailing `:`) |
| `source` | string | `""` | Local directory to upload |
| `bwlimit` | string | `""` | rclone `--bwlimit` value |
| `log_file` | string | `~/.local/share/cloud-backup.log` | Log output path |

---

## `downloads`

Controls `organize-downloads.sh`.

```yaml
downloads:
  # Directory to organise
  dir: ~/Downloads

  # Action: "move" (default) or "copy"
  action: move

  log_file: ~/.local/share/download-organizer.log
```

---

## `disk`

Controls `disk-sentinel.sh`.

```yaml
disk:
  # Alert when usage exceeds this percentage (critical)
  threshold: 85

  # Warn (lower-severity alert) at this percentage
  warn_threshold: 75

  # Mount points to monitor (empty = auto-detect all real filesystems)
  targets:
    - /
    - /home
    - /mnt/nas

  # Cleanup journal logs when threshold exceeded
  cleanup: true

  # Max seconds to allow `du` to run before timing out
  du_timeout: 30

  log_file: ~/.local/share/disk-sentinel.log
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `threshold` | int | `85` | Critical disk usage percentage |
| `warn_threshold` | int | `""` | Warning-level percentage (optional) |
| `targets` | list | auto | Mount points to check |
| `cleanup` | bool | `true` | Run journal vacuum on alert |
| `du_timeout` | int | `30` | Timeout for `du` scans |

---

## `logs`

```yaml
logs:
  # Directory where all noba log files are written
  dir: ~/.local/share
```

---

## `services`

Controls `service-watch.sh` and `noba-daily-digest.sh`.

```yaml
services:
  # Services to watch and include in digest emails
  monitor:
    - nginx
    - postgresql
    - docker
    - sshd
```

---

## `update`

Controls `noba-update.sh`.

```yaml
update:
  # Git remote name to pull from
  remote: origin

  # Branch to pull
  branch: main

  system:
    # Also run system package updates (dnf/flatpak) after git pull
    enabled: false

    # Skip confirmation prompts for system updates
    auto_confirm: false
```

---

## `notifications`

Controls email and webhook alerts sent by automation scripts.

```yaml
notifications:
  # Webhook URL to POST alert payloads to (JSON: {level, title, message})
  webhook_url: ""

  email:
    # Recipient address
    to: "admin@example.com"

    # From address (must match your msmtp config)
    from: "noba@yourhost.local"

    # Subject prefix
    subject_prefix: "[NOBA]"

  telegram:
    bot_token: ""
    chat_id: ""

  discord:
    webhook_url: ""

  slack:
    webhook_url: ""
```

---

## `web`

Settings managed by and for the web dashboard. Most of these are written by the UI; you can also edit them directly.

### Integration URLs & keys

```yaml
web:
  piholeUrl: "http://192.168.1.53"
  piholeToken: "your-pihole-api-token"

  plexUrl: "http://192.168.1.10:32400"
  plexToken: "your-plex-token"

  kumaUrl: "http://192.168.1.20:3001"

  truenasUrl: "http://192.168.1.30"
  truenasKey: "your-truenas-api-key"

  radarrUrl: "http://192.168.1.40:7878"
  radarrKey: "your-radarr-api-key"

  sonarrUrl: "http://192.168.1.40:8989"
  sonarrKey: "your-sonarr-api-key"

  qbitUrl: "http://192.168.1.40:8080"
  qbitUser: "admin"
  qbitPass: "password"
```

### Network health targets

```yaml
web:
  wanTestIp: "8.8.8.8"          # Ping target for WAN health chip
  lanTestIp: "192.168.1.1"      # Ping target for LAN health chip
  radarIps: "192.168.1.1, google.com, my-nas.local"
  monitoredServices: "nginx, docker, sshd"
```

### Bookmarks

```yaml
web:
  bookmarksStr: "Router|http://192.168.1.1|fa-network-wired, Pi-hole|http://192.168.1.53|fa-shield-alt"
```

Format: `Name|URL|FontAwesomeIcon` (comma-separated entries).

### Custom actions

```yaml
web:
  customActions:
    - id: "reboot-dns"
      name: "Reboot DNS Stack"
      icon: "fa-sync-alt"
      command: "ssh admin@192.168.1.100 sudo systemctl restart pihole-FTL"

    - id: "clear-tmp"
      name: "Clear Temp Files"
      icon: "fa-broom"
      command: "find /tmp -name 'noba-*' -delete && echo Done"
```

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `id` | string | **Yes** | Unique identifier (no spaces) |
| `name` | string | **Yes** | Display label in UI |
| `icon` | string | No | Font Awesome 6 class (e.g. `fa-bolt`) |
| `command` | string | **Yes** | Shell command to execute |

### Webhook automations

```yaml
web:
  automations:
    - id: "n8n-sync"
      name: "Trigger n8n Sync"
      url: "http://n8n.local:5678/webhook/sync"
      method: "POST"
```

### Alert rules

```yaml
web:
  alertRules:
    - id: "high-cpu"
      name: "High CPU"
      condition: "cpu_percent > 90"
      channel: "telegram"
      message: "CPU usage critical!"

    - id: "low-disk"
      name: "Low Disk Space"
      condition: "disk_percent > 85"
      channel: "email"
      message: "Disk is nearly full."
```

**Supported operators:** `>`, `<`, `>=`, `<=`, `==`, `!=`

### Proxmox

```yaml
web:
  proxmoxUrl: ""
  proxmoxUser: ""
  proxmoxTokenName: ""        # full token ID, e.g. "root@pam!noba-api"
  proxmoxTokenValue: ""
  proxmoxVerifySsl: true      # set false for self-signed certs
```

### LLM / AI

```yaml
web:
  llmEnabled: false
  llmProvider: ""             # ollama, openai, anthropic, custom
  llmModel: ""                # auto-selected per provider if empty
  llmBaseUrl: ""              # e.g. http://localhost:11434 for Ollama
  llmApiKey: ""               # required for openai/anthropic
  llmMaxTokens: 4096
  llmTemperature: 0.3
```

### Agent keys

```yaml
web:
  agentKeys: ""               # comma-separated API keys for remote agent auth
```

### Integration reference

All integrations are configured under the `web:` key. The table below groups every supported setting by category. Values are strings unless noted. Credentials are encrypted at rest (see [Credential Encryption](#credential-encryption)).

#### DNS

| Setting | Description |
|---------|-------------|
| `piholeUrl` / `piholeToken` / `piholePassword` | Pi-hole (v5 token or v6 password) |
| `adguardUrl` / `adguardUser` / `adguardPass` | AdGuard Home |
| `dnsService` | Active DNS backend: `pihole` or `adguard` |

#### Media

| Setting | Description |
|---------|-------------|
| `plexUrl` / `plexToken` | Plex Media Server |
| `jellyfinUrl` / `jellyfinKey` | Jellyfin |
| `tautulliUrl` / `tautulliKey` | Tautulli (Plex analytics) |
| `overseerrUrl` / `overseerrKey` | Overseerr / Jellyseerr |
| `radarrUrl` / `radarrKey` | Radarr |
| `sonarrUrl` / `sonarrKey` | Sonarr |
| `lidarrUrl` / `lidarrKey` | Lidarr |
| `readarrUrl` / `readarrKey` | Readarr |
| `bazarrUrl` / `bazarrKey` | Bazarr |
| `prowlarrUrl` / `prowlarrKey` | Prowlarr |
| `qbitUrl` / `qbitUser` / `qbitPass` | qBittorrent |

#### Network & Monitoring

| Setting | Description |
|---------|-------------|
| `kumaUrl` | Uptime Kuma |
| `speedtestUrl` | Speedtest Tracker |
| `unifiUrl` / `unifiUser` / `unifiPass` / `unifiSite` / `unifiVerifySsl` | UniFi Network |
| `wanTestIp` / `lanTestIp` | Ping health-check targets |
| `radarIps` | Comma-separated radar ping targets |
| `certHosts` | TLS certificate expiry monitoring hosts |
| `domainList` | Domain WHOIS expiry monitoring |
| `devicePresenceIps` | Device presence detection IPs |

#### Storage & NAS

| Setting | Description |
|---------|-------------|
| `truenasUrl` / `truenasKey` | TrueNAS |
| `omvUrl` / `omvUser` / `omvPass` | OpenMediaVault |
| `nextcloudUrl` / `nextcloudUser` / `nextcloudPass` | Nextcloud |
| `scrutinyUrl` | Scrutiny (disk health) |

#### Virtualisation & Infrastructure

| Setting | Description |
|---------|-------------|
| `proxmoxUrl` / `proxmoxUser` / `proxmoxTokenName` / `proxmoxTokenValue` / `proxmoxVerifySsl` | Proxmox VE |
| `xcpngUrl` / `xcpngUser` / `xcpngPass` | XCP-ng |
| `k8sUrl` / `k8sToken` / `k8sVerifySsl` | Kubernetes |
| `traefikUrl` | Traefik |
| `npmUrl` / `npmToken` | Nginx Proxy Manager |

#### IoT & Home Automation

| Setting | Description |
|---------|-------------|
| `hassUrl` / `hassToken` | Home Assistant |
| `hassSensors` | HA sensor entity IDs to poll |
| `hassEventTriggers` | HA event-based automation triggers (list) |
| `homebridgeUrl` / `homebridgeUser` / `homebridgePass` | Homebridge |
| `z2mUrl` | Zigbee2MQTT |
| `esphomeUrl` | ESPHome |
| `frigateUrl` | Frigate NVR |
| `cameraFeeds` | Camera feed definitions (list) |

#### Surveillance

| Setting | Description |
|---------|-------------|
| `unifiProtectUrl` / `unifiProtectUser` / `unifiProtectPass` / `unifiProtectVerifySsl` | UniFi Protect |
| `pikvmUrl` / `pikvmUser` / `pikvmPass` | PiKVM |

#### Auth & Security

| Setting | Description |
|---------|-------------|
| `authentikUrl` / `authentikToken` | Authentik |
| `oidcProviderUrl` / `oidcClientId` / `oidcClientSecret` | Generic OIDC SSO |
| `ldapUrl` / `ldapBaseDn` / `ldapBindDn` / `ldapBindPassword` | LDAP |
| `ipWhitelist` | Comma-separated allowed IPs/CIDRs |
| `require2fa` | Require two-factor authentication (bool) |
| `auditRetentionDays` | Audit log retention in days (default 90) |

#### DevOps & Source Control

| Setting | Description |
|---------|-------------|
| `giteaUrl` / `giteaToken` | Gitea |
| `gitlabUrl` / `gitlabToken` | GitLab |
| `githubToken` | GitHub (personal access token) |
| `paperlessUrl` / `paperlessToken` | Paperless-ngx |
| `vaultwardenUrl` / `vaultwardenToken` | Vaultwarden |
| `composeProjects` | Docker Compose project paths (list) |

#### Observability

| Setting | Description |
|---------|-------------|
| `influxdbUrl` / `influxdbToken` / `influxdbOrg` | InfluxDB |
| `graylogUrl` / `graylogToken` | Graylog |
| `graylogUser` | Graylog username (alternative to API token) |
| `graylogPassword` | Graylog password (used with graylogUser for Basic auth) |
| `cloudflareToken` / `cloudflareZoneId` | Cloudflare DNS/analytics |

#### Weather & Energy

| Setting | Description |
|---------|-------------|
| `weatherApiKey` / `weatherCity` | OpenWeatherMap |
| `energySensors` | Energy monitoring sensor IDs |

#### Advanced / Misc

| Setting | Description |
|---------|-------------|
| `monitoredServices` | Comma-separated systemd services to watch |
| `bookmarksStr` | Dashboard bookmarks (`Name\|URL\|Icon`, comma-separated) |
| `customMetricScripts` | Custom metric collection scripts |
| `bmcMap` | IPMI/BMC endpoint mapping |
| `wolDevices` | Wake-on-LAN device definitions (list) |
| `gameServers` | Game server monitoring targets (list) |
| `rssTriggers` | RSS-based automation triggers (list) |
| `maintenanceWindows` | Scheduled maintenance windows (list) |
| `fsTriggers` | Filesystem event triggers (list) |
| `siteMap` / `siteNames` | Multi-site topology and display names |
| `serviceDependencies` | Service dependency graph |
| `statusPageServices` | Public status page service list |
| `runbooks` | Runbook definitions (list) |

**Available metrics for conditions:**

| Metric | Description |
|--------|-------------|
| `cpu_percent` | Overall CPU usage % |
| `mem_percent` | RAM usage % |
| `cpu_temp` | CPU temperature (°C) |
| `gpu_temp` | GPU temperature (°C) |
| `disk_percent` | Root filesystem usage % |
| `ping_ms` | Ping latency to WAN target (ms) |
| `net_rx_bytes` | Network receive rate (bytes/s) |
| `net_tx_bytes` | Network transmit rate (bytes/s) |

---

## Environment Variables

These override compiled-in defaults and are useful for Docker deployments.

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | HTTP/HTTPS listen port |
| `HOST` | `0.0.0.0` | Bind address |
| `SSL_CERT` | `""` | Path to TLS certificate (PEM format) |
| `SSL_KEY` | `""` | Path to TLS private key (PEM format) |
| `NOBA_CONFIG` | `~/.config/noba/config.yaml` | Path to config.yaml |
| `NOBA_SCRIPT_DIR` | `~/.local/libexec/noba` | Directory containing automation scripts |
| `NOBA_REPO_DIR` | auto-detected | Git repo path (for self-update feature) |
| `NOBA_REDIS_URL` | `""` | Optional Redis URL for caching |
| `NOBA_CORS_ORIGINS` | `""` | Comma-separated CORS origins |
| `NOBA_TERMINAL_ENABLED` | `true` | Enable/disable web terminal |
| `NOBA_DEV` | `""` | Set to `1` to enable Swagger/ReDoc at `/api/docs` |
| `NOBA_TRUST_PROXY` | `""` | Trust `X-Forwarded-For` headers (`1`, `true`, or `yes`) |
| `NOBA_HISTORY_DAYS` | `30` | Metrics history retention (days) |
| `NOBA_AUDIT_DAYS` | `90` | Audit log retention (days) |
| `NOBA_WORKER_THREADS` | `24` | Thread pool size |
| `NOBA_PW_MIN_LEN` | `8` | Minimum password length |
| `NOBA_MAX_JOBS` | `3` | Max concurrent script jobs |
| `NOBA_JOB_TIMEOUT` | `300` | Job timeout in seconds |
| `NOBA_JOB_RETENTION_DAYS` | `30` | Completed job record retention (days) |
| `PID_FILE` | `/tmp/noba-web-server.pid` | PID file location |
| `TZ` | System default | Timezone for log timestamps |

### TLS / HTTPS example

```yaml
# docker-compose.yml
services:
  noba-dashboard:
    environment:
      - SSL_CERT=/certs/fullchain.pem
      - SSL_KEY=/certs/privkey.pem
    volumes:
      - /etc/letsencrypt/live/yourdomain.com:/certs:ro
```

---

## Credential Encryption

NOBA encrypts integration secrets (API keys, passwords, tokens) in `config.yaml` using Fernet symmetric encryption.

- **Master key** is auto-generated on first launch at `~/.config/noba/.master.key` (file mode `0600`).
- Encrypted values are stored with an `ENC:` prefix — encryption on save, decryption on read is fully transparent.
- Requires the `cryptography` Python package. If absent, secrets are stored in plain text and a warning is logged.
- Back up `.master.key` alongside `config.yaml` — without it, encrypted values cannot be recovered.

---

## File Locations (Bare-Metal)

| File | Purpose |
|------|---------|
| `~/.config/noba/config.yaml` | Main configuration |
| `~/.config/noba/.master.key` | Fernet encryption master key (mode 0600) |
| `~/.config/noba-web/users.conf` | User accounts (PBKDF2 hashed) |
| `~/.config/noba-web/auth.conf` | Legacy auth file (migrated automatically) |
| `~/.local/share/noba-web-server.log` | Server access/error log |
| `~/.local/share/noba-history.db` | SQLite metrics history |
| `~/.local/share/noba-action.log` | Script run output |
| `~/.local/share/backup-to-nas.log` | Backup script log |
| `~/.local/share/cloud-backup.log` | Cloud sync log |
| `~/.local/share/disk-sentinel.log` | Disk monitor log |
| `~/.local/share/noba-install.manifest` | Install manifest (for uninstall) |
