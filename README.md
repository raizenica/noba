<div align="center">

# 🛸 NOBA Command Center

**Your homelab deserves a mission control.**

Real-time monitoring · Remote agents · Predictive intelligence · 40+ integrations
All from a single dashboard. No build step. No nonsense.

`FastAPI` · `Alpine.js` · `Chart.js` · `SQLite WAL`

<br>

![Dashboard](docs/images/dashboard.png)

</div>

---

## ⚡ Quick Start

### 🐧 Bare Metal

```bash
git clone https://github.com/raizenica/noba.git
cd noba
bash install.sh
```

Grab your generated admin password:
```bash
journalctl --user -u noba-web.service | grep password
```

### 🐳 Docker

```bash
git clone https://github.com/raizenica/noba.git
cd noba
docker compose up -d
```

```bash
docker logs noba 2>&1 | grep password
```

Open `http://localhost:8080` and you're in. 🎉

<details>
<summary>📦 Docker volumes & options</summary>

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

**Podman?** Mount the Podman socket instead:
```yaml
volumes:
  - /run/user/1000/podman/podman.sock:/var/run/docker.sock:ro
```

</details>

---

## 🖥️ Features at a Glance

### 📊 Dashboard & Monitoring

Live system metrics, sparkline charts, health bar, anomaly detection — updated every 5 seconds via SSE.

![Dashboard](docs/images/dashboard.png)

- 🔥 **CPU, RAM, disk, network, temps, ZFS, containers** — all at a glance
- 📈 **Time-series charts** with zoom/pan and multi-metric correlation
- 🟢 **Health bar** — color-coded pips for instant infrastructure overview
- 🔍 **Anomaly detection** — automatic Z-score flagging of unusual patterns
- 📱 **Mobile responsive** — bottom nav + slide-over sidebar on small screens

### 🤖 Remote Agents

Deploy lightweight agents to any Linux (or Windows) box. Send 32+ command types in real time.

![Agents](docs/images/agents.png)

- 🚀 **Zero-dependency agent** — reads `/proc` directly, optional psutil for cross-platform
- ⚡ **WebSocket real-time** — instant command delivery with HTTP polling fallback
- 📡 **Streaming output** — long-running commands stream line-by-line
- 📁 **File transfer** — push/pull up to 50 MB with SHA256 verification
- 🛡️ **Risk-tiered auth** — low (viewer) / medium (operator) / high (admin-only)
- 🔄 **Self-update** — agents pull updates from the NOBA server and restart
- 🖱️ **One-click deploy** — from the dashboard via SSH, or copy-paste a one-liner

### 🛡️ Security Posture

Per-agent security scoring with findings, config audit, and posture ring.

![Security](docs/images/security.png)

- 🔐 **PBKDF2 hashing**, TOTP 2FA, OIDC, LDAP, API keys
- 👥 **3-tier RBAC** — admin, operator, viewer with fine-grained permissions
- 🧱 **Input validation** — regex + length limits on all user inputs
- 📋 **Audit logging** — every action tracked with username, IP, timestamp
- 🚦 **Rate limiting** — per-IP and per-user with automatic lockout

### 📡 Monitoring & SLA

SLA dashboards, incident tracking, endpoint checks, custom charts, InfluxDB panels.

![Monitoring](docs/images/monitoring.png)

- 📊 **SLA dashboard** — 7d/30d/90d uptime percentages per agent/service
- 🚨 **Composite alert rules** — AND/OR conditions with escalation policies
- 🩹 **Self-healing actions** — alerts trigger agent commands automatically
- 🔔 **Notifications** — Pushover, Gotify, Slack, email, voice, browser push (PWA)
- 🕐 **Maintenance windows** — suppress alerts during planned downtime

### 🏗️ Infrastructure & Ops

Service topology, config drift detection, network maps, predictive disk intelligence.

![Infrastructure](docs/images/infrastructure.png)

- 🗺️ **Service dependency topology** — force-directed graph with impact analysis
- 🔀 **Configuration drift** — baseline checksums across agents, alert on changes
- 🌐 **Tailscale network map** — visual node grid with online/offline status
- 💾 **Predictive disk intelligence** — SMART trend analysis with failure prediction
- 📝 **Real-time log streaming** — live tail via WebSocket, color-coded by priority
- 📄 **Public status page** — component groups, 90-day uptime, no auth required

---

## 🔌 40+ Integrations

