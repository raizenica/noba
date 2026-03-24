# NOBA API Reference

Base URL: `http://<host>:<port>` (default port 8080)

## Authentication

All endpoints except `/api/health` and `/api/login` require a valid session token.

Pass the token in either:
- **HTTP header:** `Authorization: Bearer <token>`
- **Query parameter:** `?token=<token>` (required for SSE / EventSource)

Tokens are valid for 24 hours and expire automatically. A cleanup job runs every 5 minutes to purge expired tokens.

> **Full interactive API docs** are available at `/api/docs` (Swagger UI) and `/api/redoc` (ReDoc) when the server is running. This document covers the core endpoints — for the complete reference (300+ routes across 15 routers), use the interactive docs (disabled by default — set `NOBA_OPENAPI=1` to enable).

### Roles

| Role | Access |
|------|--------|
| `viewer` | Read-only: stats, history, logs, dashboards |
| `operator` | Viewer + service control, automations, agent commands, approvals |
| `admin` | Full access: settings, user management, system update, audit log |

---

## Endpoint Reference

### 1. Core (stats.py)

Health, metrics, history, alerts, notifications, and dashboard layout.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/health` | None | Health check with version and uptime |
| GET | `/api/me` | Read | Current user info and permissions |
| GET | `/api/permissions` | Read | List all permissions by role |
| GET | `/api/plugins` | Read | List loaded plugins |
| GET | `/api/stats` | Read | Live system metrics snapshot |
| GET | `/api/stream` | SSE | Server-Sent Events metrics stream |
| GET | `/api/history/multi` | Read | Multiple metrics for overlay charting |
| GET | `/api/history/{metric}` | Read | Time-series history for a metric |
| GET | `/api/history/{metric}/export` | Read | Export metric history as CSV |
| GET | `/api/history/{metric}/trend` | Read | Trend projection for a metric |
| GET | `/api/metrics/available` | Read | List available metric names |
| GET | `/api/metrics/prometheus` | Read | Prometheus exposition format |
| GET | `/api/metrics/correlate` | Read | Aligned multi-metric correlation |
| GET | `/api/alert-rules` | Read | List configured alert rules |
| POST | `/api/alert-rules` | Admin | Create a new alert rule |
| PUT | `/api/alert-rules` | Admin | Replace all alert rules (batch) |
| PUT | `/api/alert-rules/{rule_id}` | Admin | Update an existing alert rule |
| DELETE | `/api/alert-rules/{rule_id}` | Admin | Delete an alert rule |
| GET | `/api/alert-rules/test/{rule_id}` | Admin | Test rule against current stats |
| GET | `/api/sla/{rule_id}` | Read | SLA uptime for an alert rule |
| GET | `/api/alert-history` | Read | Historical alert firings |
| GET | `/api/notifications` | Read | User notifications with unread count |
| POST | `/api/notifications/{notif_id}/read` | Read | Mark notification as read |
| POST | `/api/notifications/read-all` | Read | Mark all notifications as read |
| GET | `/api/dashboard` | Read | Get user dashboard layout |
| POST | `/api/dashboard` | Read | Save user dashboard layout |

---

### 2. Auth (auth.py)

Login, TOTP 2FA, social/OIDC auth, profile, preferences, admin user/session/key management.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/login` | None | Authenticate and get session token |
| POST | `/api/logout` | None | Revoke current session token |
| POST | `/api/auth/totp/setup` | Read | Generate TOTP secret for 2FA |
| POST | `/api/auth/totp/enable` | Read | Enable 2FA with TOTP code |
| POST | `/api/auth/totp/disable` | Admin | Disable 2FA for a user |
| GET | `/api/auth/providers` | None | List available auth providers |
| GET | `/api/auth/social/{provider}/login` | None | Redirect to social provider login |
| GET | `/api/auth/social/{provider}/callback` | None | Handle social provider callback |
| GET | `/api/auth/social/{provider}/link` | None | Initiate account linking to provider |
| GET | `/api/auth/social/{provider}/link/callback` | None | Handle account link callback |
| GET | `/api/auth/linked-providers` | Read | List linked social providers |
| DELETE | `/api/auth/linked-providers/{provider}` | Read | Unlink a social provider |
| GET | `/api/auth/oidc/login` | None | Redirect to generic OIDC provider |
| GET | `/api/auth/oidc/callback` | None | Handle OIDC callback |
| POST | `/api/auth/oidc/exchange` | None | Exchange OIDC code for token |
| GET | `/api/profile` | Read | User profile with activity summary |
| POST | `/api/profile/password` | Read | Change own password |
| GET | `/api/profile/sessions` | Read | List own active sessions |
| GET | `/api/user/preferences` | Read | Get dashboard preferences |
| PUT | `/api/user/preferences` | Read | Save dashboard preferences |
| DELETE | `/api/user/preferences` | Read | Reset preferences to defaults |
| GET | `/api/admin/users` | Admin | List all users |
| POST | `/api/admin/users` | Admin | Add, remove, or change user password |
| GET | `/api/admin/sessions` | Admin | List all active sessions |
| POST | `/api/admin/sessions/revoke` | Admin | Revoke a session by token prefix |
| GET | `/api/admin/api-keys` | Admin | List API keys |
| POST | `/api/admin/api-keys` | Admin | Create an API key |
| DELETE | `/api/admin/api-keys/{key_id}` | Admin | Delete an API key |
| GET | `/api/admin/ssh-keys` | Admin | List authorized SSH keys |
| POST | `/api/admin/ssh-keys` | Admin | Add an SSH authorized key |
| DELETE | `/api/admin/ssh-keys/{key_id}` | Admin | Remove an SSH authorized key |

