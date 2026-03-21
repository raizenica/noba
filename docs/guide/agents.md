# Remote Agents

NOBA agents are lightweight Python daemons that run on remote Linux or Windows hosts. They report system metrics to the NOBA server over HTTPS and accept commands via WebSocket.

## Deploy an Agent

### Method 1 — SSH Deploy (from the UI)

1. Open **Agents** in the sidebar.
2. Click **Deploy Agent**.
3. Enter the target host, SSH user, and port.
4. NOBA connects via SSH, installs the agent, and registers it automatically.

Requirements: the NOBA server must be able to reach the target over SSH; `python3` must be installed on the target.

### Method 2 — Install Script (manual)

Run on the target host:

```bash
curl -sf http://<noba-server>:8080/api/agents/install-script?key=<agent-key> | bash
```

The script:
- Downloads `agent.py` from the NOBA server.
- Installs it to `/opt/noba-agent/`.
- Creates a systemd unit `noba-agent.service` and enables it.
- Writes the server URL and key to `/etc/noba-agent/agent.conf`.

### Method 3 — Windows Agent

Download the Windows agent from **Agents → Deploy → Windows** and run the installer. It installs as a Windows Service.

## Agent Keys

Each agent authenticates with a unique API key. Keys are generated in **Settings → Agent Keys** (see [Agent Keys](/config/agent-keys)).

## Command Palette

Click any online agent to open its detail panel, then use the **Command** field or the Command Palette button to send a command.

Supported command types (32+):

| Category | Commands |
|----------|---------|
| System | `shell`, `reboot`, `shutdown`, `update_agent` |
| Files | `file_read`, `file_write`, `file_delete`, `file_list` |
| Services | `service_start`, `service_stop`, `service_restart`, `service_status` |
| Processes | `process_list`, `process_kill` |
| Network | `ping`, `traceroute`, `port_check`, `dns_lookup` |
| Docker | `container_list`, `container_start`, `container_stop`, `container_restart` |
| Packages | `package_install`, `package_remove`, `package_update` |
| Monitoring | `metrics_snapshot`, `disk_usage`, `log_tail` |

Commands are delivered via WebSocket for near-instant execution. Results are returned and displayed in the command history panel.

## Log Streaming

Click **Stream Logs** in an agent's detail panel to open a live log viewer. Supported log sources:

- `journald` — filtered by unit name
- Arbitrary file paths (e.g. `/var/log/nginx/access.log`)

The stream uses SSE from the agent's `/stream` endpoint, proxied through the NOBA server.

## File Transfer

Use **File Transfer** in the agent panel to upload or download files:

- **Upload** — select a local file; it is sent to the agent's target path.
- **Download** — enter a remote path; the file is fetched and downloaded to your browser.

## Agent Delete

To remove an agent:

1. Open the agent's detail panel.
2. Click **Delete Agent**.
3. Confirm. The agent record and all associated history are removed from the database.

The agent service on the remote host is not automatically stopped — run `systemctl disable --now noba-agent` on the remote host after deletion.

## Agent Status

| Status | Meaning |
|--------|---------|
| Online | Last heartbeat within 30 seconds |
| Offline | No heartbeat for 30–300 seconds |
| Dead | No heartbeat for more than 5 minutes |

Agents send a heartbeat every 15 seconds by default.