| Category | Services |
|:---------|:---------|
| 🎬 **Media** | Plex, Jellyfin, Tautulli, Overseerr, Radarr, Sonarr, Lidarr, Readarr, Bazarr, Prowlarr, qBittorrent |
| 🖥️ **Infrastructure** | TrueNAS, Proxmox VE, Scrutiny (SMART), Frigate (NVR), InfluxDB, Uptime Kuma |
| 🌐 **Network** | Pi-hole v5/v6, AdGuard Home, Traefik, Nginx Proxy Manager, Cloudflare, UniFi |
| 🏠 **IoT & Home** | Home Assistant, Homebridge, Zigbee2MQTT, ESPHome, UniFi Protect, PiKVM |
| 🛠️ **DevOps** | Kubernetes, Gitea, GitLab, GitHub, Paperless-ngx, Vaultwarden |
| 🔑 **Auth** | SSO/OIDC, LDAP/AD, TOTP 2FA, API keys, IP whitelisting |
| 📡 **Monitoring** | Tailscale mesh, cert expiry, domain expiry, weather, energy (Shelly) |

---

## 🤖 AI Ops Assistant

> *Completely optional — everything works without an LLM configured.*

- 🧠 **Multi-provider** — Anthropic (Claude), OpenAI, Ollama (local), or any OpenAI-compatible endpoint
- 💬 **Infrastructure-aware chat** — live agent status, alerts, and metrics in the system prompt
- 🔎 **Alert & log analysis** — "Explain this alert" with suggested remediation
- 🎯 **Action buttons** — AI suggests agent commands rendered as one-click buttons
- 📝 **Incident summarization** — auto-generate post-mortem reports

---

## ⚙️ Automation Engine

- 🔧 **9 automation types** — script, webhook, service, workflow, condition, delay, notify, HTTP, agent_command
- 🔀 **Workflow engine** — sequential/parallel steps with retry and exponential backoff
- ⏰ **Triggers** — cron, file system changes, RSS feeds, webhooks (HMAC validated), HA events
- ✅ **Approval gates** — require manual approval before execution

---

## 🎨 UI / UX

- 🧭 **Sidebar navigation** — persistent left sidebar with icon-only collapse
- 🔍 **Global search** — `Ctrl+K` command palette
- 🎭 **6 themes** — Default, Nord, Dracula, Tokyo, Catppuccin, Gruvbox
- 👁️ **Quick glance** — press `g` to collapse all cards to headers
- ⌨️ **Keyboard shortcuts** — fully customizable hotkeys
- 🔔 **Notification center** — bell icon with unread count + PWA push
- 💻 **Embedded terminal** — WebSocket PTY via xterm.js (admin-only)
- 📚 **API docs** — Swagger UI at `/api/docs`, ReDoc at `/api/redoc`

---

## 🚀 Deploy Agents

From the dashboard: **Agents → Deploy Agent** (SSH or install script)

**Linux (any distro):**
```bash
curl -sf "http://noba-server:8080/api/agent/install-script?key=YOUR_KEY" | sudo bash
```

**Windows (PowerShell):**
```powershell
.\install-agent.ps1 -Server "http://noba-server:8080" -Key "YOUR_KEY"
```

---

## 🗂️ Project Layout

```
share/noba-web/server/    → Python backend (FastAPI, 160+ API routes)
share/noba-web/static/    → Frontend (Alpine.js, Chart.js, vanilla CSS)
share/noba-web/index.html → Dashboard UI
share/noba-web/status.html→ Public status page
share/noba-agent/         → Remote agent + installers (Linux, Windows)
libexec/                  → Shell scripts (backup, disk check, cloud sync)
dev/                      → Developer toolkit (8 tools)
tests/                    → pytest test suite (622 tests)
```

## 🧪 Developer Toolkit

```bash
dev/eye.py               # 👁️  Playwright UI screenshot tool
dev/harness.sh           # 🔧 Dev server lifecycle manager
dev/e2e.py               # 🧪 10 browser E2E tests
dev/smoke.py             # 💨 API smoke tester (160+ routes)
dev/crossref.py          # 🔗 Multi-file cross-reference validator
dev/trace.py             # 🔬 Request trace middleware + analyzer
dev/recon.py             # 📡 Tailscale infrastructure scanner
```

## 🔧 Configuration

```
~/.config/noba/config.yaml
```

All settings are also configurable from the dashboard UI under **Settings → Integrations** (organized into 7 categories).

## 🌍 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | HTTP listen port |
| `SSL_CERT` | — | Path to TLS certificate |
| `SSL_KEY` | — | Path to TLS private key |
| `NOBA_REDIS_URL` | — | Optional Redis for caching |
| `NOBA_CELERY_BROKER` | — | Optional Celery for job queue |
| `NOBA_TERMINAL_ENABLED` | `true` | Enable/disable web terminal |

---

<div align="center">

**Prerequisites:** Python 3.10+ · Linux (Fedora, Ubuntu, Debian, Raspberry Pi OS, TrueNAS SCALE)

📄 MIT License

</div>
