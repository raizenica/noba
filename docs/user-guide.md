# NOBA // Command Center — User Guide

## Table of Contents

1. [Overview](#1-overview)
2. [Requirements](#2-requirements)
3. [Installation](#3-installation)
   - [Docker (Recommended)](#31-docker-recommended)
   - [Bare-Metal / Native Install](#32-bare-metal--native-install)
4. [First Run & Default Credentials](#4-first-run--default-credentials)
5. [Navigating the Dashboard](#5-navigating-the-dashboard)
6. [Configuring Integrations](#6-configuring-integrations)
7. [Custom Actions & Automations](#7-custom-actions--automations)
8. [User Management](#8-user-management)
9. [Alert Rules](#9-alert-rules)
10. [Running Automation Scripts](#10-running-automation-scripts)
11. [Themes](#11-themes)
12. [Keyboard Shortcuts](#12-keyboard-shortcuts)
13. [Updating](#13-updating)
14. [Uninstalling](#14-uninstalling)

---

## 1. Overview

NOBA // Command Center is a lightweight, zero-build homelab dashboard built with Python and Alpine.js. It provides:

- **Real-time system stats** — CPU, memory, disk, temperature, network I/O
- **Service management** — start/stop/restart systemd services from the UI
- **Integration cards** — Pi-hole, TrueNAS SCALE, Plex, qBittorrent, Radarr/Sonarr, Uptime Kuma
- **Automation triggers** — run backup scripts, webhooks, and custom shell commands
- **Historical charts** — time-series graphs for all key metrics
- **Audit logging** — full audit trail of all user actions
- **Multi-user access** — admin and viewer roles with PBKDF2-hashed passwords

---

## 2. Requirements

### Docker deployment
- Docker ≥ 20.10 or Podman ≥ 4.0
- Docker Compose ≥ 2.0

### Bare-metal deployment
| Tool | Required | Purpose |
|------|----------|---------|
| Python 3.9+ | **Yes** | Backend server |
| bash ≥ 4.0 | **Yes** | Automation scripts |
| rsync | **Yes** | Backup operations |
| yq (mikefarah) | Recommended | YAML config parsing |
| jq | Recommended | JSON processing |
| rclone | Optional | Cloud backup |
| msmtp / mail | Optional | Email notifications |
| sensors / lm_sensors | Optional | Temperature monitoring |
| nvidia-smi | Optional | GPU temperature |
| dialog | Optional | TUI interface |

---

## 3. Installation

### 3.1 Docker (Recommended)

**Step 1.** Create a working directory and `docker-compose.yml`:

```yaml
services:
  noba-dashboard:
    image: ghcr.io/raizenica/noba-web:latest
    container_name: noba-dashboard
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - TZ=Europe/London        # your timezone
    volumes:
      - ./data/config:/app/config
      - ./data/logs:/root/.local/share
      - /var/run/docker.sock:/var/run/docker.sock:ro  # optional: container stats
```

**Step 2.** Start the container:

```bash
docker compose up -d
```

**Step 3.** Open `http://<your-host-ip>:8080` in your browser.

> **HTTPS:** Mount your certificates and set `SSL_CERT=/certs/fullchain.pem` and `SSL_KEY=/certs/privkey.pem` in the environment section. See [Configuration Reference](configuration.md) for full TLS options.

---

### 3.2 Bare-Metal / Native Install

**Step 1.** Clone the repository:

```bash
git clone https://github.com/raizenica/noba.git
cd noba
```

**Step 2.** Run the installer:

```bash
# Interactive install (prompts before each dependency step)
bash install.sh

# Unattended install — auto-approves all prompts and package installs
bash install.sh --auto-approve

# Dry-run to preview what would be installed
bash install.sh --dry-run

# Install to a custom prefix
bash install.sh --prefix /opt/noba

# Skip dependency installation (if you manage packages yourself)
bash install.sh --skip-deps
```

The installer:
- Detects your Linux distribution and installs dependencies via the appropriate package manager (`dnf`, `apt`, `pacman`, `zypper`, `apk`)
- Copies scripts to `~/.local/libexec/noba/`
- Places the `noba` wrapper in `~/.local/bin/noba`
- Generates a default config at `~/.config/noba/config.yaml`
- Installs systemd user timers (optional — skippable with `--no-systemd`)
- Sets up shell completions for bash, zsh, or fish

**Step 3.** Ensure `~/.local/bin` is on your `PATH`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

**Step 4.** Launch the web dashboard:

```bash
noba web --port 8080
```

Or with systemd:

```bash
systemctl --user enable --now noba-web.service
```

---

## 4. First Run & Default Credentials

On first start, NOBA creates a default admin account:

| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | `admin` |

> **Change this immediately.** Go to **Settings → Users** and click **Change Password** for the admin account.

Password requirements:
- Minimum **8 characters**
- At least **one uppercase** letter
- At least **one digit or symbol**

---

## 5. Navigating the Dashboard

### Header Bar

| Element | Description |
|---------|-------------|
| **NOBA // COMMAND CENTER** | Logo / home link |
| Network health chips | WAN and LAN reachability (green = up, red = down) |
| Username + role badge | Shows your username and role (admin / viewer) |
| Theme selector | Choose from 6 colour themes |
| **r** / Refresh button | Force-fetch latest stats |
| **s** / Settings button | Open the settings panel |
| Live pill | Green "Live" = SSE connected; "Xs" = polling fallback; "Offline" = no connection |
| Logout | End your session |

### Cards

All cards are **draggable** — grab any card header and drop it to reorder. Layout persists to `localStorage`. Each card has a **collapse toggle** (chevron icon) in the top-right corner to minimise it.

Cards that depend on integrations (e.g. TrueNAS, Pi-hole) are hidden until the corresponding URL is configured in **Settings → Integrations**.

### Alerts

Red/yellow alert banners appear at the top of the dashboard when thresholds are breached. Click the **×** button to dismiss an alert for the current session.

---

## 6. Configuring Integrations

Open **Settings** (gear icon or press `s`) → **Integrations** tab.

| Integration | Required Fields | Notes |
|-------------|-----------------|-------|
| **Pi-hole** | URL, API Token | Works with Pi-hole v5 (legacy API) and v6 (new API) |
| **Plex** | URL, Token | Token found in Plex Web → Account → XML API |
| **Uptime Kuma** | URL | Must have Prometheus metrics endpoint enabled in Kuma settings |
| **TrueNAS SCALE** | URL, API Key | Create a key in TrueNAS → Settings → API Keys |
| **Radarr** | URL, API Key | Found in Radarr → Settings → General |
| **Sonarr** | URL, API Key | Found in Sonarr → Settings → General |
| **qBittorrent** | URL, Username, Password | Web UI must be enabled in qBittorrent |
| **Backup** | Destination path | Used by backup-to-nas.sh |
| **Cloud** | rclone remote name | Run `rclone config` to set up a remote first |

Click **Apply & Save** after making changes. Settings are stored in `config.yaml` on the server.

### Radar Targets (Ping Monitor)

In the **Radar IPs** field, enter a comma-separated list of hosts to ping:

```
192.168.1.1, google.com, my-nas.local
```

### Monitored Services

In the **Monitored Services** field, enter a comma-separated list of systemd service names:

```
nginx, docker, postgresql, sshd
```

---

## 7. Custom Actions & Automations

### Custom Action Buttons

Custom actions appear in the **Actions** card. Each action runs a shell command on the server.

Edit `config.yaml` directly or use **Settings → Automations**:

```yaml
web:
  customActions:
    - id: "reboot-dns"
      name: "Reboot DNS Stack"
      icon: "fa-sync-alt"
      command: "ssh admin@192.168.100.111 sudo systemctl restart pihole-FTL"

    - id: "clear-cache"
      name: "Clear Cache"
      icon: "fa-broom"
      command: "find /tmp -name 'noba-*' -delete"
```

> **Security note:** Commands run as the user that owns the NOBA process. Avoid granting unnecessary privileges.

### Webhook Automations

Automations trigger an outbound HTTP request when clicked:

```yaml
web:
  automations:
    - id: "sync-n8n"
      name: "Trigger n8n Sync"
      url: "http://n8n.local:5678/webhook/sync"
      method: "POST"
```

---

## 8. User Management

Access **Settings → Users** (admin only).

| Action | Description |
|--------|-------------|
| **Add User** | Create a new user with viewer or admin role |
| **Change Password** | Reset any user's password |
| **Remove User** | Delete a user account (cannot remove yourself) |

Roles:
- **admin** — full access including settings, user management, and service control
- **viewer** — read-only dashboard access; cannot run scripts or change settings

Password strength requirements are enforced server-side:
- ≥ 8 characters
- At least 1 uppercase letter (A–Z)
- At least 1 digit or special character

---

## 9. Alert Rules

Alert rules evaluate metric conditions and send notifications. Configure in **Settings → Automations → Alert Rules**, or directly in `config.yaml`:

```yaml
web:
  alertRules:
    - id: "high-cpu"
      name: "High CPU Usage"
      condition: "cpu_percent > 90"
      channel: "telegram"
      message: "CPU usage is critically high!"

    - id: "disk-warn"
      name: "Disk Space Warning"
      condition: "disk_percent > 85"
      channel: "email"
      message: "Disk usage has exceeded 85%"
```

Supported channels: `email`, `telegram`, `discord`, `slack`

Condition syntax: `<metric> <operator> <value>` — for example:
- `cpu_percent > 90`
- `mem_percent >= 95`
- `disk_percent > 80`
- `cpu_temp > 85`

A 5-minute cooldown prevents notification spam for the same rule.

---

## 10. Running Automation Scripts

The **Actions** card (and `noba` CLI) lets you trigger automation scripts:

| Script | UI Button | CLI Command |
|--------|-----------|-------------|
| NAS Backup | Backup | `noba backup` |
| Cloud Sync | Cloud Backup | `noba cloud` |
| Backup Verify | Verify | `noba verify` |
| Disk Check | Disk Sentinel | `noba disk` |
| Downloads Organiser | Organise | `noba organize` |
| System Update | Check Updates | `noba update` |

Scripts run asynchronously; their output streams into the **Action Log** panel in real time.

Only one script can run at a time. If you start a second script while one is running, you'll see an error message.

---

## 11. Themes

Select a theme in the header dropdown. Available themes:

| Name | Description |
|------|-------------|
| Default | Dark terminal aesthetic |
| Catppuccin | Soft pastel Mocha palette |
| Tokyo Night | Deep blue Tokyo Night |
| Gruvbox | Warm retro Gruvbox |
| Dracula | Classic Dracula purple |
| Nord | Cool arctic Nord palette |

Theme selection is stored in `localStorage` and persists between sessions.

---

## 12. Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `s` | Toggle settings panel |
| `r` | Refresh stats |
| `Esc` | Close any open modal |

---

## 13. Updating

### Docker

```bash
docker compose pull
docker compose up -d
```

### Bare-Metal

```bash
noba update
```

Or manually:

```bash
cd ~/noba   # or wherever you cloned the repo
git pull origin main
bash install.sh --skip-deps
```

---

## 14. Uninstalling

### Docker

```bash
docker compose down
rm -rf ./data   # removes config and logs
```

### Bare-Metal

```bash
bash install.sh --uninstall
```

This removes all installed files listed in `~/.local/share/noba-install.manifest`. Your config (`~/.config/noba/`) and logs (`~/.local/share/noba-*.log`) are left intact. To remove them:

```bash
rm -rf ~/.config/noba ~/.config/noba-web
rm -f ~/.local/share/noba-*.log ~/.local/share/noba-*.db
```
