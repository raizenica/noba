# Configuration Overview

NOBA configuration is stored in a single YAML file. Most settings can also be changed through the **Settings** panel in the web UI, which writes changes back to the file automatically.

## File Locations

| Deployment | Path |
|-----------|------|
| Bare-metal | `~/.config/noba/config.yaml` |
| Docker | `/app/config/config.yaml` (mount `./data/config`) |
| Override | `NOBA_CONFIG=/path/to/config.yaml` (env var) |

## Settings UI vs config.yaml

The Settings panel in the web UI covers the most common configuration. Use `config.yaml` directly for:

- Advanced options not exposed in the UI
- Scripted or automated configuration (e.g. Ansible)
- Bulk changes across many fields

Changes made in the UI take effect immediately without a server restart. Changes made to `config.yaml` directly require a reload:

```bash
# Bare-metal
noba web --reload

# Docker
docker compose restart noba
```

## Top-Level Keys

```yaml
email: ""          # Default alert recipient
backup: {}         # rsync backup settings
cloud: {}          # rclone cloud sync settings
downloads: {}      # Download organiser settings
disk: {}           # Disk sentinel settings
logs: {}           # Log directory
services: {}       # Service monitor list
update: {}         # Auto-update settings
notifications: {}  # Alert channels (email, Telegram, etc.)
web: {}            # Dashboard and integration settings
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | HTTP listen port |
| `HOST` | `0.0.0.0` | Bind address |
| `SSL_CERT` | `""` | TLS certificate path (PEM) |
| `SSL_KEY` | `""` | TLS private key path (PEM) |
| `NOBA_CONFIG` | `~/.config/noba/config.yaml` | Config file path |
| `NOBA_SCRIPT_DIR` | `~/.local/libexec/noba` | Automation scripts directory |
| `TZ` | System default | Timezone for log timestamps |
| `NOBA_BASE_URL` | `""` | Public base URL (used in notification deep links) |

## File Locations (Bare-Metal)

| File | Purpose |
|------|---------|
| `~/.config/noba/config.yaml` | Main configuration |
| `~/.config/noba-web/users.conf` | User accounts (PBKDF2 hashed) |
| `~/.local/share/noba-history.db` | SQLite metrics and history |
| `~/.local/share/noba-web-server.log` | Server log |
| `~/.local/share/noba-action.log` | Script run output |
| `~/.config/noba/plugins/` | Installed plugins |

## Related Pages

- [Integrations](/config/integrations) — connect external services
- [Agent Keys](/config/agent-keys) — manage agent authentication
- [Notifications](/config/notifications) — alert channels
- [Themes](/config/themes) — UI themes