---

### 3. Admin (admin.py)

Settings, config, audit, backup, reports, plugins, runbooks, Graylog.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/settings` | Read | Read all persisted settings |
| POST | `/api/settings` | Admin | Write settings to config.yaml |
| POST | `/api/notifications/test` | Admin | Send a test notification |
| GET | `/api/config/changelog` | Admin | Settings change history |
| GET | `/api/audit` | Admin | Retrieve audit log entries |
| GET | `/api/config/backup` | Admin | Download config.yaml backup |
| POST | `/api/config/restore` | Admin | Upload and restore config.yaml |
| GET | `/api/backup/status` | Read | NAS and cloud backup status |
| POST | `/api/backup/report` | Admin | Email backup status report |
| GET | `/api/backup/history` | Read | List backup snapshots |
| GET | `/api/backup/snapshots/{name}/browse` | Read | Browse snapshot directory tree |
| GET | `/api/backup/snapshots/diff` | Read | Diff two snapshots |
| GET | `/api/backup/file-versions` | Read | File versions across snapshots |
| POST | `/api/backup/restore` | Admin | Restore a file from a snapshot |
| GET | `/api/backup/config-history` | Admin | List config.yaml backup versions |
| GET | `/api/backup/config-history/{filename}` | Admin | Download a config backup version |
| GET | `/api/backup/restic` | Read | Restic repository status |
| GET | `/api/backup/schedules` | Read | List backup-related automations |
| POST | `/api/backup/schedule` | Admin | Create a backup schedule |
| GET | `/api/backup/progress` | Read | Running backup job progress |
| GET | `/api/backup/health` | Read | Backup destination health check |
| GET | `/api/log-viewer` | Operator | Return log file contents by type |
| GET | `/api/action-log` | Operator | Current action log output |
| GET | `/api/reports/bandwidth` | Read | Bandwidth usage report |
| GET | `/api/reports/anomalies` | Read | Anomaly detection summary |
| POST | `/api/reports/custom` | Operator | Generate custom metric report |
| GET | `/api/grafana/dashboard` | Read | Grafana dashboard JSON template |
| GET | `/api/plugins/available` | Admin | List available remote plugins |
| GET | `/api/plugins/bundled` | Admin | List bundled catalog plugins |
| POST | `/api/plugins/install` | Admin | Install a plugin |
| GET | `/api/plugins/{plugin_id}/config` | Admin | Get plugin config and schema |
| POST | `/api/plugins/{plugin_id}/config` | Admin | Save plugin config |
| GET | `/api/plugins/managed` | Read | List plugins with metadata |
| POST | `/api/plugins/{name}/enable` | Admin | Enable a plugin |
| POST | `/api/plugins/{name}/disable` | Admin | Disable a plugin |
| POST | `/api/plugins/reload` | Admin | Reload all plugins |
| GET | `/api/runbooks` | Read | List all runbooks |
| GET | `/api/runbooks/{runbook_id}` | Read | Get runbook detail |
| GET | `/api/graylog/search` | Operator | Search Graylog log messages |

---

### 4. Agents (agents.py)

Agent management, commands, file transfer, WebSocket, deploy.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/agent/report` | Agent | Receive agent metrics report |
| WS | `/api/agent/ws` | Agent | Agent WebSocket for real-time comms |
| WS | `/api/agents/{hostname}/terminal` | Operator | Browser terminal WebSocket |
| GET | `/api/agents/{hostname}/stream/{cmd_id}` | Operator | Poll log stream lines for command |
| GET | `/api/agents` | Read | List all agents with metrics |
| GET | `/api/agents/command-history` | Read | Command execution history |
| GET | `/api/agents/{hostname}` | Read | Detailed metrics for an agent |
| POST | `/api/agents/bulk-command` | Operator | Send command to multiple agents |
| POST | `/api/agents/{hostname}/command` | Operator | Queue command for an agent |
| POST | `/api/agents/{hostname}/uninstall` | Admin | Queue agent uninstall command |
| DELETE | `/api/agents/{hostname}` | Admin | Remove agent from dashboard |
| GET | `/api/agents/{hostname}/results` | Read | Get command results for agent |
| GET | `/api/agents/{hostname}/history` | Read | Historical agent metrics |
| POST | `/api/agents/{hostname}/network-stats` | Operator | Trigger network stats collection |
| POST | `/api/agents/{hostname}/stream-logs` | Operator | Start live log stream on agent |
| DELETE | `/api/agents/{hostname}/stream-logs/{cmd_id}` | Operator | Stop a running log stream |
| GET | `/api/agents/{hostname}/streams` | Read | List active log streams |
| GET | `/api/sla/summary` | Read | SLA uptime across agents/services |
| GET | `/api/agent/update` | Agent | Serve latest agent.py for update |
| GET | `/api/agent/install-script` | Agent | Generate agent install script |
| POST | `/api/agents/deploy` | Admin | Remote deploy agent via SSH |
| POST | `/api/agent/file-upload` | Agent | Receive file chunk from agent |
| GET | `/api/agent/file-download/{transfer_id}` | Agent | Serve file to agent for push |
| POST | `/api/agents/{hostname}/transfer` | Admin | Initiate file push to agent |

