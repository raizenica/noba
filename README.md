# NOBA Command Center

A full-featured operations center for homelab and multi-site infrastructure management. Real-time monitoring, remote agent management, predictive intelligence, and 40+ service integrations — all from a single dashboard.

**Stack:** FastAPI · Alpine.js · Chart.js · SQLite WAL · No build step

## Features

### Core Monitoring
- **System Metrics** — CPU, memory, disk, network, temperatures, ZFS pools, containers (Docker/Podman)
- **Real-time SSE** — Server-Sent Events push live metrics to the browser every 5 seconds
- **Metrics History** — Time-series charts with zoom/pan, multi-metric correlation overlay
- **Sparkline Charts** — Inline SVG trend charts in dashboard cards
- **Health Bar** — Color-coded status pips for instant infrastructure overview
- **Anomaly Detection** — Automatic flagging of unusual resource patterns

### Remote Agents (v2.0)
- **Zero-dependency agent** — Standalone Python script, works on any Linux (reads /proc directly), optional psutil for cross-platform
- **32 command types** — System, services, network, files, users, containers, packages, and agent management
- **WebSocket real-time** — Instant command delivery via RFC 6455 client, with HTTP polling fallback
- **Streaming output** — Long-running commands stream output line-by-line via WebSocket
- **File transfer** — Push/pull files up to 50MB with chunked upload and SHA256 verification
- **Risk-tiered auth** — Low (viewer), medium (operator), high (admin-only) command classification
- **Agent metric persistence** — CPU/RAM/disk history stored in SQLite, queryable per-agent
- **One-click deployment** — Deploy from the dashboard via SSH, or copy-paste a one-liner (Linux/Windows)
- **Self-update** — Agents pull updates from the NOBA server and restart

### Alerting & Incidents
- **Composite alert rules** — AND/OR conditions with escalation policies
- **Self-healing actions** — Alerts can trigger agent commands (restart service, run script, webhook)
- **Anomaly detection** — Moving-window Z-score detection against historical baselines
- **Incident timeline** — Auto-generated from fired alerts, with resolve actions
- **Notification channels** — Pushover, Gotify, Slack, email, voice alerts, browser push (PWA)
- **Maintenance windows** — Suppress alerts during planned downtime
- **SLA Dashboard** — Uptime percentages per agent/service (7d/30d/90d)

### 40+ Integrations

| Category | Services |
|----------|----------|
| **Media** | Plex, Jellyfin, Tautulli, Overseerr, Radarr, Sonarr, Lidarr, Readarr, Bazarr, Prowlarr, qBittorrent |
| **Infrastructure** | TrueNAS, Proxmox VE, Scrutiny (SMART), Frigate (NVR), InfluxDB, Uptime Kuma |
| **Network** | Pi-hole v5/v6, AdGuard Home, Traefik, Nginx Proxy Manager, Cloudflare, UniFi |
| **IoT & Home** | Home Assistant, Homebridge, Zigbee2MQTT, ESPHome, UniFi Protect, PiKVM |
| **DevOps** | Kubernetes, Gitea, GitLab, GitHub, Paperless-ngx, Vaultwarden |
| **Auth** | SSO/OIDC, LDAP/AD, TOTP 2FA, API keys, IP whitelisting |
| **Monitoring** | Tailscale mesh, certificate expiry, domain expiry, weather, energy (Shelly) |

### Operations Center
- **Multi-site awareness** — Site A/B toggle filters the entire dashboard
- **Endpoint monitoring** — Scheduled HTTP health checks with TLS certificate expiry tracking
- **Service dependency topology** — SVG force-directed graph with transitive impact analysis
- **Configuration drift detection** — Baseline file checksums across agents, alert on changes
- **Real-time log streaming** — Live tail from agents via WebSocket, color-coded by priority
- **Saved custom dashboards** — Build and save metric views, share between users
- **Tailscale network map** — Visual node grid with online/offline, direct/relay, subnet routes
- **Predictive disk intelligence** — SMART attribute trend analysis with failure prediction
- **Graylog integration** — Search centralized logs from the dashboard
- **InfluxDB query panel** — Flux query editor with Chart.js visualization
- **Config changelog** — Tracks every settings change with old→new diffs
- **Metrics correlation** — Overlay multiple metrics on a single timeline
- **Public status page** — Component groups, manual incidents, 90-day uptime history, no-auth

### AI Ops Assistant
- **Multi-provider LLM** — Anthropic (Claude), OpenAI, Ollama (local), or any OpenAI-compatible endpoint
- **Infrastructure-aware chat** — System prompt includes live agent status, alerts, metrics
- **Alert analysis** — "Explain this alert" with suggested remediation steps
- **Log analysis** — Send log excerpts for AI-powered issue identification
- **Incident summarization** — Auto-generate post-mortem reports
- **Action buttons** — AI suggests agent commands rendered as one-click buttons
- **Completely optional** — Everything works without LLM configured

