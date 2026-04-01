# NOBA Standout Features — Design Spec

**Date:** 2026-03-20
**Goal:** Add 10 differentiating features that no single homelab tool offers, making NOBA the definitive homelab ops center.

---

## Feature 1: Network Auto-Discovery & Topology

Agents scan their local network and build a live map of every device.

### Agent command: `network_discover`
- ARP scan via `ip neigh` or `arp -a`
- mDNS scan via `avahi-browse -apt` (if available)
- Port probe on discovered IPs (top 20 common ports: 22, 80, 443, 8080, etc.)
- Returns: `{devices: [{ip, mac, hostname, vendor, open_ports: [22, 80, ...]}]}`

### Server
- `network_devices` table: ip, mac, hostname, vendor (OUI lookup), open_ports, agent_hostname, first_seen, last_seen
- Merge results from multiple agents (same MAC = same device)
- API: `GET /api/network/devices`, `POST /api/network/discover/{hostname}`, `GET /api/network/topology`

### Frontend (Infrastructure > Network Map tab)
- Visual network map: devices as nodes, colored by type (server/IoT/unknown), grouped by subnet
- Click device → shows open ports, hostname, vendor, which agent discovered it, first/last seen
- Auto-refresh on discovery

### Files
- Modify: `share/noba-agent/agent.py`, `agent_config.py`
- Create: `share/noba-web/server/db/network.py`
- Modify: `share/noba-web/server/db/core.py`, `routers/system.py`
- Modify: `share/noba-web/index.html`, `static/system-actions.js`, `static/app.js`

---

## Feature 2: Infrastructure-as-Code Export

Export current infrastructure state as reproducible code.

### Server
- `GET /api/export/ansible` — Generate Ansible playbook from agent data (installed packages, services, configs)
- `GET /api/export/docker-compose` — Generate compose file from running containers
- `GET /api/export/shell` — Generate shell script that recreates the current setup

### How it works
- Query each agent for: `list_services`, `container_list`, tracked config baselines
- Template the results into Ansible YAML / Docker Compose / shell scripts
- Return as downloadable files

### Frontend (Infrastructure page)
- "Export" tab with format selector (Ansible/Docker Compose/Shell)
- Agent/scope selector (single agent or all)
- Preview pane showing generated code
- Download button

### Files
- Create: `share/noba-web/server/iac_export.py`
- Modify: `routers/system.py`, `index.html`, `system-actions.js`

---

## Feature 3: Security Posture Scoring

Scan your network for vulnerabilities and score your security.

### Agent command: `security_scan`
- Check for: open ports with no auth, default credentials (known ports), outdated packages, weak SSH configs
- Read `/etc/ssh/sshd_config` for: PermitRootLogin, PasswordAuthentication, key-only
- Check firewall status (iptables/nftables/ufw)
- Check for unattended-upgrades / auto-update
- Returns: `{score, findings: [{severity, category, description, remediation}]}`

### Server
- `security_findings` table: agent, category, severity, description, remediation, found_at, resolved_at
- Aggregate score across all agents (0-100)
- API: `GET /api/security/score`, `GET /api/security/findings`, `POST /api/security/scan/{hostname}`

### Frontend (new Security page in sidebar)
- Overall score gauge (0-100, color-coded)
- Per-agent scores
- Findings table with severity, description, remediation steps
- "Scan Now" button
- Historical score chart

### Files
- Modify: `agent.py`, `agent_config.py`
- Create: `share/noba-web/server/db/security.py`
- Modify: `db/core.py`, `routers/system.py`, `index.html`, `app.js`, `system-actions.js`, `style.css`

---

## Feature 4: Backup Verification

Actually test that backups work by restoring and checking integrity.

### How it works
- Agent command: `verify_backup` — takes a backup path + verification type
- Verification types:
  - `checksum`: Compare file checksums against a manifest
  - `restore_test`: Extract to temp dir, verify key files exist
  - `db_integrity`: Run `sqlite3 db PRAGMA integrity_check` or `pg_restore --list`
- Track 3-2-1 status: 3 copies, 2 media types, 1 offsite

### Server
- `backup_verifications` table: backup_path, agent, verification_type, status, details, verified_at
- 3-2-1 tracker: which backups exist where, how fresh they are
- API: CRUD + verify trigger + 3-2-1 status

### Frontend (Settings > Backup page enhancement)
- 3-2-1 status dashboard (visual: 3 copies ✓, 2 media ✓, 1 offsite ✓)
- Verification history table
- "Verify Now" button per backup
- Freshness indicators (green < 24h, yellow < 7d, red > 7d)

### Files
- Modify: `agent.py`, `agent_config.py`
- Create: `share/noba-web/server/db/backup_verify.py`
- Modify: `db/core.py`, `routers/system.py` (or `admin.py`), `index.html`, `system-actions.js`

---

## Feature 5: Collaborative Incident War Room

Multi-user incident response with chat, assignment, and shared timeline.

### Server
- Extend `status_incidents` with: `assigned_to`, `severity_level`, `tags`
- New `incident_messages` table: incident_id, author, message, timestamp, type (comment/action/system)
- When alert-triggered actions run, auto-post to incident thread
- API: `POST /api/incidents/{id}/messages`, `PUT /api/incidents/{id}/assign`, `GET /api/incidents/{id}/messages`

### Frontend (Monitoring > Incidents tab enhancement)
- Click incident → opens war room view
- Chat-style message thread with timestamps and authors
- "Assign to" dropdown (list of users)
- Action log (automated actions appear as system messages)
- Runbook integration: "Run playbook" button in incident context

