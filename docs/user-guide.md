# NOBA // Command Center — User Guide

## Table of Contents

1. [Overview](#1-overview)
2. [Requirements](#2-requirements)
3. [Installation](#3-installation)
4. [First Run](#4-first-run)
5. [Navigating the Dashboard](#5-navigating-the-dashboard)
6. [Remote Agents](#6-remote-agents)
7. [Integrations](#7-integrations)
8. [Automations & Workflows](#8-automations--workflows)
9. [Self-Healing Pipeline](#9-self-healing-pipeline)
10. [Monitoring & SLA](#10-monitoring--sla)
11. [User Management](#11-user-management)
12. [Themes & Customization](#12-themes--customization)
13. [Keyboard Shortcuts](#13-keyboard-shortcuts)
14. [Updating](#14-updating)
15. [Uninstalling](#15-uninstalling)

---

## 1. Overview

NOBA // Command Center is a self-hosted infrastructure management platform built with FastAPI and Vue 3. It provides:

- **Real-time system metrics** — CPU, memory, disk, temperature, network I/O, containers, ZFS
- **Remote agent management** — deploy agents to any host, manage from one dashboard
- **40+ integration cards** — Pi-hole, TrueNAS, Proxmox, Plex, Home Assistant, UniFi, and more
- **Self-healing pipeline** — automatic detection, correlation, remediation, and graduated trust
- **Automation engine** — 10 automation types, visual workflow builder, approval gates, cron scheduling
- **Endpoint monitoring** — HTTP/HTTPS checks, SLA tracking, cert expiry alerts
- **Security posture** — per-agent scoring, config drift detection, findings dashboard
- **Multi-user RBAC** — admin, operator, viewer roles with PBKDF2 hashing, TOTP 2FA, social login

---

## 2. Requirements

### Docker deployment
- Docker >= 20.10 or Podman >= 4.0
- Docker Compose >= 2.0

### Bare-metal deployment
- Python 3.10+
- pip packages: `fastapi`, `uvicorn[standard]`, `psutil`, `pyyaml`, `httpx`
- Node.js 18+ (only if rebuilding the frontend)
- bash >= 4.0 (for automation scripts)
- git (for self-update feature)

---

## 3. Installation

### Docker

```bash
git clone https://github.com/raizenica/noba.git
cd noba
docker compose up -d
```

Grab your generated admin password:
```bash
docker logs noba 2>&1 | grep password
```

Open `http://localhost:8080`.

### Bare-Metal

```bash
git clone https://github.com/raizenica/noba.git
cd noba
bash install.sh
```

The installer detects your Linux distribution and handles dependencies. Options:

```bash
bash install.sh --auto-approve   # Unattended install
bash install.sh --dry-run        # Preview only
bash install.sh --skip-deps      # Skip package installation
bash install.sh --no-systemd     # Skip systemd unit setup
```

Grab your generated admin password:
```bash
journalctl --user -u noba-web.service | grep password
```

---

## 4. First Run

On first start, NOBA generates a random admin password (shown in the service log). Use it to log in, then change it in **Settings → Users**.

### Roles

| Role | Access |
|------|--------|
| **admin** | Full access: settings, user management, system update, agent deploy |
| **operator** | Service control, automations, agent commands, approvals |
| **viewer** | Read-only: dashboards, metrics, logs |

---

## 5. Navigating the Dashboard

### Sidebar
Persistent left sidebar with navigation to all views: Dashboard, Agents, Automations, Monitoring, Healing, Infrastructure, Security, Logs, Settings. Collapses to icon-only on small screens or via the hamburger button.

### Header Bar

| Element | Description |
|---------|-------------|
| Search bar | `Ctrl+K` command palette for quick navigation |
| Refresh button | Force-fetch latest stats |
| Theme selector | Choose from 7 colour themes |
| Notification bell | Unread count + notification center |
| Approval badge | Pending approvals count (operators/admins) |
| Update pill | Appears when a new version is available (admins) |
| Connection pill | Live (SSE) / Polling / Offline |
| User avatar | Opens profile modal (API keys, sessions, password) |

### Dashboard Cards
All cards are **draggable** — grab any card header to reorder. Layout saves per-user. Cards can be shown/hidden via **Settings → Visibility**. Press `g` to collapse all cards to headers for a quick overview.

Integration cards auto-appear when you configure their service in **Settings → Integrations**.

---

## 6. Remote Agents

Deploy lightweight agents to any Linux or Windows host to monitor and manage them remotely.

### Deploying

From the dashboard: **Agents → Deploy Agent**

**Linux (one-liner):**
```bash
curl -sf "http://noba-server:8080/api/agent/install-script?key=YOUR_KEY" | sudo bash
```

**Windows (PowerShell):**
```powershell
.\install-agent.ps1 -Server "http://noba-server:8080" -Key "YOUR_KEY"
```

### Capabilities

- 32+ command types (service control, file transfer, log streaming, security scan, etc.)
- WebSocket real-time communication with HTTP polling fallback
- Browser-based remote terminal (PTY via xterm.js, admin-only)
- File transfer up to 50 MB with SHA256 verification
- Risk-tiered permissions (viewer/operator/admin)
- Agents self-update from the NOBA server automatically

---

## 7. Integrations

### Setup Wizard

Go to **Settings → Integrations** and use the 4-step wizard:
1. Pick a category (Media, Infrastructure, Network, IoT, etc.)
2. Pick a platform (Plex, TrueNAS, Pi-hole, etc.)
3. Configure URL, auth credentials, site, and tags
4. Test connection → Save

Configured integrations appear as dashboard cards automatically.

### Supported Categories (29)

Media, Infrastructure, Network, IoT & Home, DevOps, Auth, Monitoring — covering 40+ platforms including Pi-hole, AdGuard, UniFi, TrueNAS, Proxmox, Plex, Jellyfin, Home Assistant, Frigate, qBittorrent, Vaultwarden, Uptime Kuma, Tailscale, and more.

See the [main README](../README.md) for the full integration table.

---

## 8. Automations & Workflows

### Automation Types

| Type | Description |
|------|-------------|
| Script | Run a shell command or registered script |
| Webhook | Send an outbound HTTP request |
| Service | Start/stop/restart a systemd service |
| HTTP | Generic HTTP request with auth options |
| Condition | Evaluate a metric expression (gates workflow flow) |
| Delay | Wait N seconds (in workflows) |
| Notify | Send a notification via configured channels |
| Agent Command | Execute a command on a remote agent |
| Remediation | Run a healing action from the 55-action registry |
| Workflow | Chain multiple automations with branching and approval gates |

### Triggers

- **Cron schedule** — standard 5-field cron expressions
- **File system** — trigger on file/directory changes
- **RSS feed** — trigger on new feed items
- **Webhook** — inbound HMAC-validated webhooks
- **Manual** — one-click from the dashboard

### Workflow Builder

Create multi-step workflows with:
- Sequential and parallel execution
- Conditional branching (metric-based)
- Approval gates (pause until approved)
- Delay nodes
- Retry policies

---

## 9. Self-Healing Pipeline

A 6-layer architecture for autonomous infrastructure repair:

1. **Correlation** — deduplicate and absorb related events
2. **Dependency analysis** — identify root cause, suppress downstream noise
3. **Planning** — select escalation chain, score effectiveness
4. **Execution** — run action with pre-flight checks and capability validation
5. **Verification** — confirm target recovered
6. **Learning** — record outcome, adjust trust levels

### Trust Levels

New rules start at `notify` and earn autonomy over time:

`observation` → `dry_run` → `notify` → `approve` → `execute`

Admins can promote/demote manually. Circuit breaker demotes on repeated failures.

### Safety Controls

- **Maintenance windows** — suppress or queue healing during planned downtime
- **Tiered approvals** — low-risk auto-heals, high-risk requires human approval
- **State snapshots** — pre-heal state captured for rollback
- **Site isolation** — ISP outage detection prevents false restarts
- **Chaos testing** — 12 scenarios for controlled fault injection

---

## 10. Monitoring & SLA

### Endpoint Monitoring

Create HTTP/HTTPS monitors in **Monitoring → Endpoints**:
- Custom check intervals, expected status codes, timeout
- Agent-dispatched checks for internal endpoints
- TLS certificate expiry tracking and alerts
- Response time metrics and trending

### SLA Dashboard

- 7-day, 30-day, 90-day uptime percentages per agent/service
- Incident tracking with severity, assignment, and resolution
- Public status page (no auth required) at `/#/status`

---

## 11. User Management

**Settings → Users** (admin only)

- Create users with admin, operator, or viewer role
- Change passwords (enforced: 8+ chars, uppercase, digit/symbol)
- TOTP 2FA enrollment
- Social login (Google, GitHub, Facebook, Microsoft) via OIDC
- API key management (per-user, with expiry)
- Session management (view/revoke active sessions)

---

## 12. Themes & Customization

Select a theme from the header dropdown:

| Theme | Description |
|-------|-------------|
| Default | Dark terminal aesthetic |
| Catppuccin | Soft pastel Mocha palette |
| Tokyo Night | Deep blue with neon accents |
| Gruvbox | Warm retro palette |
| Dracula | Classic purple/pink |
| Nord | Cool arctic blues |
| Blood Moon | Deep red/crimson |

Theme selection persists per-user across sessions.

### Card Visibility & Layout

- **Settings → Visibility** — toggle individual cards on/off
- **Drag and drop** — reorder cards on the dashboard
- **Settings → General → Reset Layout** — restore defaults

---

## 13. Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+K` | Open command palette / search |
| `g` | Toggle quick-glance mode (collapse all cards) |
| `Escape` | Close any open modal |

Customize shortcuts in **Settings → Shortcuts**.

---

## 14. Updating

### From the UI (recommended)

Admins see an update notification in the header when a new version is available. Go to **Settings → General → System Update** to view the changelog and apply the update with one click.

### Docker

```bash
docker compose pull
docker compose up -d
```

### Bare-Metal (manual)

```bash
cd ~/noba
git pull origin main
bash install.sh --auto-approve
```

---

## 15. Uninstalling

### Docker

```bash
docker compose down
rm -rf ./data   # removes config and database
```

### Bare-Metal

```bash
bash install.sh --uninstall
```

This removes all installed files. Config (`~/.config/noba/`) and database (`~/.local/share/noba-history.db`) are preserved. To remove everything:

```bash
rm -rf ~/.config/noba ~/.config/noba-web
rm -f ~/.local/share/noba-history.db
```
