# NOBA Agent Enhancement — Design Spec

**Date:** 2026-03-20
**Goal:** Transform the NOBA remote agent from a telemetry collector into a full remote management platform with 32 command types, real-time WebSocket command channel, file transfer, and a user-friendly dashboard command palette.

---

## Current State

The agent (`share/noba-agent/agent.py`, 711 lines) is a pull-based telemetry collector:
- Reports CPU/memory/disk/network metrics every 30 seconds via `POST /api/agent/report`
- Receives pending commands in the response and executes them
- 9 command types: exec, restart_service, update_agent, set_interval, ping, get_logs, check_service, network_test, package_updates
- Authentication via `X-Agent-Key` header
- Zero external dependencies (stdlib only, optional psutil)
- All agent state is in-memory on the server (lost on restart)
- Platform support: Linux primary, Windows via PowerShell installer, BSD/macOS via psutil

---

## Implementation Sub-Phases

Phase 1 is broken into 4 independent sub-phases, each testable and deployable on its own:

- **Phase 1a: Foundation** — Agent persistence (SQLite), expanded command set (agent-side), risk tier enforcement, version-to-capability mapping
- **Phase 1b: Real-time** — WebSocket client + server endpoint, dual-path command routing, streaming output
- **Phase 1c: File operations** — File transfer protocol with checksums, upload/download endpoints, file commands
- **Phase 1d: Dashboard UX** — Command palette, agent list overhaul, output panel, command history

---

## Phase 1a: Foundation

### 1. Expanded Command Set (9 → 32)

Commands are classified by risk tier. **Admins bypass all gates — no confirmation, no restrictions.**

Operators:
- Low + medium: execute immediately
- High: **cannot execute** — admin only

(The confirmation gate UX is removed for simplicity. High = admin only. Period.)

#### Low Risk (operator can execute, viewer can see results)

| Command | Params | Platforms | Description |
|---------|--------|-----------|-------------|
| `ping` | — | All | Connectivity check + version |
| `check_service` | `service` | All | Service status |
| `get_logs` | `unit`, `lines`, `priority` | Lin/BSD | Journal/syslog tail |
| `network_test` | `target`, `mode` | All | Ping/traceroute |
| `package_updates` | — | All | List available updates |
| `system_info` | — | All | Hardware, OS, IPs, kernel, uptime |
| `disk_usage` | `path` | All | df-style breakdown for a path |
| `list_services` | `filter` | All | All services with status |
| `list_users` | — | All | System users with UID, groups, shell |
| `file_read` | `path`, `lines`, `offset` | All | Read file (max 64KB, text only) |
| `file_list` | `path`, `recursive`, `pattern` | All | Directory listing with glob |
| `file_checksum` | `path`, `algo` | All | SHA256/MD5 of a file |
| `file_stat` | `path` | All | File metadata (permissions, owner, size, timestamps) |
| `container_list` | `all` | Lin/BSD | List Docker/Podman containers with status |
| `container_logs` | `name`, `lines` | Lin/BSD | Container log tail |
| `dns_lookup` | `domain`, `type` | All | DNS resolution from agent's network |
| `network_config` | — | All | Full network dump (IPs, routes, DNS) — read-only |

#### Medium Risk (operator can execute)

| Command | Params | Platforms | Description |
|---------|--------|-----------|-------------|
| `restart_service` | `service` | All | Restart a service |
| `set_interval` | `interval` | All | Change poll interval (5-3600s) |
| `service_control` | `service`, `action` | All | Start/stop/enable/disable service |
| `file_transfer` | `path` | All | Download file from agent to server |
| `file_push` | `path`, `transfer_id` | All | Push file from server to agent |
| `container_control` | `name`, `action` | Lin/BSD | Start/stop/restart Docker/Podman container |

#### High Risk (admin only)

