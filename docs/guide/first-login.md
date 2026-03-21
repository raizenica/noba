# First Login

After installation, open `http://<your-host>:8080` in a browser.

## Default Credentials

| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | `admin` |

> **Change this immediately.** A default password is a security risk on any network-accessible service.

## Change Your Password

1. Click your username in the top-right header to open **Settings**.
2. Navigate to **Settings → Users**.
3. Click **Change Password** next to the `admin` account.
4. Enter and confirm a new password that meets the requirements:
   - Minimum 8 characters
   - At least one uppercase letter
   - At least one digit or special character

## UI Overview

![NOBA Dashboard](/images/dashboard.png)

### Header Bar

| Element | Description |
|---------|-------------|
| **NOBA // COMMAND CENTER** | Logo — click to return to the dashboard |
| Network health chips | WAN and LAN reachability indicators (green = up, red = down) |
| Username + role badge | Shows your username and role (`admin` / `operator` / `viewer`) |
| Theme selector | Switch between 6 built-in colour themes |
| Refresh button (`r`) | Force-fetch the latest system stats |
| Settings button (`s`) | Open the Settings panel |
| Live pill | `Live` = SSE connected; `Xs` = polling fallback; `Offline` = no connection |
| Logout | Revoke your session token |

### Sidebar Navigation

The left sidebar (collapsible) organises NOBA's major sections:

| Section | Description |
|---------|-------------|
| Dashboard | Real-time system cards and metric overview |
| Agents | Remote agent management and command palette |
| Monitoring | Endpoint monitors, uptime, SLA, incidents |
| Infrastructure | Services, K8s, Proxmox, network topology |
| Automations | Script runners, webhooks, visual workflows |
| Security | Security scans, findings, RBAC |
| Maintenance | Maintenance windows and alert suppression |
| Predictions | Capacity forecasting and health scoring |
| Plugins | Plugin catalogue and management |
| Settings | Configuration, integrations, users, audit log |

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `s` | Toggle Settings panel |
| `r` | Refresh stats |
| `Esc` | Close any open modal |

## Theme Selection

Click the theme dropdown in the header to choose from six built-in themes. Your choice is saved in `localStorage` and persists between sessions. See [Themes](/config/themes) for descriptions of each theme.