### Automation Engine
- **9 automation types** — Script, webhook, service, workflow, condition, delay, notify, HTTP, **agent_command**
- **Workflow engine** — Sequential/parallel steps with retry and exponential backoff
- **Agent command actions** — Workflows and alerts can trigger commands on remote agents
- **Triggers** — Cron schedule, file system changes, RSS feeds, webhooks (HMAC validated), HA events
- **Approval gates** — Require manual approval before execution

### Security
- **Authentication** — PBKDF2 hashing, TOTP 2FA, OIDC, LDAP, API keys
- **Role-based access** — Admin, operator, viewer with fine-grained permissions
- **Input validation** — Regex + length limits on all user inputs, no command injection
- **Audit logging** — Every action tracked with username, IP, timestamp
- **Rate limiting** — Per-IP and per-user with lockout

### UI/UX
- **Sidebar navigation** — Persistent left sidebar with icon-only collapse, hash-based page routing
- **Global search** — `Ctrl+K` command palette searches pages, commands, agents, settings
- **6 themes** — Default, Nord, Dracula, Tokyo, Catppuccin, Gruvbox
- **Per-user layouts** — Card visibility and order synced to server per user
- **Quick glance mode** — Press `g` to collapse all cards to headers
- **Context menus** — Right-click cards for quick actions
- **Mobile responsive** — Bottom nav + slide-over sidebar on mobile
- **Keyboard shortcuts** — Customizable hotkeys
- **Notification center** — Bell icon with unread count + PWA push notifications
- **Embedded terminal** — WebSocket PTY via xterm.js (admin-only)
- **API documentation** — Swagger UI at `/api/docs`, ReDoc at `/api/redoc`

## Quick Start

### Prerequisites
- Python 3.10+
- Linux (Fedora, Ubuntu, Debian, Raspberry Pi OS, TrueNAS SCALE)

### Install

```bash
git clone https://github.com/raizenica/noba.git
cd noba
bash install.sh
```

The installer deploys scripts, the web dashboard, and a systemd user service on port **8080**.

### First Login

```bash
journalctl --user -u noba-web.service | grep password
```

### Deploy Agents

From the dashboard: **Agents card → Deploy Agent** (SSH or install script)

Or manually on any Linux node:
```bash
curl -sf "http://noba-server:8080/api/agent/install-script?key=YOUR_KEY" | sudo bash
```

Windows (PowerShell):
```powershell
.\install-agent.ps1 -Server "http://noba-server:8080" -Key "YOUR_KEY"
```

### Docker

```bash
git clone https://github.com/raizenica/noba.git
cd noba
docker compose up -d
```

Open `http://localhost:8080` and check the logs for the generated admin password:
```bash
docker logs noba 2>&1 | grep password
```

**Volumes:**

| Mount | Purpose |
|-------|---------|
| `./data/config:/app/config` | Settings, users, agent keys |
| `./data/db:/app/data` | SQLite database (metrics, history, agent registry) |
| `./data/certs:/app/certs:ro` | TLS certificates (optional) |
| `/var/run/docker.sock:/var/run/docker.sock:ro` | Container monitoring (optional) |

**Custom port or timezone:**
```yaml
ports:
  - "9090:8080"
environment:
  - TZ=America/New_York
```

For Podman, mount the Podman socket instead of Docker's:
```yaml
volumes:
  - /run/user/1000/podman/podman.sock:/var/run/docker.sock:ro
```

## Configuration

```
~/.config/noba/config.yaml
```

All settings are also configurable from the dashboard UI under **Settings → Integrations** (organized into 7 categories: Infrastructure, Media, Network, IoT & Home, DevOps, Notifications, Auth & Security).

## Project Layout

```
share/noba-web/server/   → Python backend (FastAPI, 160+ API routes)
share/noba-web/static/   → Frontend (Alpine.js, Chart.js, vanilla CSS)
share/noba-web/index.html → Dashboard UI
share/noba-web/status.html → Public status page
share/noba-agent/        → Remote agent + installers (Linux, Windows)
libexec/                 → Shell scripts (backup, disk check, cloud sync)
dev/                     → Developer toolkit (8 tools)
tests/                   → pytest test suite (622 tests)
```

## Developer Toolkit

```bash
dev/eye.py               # Playwright UI screenshot tool
dev/harness.sh           # Dev server lifecycle manager
dev/e2e.py               # 10 browser E2E tests
dev/smoke.py             # API smoke tester (160+ routes)
dev/crossref.py          # Multi-file cross-reference validator
dev/trace.py             # Request trace middleware + analyzer
dev/recon.py             # Tailscale infrastructure scanner
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | HTTP listen port |
| `SSL_CERT` | — | Path to TLS certificate |
| `SSL_KEY` | — | Path to TLS private key |
| `NOBA_REDIS_URL` | — | Optional Redis for caching |
| `NOBA_CELERY_BROKER` | — | Optional Celery for job queue |
| `NOBA_TERMINAL_ENABLED` | `true` | Enable/disable web terminal |

## License

MIT