### Files
- Modify: `db/status_page.py`, `db/core.py`, `routers/system.py`
- Modify: `index.html`, `system-actions.js`, `app.js`, `style.css`

---

## Feature 6: Network Traffic Analysis

Real-time bandwidth monitoring per device/service.

### Agent command: `network_stats`
- Read `/proc/net/dev` for per-interface byte counters
- Parse `ss -tnp` for per-process connection info
- Returns: `{interfaces: [{name, rx_bytes, tx_bytes, rx_rate, tx_rate}], connections: [{pid, process, local, remote, state}]}`

### Server
- Store as metrics for trending: `net_if_{hostname}_{interface}_{rx|tx}`
- API: `GET /api/agents/{hostname}/network-stats`

### Frontend (Infrastructure > Network tab enhancement)
- Per-interface bandwidth chart (live updating)
- Top talkers list (which processes use most bandwidth)
- Connection table with filtering

### Files
- Modify: `agent.py`, `agent_config.py`
- Modify: `routers/system.py`, `index.html`, `system-actions.js`

---

## Feature 7: Infrastructure Health Score

Gamified infrastructure health with actionable recommendations.

### Scoring criteria (each 0-10, total 0-100)
1. **Backup freshness** — All critical data backed up within 24h
2. **Certificate health** — No certs expiring within 30 days
3. **Update status** — No critical security updates pending
4. **Monitoring coverage** — All hosts have agents, all services monitored
5. **Security posture** — From Feature 3's security scan
6. **Uptime** — 30-day SLA average
7. **Redundancy** — Services with failover configured
8. **Alert response** — Mean time to acknowledge/resolve
9. **Documentation** — Service dependencies mapped, runbooks defined
10. **Capacity** — No disk/CPU/RAM at >85%

### Server
- `GET /api/health-score` — compute and return score with breakdown
- Cache score for 5 minutes

### Frontend (Dashboard card + dedicated page)
- Health score gauge in dashboard (big number, color ring)
- Click → detailed breakdown with per-category scores
- Recommendations: "Add backup for host-b", "Renew cert for example.com"
- Historical score trend chart

### Files
- Create: `share/noba-web/server/health_score.py`
- Modify: `routers/system.py`, `index.html`, `app.js`, `system-actions.js`, `style.css`

---

## Feature 8: Webhook Receiver

Accept incoming webhooks to trigger automations.

### Server
- `POST /api/webhooks/{hook_id}` — receive webhook, validate HMAC signature, trigger linked automation
- `webhook_endpoints` table: id, name, secret, automation_id, enabled, last_triggered
- Auto-generate unique URLs with HMAC secrets
- API: CRUD for webhook endpoints

### Use cases
- GitHub push → deploy via agent command
- Docker Hub → pull new image on agent
- UptimeRobot → trigger incident
- Custom CI/CD → run deployment playbook

### Frontend (Automations page enhancement)
- "Webhook Triggers" section showing configured endpoints
- Create webhook: name, linked automation, copy URL + secret
- Trigger history log

### Files
- Create: `share/noba-web/server/db/webhooks.py`
- Modify: `db/core.py`, `routers/system.py`, `index.html`, `system-actions.js`

---

## Feature 9: Mobile PWA Enhancements

Make the PWA a first-class mobile experience.

### Changes
- **Compact mobile views** — Simplified card rendering for small screens
- **Quick actions widget** — Swipe-up panel with: restart service, run command, acknowledge alert
- **Offline dashboard** — Cache last known state in service worker, show stale data with "offline" badge
- **Touch gestures** — Pull-to-refresh, swipe between pages
- **App-like navigation** — Bottom sheet modals instead of full-page modals on mobile

### Files
- Modify: `style.css` (mobile-specific styles), `app.js` (offline state), `service-worker.js` (offline caching), `index.html` (mobile-optimized layouts)

---

## Feature 10: Plugin System

Formalize the plugin architecture for community contributions.

### How it works
- Plugins are Python files in `~/.config/noba/plugins/`
- Each plugin exports: `name`, `version`, `register(app, db)` function
- Plugins can:
  - Add API routes (`app.include_router(...)`)
  - Add dashboard cards (register HTML template)
  - Add automation types
  - Add metric collectors
- Plugin manager already exists — formalize the interface

### Server
- `GET /api/plugins` — list installed plugins with status
- `POST /api/plugins/{name}/enable` / `disable`
- Plugin manifest format (YAML): name, version, author, description, requires

### Frontend (Settings > Plugins page)
- Installed plugins list with enable/disable toggles
- Plugin details: name, version, author, description
- "Reload Plugins" button

### Files
- Modify: `share/noba-web/server/plugins.py` (formalize interface)
- Modify: `routers/system.py`, `index.html`, `app.js`, `system-actions.js`

---

## Execution Waves

### Wave 1 (parallel, high impact)
1. Network auto-discovery & topology
2. Security posture scoring
3. Infrastructure health score
4. Webhook receiver

### Wave 2 (parallel)
5. Infrastructure-as-Code export
6. Backup verification
7. Network traffic analysis

### Wave 3 (parallel)
8. Collaborative incident war room
9. Mobile PWA enhancements
10. Plugin system

---

## Constraints
- Zero new Python dependencies (use stdlib + existing httpx/psutil)
- Agent stays single file with zero external deps
- All existing 622 tests must pass
- All 6 themes must work
- Sidebar navigation preserved
- Mobile responsive
