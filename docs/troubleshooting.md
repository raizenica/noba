# NOBA Troubleshooting Guide

## Table of Contents

1. [Dashboard won't load](#1-dashboard-wont-load)
2. [Login issues](#2-login-issues)
3. [Stats show "Offline" or don't update](#3-stats-show-offline-or-dont-update)
4. [Integration cards missing or showing errors](#4-integration-cards-missing-or-showing-errors)
5. [Scripts fail to run from the UI](#5-scripts-fail-to-run-from-the-ui)
6. [Backup failures](#6-backup-failures)
7. [Email / notifications not sending](#7-email--notifications-not-sending)
8. [Systemd timers not firing](#8-systemd-timers-not-firing)
9. [Temperature not showing](#9-temperature-not-showing)
10. [Docker-specific issues](#10-docker-specific-issues)
    - [Docker on Proxmox VE](#docker-on-proxmox-ve--containers-fail-to-start-or-crash-immediately)
    - [Self-update shows "Git repository not found"](#self-update-shows-git-repository-not-found)
11. [Agent commands stuck in "queued"](#11-agent-commands-stuck-in-queued)
12. [Dashboard layout corruption after navigation](#12-dashboard-layout-corruption-after-navigation)
13. [Browser shows stale UI after update](#13-browser-shows-stale-ui-after-update)
14. [Log analysis tips](#14-log-analysis-tips)
15. [Resetting to defaults](#15-resetting-to-defaults)

---

## 1. Dashboard won't load

### Symptom
Browser shows "Connection refused", a blank page, or a 502 from a reverse proxy.

### Steps

**1. Check if the server process is running:**
```bash
# Bare-metal
pgrep -a python3 | grep noba
# or
cat /tmp/noba-web-server.pid && kill -0 $(cat /tmp/noba-web-server.pid)

# Docker
docker ps | grep noba
```

**2. Check the server log for startup errors:**
```bash
# Bare-metal
tail -50 ~/.local/share/noba-web-server.log

# Docker
docker logs noba-dashboard
```

**3. Confirm the port is listening:**
```bash
ss -tlnp | grep 8080
```

**4. Try curl from the same machine:**
```bash
curl -v http://localhost:8080/api/health
```

Expected: `{"status": "ok", ...}`

### Common causes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Address already in use` | Another process owns port 8080 | Change `PORT` env var or kill the other process |
| `ModuleNotFoundError` | Python dependency missing | `pip3 install fastapi 'uvicorn[standard]' psutil pyyaml httpx` |
| `Permission denied` on port 80/443 | Binding to privileged port | Use port 8080/8443 and a reverse proxy, or set `CAP_NET_BIND_SERVICE` |
| Server starts but page is blank | JS error in browser | Open DevTools (F12) → Console tab; look for CORS or CSP errors |

---

## 2. Login issues

### "Invalid credentials" on first login

On first run, NOBA generates a random admin password (shown in the service log). If you've lost it:

**Reset admin password:**
```bash
# Stop the server first, then:
python3 - <<'EOF'
import hashlib, secrets
salt = secrets.token_hex(16)
pw = input("New password: ")
dk = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200_000)
print(f"admin:pbkdf2:{salt}:{dk.hex()}:admin")
EOF
```

Copy the output line into `~/.config/noba-web/users.conf` (replacing the existing admin line), then restart the server.

### "Too many login attempts"

The rate limiter triggers after 5 failed attempts within 60 seconds. The lockout lasts 300 seconds (5 minutes). Wait and try again, or restart the server to clear the lockout.

### Token expires immediately

Check that the server clock is correct:
```bash
date
```
If the server and browser clocks differ by more than a few minutes, tokens may appear expired. Sync the server clock with NTP:
```bash
timedatectl set-ntp true
```

---

## 3. Stats show "Offline" or don't update

### The live pill shows "Offline"

The SSE stream has disconnected and polling is also failing. Likely causes:

1. **Server is down** — see [section 1](#1-dashboard-wont-load).
2. **Reverse proxy is stripping SSE headers.** Add to your proxy config:
   - Nginx: `proxy_buffering off; proxy_cache off; proxy_read_timeout 86400s;`
   - Caddy: `flush_interval -1`
3. **Token expired** — log out and log back in.

### Stats update but show stale data

The background collector runs every 5 seconds. If CPU/memory values never change:

```bash
# Check background thread is alive
tail -20 ~/.local/share/noba-web-server.log | grep -i collector
```

If the log shows repeated errors from `_collect_system`, a slow `/proc` read may be blocking the thread. Restart the server.

---

## 4. Integration cards missing or showing errors

### Card is completely missing

Cards only appear if the corresponding URL is configured. Go to **Settings → Integrations** and ensure the URL field is filled in.

### Card shows "API error" or similar

**Pi-hole:**
- Verify the URL is reachable: `curl http://<pihole-ip>/api/stats/summary`
- Ensure the API token is correct (Settings → Pi-hole in the admin panel)
- Pi-hole v6 uses a new API; v5 uses the legacy `?summaryRaw` endpoint. NOBA detects both automatically.

**TrueNAS:**
- Test API access: `curl -H "Authorization: Bearer <key>" http://<truenas>/api/v2.0/app`
- API keys are created in TrueNAS → Settings → API Keys → Add

**Plex:**
- Verify token: `curl "http://<plex>:32400/status/sessions?X-Plex-Token=<token>"`
- Token can be found at: Plex Web → Account → XML API (in the URL)

**qBittorrent:**
- The Web UI must be enabled: qBittorrent → Tools → Options → Web UI
- Check CORS isn't blocking: if qBittorrent is on a different host, ensure NOBA's server (not the browser) can reach it — it proxies requests server-side.

**Uptime Kuma:**
- Enable Prometheus metrics in Kuma: Settings → Security → "Enable Prometheus metrics endpoint"
- The URL should point to the Kuma root (e.g. `http://kuma.local:3001`), not the metrics path directly.

---

## 5. Scripts fail to run from the UI

### "A script is already running"

Only one script can run at a time. If a previous run crashed without cleaning up:
```bash
# Check the lock
cat ~/.local/share/noba-action.log | tail -5

# Restart the server to clear the job state
noba web --kill && noba web
```

### Script exits immediately with no output

The server looks for scripts in `NOBA_SCRIPT_DIR` (default `~/.local/libexec/noba/`). Check:
```bash
ls -la ~/.local/libexec/noba/
```

All scripts should be executable. If not:
```bash
chmod +x ~/.local/libexec/noba/*.sh
```

### "Script not found" error

The `SCRIPT_MAP` in `config.py` maps UI names to filenames. If you've customised the install prefix, set `NOBA_SCRIPT_DIR`:
```bash
# In noba-web or docker-compose.yml
NOBA_SCRIPT_DIR=/opt/noba/libexec/noba
```

### Script runs but fails with configuration error

Run the script directly in a terminal to see the full error:
```bash
~/.local/libexec/noba/backup-to-nas.sh --dry-run --verbose
```

Or use `noba doctor` to check all dependencies and config:
```bash
noba doctor --verbose
```

---

## 6. Backup failures

### "rsync: connection refused" or "No route to host"

The NAS is unreachable. Check:
```bash
ping -c 3 <nas-ip>
mount | grep nas
df -h /mnt/nas
```

If the NAS mount is not listed, mount it first:
```bash
sudo mount /mnt/nas
```

### "No space left on device"

The backup destination is full. The script checks free space before writing (requires at least 500 MB margin). Clear old snapshots or increase disk space.

### Backup runs but files are missing

Check the rsync exclusion rules in `config.yaml`:
```yaml
backup:
  rsync_opts: "--exclude=*.tmp"
```

Run with `--dry-run` to preview what would be transferred:
```bash
noba backup --dry-run --verbose
```

### Integrity verification fails

`backup-verifier.sh` samples random files and checksums them against originals. If it fails:
```bash
noba verify --verbose
```

This points to disk errors or filesystem corruption. Run `fsck` on the source and destination.

---

## 7. Email / notifications not sending

### Check msmtp configuration

```bash
echo "Test email body" | msmtp --debug your@email.com
```

Common issues:
- Wrong SMTP credentials in `~/.config/msmtp/config`
- Port 587 blocked by ISP (try port 465 with `tls_starttls off`)
- Missing `tls_trust_file` for certificate validation

### Check the alert rule channel

Verify `config.yaml` has valid notification settings:
```bash
yq '.notifications' ~/.config/noba/config.yaml
```

### Test from the UI

Go to **Settings → Integrations** and scroll down to find the **Test Notifications** button (admin only). Check the server log for the result:
```bash
tail -f ~/.local/share/noba-web-server.log
```

---

## 8. Systemd timers not firing

### List installed timers

```bash
systemctl --user list-timers
```

### Check if a timer is enabled

```bash
systemctl --user status noba-backup-to-nas.timer
```

### Enable and start a timer

```bash
systemctl --user enable --now noba-backup-to-nas.timer
```

### Check the most recent run

```bash
journalctl --user -u noba-backup-to-nas.service --since today
```

### Timers only fire when logged in

User systemd sessions require `loginctl enable-linger`:
```bash
loginctl enable-linger "$USER"
```

This allows your timers to run even when you are not logged into a terminal session.

---

## 9. Temperature not showing

### CPU temperature

NOBA reads from `sensors` (lm_sensors package):
```bash
sensors
```

If nothing appears:
```bash
sudo sensors-detect --auto
```

Then restart the server.

### GPU temperature

For NVIDIA GPUs, `nvidia-smi` must be installed and the GPU must be visible to the NOBA process (check that `nvidia-smi` works as the same user that runs NOBA).

For AMD GPUs in Docker, pass the device:
```yaml
devices:
  - /dev/dri:/dev/dri
```

---

## 10. Docker-specific issues

### Container can't reach host services

Use `host.docker.internal` (Docker Desktop) or the host's LAN IP. Avoid `localhost` inside containers — it refers to the container itself.

```yaml
web:
  piholeUrl: "http://192.168.1.53"   # Use LAN IP, not localhost
```

### Container monitoring not working

The Docker socket must be mounted read-only:
```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

For Podman, mount the Podman socket instead:
```yaml
volumes:
  - /run/user/1000/podman/podman.sock:/var/run/docker.sock:ro
```

### systemd service control not working in Docker

`systemctl` is not available inside containers. Service control will silently fail. For container-based deployments, use **Custom Actions** with Docker API calls instead:
```yaml
web:
  customActions:
    - id: "restart-nginx"
      name: "Restart nginx"
      icon: "fa-sync"
      command: "docker restart nginx"
```

### Docker on Proxmox VE — containers fail to start or crash immediately

**Symptom:** Containers start but internal processes fail with `Permission denied`. For example, nginx logs:
```
socketpair() failed while spawning "worker process" (13: Permission denied)
```

**Cause:** Proxmox ships with AppArmor enforcing ~120 profiles by default (primarily for LXC isolation). These profiles restrict syscalls like `socketpair()` inside Docker containers, even when seccomp is disabled.

**Fix (quick — test/dev environments):**

Run containers with `--privileged` to bypass both AppArmor and seccomp:
```bash
docker run -d --privileged --name my-container -p 8080:80 nginx:alpine
```

Or in `docker-compose.yml`:
```yaml
services:
  my-service:
    image: nginx:alpine
    privileged: true
```

**Fix (production — custom AppArmor profile):**

Create a permissive profile for Docker:
```bash
cat > /etc/apparmor.d/docker-default-relaxed <<'EOF'
#include <tunables/global>
profile docker-default-relaxed flags=(attach_disconnected,mediate_deleted) {
  #include <abstractions/base>
  network,
  capability,
  file,
  umount,
  signal,
  ptrace,
  mount,
  unix,
}
EOF

apparmor_parser -r /etc/apparmor.d/docker-default-relaxed
```

Then run containers with the custom profile:
```bash
docker run -d --security-opt apparmor=docker-default-relaxed --name my-container nginx:alpine
```

**Verification:**
```bash
# Check if AppArmor is the issue
docker logs <container-name> 2>&1 | grep -i "permission denied"

# Check AppArmor status
aa-status | head -5

# Confirm Docker's security driver
docker info --format '{{.SecurityOptions}}'
```

> **Note:** `--security-opt seccomp=unconfined` alone is NOT sufficient on Proxmox — AppArmor is the blocker, not seccomp.

### Self-update shows "Git repository not found"

**Symptom:** The **Settings → Updates** panel shows `update_available: false` with error `Git repository not found. Set NOBA_REPO_DIR environment variable.`

**Cause:** The update checker needs to know where the NOBA git repository lives. On bare-metal installs this is usually auto-detected, but when the install path (`/opt/noba`) differs from the development checkout, or when deployed via `install.sh`, the server can't find the `.git` directory.

**Fix:** Set `NOBA_REPO_DIR` in your systemd service environment:
```bash
# Edit the service override
systemctl --user edit noba-web

# Add:
[Service]
Environment=NOBA_REPO_DIR=/opt/noba
```

Then restart:
```bash
systemctl --user restart noba-web
```

For Docker deployments, add the environment variable:
```yaml
environment:
  NOBA_REPO_DIR: /app
```

### Config changes don't persist

Ensure the config volume is correctly mounted:
```bash
docker inspect noba-dashboard | python3 -c "import json,sys; m=json.load(sys.stdin); [print(m['Mounts']) for m in m]"
```

The config directory inside the container is `/app/config/`.

---

## 11. Agent commands stuck in "queued"

### Symptom
Commands sent from the dashboard (command palette or agent detail panel) stay "queued" in command history and never complete.

### Steps

**1. Check agent connectivity:**
```bash
# From the dashboard, verify agents show "online" in the Agents page
# Or via API:
curl -H "Authorization: Bearer <token>" http://localhost:8080/api/agents
```

**2. Check the agent version:**
Agents must be running the latest version for reliable WebSocket command delivery. The agent version is shown in the agent detail panel.

**3. Update agents:**
Send an `update_agent` command from the dashboard, or manually update:
```bash
# On the agent host:
curl -sf http://noba-server:8080/api/agent/update?key=YOUR_KEY -o /opt/noba-agent/agent.py
sudo systemctl restart noba-agent
```

### Common causes

| Symptom | Cause | Fix |
|---------|-------|-----|
| All commands stuck | Agent version mismatch with WebSocket result format | Update agent from dashboard or manually |
| Some commands work (via HTTP) but not WebSocket ones | Server doesn't recognize old-format results | Update both server and agent |
| "Sending..." button never clears | Frontend JS error (stale cached files) | Hard refresh: Ctrl+Shift+R |

---

## 12. Dashboard layout corruption after navigation

### Symptom
Navigating from another page (e.g., Security) to the Dashboard shows a large blank area at the top, with cards pushed down.

### Steps

**1. Hard refresh the browser:**
```
Ctrl+Shift+R (or Cmd+Shift+R on macOS)
```

This forces the browser to fetch fresh static files and resolves most layout issues caused by stale cached JavaScript.

**2. Check browser console for errors:**
Open DevTools (F12) → Console tab. Look for ResizeObserver or Vue errors.

### Common causes

This was caused by a layout bug where the ResizeObserver leaked across page navigations. Fixed — the observer now disconnects before recreating and is scoped to dashboard cards only.

---

## 13. Browser shows stale UI after update

### Symptom
After updating NOBA (via `install.sh`, `git pull`, or Docker rebuild), the dashboard still shows old behavior or old bugs.

### Fix

Static files (JS, CSS) are cached by the browser for up to 1 hour. After any update:

```
Ctrl+Shift+R  (hard refresh — bypasses cache)
```

Or clear the browser cache manually: Settings → Clear browsing data → Cached images and files.

In Docker, rebuild with `--no-cache`:
```bash
docker compose build --no-cache && docker compose up -d
```

---

## 14. Log analysis tips

### Key log files

| File | Contains |
|------|---------|
| `~/.local/share/noba-web-server.log` | Server access log and errors |
| `~/.local/share/noba-action.log` | Output from the last script run |
| `~/.local/share/backup-to-nas.log` | Backup script detailed log |
| `~/.local/share/cloud-backup.log` | Cloud sync log |
| `~/.local/share/disk-sentinel.log` | Disk monitor log |

### Useful commands

```bash
# Follow the server log in real time
tail -f ~/.local/share/noba-web-server.log

# Filter for errors only
grep -i 'error\|exception\|traceback' ~/.local/share/noba-web-server.log

# Check the last backup run
tail -100 ~/.local/share/backup-to-nas.log

# Show all failed systemd user services today
journalctl --user --since today | grep -i failed

# Run the full dependency/config check
noba doctor --verbose

# Check what the disk-sentinel would do
noba disk --dry-run --verbose
```

### Reading the audit log

From the UI: **Settings → Audit** tab (admin only)

Via API:
```bash
curl -H "Authorization: Bearer <token>" http://localhost:8080/api/audit?limit=50 | python3 -m json.tool
```

---

## 15. Resetting to defaults

### Reset just the web dashboard users

```bash
rm ~/.config/noba-web/users.conf
# Restart server — a new random admin password is generated (check service log)
```

### Reset config.yaml

```bash
# Back up first
cp ~/.config/noba/config.yaml ~/.config/noba/config.yaml.bak

# Regenerate
rm ~/.config/noba/config.yaml
# Then either re-run the installer or copy from the repo:
cp /path/to/noba/data/config/config.yaml ~/.config/noba/config.yaml
```

### Full reset (bare-metal)

```bash
bash install.sh --uninstall
rm -rf ~/.config/noba ~/.config/noba-web
rm -f ~/.local/share/noba-*.log ~/.local/share/noba-*.db
```

Then reinstall from scratch.

### Full reset (Docker)

```bash
docker compose down
rm -rf ./data
docker compose up -d
```