| Command | Params | Platforms | Description |
|---------|--------|-----------|-------------|
| `exec` | `command`, `timeout` | All | Arbitrary shell execution (max 60s, 64KB output) |
| `file_write` | `path`, `content`, `mode` | All | Write file (max 1MB, auto-backup) |
| `file_delete` | `path` | All | Delete file (backup to agent's backup dir) |
| `update_agent` | — | All | Re-download agent.py from server |
| `package_install` | `packages[]` | Lin/BSD | Install packages via apt/dnf/pkg |
| `package_remove` | `packages[]` | Lin/BSD | Remove packages |
| `user_manage` | `action`, `username`, `groups[]` | Lin/BSD | Create/delete/modify users |
| `uninstall_agent` | `confirm` | All | Stop service, remove files, clean up |
| `reboot` | `delay` | All | Reboot with delay (default 60s) |
| `process_kill` | `pid` or `name`, `signal` | All | Kill process by PID or name |

**Risk reclassification rationale:**
- `exec` → high: arbitrary shell execution is the most powerful command
- `file_write` → high: can overwrite critical system files (`/etc/fstab`, etc.)
- `file_delete` → high: can delete critical system files
- `network_config` → low: read-only, no side effects

### 2. Agent-Side Path Validation

In addition to server-side validation, the agent enforces:
- **Deny list**: `/etc/shadow`, `/etc/gshadow`, `/proc/kcore`, `*/.ssh/id_*` — never read/write
- **Path canonicalization**: resolve symlinks before checking deny list
- **Size limits enforced agent-side**: `file_read` max 64KB, `file_write` max 1MB

### 3. Cross-Platform Command Implementation

| Platform | Service Manager | Package Manager | Container Runtime | Support Level |
|----------|----------------|-----------------|-------------------|---------------|
| Linux (systemd) | `systemctl` | `apt` or `dnf` | Docker, Podman | **Full** |
| Linux (non-systemd) | `service`, `rc-service` | varies | Docker, Podman | Full |
| FreeBSD | `service` | `pkg` | Docker (if present) | **Best-effort** |
| macOS | `launchctl` | `brew` (if present) | Docker Desktop | **Best-effort** |
| Windows | `sc.exe`, `Get-Service` | `winget` (if present) | Docker Desktop | **Best-effort** |

"Best-effort" means: core commands work (ping, exec, system_info, file operations), but service/package management may be incomplete due to platform differences. Commands return `{"error": "not_supported", "platform": "..."}` when unavailable.

### 4. Version-to-Capability Mapping

Server maintains a capability registry:
```python
AGENT_CAPABILITIES = {
    "1.1.0": {"exec", "restart_service", "update_agent", "set_interval", "ping",
              "get_logs", "check_service", "network_test", "package_updates"},
    "2.0.0": set(RISK_LEVELS.keys()),  # all 32 commands
}
```

Before queueing a command, server checks: `cmd in AGENT_CAPABILITIES.get(agent_version, set())`. Unsupported commands return HTTP 400 with `"Agent v{version} does not support '{cmd}'"`.

### 5. Agent Persistence

New table in `db/core.py` schema:
```sql
CREATE TABLE IF NOT EXISTS agent_registry (
    hostname TEXT PRIMARY KEY,
    ip TEXT,
    platform TEXT,
    arch TEXT,
    agent_version TEXT,
    first_seen INTEGER,
    last_seen INTEGER,
    config_json TEXT DEFAULT '{}'
);
```

- Agent data persists across server restarts
- `first_seen` tracks when agent was first registered
- `config_json` stores per-agent settings (custom interval, tags, notes)
- On report, upsert into `agent_registry` + update in-memory `_agent_data`
- On startup, load `agent_registry` into `_agent_data` (marked offline until first report)

### 6. Agent Script Architecture — Single File

**The agent stays as a single file** (`agent.py`). This preserves:
- `curl | python3` installation simplicity
- Self-update via `update_agent` (downloads one file, replaces itself)
- All installer scripts (bash, PowerShell, SSH deploy) work unchanged

The file will grow from ~711 to ~1500-2000 lines. This is managed with clear section headers and a command handler registry:

```python
_HANDLERS = {
    "exec": _cmd_exec,
    "restart_service": _cmd_restart_service,
    "system_info": _cmd_system_info,
    # ... all 32 commands
}
```

Platform-specific logic uses `if platform.system() == "Linux"` branching within each handler — the existing pattern (Linux `/proc` collectors with psutil fallback).

If the file exceeds ~2500 lines, consider a two-file split: `agent.py` (core + telemetry + transport) and `agent_commands.py` (all command handlers). Two files are still trivially distributable. The update endpoint would serve both files as a tarball.

---

## Phase 1b: Real-time (WebSocket)

### WebSocket Server Endpoint: `/api/agent/ws`

New WebSocket endpoint in `routers/system.py`:
- Agent upgrades HTTP to WebSocket with `X-Agent-Key` auth
- Supports both `ws://` and `wss://` (for deployments behind TLS reverse proxies)
- Server maintains a registry of connected WebSocket agents

Connection state in `agent_store.py`:
```python
_agent_websockets: dict[str, WebSocket] = {}  # hostname -> active WebSocket
_agent_ws_lock = threading.Lock()
```

Command routing (dual-path):
1. Check `_agent_websockets` — if connected, send via WebSocket (instant)
2. If not connected, queue in `_agent_commands` (delivered on next poll)

### Message Protocol

Server → Agent:
```json
{"type": "command", "id": "uuid", "cmd": "restart_service", "params": {"service": "nginx"}}
```

Agent → Server:
```json
{"type": "result", "id": "uuid", "status": "ok", "output": "...", "exit_code": 0}
{"type": "stream", "id": "uuid", "line": "Installing package..."}
```

Stream messages enable real-time output for long-running commands (`exec`, `package_install`).

### Agent-Side WebSocket Client (stdlib only)

Implemented using `socket`, `hashlib`, `struct`, `base64`, `ssl` — all Python stdlib since 3.6. This is ~250 lines of RFC 6455 implementation covering:
- HTTP Upgrade handshake with `X-Agent-Key` header
- Frame masking (client-to-server frames MUST be masked per RFC 6455)
- Ping/pong control frames for keepalive
- Close frame handshake
- TLS support via `ssl.create_default_context()` for `wss://`
- Reconnect with exponential backoff (5s → 10s → 20s → 60s max)
- Runs in a separate thread alongside the telemetry loop

---

## Phase 1c: File Operations

### File Transfer Protocol

File transfers are triggered by commands but use dedicated HTTP endpoints for the actual data.

#### Agent → Server (`file_transfer` command)

1. Server sends `file_transfer` command with `path`
2. Agent reads the file, computes SHA256 checksum, chunks it (256KB blocks)
3. Agent POSTs each chunk to `/api/agent/file-upload`:
   ```
   POST /api/agent/file-upload
   X-Agent-Key: {key}
   X-Transfer-Id: {uuid}
   X-Chunk-Index: 0
   X-Total-Chunks: 4
   X-Filename: nginx.conf
   X-File-Checksum: sha256:{hash}
   Content-Type: application/octet-stream
   Body: <chunk bytes>
   ```
4. Server responds with `{"status": "ok", "received": 0}` per chunk (acknowledgment)
5. On failure, agent retries the specific failed chunk (max 3 retries)
6. After all chunks sent, server verifies SHA256 of reassembled file
7. If checksum mismatch, server discards and reports error
8. Orphaned partial uploads cleaned up after 1 hour

#### Server → Agent (`file_push` command)

1. Admin uploads file through dashboard → stored on server with `transfer_id` + SHA256
2. Server sends `file_push` command with `path` (destination) and `transfer_id`
3. Agent GETs `/api/agent/file-download/{transfer_id}` with `X-Agent-Key` auth
4. Agent verifies SHA256 after download
5. Agent creates backup of existing file (to `~/.noba-agent/backups/`, not `/tmp`)
6. Agent writes file to destination `path`

**Limits:** Max 50MB per transfer. Chunk size 256KB (suitable for both LAN and WAN).

---

## Phase 1d: Dashboard UX

### Agent List View

Each agent card shows:
- Hostname + OS icon (Linux penguin, Windows logo, Apple, FreeBSD devil)
- CPU/RAM/Disk bars with percentages
- Online/offline indicator with "last seen" timestamp
- WebSocket connection indicator (bolt icon when real-time connected)
- Site tag (if configured)
- Quick action icons: terminal (exec), refresh, update, reboot

Top bar:
- Search/filter by hostname
- Filter: All / Online / Offline / by OS / by site
- Bulk select checkboxes
- "Run on selected" button → opens command palette

### Command Palette (replaces single text input)

Structured command builder:
- **Target**: multi-select dropdown with agent hostnames, groups ("All Linux", "Site A"), or individual agents
- **Category dropdown**: System, Services, Files, Packages, Network, Containers, Agent
- **Command dropdown**: filtered by selected category, grayed-out commands the user's role can't execute
- **Dynamic parameter form**: fields appear based on selected command
- **Risk indicator**: color-coded badge (green/yellow/red) next to Run button
- Role enforcement: high-risk commands hidden for operator, all visible for admin

### Output Panel

Below the command palette:
- Tabbed output: one tab per target agent
- Streaming output for long-running commands (WebSocket-fed)
- Timestamp + duration per result
- Copy button, expand/collapse
- Error results highlighted in red

### Command History

- Table of recent commands: timestamp, target(s), command, status, duration
- Re-run button per entry
- Filter by agent, command type, status
- Persisted in SQLite (new `agent_command_history` table)

### Agent Detail Modal (click agent card)

Phase 1d includes 3 tabs (remaining 4 in Phase 2):
- **Overview**: OS, kernel, IPs, uptime, agent version, CPU/RAM/disk charts
- **Services**: scrollable list, toggle switches for start/stop, status indicators
- **History**: command history for this agent, metric charts over time

Deferred to Phase 2:
- **Files** tab (directory browser, view/edit, upload/download)
- **Packages** tab (list installed, check updates, install/remove)
- **Network** tab (interfaces, routes, DNS, open ports)
- **Containers** tab (list, start/stop/restart, logs viewer)

---

## New API Endpoints

| Endpoint | Method | Auth | Sub-Phase | Purpose |
|----------|--------|------|-----------|---------|
| `/api/agent/ws` | WebSocket | X-Agent-Key | 1b | Real-time command channel |
| `/api/agent/file-upload` | POST | X-Agent-Key | 1c | Receive file chunks from agent |
| `/api/agent/file-download/{id}` | GET | X-Agent-Key | 1c | Serve file to agent |
| `/api/agents/{hostname}/transfer` | POST | Admin | 1c | Initiate file push to agent |
| `/api/agents/{hostname}/uninstall` | POST | Admin | 1a | Queue uninstall command |
| `/api/agents/bulk-command` | POST | Operator+ | 1a | Send command to multiple agents |
| `/api/agents/command-history` | GET | User auth | 1d | Recent command history |

Existing endpoints remain unchanged — backward compatible.

---

## Risk Classification System

```python
RISK_LEVELS = {
    # Low — viewer can see results, operator can execute
    "ping": "low", "check_service": "low", "get_logs": "low",
    "network_test": "low", "package_updates": "low", "system_info": "low",
    "disk_usage": "low", "list_services": "low", "list_users": "low",
    "file_read": "low", "file_list": "low", "file_checksum": "low",
    "file_stat": "low", "container_list": "low", "container_logs": "low",
    "dns_lookup": "low", "network_config": "low",

    # Medium — operator can execute
    "restart_service": "medium", "set_interval": "medium",
    "service_control": "medium", "file_transfer": "medium",
    "file_push": "medium", "container_control": "medium",

    # High — admin only
    "exec": "high", "file_write": "high", "file_delete": "high",
    "update_agent": "high", "package_install": "high", "package_remove": "high",
    "user_manage": "high", "uninstall_agent": "high", "reboot": "high",
    "process_kill": "high",
}
```

Enforcement:
- Server checks role + risk level before queueing command
- Viewer: can only view results, cannot execute any command
- Operator: low + medium only
- **Admin: all commands, no restrictions, no confirmation gates**

---

## Input Validation

All command parameters validated **both server-side and agent-side**:

Server-side (before queueing):
- Service names: `^[a-zA-Z0-9@._-]+$`
- File paths: reject `..` traversal, null bytes, control characters
- Package names: `^[a-zA-Z0-9._+-]+$`
- Usernames: `^[a-z_][a-z0-9_-]*$`
- Groups (for `user_manage`): validated against same pattern, logged if includes `sudo`/`wheel`/`root`
- Hostnames/IPs: validated via `ipaddress` module or hostname regex
- Command strings (exec): length limit 4096, logged in audit

Agent-side (before executing):
- Path deny list: `/etc/shadow`, `/etc/gshadow`, `/proc/kcore`, `*/.ssh/id_*`
- Path canonicalization: resolve symlinks before checking
- Size enforcement: `file_read` ≤ 64KB, `file_write` ≤ 1MB

All medium and high risk commands logged in audit table with executing user, target agent, command, and parameters.

---

## Constraints

- **Zero new Python dependencies** for agent (stdlib only, psutil optional)
- **Agent stays as single file** (`agent.py`) — preserves curl install, self-update, all installers
- **Backward compatible** — old v1.x agents continue to work via polling
- **Server detects agent version** and only sends supported commands
- **No new server dependencies** — FastAPI already supports WebSocket
- **File transfers max 50MB**, chunked at 256KB, SHA256 verified
- **Command output max 64KB** (up from 4KB for long-running commands)
- **Audit trail** for all medium and high risk commands
- **Container support**: Docker AND Podman (auto-detected)

---

## Phase 2 (follow-up, not in this spec)

After Phase 1 sub-phases are solid:
- Agent detail modal: Files, Packages, Network, Containers tabs
- `cron_list` / `cron_manage` — crontab management
- `firewall_rules` — iptables/nftables/pf listing
- `disk_health` — local SMART data from agent
- `port_scan` — check ports from agent's perspective
- `cert_check` — TLS cert expiry from agent's network
- `backup_trigger` — run predefined backup scripts
- Live log streaming via WebSocket (`get_logs` with follow mode)

---

## Success Criteria

- 32 commands implemented and tested across Linux (full), with stubs for Win/BSD/Mac
- WebSocket channel working with fallback to polling (Phase 1b)
- File transfer (push + pull) working up to 50MB with SHA256 verification (Phase 1c)
- Agent state persists across server restarts (Phase 1a)
- Dashboard command palette replaces raw text input (Phase 1d)
- Bulk operations work on multiple agents (Phase 1a)
- Risk tiers enforced per role (Phase 1a)
- All existing 402 tests still pass + new agent tests
- Old v1.x agents continue to work via polling
- Agent.py remains a single file
