# NOBA API Reference

Base URL: `http://<host>:<port>` (default port 8080)

## Authentication

All endpoints except `/api/health` and `/api/login` require a valid session token.

Pass the token in either:
- **HTTP header:** `Authorization: Bearer <token>`
- **Query parameter:** `?token=<token>` (required for SSE / EventSource)

Tokens are valid for 24 hours and expire automatically. A cleanup job runs every 5 minutes to purge expired tokens.

> **Full interactive API docs** are available at `/api/docs` (Swagger UI) and `/api/redoc` (ReDoc) when the server is running. This document covers the core endpoints — for the complete reference (235+ routes across 13 routers), use the interactive docs.

### Roles

| Role | Access |
|------|--------|
| `viewer` | Read-only: stats, history, logs, dashboards |
| `operator` | Viewer + service control, automations, agent commands, approvals |
| `admin` | Full access: settings, user management, system update, audit log |

---

## Endpoints

### `GET /api/health`

Health check. No authentication required.

**Response `200`:**
```json
{
  "status": "ok",
  "version": "1.11.0",
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
  "cpu_history": [10.1, 11.2, 12.4, ...],
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
  "containers": [...],
  "pihole": { "queries": 12345, "blocked": 2345, "percent": 19.0 },
  "plex": { "sessions": 2, "activities": 0 },
  "truenas": { "apps": 5, "alerts": 0, "vms": [...] },
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
  { "time": 1717996460, "value": 12.8 },
  ...
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
  },
  ...
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

Read all persisted settings. **Admin only.**

**Response `200`:**
```json
{
  "piholeUrl": "http://192.168.1.53",
  "piholeToken": "...",
  "monitoredServices": "nginx,docker",
  "radarIps": "192.168.1.1,8.8.8.8",
  "bookmarksStr": "Router|http://192.168.1.1|fa-network-wired",
  "customActions": [...],
  "automations": [...],
  "alertRules": [...],
  ...
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

### `GET /api/notifications/test`

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

Password must meet strength requirements (≥8 chars, ≥1 uppercase, ≥1 digit or symbol).

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

### Additional API Groups

The following endpoint groups are fully documented in the interactive Swagger UI (`/api/docs`):

| Prefix | Router | Description |
|--------|--------|-------------|
| `/api/agents/*` | agents | Agent management, commands, file transfer, WebSocket |
| `/api/automations/*` | automations | CRUD, job runs, workflows, approval queue |
| `/api/healing/*` | healing | Ledger, trust, suggestions, dependencies, dry-run, chaos |
| `/api/monitoring/*` | monitoring | Endpoint monitors, SLA, incidents, dashboards |
| `/api/integrations/*` | integrations | Instance CRUD, groups, catalog, connection test |
| `/api/infrastructure/*` | infrastructure | Services, network devices, dependencies, baselines |
| `/api/security/*` | security | Scores, findings, scan-all |
| `/api/intelligence/*` | intelligence | AI chat, alert analysis (optional LLM) |
| `/api/system/*` | operations | System info, health, update check/apply, backup/restore |
| `/api/status/*` | stats | Public status page, components, uptime history |

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
