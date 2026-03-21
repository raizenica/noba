# Integrations

Configure integrations in **Settings → Integrations**. All credentials are stored server-side in `config.yaml` and never sent to the browser.

## Media & Downloads

### Plex

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.10:32400` |
| Token | Found in Plex Web → Account → XML API (in the URL) |

```yaml
web:
  plexUrl: "http://192.168.1.10:32400"
  plexToken: "xxxxxxxxxxxxxxxxxxxx"
```

### Radarr

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.40:7878` |
| API Key | Radarr → Settings → General → API Key |

### Sonarr

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.40:8989` |
| API Key | Sonarr → Settings → General → API Key |

### Prowlarr

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.40:9696` |
| API Key | Prowlarr → Settings → General → API Key |

### Jellyfin

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.10:8096` |
| API Key | Jellyfin → Admin Dashboard → API Keys → New Key |

### qBittorrent

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.40:8080` |
| Username | qBittorrent Web UI username |
| Password | qBittorrent Web UI password |

The Web UI must be enabled: qBittorrent → Tools → Options → Web UI.

---

## Networking

### Pi-hole

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.53` |
| API Token | Pi-hole admin panel → Settings → API |

Works with Pi-hole v5 (legacy `?summaryRaw` API) and v6 (new REST API). NOBA detects the version automatically.

### UniFi

| Field | Description |
|-------|-------------|
| URL | `https://192.168.1.1` (controller URL) |
| Username | Local admin username |
| Password | Local admin password |

NOBA uses a dedicated httpx client with cookie persistence for UniFi authentication.

### AdGuard Home

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.53:3000` |
| Username | AdGuard admin username |
| Password | AdGuard admin password |

---

## Storage & Infrastructure

### TrueNAS SCALE

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.30` |
| API Key | TrueNAS → Settings → API Keys → Add |

Surfaces pool health, apps, alerts, and VMs.

### Proxmox VE

| Field | Description |
|-------|-------------|
| URL | `https://192.168.1.200:8006` |
| Token ID | `user@pam!token-name` |
| Token Secret | Secret from PVE → Datacenter → API Tokens |

### Synology DSM

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.25:5000` |
| Username | DSM admin username |
| Password | DSM admin password |

---

## Monitoring

### Uptime Kuma

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.20:3001` |

Enable Prometheus metrics in Kuma: Settings → Security → "Enable Prometheus metrics endpoint". No API key required.

### Grafana

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.20:3000` |
| API Key | Grafana → Administration → Service accounts → Add token |

### InfluxDB

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.20:8086` |
| Token | InfluxDB → API Tokens → Generate |
| Org | Organisation name |
| Bucket | Target bucket for NOBA metrics |

---

## Smart Home & IoT

### Home Assistant

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.100:8123` |
| Long-Lived Token | HA → Profile → Long-Lived Access Tokens |

### ESPHome

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.100:6052` |
| API Key | (optional) ESPHome dashboard API key |

---

## Containers & Orchestration

### Kubernetes

| Field | Description |
|-------|-------------|
| Kubeconfig | Upload `~/.kube/config` or paste contents |

Or use in-cluster credentials if NOBA runs inside Kubernetes.

### Portainer

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.20:9000` |
| API Key | Portainer → My account → Access tokens |

---

## Version Control & CI/CD

### Gitea

| Field | Description |
|-------|-------------|
| URL | `http://192.168.1.20:3000` |
| Token | Gitea → Settings → Applications → Generate token |

### Forgejo

Same as Gitea — the API is compatible.

### GitHub Actions / GitLab CI

Connect via webhook: configure your CI pipeline to POST run status to NOBA's automation webhook endpoint.

---

## Network Configuration

### Radar Targets (Ping Monitor)

Enter a comma-separated list of hosts in **Settings → Integrations → Radar IPs**:

```
192.168.1.1, 8.8.8.8, google.com, my-nas.local
```

### Monitored Services

Enter a comma-separated list of systemd service names:

```
nginx, docker, postgresql, sshd
```

### Bookmarks

Format: `Name|URL|FontAwesomeIcon` (comma-separated):

```
Router|http://192.168.1.1|fa-network-wired, Pi-hole|http://192.168.1.53|fa-shield-alt
```