---

### 5. Containers (containers.py)

Docker/Podman control, stats, compose, TrueNAS VMs.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/container-control` | Operator | Start/stop/restart a container |
| GET | `/api/containers/{name}/logs` | Operator | Get container logs (tail N lines) |
| GET | `/api/containers/{name}/inspect` | Operator | Detailed container inspection |
| GET | `/api/containers/stats` | Read | Per-container resource usage |
| POST | `/api/containers/{name}/pull` | Admin | Pull latest image for container |
| GET | `/api/compose/projects` | Read | List Docker Compose projects |
| POST | `/api/compose/{project}/{action}` | Operator | Compose up/down/pull/restart |
| POST | `/api/truenas/vm` | Operator | Start/stop/restart TrueNAS VM |

---

### 6. Monitoring (monitoring.py)

Uptime, health score, status page, endpoint monitors.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/uptime` | Read | Uptime stats for all services |
| GET | `/api/health-score` | Read | Infrastructure health score (0-100) |
| GET | `/status` | None | Public status page (HTML) |
| GET | `/api/status/public` | None | Public status data (JSON) |
| GET | `/api/status/incidents` | None | Public incident list with updates |
| POST | `/api/status/components` | Admin | Create status page component |
| PUT | `/api/status/components/{comp_id}` | Admin | Update a status component |
| DELETE | `/api/status/components/{comp_id}` | Admin | Delete a status component |
| GET | `/api/status/components` | Read | List all status components |
| POST | `/api/status/incidents/create` | Admin | Create a status incident |
| POST | `/api/status/incidents/{id}/update` | Admin | Add update to a status incident |
| PUT | `/api/status/incidents/{id}/resolve` | Admin | Resolve a status incident |
| GET | `/api/endpoints` | Read | List endpoint monitors |
| POST | `/api/endpoints` | Admin | Create an endpoint monitor |
| PUT | `/api/endpoints/{monitor_id}` | Admin | Update an endpoint monitor |
| DELETE | `/api/endpoints/{monitor_id}` | Admin | Delete an endpoint monitor |
| POST | `/api/endpoints/{monitor_id}/check` | Operator | Trigger immediate endpoint check |

---

### 7. Infrastructure (infrastructure.py)

