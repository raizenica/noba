# NOBA // Command Center

A lightning-fast, highly secure, and monolithic homelab dashboard. 

Built for bare-metal enthusiasts and Docker users alike, NOBA focuses on deep API integrations with popular self-hosted software while maintaining a zero-build, ultra-lightweight footprint.

![NOBA Dashboard Showcase](https://via.placeholder.com/1000x500.png?text=NOBA+//+Command+Center+Screenshot)

## 🚀 Features

* **Zero-Build Frontend:** Pure HTML, CSS, and Alpine.js. No Webpack, no Node.js dependencies, no bloat.
* **Dynamic UI:** Cards for TrueNAS, Plex, Pi-hole, and the Download Stack only render if you configure them. Your dashboard stays clean.
* **Deep Integrations:**
  * **TrueNAS SCALE:** Live app status and critical hardware alerts.
  * **Media & Downloads:** Live qBittorrent I/O speeds, active torrents, and Radarr/Sonarr queue counts.
  * **DNS & Uptime:** Native Pi-hole (v5/v6) block rates and Uptime Kuma monitor tracking.
* **Config-Driven Actions:** Trigger custom bash scripts, SSH commands, or webhooks directly from the UI via YAML configuration.
* **Enterprise-Grade Security:** PBKDF2 password hashing, atomic cache locking, and API secrets strictly confined to the backend server.

## 🐳 Getting Started (Docker)

The fastest way to deploy NOBA is via Docker.

1. Create a `docker-compose.yml` file:
```yaml
services:
  noba-dashboard:
    image: ghcr.io/raizenica/noba-web:latest # Or build locally: build: .
    container_name: noba-dashboard
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - TZ=Europe/Brussels
    volumes:
      - ./data/config:/app/config
      - ./data/logs:/root/.local/share
      - /var/run/docker.sock:/var/run/docker.sock:ro # Optional: for container stats

    Start the container:

Bash

docker-compose up -d

    Navigate to http://<your-ip>:8080.

    The default login is admin / admin (change this immediately in the UI Settings -> Users tab).

⚙️ Configuration

NOBA is designed to be configured entirely through the Web UI. Click the Settings (gear) icon to add your API keys, base URLs, and preferences.
Custom Actions

To add your own custom buttons (like restarting a remote DNS container or triggering an n8n webhook), edit the config.yaml file in your mapped volume directory:
YAML

web:
  customActions:
    - id: "reboot-dns"
      name: "Reboot DNS Stack"
      icon: "fa-sync-alt"
      command: "ssh admin@192.168.100.111 sudo reboot"
    - id: "n8n-trigger"
      name: "Trigger Sync Webhook"
      icon: "fa-bolt"
      command: "curl -X POST [http://n8n.local/webhook/sync](http://n8n.local/webhook/sync)"

🎨 Theming

NOBA supports 6 built-in color profiles including Nord, Catppuccin, Dracula, and Tokyo Night. Select your preference directly from the header dropdown.
🛡️ Security Notes

NOBA is built with security in mind. API keys for your external services are never exposed to the browser. The frontend only receives sanitized JSON payloads, ensuring your TrueNAS keys and Plex tokens remain securely locked on the backend.

Built as part of the Nobara Automation Suite.
