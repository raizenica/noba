# Agents API

All agent endpoints are under `/api/agents`. Requires authentication. Most endpoints require `operator` role or higher.

## List Agents

```
GET /api/agents
```

**Response `200`:**
```json
[
  {
    "id": "agent_abc123",
    "label": "web-01",
    "hostname": "web-01.local",
    "ip": "192.168.1.10",
    "os": "Ubuntu 24.04",
    "version": "2.1.0",
    "status": "online",
    "last_seen": 1718000000,
    "tags": ["web", "production"]
  }
]
```

## Agent Detail

```
GET /api/agents/{agent_id}
```

Returns full agent info including current metrics snapshot.

## Agent Heartbeat / Report

Called by the agent (not by users directly):

```
POST /api/agents/{agent_id}/report
X-Agent-Key: <key>
```

```json
{
  "hostname": "web-01",
  "os": "Ubuntu 24.04",
  "cpu_percent": 12.4,
  "mem_percent": 45.0,
  "disk_percent": 62.0,
  "uptime_s": 86400
}
```

## Send Command

```
POST /api/agents/{agent_id}/commands
```

Requires `operator` role.

**Request:**
```json
{
  "type": "shell",
  "params": {
    "command": "df -h",
    "timeout": 30
  }
}
```

**Response `200`:**
```json
{
  "command_id": "cmd_xyz789",
  "status": "queued"
}
```

Command is delivered via WebSocket. Poll for results or use the stream endpoint.

## Command History

```
GET /api/agents/{agent_id}/commands
```

Returns the last 100 commands for an agent with status and output.

## Deploy Agent

```
POST /api/agents/deploy
```

Requires `admin` role.

**Request:**
```json
{
  "host": "192.168.1.15",
  "ssh_user": "ubuntu",
  "ssh_port": 22,
  "ssh_key": "~/.ssh/id_ed25519",
  "label": "db-01"
}
```

**Response `200`:**
```json
{
  "agent_id": "agent_new123",
  "key": "generated-agent-key",
  "status": "deployed"
}
```

## Install Script

```
GET /api/agents/install-script?key=<agent-key>
```

Returns a shell script that installs and configures the agent. Pipe to bash on the target host.

## Log Stream

```
GET /api/agents/{agent_id}/stream/logs?source=journald&unit=nginx&token=<token>
```

SSE stream. Events are log lines from the specified source.

| Parameter | Description |
|-----------|-------------|
| `source` | `journald` or `file` |
| `unit` | Systemd unit name (for `journald`) |
| `path` | File path (for `file`) |
| `token` | Session token (required for SSE) |

## Metrics Stream

```
GET /api/agents/{agent_id}/stream/metrics?token=<token>
```

SSE stream. Events are metric snapshots every 5 seconds.

## File Download

```
GET /api/agents/{agent_id}/files?path=/var/log/nginx/access.log
```

Returns file contents as `application/octet-stream`.

## File Upload

```
POST /api/agents/{agent_id}/files
Content-Type: multipart/form-data
```

| Field | Description |
|-------|-------------|
| `file` | File to upload |
| `dest` | Destination path on the agent |

## Delete Agent

```
DELETE /api/agents/{agent_id}
```

Requires `admin` role. Removes the agent record and all associated history from the database.

**Response `200`:** `{ "status": "deleted" }`