Service control, network, Proxmox, Kubernetes, terminal.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/service-control` | Operator | Start/stop/restart systemd service |
| GET | `/api/network/connections` | Operator | List active network connections |
| GET | `/api/network/ports` | Read | List listening ports with process |
| GET | `/api/network/interfaces` | Read | Network interface details |
| GET | `/api/services/map` | Read | Service dependency map |
| GET | `/api/disks/prediction` | Read | Disk capacity prediction |
| GET | `/api/k8s/namespaces` | Read | List Kubernetes namespaces |
| GET | `/api/k8s/pods` | Read | List pods with details |
| GET | `/api/k8s/pods/{ns}/{name}/logs` | Operator | Get pod logs |
| GET | `/api/k8s/deployments` | Read | List deployments with replicas |
| POST | `/api/k8s/deployments/{ns}/{name}/scale` | Operator | Scale a deployment |
| GET | `/api/proxmox/nodes/{node}/vms` | Read | List VMs/containers on PVE node |
| GET | `/api/proxmox/nodes/{node}/vms/{vmid}/snapshots` | Read | List VM snapshots |
| POST | `/api/proxmox/nodes/{node}/vms/{vmid}/snapshot` | Admin | Create a VM snapshot |
| GET | `/api/proxmox/nodes/{node}/vms/{vmid}/console` | Operator | Get noVNC console URL |
| WS | `/api/terminal` | Admin | WebSocket terminal (server shell) |
| GET | `/api/network/devices` | Read | List discovered network devices |
| POST | `/api/network/discover/{hostname}` | Operator | Trigger network discovery on agent |
| DELETE | `/api/network/devices/{device_id}` | Operator | Remove a discovered device |

---

### 8. Automations (automations.py)

Automation CRUD, job runs, webhooks, maintenance windows, approvals.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/run-status` | Read | Check if a script is running |
| GET | `/api/runs` | Read | List job runs with filters |
| GET | `/api/runs/{run_id}` | Read | Get job run details |
| POST | `/api/runs/{run_id}/cancel` | Operator | Cancel an active run |
| POST | `/api/runs/{run_id}/approve` | Admin | Approve a pending run |
| GET | `/api/automations` | Read | List all automations |
| POST | `/api/automations` | Operator | Create an automation |
| PUT | `/api/automations/{auto_id}` | Operator | Update an automation |
| DELETE | `/api/automations/{auto_id}` | Admin | Delete an automation |
| POST | `/api/automations/{auto_id}/run` | Operator | Manually trigger automation |
| GET | `/api/automations/templates` | Read | List automation templates |
| GET | `/api/playbooks` | Read | List playbook templates |
| GET | `/api/playbooks/{playbook_id}` | Read | Get a playbook template |
| POST | `/api/playbooks/{playbook_id}/install` | Operator | Install playbook as workflow |
| GET | `/api/automations/stats` | Read | Automation execution statistics |
| GET | `/api/automations/export` | Admin | Export automations as YAML |
| POST | `/api/automations/import` | Admin | Import automations from YAML |
| POST | `/api/automations/{auto_id}/trigger` | None | Trigger via API key or X-Trigger-Key |
| GET | `/api/automations/{auto_id}/trace` | Read | Workflow execution trace |
| POST | `/api/automations/validate-workflow` | Operator | Validate workflow step IDs |
| POST | `/api/webhook` | Operator | Trigger a configured webhook |
| POST | `/api/run` | Operator | Execute a script asynchronously |
| GET | `/api/webhooks` | Admin | List webhook receiver endpoints |
| POST | `/api/webhooks` | Admin | Create a webhook endpoint |
| DELETE | `/api/webhooks/{webhook_id}` | Admin | Delete a webhook endpoint |
| GET | `/api/maintenance-windows/active` | Read | Get active maintenance windows |
| GET | `/api/maintenance-windows` | Read | List all maintenance windows |
| POST | `/api/maintenance-windows` | Admin | Create a maintenance window |
| PUT | `/api/maintenance-windows/{id}` | Admin | Update a maintenance window |
| DELETE | `/api/maintenance-windows/{id}` | Admin | Delete a maintenance window |
| GET | `/api/approvals/count` | Read | Count of pending approvals |
| GET | `/api/approvals` | Read | List approvals by status |
| GET | `/api/approvals/{approval_id}` | Read | Get approval details |
| POST | `/api/approvals/{approval_id}/decide` | Operator | Approve or deny a pending action |
| GET | `/api/action-audit` | Read | Query action audit trail |
| POST | `/api/webhooks/receive/{hook_id}` | None | Public webhook receiver (HMAC) |

---

### 9. Integrations (integrations.py)

