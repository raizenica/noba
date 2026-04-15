# NOBA // Command Center — User Guide

## Table of Contents

1. [Overview](#1-overview)
2. [Requirements](#2-requirements)
3. [Installation](#3-installation)
4. [First Run](#4-first-run)
5. [Navigating the Dashboard](#5-navigating-the-dashboard)
6. [Custom Dashboards](#6-custom-dashboards)
7. [Remote Agents](#7-remote-agents)
8. [Integrations](#8-integrations)
9. [Automations & Workflows](#9-automations--workflows)
10. [Self-Healing Pipeline](#10-self-healing-pipeline)
11. [AI / LLM Intelligence](#11-ai--llm-intelligence)
12. [Monitoring & SLA](#12-monitoring--sla)
13. [Health Score](#13-health-score)
14. [Security Posture](#14-security-posture)
15. [Status Page](#15-status-page)
16. [User Management](#16-user-management)
17. [Themes & Customization](#17-themes--customization)
18. [Keyboard Shortcuts](#18-keyboard-shortcuts)
19. [Multi-Site Operations](#19-multi-site-operations)
20. [Infrastructure Export](#20-infrastructure-export)
21. [Updating](#21-updating)
22. [Uninstalling](#22-uninstalling)

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
git clone https://github.com/raizenica/noba-ce.git
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
git clone https://github.com/raizenica/noba-ce.git
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
| Theme selector | Choose from 8 colour themes (including System/auto) |
| Notification bell | Unread count + notification center |
| Approval badge | Pending approvals count (operators/admins) |
| Update pill | Appears when a new version is available (admins) |
| Connection pill | Live (SSE) / Polling / Offline |
| User avatar | Opens profile modal (API keys, sessions, password) |

### Dashboard Cards
All cards are **draggable** — grab any card header to reorder. Layout saves per-user. Cards can be shown/hidden via **Settings → Visibility**. Press `g` to collapse all cards to headers for a quick overview.

Integration cards auto-appear when you configure their service in **Settings → Integrations**.

---

## 6. Custom Dashboards

Create purpose-built dashboards beyond the default view.

### Creating a Dashboard

`POST /api/dashboards` with a JSON body:

```json
{
  "name": "NOC Overview",
  "config_json": {
    "widgets": [
      { "type": "metric", "source": "cpu", "agent": "gateway-01" },
      { "type": "chart", "source": "network_io", "span": "24h" },
      { "type": "status_grid", "source": "endpoints" }
    ]
  },
  "shared": true
}
```

### Widget Types

| Type | Description |
|------|-------------|
| `metric` | Single-value gauge (CPU, memory, temperature, etc.) |
| `chart` | Time-series chart (line, bar, area) |
| `status_grid` | Grid of endpoint/agent statuses |
| `integration` | Embedded integration card |
| `incidents` | Active incidents list |
| `text` | Markdown note or runbook excerpt |

### Sharing

- **Private** — only the creator sees it (`"shared": false`)
- **Shared** — visible to all users with at least viewer role (`"shared": true`)
- Admins can manage all dashboards; operators/viewers only their own

Full CRUD is available: `GET /api/dashboards`, `PUT /api/dashboards/{id}`, `DELETE /api/dashboards/{id}`.

---

## 7. Remote Agents

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

- 42+ command types (service control, file transfer, log streaming, security scan, network diagnostics, etc.)
- WebSocket real-time communication with HTTP polling fallback
- Browser-based remote terminal (PTY via xterm.js, admin-only)
- File transfer up to 50 MB with SHA256 verification
- Risk-tiered permissions (operator/admin — viewers have read-only access, no agent commands)
- Agents self-update from the NOBA server automatically

---

## 8. Integrations

### Setup Wizard

Go to **Settings → Integrations** and use the 4-step wizard:
1. Pick a category (Media, Infrastructure, Network, IoT, etc.)
2. Pick a platform (Plex, TrueNAS, Pi-hole, etc.)
3. Configure URL, auth credentials, site, and tags
4. Test connection → Save

Configured integrations appear as dashboard cards automatically.

### Supported Categories (29)

Media, Infrastructure, Network, IoT & Home, DevOps, Auth, Monitoring — covering 40+ platforms including Pi-hole, AdGuard, UniFi, TrueNAS, Proxmox, Plex, Jellyfin, Home Assistant, Frigate, qBittorrent, Vaultwarden, Uptime Kuma, Tailscale, and more.

See the [main README](https://github.com/raizenica/noba-ce#-40-integrations) for the full integration table.

### Graylog

Set `graylogUrl` to the Graylog API endpoint (e.g., `http://graylog:9000`). Authentication uses either an API token (`graylogToken`) or username/password (`graylogUser` + `graylogPassword`). Graylog v7+ requires the `X-Requested-By` header, which NOBA adds automatically.

---

## 9. Automations & Workflows

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

## 10. Self-Healing Pipeline

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

### Remote Agent Healing

To heal services on remote agents, set the `target` field in the alert rule action to the agent hostname (e.g., `pve`). NOBA dispatches the heal command via WebSocket. If the target agent is offline, execution falls back to local.

---

## 11. AI / LLM Intelligence

NOBA includes an optional AI assistant that understands your infrastructure in real time.

### Configuration

Enable in **Settings → AI/LLM**:

| Setting | Description |
|---------|-------------|
| `llmEnabled` | Toggle AI features on/off |
| `llmProvider` | `ollama`, `openai`, `anthropic`, or `custom` |
| `llmModel` | Model name (e.g. `llama3.2:3b`, `gpt-4o`, `claude-sonnet-4-20250514`) |
| `llmBaseUrl` | API endpoint (e.g. `http://localhost:11434` for Ollama) |

For local/zero-cost operation, Ollama with `llama3.2:3b` is recommended for CPU-only hosts.

### Infrastructure Chat

Send natural-language questions via `POST /api/ai/chat`:

```json
{ "message": "Which agents have high CPU right now?" }
```

The system automatically injects live context — agent statuses, endpoint health, healing history, and health scores — so the model answers with awareness of your actual infrastructure.

### Log Analysis

Paste a log snippet to `POST /api/ai/analyze-logs` for an AI-generated breakdown:

```json
{ "logs": "Mar 24 02:14:07 gw kernel: nf_conntrack: table full..." }
```

Returns structured findings: root cause, severity, and recommended actions.

---

## 12. Monitoring & SLA

### Endpoint Monitoring

Create HTTP/HTTPS monitors in **Monitoring → Endpoints**:
- Custom check intervals, expected status codes, timeout
- Agent-dispatched checks for internal endpoints
- TLS certificate expiry tracking and alerts
- Response time metrics and trending

### SLA Dashboard

- 7-day, 30-day, 90-day uptime percentages per agent/service
- Incident tracking with severity, assignment, and resolution
- Public status page — see [Section 15: Status Page](#15-status-page)

---

## 13. Health Score

Each agent and the platform as a whole receive a composite health score from 0 to 100, mapped to a letter grade.

### Grading Scale

| Score | Grade | Meaning |
|-------|-------|---------|
| 90–100 | A | Excellent — all checks passing |
| 80–89 | B | Good — minor issues |
| 70–79 | C | Fair — attention needed |
| 60–69 | D | Poor — multiple problems |
| < 60 | F | Critical — immediate action required |

### Scoring Categories

| Category | What It Measures |
|----------|-----------------|
| Monitoring coverage | Percentage of services with active checks |
| Certificate health | Days to expiry, chain validity |
| Update status | OS and package update freshness |
| Uptime / SLA | Recent uptime percentage vs target |
| Capacity | Disk, memory, and CPU headroom |
| Backup freshness | Age of most recent verified backup |

Scores update on every metrics cycle. View per-agent scores in **Agents → Health** or the aggregated platform score on the main dashboard.

---

## 14. Security Posture

Agent-based security scanning evaluates each host against hardening best practices.

### Running a Scan

Trigger a scan from the UI (**Security → Scan**) or via API:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$NOBA_URL/api/security/scan/gateway-01"
```

### Categories Checked

- **SSH configuration** — root login, password auth, key-only enforcement
- **Firewall** — active ruleset, default deny, open ports
- **Automatic updates** — unattended-upgrades or equivalent enabled
- **Password policy** — complexity requirements, account lockout
- **File integrity** — SUID/SGID binaries, world-writable paths

### Findings

Each finding includes severity (`critical`, `high`, `medium`, `low`, `info`) and remediation advice. Findings aggregate across all agents into a platform-wide security score.

### Baseline Drift Detection

Create a baseline snapshot of expected file hashes for critical paths. NOBA compares subsequent scans against the baseline and flags any changes — useful for detecting unauthorized modifications across sites.

---

## 15. Status Page

A public-facing status page at `/#/status` (no authentication required) shows service health to users and stakeholders.

### Components

Organize services into groups:

| Group | Example Components |
|-------|--------------------|
| Core | NOBA API, Database, Auth |
| Infrastructure | Proxmox, TrueNAS, Network |
| Services | Plex, Home Assistant, Pi-hole |

Each component shows real-time status: **operational**, **degraded**, **partial outage**, or **major outage**.

### Incidents

Incidents follow a lifecycle:

1. **Investigating** — issue detected, root cause unknown
2. **Identified** — cause found, working on fix
3. **Monitoring** — fix applied, watching for recurrence
4. **Resolved** — confirmed fixed

Each status transition can include a timestamped message, building a public update timeline. Incidents can be created manually or auto-generated by the healing pipeline.

---

## 16. User Management

**Settings → Users** (admin only)

- Create users with admin, operator, or viewer role
- Change passwords (enforced: 8+ chars, uppercase, digit/symbol)
- TOTP 2FA enrollment
- Social login (Google, GitHub, Facebook, Microsoft) via OIDC
- API key management (per-user, with expiry)
- Session management (view/revoke active sessions)

---

## 17. Themes & Customization

Select a theme from the header dropdown:

| Theme | Description |
|-------|-------------|
| System | Auto-detect from OS light/dark preference |
| Operator | Dark terminal aesthetic (default) |
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

## 18. Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+K` | Open command palette / search |
| `g` | Toggle quick-glance mode (collapse all cards) |
| `Escape` | Close any open modal |

Customize shortcuts in **Settings → Shortcuts**.

---

## 19. Multi-Site Operations

NOBA supports distributed deployments across multiple physical sites with independent failure domains.

### Architecture

Deploy a NOBA instance at each site. Each instance operates autonomously — if one site loses connectivity, the other continues monitoring and healing without interruption.

### Cross-Site Endpoint Monitoring

Configure each site to monitor the other's critical endpoints:

- Site A watches Site B's gateway, NAS, and services
- Site B watches Site A's gateway, NAS, and services
- Alerts fire locally when the remote site becomes unreachable

### Webhook Chains

Link sites via outbound webhooks for cross-site alerting. All webhook payloads are signed with HMAC-SHA256 to prevent spoofing:

```json
{
  "type": "webhook",
  "url": "https://site-b.example.com/api/webhooks/inbound",
  "secret": "shared-hmac-key",
  "events": ["healing.executed", "endpoint.down", "agent.offline"]
}
```

### Agent Multi-Homing

A single agent can report to multiple NOBA instances simultaneously. Configure additional server URLs in the agent config:

```yaml
servers:
  - url: "https://noba-site-a.local:8080"
    key: "SITE_A_KEY"
  - url: "https://noba-site-b.local:8080"
    key: "SITE_B_KEY"
```

Both instances receive metrics and can issue commands. In a split-brain scenario, the agent accepts commands from either server independently.

### Design Principles

- **Independent failure domains** — no shared database or single point of failure
- **Eventual consistency** — webhook events propagate state changes between sites
- **Local-first healing** — each site heals its own infrastructure without cross-site dependencies

---

## 20. Infrastructure Export

NOBA can export your infrastructure as Ansible playbooks, Docker Compose files, or shell scripts via **Operations → Export** or the `/api/export/*` endpoints.

### IaC Auto-Discovery

Add `?discover=true` to export requests to auto-discover containers and services from agents before generating output. The UI includes a "Discover" checkbox for this.

---

## 21. Updating

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

## 22. Uninstalling

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
