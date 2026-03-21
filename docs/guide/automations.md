# Automations

Automations let you trigger shell commands, HTTP webhooks, or multi-step workflows from the NOBA UI, on a schedule, or in response to alerts.

## Creating an Automation

Navigate to **Automations** in the sidebar and click **New Automation**.

| Field | Description |
|-------|-------------|
| Name | Display label |
| Type | See types below |
| Icon | Font Awesome 6 class (e.g. `fa-bolt`) |
| Description | Optional notes |

## Automation Types

| Type | Description |
|------|-------------|
| `script` | Run a shell command on the NOBA server |
| `webhook` | Send an outbound HTTP request |
| `workflow` | Multi-step visual workflow (see [Workflows](/guide/workflows)) |
| `agent_command` | Send a command to a specific agent |
| `service_control` | Start / stop / restart a systemd service |
| `notification` | Send a notification to one or more channels |
| `composite` | Run multiple automations in sequence |

### Script Automation

```yaml
type: script
command: "find /tmp -name 'noba-*' -delete && echo Done"
timeout: 30
```

Script output streams into the Action Log panel in real time. Only one script can run at a time.

### Webhook Automation

```yaml
type: webhook
url: "http://n8n.local:5678/webhook/sync"
method: POST
headers:
  Content-Type: application/json
body: '{"source": "noba"}'
```

### Alert Rules

Alert rules evaluate metric conditions and trigger notifications or automations.

Configure in **Automations → Alert Rules**:

| Field | Description |
|-------|-------------|
| Condition | Metric expression, e.g. `cpu_percent > 90` |
| Channel | Notification channel: `email`, `telegram`, `discord`, `slack`, `pushover`, `gotify` |
| Message | Notification text (supports `{value}` placeholder) |
| Cooldown | Seconds between repeat notifications (default 300) |
| Action | Optional: automation to trigger when condition is met |

**Available metrics:**

| Metric | Description |
|--------|-------------|
| `cpu_percent` | CPU usage % |
| `mem_percent` | RAM usage % |
| `cpu_temp` | CPU temperature (°C) |
| `gpu_temp` | GPU temperature (°C) |
| `disk_percent` | Root filesystem usage % |
| `ping_ms` | Ping latency to WAN target (ms) |
| `net_rx_bytes` | Network receive rate (bytes/s) |
| `net_tx_bytes` | Network transmit rate (bytes/s) |

**Operators:** `>`, `<`, `>=`, `<=`, `==`, `!=`

## Running Automations

- Click the **Run** button on any automation card to execute it immediately.
- Automations can also be triggered via the [API](/api/automations) or on a cron schedule.

## Templates

Click **Templates** to browse the built-in automation library:

| Template | Description |
|----------|-------------|
| NAS Backup | rsync backup to a NAS mount |
| Cloud Sync | rclone sync to a configured remote |
| Disk Cleanup | Clear tmp files and journal logs |
| Update Check | Run system package update check |
| Certificate Renew | Run certbot renew |
| Docker Prune | Remove unused Docker images and volumes |

Apply a template to create a pre-configured automation that you can customise.

## Import / Export

- **Export** — downloads your automation definitions as a JSON file.
- **Import** — upload a previously exported JSON to restore or copy automations.

Automation IDs are regenerated on import to avoid collisions.

## Schedules

Attach a cron schedule to any automation:

```
0 3 * * *   # Every day at 03:00
*/15 * * * * # Every 15 minutes
0 0 * * 0   # Every Sunday at midnight
```

The schedule editor includes a human-readable preview (e.g. "Every day at 03:00").