Cameras, Tailscale, Home Assistant, Pi-hole, game servers, cloud remotes, InfluxDB.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/cameras/snapshot/{cam}` | Read | Proxy camera snapshot from Frigate |
| GET | `/api/cameras` | Read | List configured camera feeds |
| GET | `/api/tailscale/status` | Read | Tailscale network status |
| GET | `/api/disks/intelligence` | Read | Scrutiny disk intelligence |
| GET | `/api/services/dependencies/blast-radius` | Read | Service blast radius analysis |
| POST | `/api/hass/services/{domain}/{service}` | Operator | Call Home Assistant service |
| GET | `/api/hass/entities` | Read | List HA entities with state |
| GET | `/api/hass/services` | Read | List available HA services |
| POST | `/api/hass/toggle/{entity_id}` | Operator | Toggle a HA entity |
| POST | `/api/hass/scene/{entity_id}` | Operator | Activate a HA scene |
| POST | `/api/pihole/toggle` | Operator | Enable/disable Pi-hole blocking |
| GET | `/api/game-servers` | Read | Probe configured game servers |
| POST | `/api/wol` | Operator | Send Wake-on-LAN magic packet |
| GET | `/api/cloud-remotes` | Read | List rclone remotes |
| POST | `/api/cloud-remotes/create` | Admin | Create an rclone remote |
| DELETE | `/api/cloud-remotes/{name}` | Admin | Delete an rclone remote |
| POST | `/api/cloud-test` | Operator | Test rclone remote connectivity |
| POST | `/api/influxdb/query` | Admin | Execute an InfluxDB Flux query |

---

### 10. Integration Instances (integration_instances.py)

Multi-instance integration management, catalog, groups.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/integrations/instances` | Read | List integration instances |
| GET | `/api/integrations/instances/{id}` | Read | Get a single instance |
| POST | `/api/integrations/instances` | Admin | Create an integration instance |
| PATCH | `/api/integrations/instances/{id}` | Admin | Update an instance (partial) |
| DELETE | `/api/integrations/instances/{id}` | Admin | Delete an integration instance |
| POST | `/api/integrations/instances/test-connection` | Operator | Test instance connectivity |
| GET | `/api/integrations/catalog/categories` | Read | List integration categories |
| GET | `/api/integrations/catalog/categories/{cat}/platforms` | Read | List platforms for a category |
| GET | `/api/integrations/groups` | Read | List integration groups |
| GET | `/api/integrations/groups/{name}/members` | Read | List group members |
| POST | `/api/integrations/groups/{name}/members` | Admin | Add instance to group |
| DELETE | `/api/integrations/groups/{name}/members/{id}` | Admin | Remove instance from group |

---

### 11. Intelligence (intelligence.py)

Incidents, dependencies, baselines, config drift, AI/LLM, prediction.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/incidents` | Read | List recent incidents |
| POST | `/api/incidents/{id}/resolve` | Operator | Resolve an incident |
| GET | `/api/incidents/{id}/messages` | Read | Get incident war room messages |
| POST | `/api/incidents/{id}/messages` | Operator | Post to incident war room |
| PUT | `/api/incidents/{id}/assign` | Operator | Assign incident to a user |
| GET | `/api/dependencies` | Read | Service dependency graph |
| POST | `/api/dependencies` | Admin | Create a service dependency |
| DELETE | `/api/dependencies/{dep_id}` | Admin | Delete a service dependency |
| GET | `/api/dependencies/impact/{service}` | Read | Transitive impact analysis |
| POST | `/api/dependencies/discover/{hostname}` | Operator | Discover services on agent |
| GET | `/api/baselines` | Read | List config baselines |
| POST | `/api/baselines` | Admin | Create a config baseline |
| DELETE | `/api/baselines/{id}` | Admin | Delete a config baseline |
| POST | `/api/baselines/{id}/set-from/{hostname}` | Admin | Set baseline hash from agent |
| POST | `/api/baselines/check` | Operator | Trigger immediate drift check |
| GET | `/api/baselines/{id}/results` | Read | Drift check results per agent |
| GET | `/api/ai/status` | Read | AI/LLM configuration status |
| POST | `/api/ai/chat` | Operator | Chat with AI assistant |
| POST | `/api/ai/analyze-alert/{alert_id}` | Operator | AI analysis of an alert |
| POST | `/api/ai/analyze-logs` | Operator | AI analysis of log excerpt |
| POST | `/api/ai/summarize-incident/{id}` | Operator | AI incident summary/report |
| GET | `/api/predict/capacity` | Read | Multi-metric capacity prediction |
| POST | `/api/ai/test` | Admin | Test LLM connection |

---

### 12. Security (security.py)

Security scanning, findings, posture scoring.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/security/score` | Read | Aggregate security score |
| GET | `/api/security/findings` | Read | Security findings with filters |
| GET | `/api/security/history` | Read | Historical security scores |
| POST | `/api/security/scan/{hostname}` | Operator | Trigger security scan on agent |
| POST | `/api/security/scan-all` | Operator | Scan all online agents |
| POST | `/api/security/record` | Admin | Record scan results (internal) |

---

### 13. Healing (healing.py)

