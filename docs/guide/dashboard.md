# Dashboard

The Dashboard is the main view in NOBA. It displays real-time system metrics as a grid of cards, each polling via a persistent Server-Sent Events (SSE) connection.

## Card System

Each card shows a focused slice of system state:

| Card | Content |
|------|---------|
| **System** | Hostname, OS, kernel, uptime, load average |
| **CPU** | Usage %, per-core bars, temperature, history chart |
| **Memory** | RAM used/total, swap, usage history |
| **Disk** | Per-mount usage bars |
| **Network** | Rx/Tx rates, interface details |
| **Services** | Systemd service status with start/stop/restart controls |
| **Containers** | Docker/Podman container list and status |
| **Radar** | Ping latency to configured hosts |
| **Pi-hole** | Query count, block rate, top blocked domains |
| **Plex** | Active streams and transcodes |
| **TrueNAS** | Pool health, apps, alerts, VMs |
| **Radarr/Sonarr** | Queue, wanted, calendar items |
| **qBittorrent** | Active torrents, speed, ratio |
| **Alerts** | Active threshold violations |
| **Bookmarks** | Quick-launch links |

## Card Visibility

Cards that depend on integrations are hidden until the corresponding URL is configured in **Settings → Integrations**. Cards with no data to show collapse automatically.

To manually hide a card, click the chevron icon in its top-right corner. The collapsed state is saved per-card in `localStorage`.

## Masonry Layout

Cards use a masonry grid layout that automatically fills vertical gaps. The layout recalculates whenever a card is expanded, collapsed, or the window is resized.

## Drag to Reorder

Grab any card by its header and drag it to a new position. The order is saved in `localStorage` and persists between sessions.

To reset the layout to the default order, open the browser console and run:
```js
localStorage.removeItem('noba-card-order')
location.reload()
```

## Health Bar

The header displays a global health bar derived from the worst active alert severity:

| Colour | Meaning |
|--------|---------|
| Green | All systems nominal |
| Yellow | At least one warning-level alert |
| Red | At least one critical-level alert |

## Alerts

Alert banners appear at the top of the dashboard when metric thresholds are breached. Alerts are evaluated server-side every 5 seconds against configured alert rules.

- Click **×** to dismiss an alert for the current session.
- Persistent alerts re-appear on the next SSE push if the condition is still true.
- Notifications (Telegram, email, Discord, Slack, etc.) fire once per alert with a 5-minute cooldown.

See [Automations — Alert Rules](/guide/automations#alert-rules) for how to configure thresholds.

## Live Connection Indicator

The **Live** pill in the header shows SSE connection state:

- **Live** — SSE stream is active; updates arrive every 5 seconds.
- **Xs** — SSE disconnected; falling back to polling every X seconds.
- **Offline** — No connection. Check that the server is running.

For reverse proxies, ensure SSE headers are not stripped. See [Troubleshooting](/troubleshooting) for Nginx and Caddy config examples.