Heal ledger, effectiveness, trust, maintenance, chaos, dry-run, rollback.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/healing/ledger` | Read | Healing action ledger |
| GET | `/api/healing/effectiveness` | Read | Healing success rate stats |
| GET | `/api/healing/suggestions` | Read | List healing suggestions |
| POST | `/api/healing/suggestions/{id}/dismiss` | Operator | Dismiss a healing suggestion |
| GET | `/api/healing/trust` | Read | List trust states per rule |
| POST | `/api/healing/trust/{rule_id}/promote` | Admin | Promote trust level |
| POST | `/api/healing/trust/{rule_id}/demote` | Admin | Demote trust level |
| GET | `/api/healing/capabilities/{hostname}` | Read | Agent capability manifest |
| GET | `/api/healing/dependencies` | Read | Dependency graph nodes |
| POST | `/api/healing/dependencies/validate` | Read | Validate dependency config |
| POST | `/api/healing/capabilities/{hostname}/refresh` | Operator | Refresh agent capabilities |
| GET | `/api/healing/maintenance` | Read | Active healing maintenance windows |
| POST | `/api/healing/maintenance` | Operator | Create healing maintenance window |
| DELETE | `/api/healing/maintenance/{id}` | Operator | End maintenance window early |
| POST | `/api/healing/rollback/{ledger_id}` | Admin | Rollback a heal action |
| POST | `/api/healing/dry-run` | Operator | Simulate a heal event |
| GET | `/api/healing/chaos/scenarios` | Read | List chaos test scenarios |
| POST | `/api/healing/chaos/run` | Admin | Run a chaos test scenario |
| GET | `/api/healing/health` | Read | Healing pipeline health summary |

---

### 14. Dashboards (dashboards.py)

Custom dashboard CRUD.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/dashboards` | Read | List user's dashboards |
| POST | `/api/dashboards` | Operator | Create a custom dashboard |
| PUT | `/api/dashboards/{id}` | Operator | Update a custom dashboard |
| DELETE | `/api/dashboards/{id}` | Operator | Delete a custom dashboard |

---

### 15. Operations (operations.py)

System info, recovery, journal, SMART, processes, exports, backups, updates.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/recovery/tailscale-reconnect` | Operator | Reconnect Tailscale VPN |
| POST | `/api/recovery/dns-flush` | Operator | Restart DNS service |
| POST | `/api/recovery/service-restart` | Operator | Restart a named service |
| GET | `/api/sites/sync-status` | Read | Multi-site sync status |
| GET | `/api/smart` | Read | SMART disk health data |
| GET | `/api/journal` | Operator | Query systemd journal |
| GET | `/api/journal/units` | Operator | List systemd units for filter |
| GET | `/api/system/info` | Read | Extended system information |
| GET | `/api/system/health` | Read | System health score with checks |
| POST | `/api/system/cpu-governor` | Admin | Set CPU frequency governor |
| GET | `/api/processes/history` | Read | Top process history (rolling) |
| GET | `/api/processes/current` | Read | Current process list |
| GET | `/api/export/ansible` | Operator | Generate Ansible playbook |
| GET | `/api/export/docker-compose` | Operator | Generate docker-compose.yml |
| GET | `/api/export/shell` | Operator | Generate bash setup script |
| GET | `/api/backup/verifications` | Read | Backup verification history |
| POST | `/api/backup/verify` | Operator | Trigger backup verification |
| GET | `/api/backup/321-status` | Read | 3-2-1 backup compliance status |
| PUT | `/api/backup/321-status` | Operator | Update 3-2-1 compliance tracking |
| GET | `/api/system/update/check` | Operator | Check for available updates |
| POST | `/api/system/update/apply` | Admin | Pull, install, and restart |

---

## Detailed Endpoint Documentation

### `GET /api/health`

Health check. No authentication required.

**Response `200`:**
```json
{
  "status": "ok",
  "version": "2.0.0",
  "uptime_s": 3723
}
```

---

### `POST /api/login`

Authenticate and obtain a session token.

Rate limited: 5 attempts per 60 seconds per IP. Exceeding the limit triggers a 300-second lockout.

**Request body:**
```json
{
  "username": "admin",
  "password": "yourpassword"
}
```

**Response `200`:**
```json
{
  "token": "abc123...",
  "role": "admin",
  "username": "admin"
}
```

**Response `401`** — wrong credentials:
```json
{ "error": "Invalid credentials" }
```

**Response `429`** — rate limited:
```json
{ "error": "Too many login attempts. Try again in 287 seconds." }
```

---

### `POST /api/logout`

Revoke the current session token.

**Headers:** `Authorization: Bearer <token>`

**Response `200`:**
```json
{ "status": "ok" }
```

---

### `GET /api/me`

Return the authenticated user's info.

**Response `200`:**
```json
{
  "username": "admin",
  "role": "admin"
}
```

---

### `GET /api/stats`

Return the latest collected system snapshot.

**Response `200`:**
```json
{
  "timestamp": 1718000000,
  "hostname": "myserver",
  "os": "Fedora Linux 40",
  "kernel": "6.8.9-300.fc40.x86_64",
  "uptime": "3 days, 2:14:05",
  "load": [0.52, 0.61, 0.58],
  "cpu_percent": 12.4,
  "cpu_history": [10.1, 11.2, 12.4, "..."],
  "cpu_temp": 45.0,
  "gpu_temp": null,
  "memory": {
    "total": 17179869184,
    "available": 8589934592,
    "percent": 50.0,
    "used": 8589934592
  },
  "disks": [
    { "mount": "/", "percent": 62, "total": "500G", "used": "310G", "free": "190G" }
  ],
  "net_rx_bytes": 12345,
  "net_tx_bytes": 6789,
  "services": [
    { "name": "nginx", "active": true, "user": true }
  ],
  "containers": ["..."],
  "pihole": { "queries": 12345, "blocked": 2345, "percent": 19.0 },
  "plex": { "sessions": 2, "activities": 0 },
  "truenas": { "apps": 5, "alerts": 0, "vms": ["..."] },
  "alerts": [
    { "severity": "warning", "msg": "CPU usage: 78%" }
  ],
  "radar": [
    { "host": "192.168.1.1", "up": true, "latency_ms": 1.2 }
  ]
}
```

---

### `GET /api/stream`

Server-Sent Events stream — pushes a stats update every 5 seconds.

**Query parameters** (passed as query string, token required here):

| Parameter | Description |
|-----------|-------------|
| `token` | Session token |
| `services` | Comma-separated service names to monitor |
| `radarIps` | Comma-separated hosts to ping |
| `piholeUrl` | Pi-hole base URL |
| `plexUrl` | Plex base URL |
| `plexToken` | Plex token |
| `kumaUrl` | Uptime Kuma URL |
| `truenasUrl` | TrueNAS URL |
| `truenasKey` | TrueNAS API key |
| `bmcMap` | BMC host mapping |

**Event format:**
```
data: {"timestamp":1718000000,"cpu_percent":12.4,...}\n\n
```

The browser frontend uses this stream via `EventSource`. On connection error it falls back to 5-second polling of `/api/stats`.

---

### `GET /api/history/{metric}`

Retrieve time-series history for a metric.

**Path parameter:** metric name (one of `cpu_percent`, `mem_percent`, `cpu_temp`, `gpu_temp`, `disk_percent`, `ping_ms`, `net_rx_bytes`, `net_tx_bytes`)

**Query parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `range_h` | `24` | How many hours of history to return |
| `resolution` | `60` | Aggregation bucket size in seconds |

**Response `200`:**
```json
[
  { "time": 1717996400, "value": 11.2 },
  { "time": 1717996460, "value": 12.8 }
]
```

---

### `GET /api/audit`

Retrieve audit log entries. **Admin only.**

**Query parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `limit` | `100` | Maximum entries to return |

**Response `200`:**
```json
[
  {
    "time": 1718000000,
    "username": "admin",
    "action": "script_run",
    "details": "backup -> done",
    "ip": "192.168.1.42"
  }
]
```

**Logged actions:**

| Action | Trigger |
|--------|---------|
| `system_start` | Server startup |
| `system_stop` | Server shutdown |
| `login` | Successful login |
| `login_failed` | Failed login attempt |
| `logout` | Token revoked |
| `user_add` | New user created |
| `user_remove` | User deleted |
| `user_password_change` | Password changed |
| `script_run` | Automation script executed |
| `service_control` | systemctl action triggered |
| `vm_action` | TrueNAS VM action |
| `webhook` | Webhook triggered |
| `cloud_test` | rclone remote tested |
| `settings_save` | Settings written to config.yaml |

---

### `GET /api/settings`

Read all persisted settings. **Authenticated (any role).**

**Response `200`:**
```json
{
  "piholeUrl": "http://192.168.1.53",
  "piholeToken": "...",
  "monitoredServices": "nginx,docker",
  "radarIps": "192.168.1.1,8.8.8.8",
  "bookmarksStr": "Router|http://192.168.1.1|fa-network-wired",
  "customActions": ["..."],
  "automations": ["..."],
  "alertRules": ["..."]
}
```

---

### `POST /api/settings`

Write settings to `config.yaml`. **Admin only.**

**Request body:** JSON object with any subset of the settings keys (unknown keys are ignored):

```json
{
  "piholeUrl": "http://192.168.1.53",
  "piholeToken": "abc123",
  "monitoredServices": "nginx,docker,sshd"
}
```

**Response `200`:**
```json
{ "status": "ok" }
```

---

### `GET /api/cloud-remotes`

List available rclone remotes.

**Response `200`:**
```json
{
  "available": true,
  "remotes": [
    { "name": "gdrive", "label": "Cloud" },
    { "name": "b2", "label": "Cloud" }
  ]
}
```

If rclone is not installed: `{ "available": false, "remotes": [] }`

---

### `POST /api/run`

Execute an automation script asynchronously. Only one script can run at a time.

**Request body:**

| Field | Type | Description |
|-------|------|-------------|
| `script` | string | One of: `backup`, `cloud`, `verify`, `organize`, `diskcheck`, `check_updates`, `speedtest`, `custom` |
| `args` | string or list | Extra arguments passed to the script |

For `custom` scripts, pass the action `id` as `args`:
```json
{ "script": "custom", "args": "reboot-dns" }
```

**Response `200`:**
```json
{
  "success": true,
  "status": "done",
  "script": "backup"
}
```

Possible `status` values: `done`, `failed`, `timeout`, `error`

---

### `GET /api/action-log`

Return the current contents of the action log (script output).

**Response `200`:**
```json
{ "content": ">> [14:32:01] Initiating: backup\n\n[INFO] Starting backup...\n..." }
```

---

### `GET /api/run-status`

Check whether a script is currently running.

**Response `200`:**
```json
{
  "script": "backup",
  "status": "running",
  "started": "2024-06-10T14:32:01.123456"
}
```

Or when idle:
```json
{ "status": "idle" }
```

---

### `GET /api/log-viewer`

Return log file contents.

**Query parameters:**

| Parameter | Values | Description |
|-----------|--------|-------------|
| `type` | `syserr`, `action`, `backup`, `cloud` | Which log to return |

**Response `200`:**
```json
{ "content": "Jun 10 14:32:01 myserver nginx[1234]: ..." }
```

---

### `POST /api/service-control`

Start, stop, or restart a systemd service.

**Request body:**

| Field | Type | Description |
|-------|------|-------------|
| `service` | string | Service name (validated against `[a-zA-Z0-9_@:.\\-]+`) |
| `action` | string | One of: `start`, `stop`, `restart`, `poweroff` |
| `is_user` | bool | `true` for user-scope (`--user`), `false` for system scope |

**Response `200`:**
```json
{ "success": true, "stderr": "" }
```

System-scope actions require passwordless `sudo` for `systemctl`.

---

### `POST /api/truenas/vm`

Start, stop, restart, or power off a TrueNAS VM.

**Request body:**

```json
{
  "id": 1,
  "name": "my-vm",
  "action": "start"
}
```

**Response `200`:**
```json
{ "success": true }
```

---

### `POST /api/webhook`

Trigger a configured webhook automation.

**Request body:**
```json
{ "id": "n8n-sync" }
```

**Response `200`:**
```json
{ "success": true }
```

---

### `POST /api/cloud-test`

Test connectivity to an rclone remote.

**Request body:**
```json
{ "remote": "gdrive" }
```

**Response `200`:**
```json
{ "success": true, "error": "" }
```

---

### `POST /api/notifications/test`

Send a test notification via all configured channels. **Admin only.**

**Response `200`:**
```json
{ "status": "sent" }
```

---

### `GET /api/admin/users`

List all users. **Admin only.**

**Request body:**
```json
{ "action": "list" }
```

**Response `200`:**
```json
[
  { "username": "admin", "role": "admin" },
  { "username": "viewer", "role": "viewer" }
]
```

---

### `POST /api/admin/users`

Manage user accounts. **Admin only.**

#### Add user

```json
{
  "action": "add",
  "username": "newuser",
  "password": "SecurePass1!",
  "role": "viewer"
}
```

Password must meet strength requirements (>=8 chars, >=1 uppercase, >=1 digit or symbol).

**Response `200`:** `{ "status": "ok" }`
**Response `400`:** `{ "error": "Password must be at least 8 characters" }`
**Response `409`:** `{ "error": "User already exists" }`

#### Change password

```json
{
  "action": "change_password",
  "username": "existinguser",
  "password": "NewSecurePass2!"
}
```

**Response `200`:** `{ "status": "ok" }`

#### Remove user

```json
{
  "action": "remove",
  "username": "olduser"
}
```

**Response `200`:** `{ "status": "ok" }`
**Response `404`:** `{ "error": "User not found" }`

---

## Error Codes

| HTTP Status | Meaning |
|-------------|---------|
| `200` | Success |
| `400` | Bad request — invalid parameters |
| `401` | Not authenticated — missing or expired token |
| `403` | Forbidden — insufficient role |
| `404` | Resource not found |
| `409` | Conflict — resource already exists |
| `429` | Rate limited |
| `500` | Internal server error |

---

## Rate Limiting

Only the `/api/login` endpoint is rate limited:
- **Window:** 60 seconds
- **Max attempts:** 5 per IP
- **Lockout duration:** 300 seconds

---

## Security Notes

- API keys for integrations (TrueNAS, Plex, etc.) are stored server-side in `config.yaml` and never sent to the browser. The frontend only receives sanitised metric payloads.
- Passwords are hashed with PBKDF2-HMAC-SHA256 (200,000 iterations) with a per-user random salt.
- Alert rule conditions use a safe regex-based parser — no `eval()` is used anywhere.
- The Content Security Policy (`default-src 'self'`) prevents XSS injection into the dashboard.
