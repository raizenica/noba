# Changelog

All notable changes to NOBA Command Center are documented in this file.

## [Unreleased]

### Fixed (second honesty-gap sweep — after targeted re-audit)
- **Webhook signing actually works now** — the outgoing-webhook automation builder was previously unreachable end-to-end: the `AutomationFormModal` only collected `url`, so `_build_auto_webhook_process` was always called with `{"url": ...}` and `config.get("secret")` returned an empty string, making the HMAC path dead code. The form now exposes **HTTP method**, **request body**, **extra headers**, and an **HMAC-SHA256 signing secret**; the builder wires them through to `_do_http_request(..., signing_secret=...)` which computes `X-Noba-Signature: sha256=HMAC(secret, body)` per call. Added 5 tests (`test_workflow_engine.py`) that exercise the signing path end-to-end with a mocked `httpx.request` — including byte-level HMAC verification against a hand-computed expected signature.
- **Pi-hole v6 toggle fix** — `/api/pihole/toggle` in `routers/integrations.py` was reusing the static `piholeToken` config field as the SID, which Pi-hole v6 rejects (v6 requires a fresh session via `POST /api/auth {"password": ...}` per call). Added `_pihole_get_sid(base, password)` helper; the toggle endpoint now fetches a new SID per call and falls back cleanly to the v5 `/admin/api.php` path when no password is configured.
- **WebSocket CSWSH protection** — `routers/agent_rdp.py` (remote desktop) and `routers/agent_terminal.py` (PTY) had no WebSocket Origin header check, meaning a cross-origin attacker page could hijack a one-shot token stolen via any other vector to open a live WS session against a NOBA instance. Added `check_ws_origin(origin, request_host)` helper in `deps.py` and wired it as the first line of defence in both endpoints (runs BEFORE token consume). Empty Origin → reject. Allowed origins: `NOBA_CORS_ORIGINS` allowlist or same-host. Added `tests/test_ws_origin.py` with 10 tests covering empty origin, same-origin, allowlist match, malformed origin, case-insensitive hostname, and port-in-host-header edge cases.
- **IaC export info-disclosure tightening** — `/api/export/ansible`, `/api/export/docker-compose`, `/api/export/shell` GET endpoints raised from viewer (`_get_auth`) to operator (`_require_operator`). A rendered Ansible playbook, docker-compose file, or shell provisioning script reveals the full infrastructure topology (hostnames, services, ports, paths, container images, volumes, env files) — info-disclosure risk that viewer accounts should not have. The POST counterparts (which can also trigger fresh discovery) were already operator-only. Tests updated.
- **Remote agent uninstall (new endpoint)** — ported `POST /api/agents/{hostname}/remote-uninstall` from enterprise's `routers/agent_deploy.py`. Admin-only; SSHs into a target host with password or key auth, stops + disables + removes the `noba-agent.service` systemd unit and `/opt/noba-agent` tree, then cleans the in-memory agent registry and DB row so the removed host doesn't reappear on the next collector cycle. Falls back to `sshpass` when a password is provided. Strict hostname + username regex validation; 30-second SSH timeout.
- **agents.py auto-update zipfile cleanup** — combined the nested `with zipfile.ZipFile() as zf: with zf.open() as f:` pair into a single with-statement for cleaner resource release on any exit path. The bare `except: pass` on auto-update enqueue failure now logs at debug level so operators can notice persistent failures.

### Fixed (CF-9 + full honesty-gap sweep — follow-up)
- **CF-9 per-category httpx pool sharding** — `integrations/base.py` now provisions one `httpx.Client` per integration category (monitoring, nas, hypervisor, media_server, dns, identity_auth, …), sized by expected fan-out, replacing the single shared `_client` pool that could be starved by one slow target. `get_category_client(category)` + `get_instance_semaphore(category, instance_id)` expose the per-category pools and a per-(category, instance) concurrency cap (default 4) for dispatch-level bulkheading. Every collector in `integrations/pihole.py`, `integrations/hass.py`, `integrations/n8n.py`, `integrations/proxmox.py`, `integrations/truenas_ws.py`, `integrations/simple_*.py` now routes through the right category pool; `_http_get` accepts a `category=` kwarg so uncategorised callers keep working against the legacy default pool.
- **Honesty contract in health_score.py** — `_calc_uptime_score`, `_calc_latency_score`, `_calc_error_rate_score`, `_calc_headroom_score` return `None` on unknown / failed data instead of a fake 100/100. `compute_service_health_scores` now computes composites from the subset of known components (weights renormalised), emits `status: "unknown"` for monitors with zero knowable data, and returns `overall: None` + `grade: "N/A"` + `unknown_count` when no real scores exist — empty installs no longer inherit an undeserved A.
- **DB layer honesty** — `db.get_endpoint_uptime` now returns `None` on zero history (was returning a fake 100). `db.get_sla` now returns `None` on zero-window or DB failure (was also returning a fake 100). Downstream callers filter None out of aggregate computations instead of averaging it as a perfect score.
- **CF-10 NAS full sweep** — 22 of 40 NAS registry cells were fictional per Phase B research. All Synology `/webapi/SYNO.*` cells (8) marked unsupported with `no-public-api` reason (the SYNO namespaces are internal/undocumented). All QNAP `/cgi-bin/*` cells (8) marked unsupported with `internal-cgi-undocumented` reason. OMV `FileSystemMgmt.repair` / `.scrub`, `ReplicationMgmt`, `SnapMgmt` services marked unsupported (verified absent from OMV 7 source). OMV `QuotaMgmt.enforceQuota` corrected to the real `Quota.set` method. TrueNAS REST `/api/v2.0/pool/id/…/repair`, `/zfs/snapshot`, rollback, and `/service/restart` endpoints (all frozen/removed in TrueNAS 25.10 Goldeye) rewritten to exec-backed `zpool`, `midclt`, and native service commands. Unraid `quotaon -a` marked unsupported (Unraid user-share layer has no per-user quota API).
- **Healing watchdog honest state** — `routers/healing.py` `/api/healing/health` no longer returns `{"degraded": false}` when the watchdog isn't initialised — returns `{"degraded": null, "status": "unknown", "reason": "watchdog not initialised"}` so the frontend can render a third state instead of falsely claiming "all good".
- **operations.py OWASP sanitization** — 3 more `str(e)` error leaks sanitized in `_recovery_tailscale`, `_recovery_dns_flush`, `_recovery_service_restart` — raw exceptions now go to `logger.error`, API responses return generic `"Operation failed"`.
- **Silent-failure logging** — `auth.py` PBKDF2 iteration upgrade + legacy-hash migration now log warnings on failure (was silent `pass` — operators couldn't tell upgrades were failing). `collector.py` managed-instance auth_config JSON parse failure now logs a warning. `routers/infrastructure.py` per-node Proxmox VM fetch failures now log debug lines instead of a bare `pass`.
- **proxmox.py honest error reporting** — `integrations/proxmox.py` per-VM and node-list failures now log at debug level and set `result["error"]` to a sanitized "Connection failed" string instead of silently passing, matching the rest of the integrations layer.

### Fixed (enterprise research back-port)
- **Pi-hole v6 parsing** — `integrations/pihole.py` now reads `queries.blocked` / `queries.percent_blocked` and derives status from `gravity.domains_being_blocked` instead of the v5-only `ads.*` / `gravity.status` fields that returned zeros on real v6 instances.
- **InfluxDB v3 support (CF-6, deadline 2026-05-27)** — `query_influxdb` now sniffs query language, dispatches Flux to `/api/v2/query` with `Token` auth, and SQL/InfluxQL to `/api/v3/query_sql` with `Bearer` auth. Retries to v3 on 404/501 and returns a clear migration error when Flux hits a v3 instance. Prevents silent breakage when Docker `influxdb:latest` flips to v3.
- **Silent health-score failures** — `healing/health_triggers.py` no longer treats categories with missing/unknown scores as a perfect 10/10, which was hiding broken collectors from the healing pipeline.
- **Pre-action snapshots** — `healing/snapshots.py` now captures real docker/systemd/disk/resolv.conf state pre-heal instead of returning an empty dict (rollback was a no-op).
- **Live chaos mode** — `healing/chaos.py` now executes the configured injection, waits `settle_seconds`, evaluates expectations against the heal ledger, and runs teardown. Was a `"live_not_implemented"` placeholder.
- **Real backup trigger** — `_handle_trigger_backup` now looks up a user-defined backup automation or falls back to `SCRIPT_DIR/backup-to-nas.sh` instead of echoing a debug string.
- **DNS failover via sudo tee** — `_handle_failover_dns` writes through `sudo -n tee /etc/resolv.conf` with graceful FileNotFoundError / permission handling.
- **fail-closed crypto** — `crypto.encrypt_value` now raises `RuntimeError` when the `cryptography` package is missing instead of silently returning cleartext; `decrypt_value` raises `ValueError` on decrypt failure instead of leaking the ciphertext.
- **Container name DoS guard** — `routers/containers.py` regexes now cap names at 253 chars (`[a-zA-Z0-9_.-]{0,252}`) to match docker/podman limits and prevent oversized-name abuse.
- **REST verb correctness** — `PUT /api/status/incidents/{id}/resolve` replaces the prior `POST` (state transition is idempotent per RFC 9110).
- **OWASP error sanitization** — 58 `str(e)` leaks removed from `integrations/simple_*.py`, `integrations/pihole.py` v6 retry path, `remediation.py` handlers, and collector paths; raw errors stay in server logs, sanitized messages go to clients.
- **Yaml settings cache invalidation** — `_bust_settings_cache` now resets `_settings_cache_t` too; stale `proxmoxVerifySsl: True` default added.
- **Honesty contract in health_score** — categories that can't be evaluated (exceptions or empty datasets) now report `status: "unknown"` / `score: None` and are excluded from the normalized denominator; empty installs no longer inherit an undeserved A grade. Test suite rewritten to encode this contract (25 tests).
- **history prune configurable** — `db/metrics.prune_history` accepts an optional `days` override for tooling that needs shorter retention windows.
- **Webhook signing helper** — `workflow_engine._sign_request_headers` extracted so any outbound HTTP via `_do_http_request` can pass a `signing_secret` kwarg and get HMAC-SHA256 coverage.

### Fixed (integration_registry corrections — Phase B research)
- **CF-1/CF-14 git_devops** — Gitea/Forgejo fictional `/git/gc`, `/actions/queue`, `/actions/caches` endpoints replaced with `gitea admin run gc` / `forgejo admin run gc` exec paths. GitLab `/runners/queue` and `/runners/cache` fictional DELETE endpoints replaced with `gitlab-runner cache-cleanup` exec.
- **CF-2 container_rollback_image** — Kubernetes `/apps/v1/.../rollback` (removed in k8s PR #70039, dead since 1.16) replaced with `kubectl rollout undo`.
- **CF-3/CF-4/CF-12/CF-13 identity_auth** — All 5 Authelia admin REST entries (the project has no admin REST API) rewritten to `docker exec authelia authelia storage …` CLI. Authentik endpoints updated for 2026.5 removals (`/core/tokens/expire_tokens/` → iterate+delete, `/sources/ldap/{slug}/sync/` → GET status-only). Keycloak `ldap-server-capabilities` + `revoke-refresh-token` replaced with documented alternatives (`PUT components`, `PUT realm notBefore`).
- **CF-5 mail** — Mailcow `/edit/rspamd/flush_storage` + `/edit/doveadm/reindex` (verified absent from canonical OpenAPI) replaced with `docker exec rspamd-mailcow rspamadm control fuzzy_storage` / `docker exec dovecot-mailcow doveadm index -A '*'`.
- **CF-7/CF-15 media_management** — Servarr `/queue/failed/{id}` (never existed) replaced with `/queue/grab/{id}` (verified in `QueueActionController.cs`). Prowlarr removed from `servarr_queue_clear` / `servarr_failed_retry` (`supports_queue=False`) and its fictional `/api/v1/cache` entry replaced with `/api/v1/command`.
- **CF-10 nas** — `nas_cache_clear` truenas/synology/qnap fictional REST cache-flush endpoints replaced with `echo 3 > /proc/sys/vm/drop_caches` (ZFS ARC has no user-flush API). Banner comment flags remaining NAS entries as UNVERIFIED per Phase B finding (~22 of 40 cells fictional).
- **CF-11 document_wiki** — Paperless `manage.py clearcache` (doesn't exist), Nextcloud `db:optimize` (doesn't exist), BookStack `bookstack:regenerate-thumbnails` (doesn't exist), and Wiki.js `node wiki --clear-cache/--regen-thumbnails/--optimize-storage` flags (don't exist) corrected. Wiki.js thumb regen and storage optimize marked `unsupported` with reason.
- **CF-16 dns_service_restart** — AdGuard `/control/restart` (fictional) replaced with `systemctl restart AdGuardHome`.
- **CF-17 database** — Fictional InfluxDB v2 CLI commands `influx admin compact`, `influx admin rebuild-index`, `influx query kill {id}` marked `unsupported` with reason (Enterprise-only or not implemented).

### Security
- **PBKDF2 600k iterations** — Upgraded from 200,000 to 600,000 iterations (OWASP minimum for PBKDF2-HMAC-SHA256). Hash format now includes iteration count (`pbkdf2:{iters}:{salt}:{hash}`). Backward-compatible with legacy 3-part hashes (200k assumed). Auto-upgrades password hash on successful login.
- **TOTP fail-fast** — `generate_totp_secret` now raises RuntimeError when pyotp is missing instead of silently returning a weak fallback.
- **OWASP security headers** — X-Frame-Options DENY, HSTS (2-year), COOP, COEP, CORP, CSP `frame-ancestors 'none'`, X-XSS-Protection disabled (modern approach), stricter Referrer-Policy.
- **Exception chain suppression** — `from None` on 40+ HTTPException raises across all routers prevents stack trace leakage in error responses.
- **Error message sanitization** — Exception details logged server-side, generic messages returned to clients across integrations, infrastructure, intelligence, containers, operations, dashboards, collector, remediation, runner, and plugins.
- **Hostname validation** — Regex validation on WebSocket connect and agent report endpoint prevents injection via malformed hostnames.
- **Global error handlers** — Custom 500/422 exception handlers log details server-side, return generic messages to prevent information disclosure.
- **Agent deploy hostname validation** — Regex validation on deploy target hostname.
- **AiChatPanel XSS protection** — DOMPurify sanitization on AI chat output (whitelist: pre, code, strong, br tags only).
- **Dockerfile non-root user** — Container now runs as `noba` user instead of root.
- **Shell temp file security** — `mktemp` + trap pattern replaces predictable `.tmp` suffix in noba-lib.sh.

### Fixed
- **Agent deploy localhost detection** — Rejects localhost/127.0.0.1/::1 with clear error message in both install-script and SSH deploy endpoints. Falls back to configured serverUrl.
- **Agent deploy preflight checks** — Python3 availability, sudo access, and existing agent cleanup verified before SSH deployment. Alpine Linux (apk) support added.
- **Agent deploy SSH config** — `-F /dev/null` avoids broken distro ssh_config issues (Fedora/Nobara + OpenSSH 10).
- **Agent deploy verify_ssl** — Auto-disabled for IP-based server URLs where domain certs can't match.
- **Agent deploy connectivity check** — Post-deploy curl check warns if the remote agent can't reach the server.
- **5 frontend API path mismatches** — topology→dependencies, site-sync→sites/sync-status, /api/users→/api/admin/users, test-notifications→notifications/test, run-script→run.
- **HealthScoreGauge missing initialization** — Component now fetches health score data on mount.
- **DashboardToolbar missing initialization** — Component now fetches dashboard list on mount.
- **RemoteDesktopView JSON.parse crash** — WebSocket message handler now guards against malformed/binary frames.
- **SystemLogTab nextTick shim** — Replaced setTimeout(0) shim with native Vue nextTick.
- **HealingApprovalTab timestamp field** — Corrected `requested_at` → `created_at` to match backend.
- **STREAM_BUFFER_MAX_LINES sign fix** — Changed from -2000 to 2000 (buffer was unbounded due to double negation in slice).
- **Service worker error suppression** — Registration failure no longer throws unhandled error in unsupported environments.
- **DNS failover implementation** — `_handle_failover_dns` now actually modifies /etc/resolv.conf instead of just logging.
- **Webhook HMAC-SHA256 signing** — Outbound webhooks with configured secrets now include `X-Noba-Signature` header.
- **healing/agent_verify key typo** — `"type"` → `"command"` in agent command dict.
- **Shutdown ordering** — Shutdown flag set first to prevent port-bind failures on restart.
- **noba-lib.sh PBKDF2 sync** — Shell password hashing synced to 600k iterations and 4-part format.
- **noba-tui.sh quoting** — `$DIALOG` variable quoted throughout to prevent word splitting.
- **install.sh hardening** — Sudo detection, python-multipart+lxml deps, --break-system-packages fallback for Python 3.11+.

### Improved
- **App.vue theme persistence** — Theme saved to localStorage with fallback chain for nested preferences structure.
- **Dashboard masonry MutationObserver** — New cards added by SSE are automatically observed for masonry layout.
- **WelcomeSetup UX** — Completed steps now show "Edit" button and remain clickable.
- **DeployModal URL validation** — Warns on localhost, HTTP, short hostnames, and IP-based HTTPS URLs.
- **Frontend code cleanup** — Removed unused imports/refs across 10+ components.
- **Dockerfile Python 3.14** — Updated base image from 3.13-slim to 3.14-slim.

### Fixed
- **RDP keyboard on Wayland/Mutter** — `NotifyKeyboardKeycode` expects Linux evdev keycodes, not X11 hardware keycodes. The `_JS_CODE_TO_X11` table in `rdp.py` correctly maps W3C `e.code` → X11, but `rdp_session.py` was passing those values directly to Mutter. Fixed by subtracting 8 before the D-Bus call (`kc = max(0, int(ev.get("keycode", 0)) - 8)`). Previously, pressing 'A' (X11=38) was interpreted as evdev 38 = `KEY_L`; pressing any key sent evdev 65 = `KEY_F7`, opening LibreOffice's spell checker. Confirmed via live AZERTY layout test on a Belgian-layout host (Q→a, A→q, W→z, Z→w all correct). Agent bumped to v3.0.1 to trigger auto-update.
- **Dashboard masonry grid stability** — Cards no longer jump or reorder during live SSE telemetry updates. Root causes fixed: (1) `watch(activeInstances)` was firing on every SSE data tick because `Array.filter()` always returns a new reference — replaced with a stable string key `map(i=>i.id).join(',')`. (2) ResizeObserver was writing `gridRowEnd` on every call regardless of whether the value changed, triggering a layout→observer cascade — added a change guard. (3) `HardwareCard` GPU Temp row used `v-if` tied to a `computed` that toggled on/off when `nvidia-smi` transiently returns N/A, causing ~40px height oscillations — replaced with a "once seen, never hide" `ref` pattern.
- **Dashboard save/load card order** — Saving a layout now correctly captures the live drag order from the SortableJS instance (`_sortable.toArray()`) rather than stale store state. Loading a dashboard now correctly reorders the DOM via `applyCardOrder()` and persists across page refreshes: `cardOrder` is now stored inside `preferences.preferences` (the inner object sent to and returned by the server), not at the outer preferences level where the server ignored it. Late-arriving managed instance cards (SSE-driven) are re-sorted by the `activeInstances` watcher so they land in their saved position even if they mount after `initSortable` runs.

### Added
- Plugin workflow nodes: plugins can declare `WORKFLOW_NODE` + `workflow_node_run` to contribute action nodes to the workflow builder palette
- `GET /api/workflow-nodes` endpoint returns built-in + plugin node descriptors
- `PluginNodeConfig` component renders dynamic field forms from plugin node schemas
- `mqtt_listener` bundled plugin now includes an MQTT Publish workflow node as a reference example

### Security
- **GitHub Actions least-privilege permissions** — All CI jobs in `test.yml` now declare `permissions: contents: read`; `update-repo.yml` declares `contents: write` (the minimum needed to push gh-pages). Eliminates broad default GITHUB_TOKEN scope on every workflow run.
- **TLS 1.2 minimum enforced** — Four SSL contexts in `noba-agent/websocket.py`, `noba-agent/commands.py`, `server/scheduler.py`, and `server/metrics/network.py` now explicitly set `ctx.minimum_version = ssl.TLSVersion.TLSv1_2`, removing any platform-dependent TLS 1.0/1.1 fallback.
- **picomatch 4.0.4** — Updated transitive dependency picomatch from 4.0.3 to 4.0.4 in frontend lock file, fixing CVE method injection via POSIX bracket expressions (CWE-1321) that could cause incorrect glob matching in security-relevant filtering logic.

### Added
- **`handle_errors` decorator** — New `@handle_errors` decorator in `server/deps.py` centralizes unhandled-exception handling across all HTTP route handlers. Applied to ~300 routes across all 17 routers; returns HTTP 500 with the exception message and logs the full traceback. WebSocket and SSE routes are excluded (decorator is not applied to them). Eliminates hundreds of lines of repetitive try/except boilerplate.
- **db/core.py mixin split** — The 1,681-line `db/core.py` monolith is replaced by 22 co-located domain modules (`db/metrics.py`, `db/audit.py`, `db/healing.py`, etc.), each exposing an `init_schema(conn)` function and a `_XxxMixin` class. `db/core.py` is now a 177-line coordinator: imports all modules, runs `_run_alter_migrations`, and assembles `Database` from `DatabaseBase` + 21 mixins via multiple inheritance.
- **integrations/simple.py category split** — The 2,800-line `integrations/simple.py` is split into 6 focused category files: `simple_media.py`, `simple_network.py`, `simple_infra.py`, `simple_monitoring.py`, `simple_iot.py`, `simple_comms.py`. `simple.py` is now a 47-line re-exporter for backward compatibility.
- **IntegrationsTab.vue decomposition** — The 1,532-line `IntegrationsTab.vue` is decomposed into 5 focused sub-components under `components/settings/integrations/`: `IntegrationCategoryList.vue`, `IntegrationInstanceCard.vue`, `IntegrationSearchFilter.vue`, `IntegrationEmptyState.vue`, `IntegrationSettingsPanel.vue`. Coordinator reduced to 161 lines.
- **AutomationListTab.vue decomposition** — The 967-line `AutomationListTab.vue` is decomposed into 5 sub-components: `AutomationStatusBadge.vue`, `AutomationRunHistory.vue`, `AutomationRow.vue`, `AutomationWebhooks.vue`, `AutomationTraceModal.vue`. Coordinator reduced to 256 lines.
- **WorkflowBuilder.vue decomposition** — The 784-line `WorkflowBuilder.vue` is decomposed into 3 sub-components under `workflow/`: `WorkflowNodePalette.vue`, `WorkflowNodeConfig.vue`, `WorkflowRawEditor.vue`. Coordinator reduced to 239 lines. Existing `WorkflowNode.vue` is unchanged.
- **Agent v3.0.0 zipapp package** — The 4,949-line `agent.py` monolith is replaced by a Python zipapp package (`agent.pyz`). The source is split into 9 co-located modules in `share/noba-agent/`: `__main__.py` (entry point, VERSION, main loop, WebSocket thread), `utils.py` (platform detection, path safety, subprocess helper), `metrics.py` (system metrics collection, psutil + /proc fallbacks), `websocket.py` (RFC 6455 WebSocket client), `commands.py` (all command handlers), `rdp.py` (Mutter D-Bus screen capture and input injection), `rdp_session.py` (GStreamer/PipeWire subprocess script), `terminal.py` (PTY session management), `healing.py` (autonomous heal runtime). Built by `scripts/build-agent.sh` into `share/noba-agent.pyz`. Server auto-update now reads the version from the zipapp via `zipfile` inspection instead of reading `agent.py` line-by-line.

- **Headless GNOME Wayland screen capture** (agent v2.4.16) — New `_capture_screen_pipewire()` method enables RDP screen capture on fully headless GNOME Wayland systems (no physical displays, no `wl_output`). Uses Mutter's `RemoteDesktop` + `ScreenCast` D-Bus APIs to create a virtual screencast session, then links pipewiresrc via WirePlumber's `node.target` stream-property (bypassing the crashing `findDefaultLinkable` path). Captures a 1280×720 RGB frame via GStreamer appsink and encodes it as PNG. Root agent drops to display-owner uid/gid for the subprocess.
- **Remote Desktop sortable host groups** — The Remote page now supports customizable tabs to group and sort hosts. Users can add named groups (+ button), rename by double-click, delete with ×, and drag rows to reorder within any tab. Custom group membership (+ Add / − Remove buttons) and sort order persist in `localStorage`. The built-in "All" tab always shows all agents with its own drag-reorderable order.

- **Architectural Decision Records** — 7 ADRs added under `docs/adr/` documenting key design decisions: SQLite dual-connection pattern, WebSocket handshake tokens, agent zipapp distribution, SSE telemetry, RDP frame fan-out, risk-tiered commands, and the `@handle_errors` decorator. `CLAUDE.md` updated with direct links to the most commonly referenced ADRs.

### Fixed
- **RDP clipboard broadcast leak** — `rdp_clipboard` responses are now routed only to the viewer that issued `rdp_clipboard_get`, not broadcast to all connected viewers. Server injects a `_req_id` into the forwarded request; agent echoes it back; server pops the registered queue and routes exclusively to the requesting subscriber.
- **Windows/macOS RDP keyboard regression** — `onKeyDown`/`onKeyUp` now include `keycode: e.keyCode` alongside `code` and `key`. The agent's Windows and macOS input injectors read `event['keycode']` which was defaulting to 0 after the prior keyboard refactor.
- **Windows clipboard crash** — `_rdp_clipboard_env()` (which imports the Unix-only `pwd` module) is now called only inside `if _PLATFORM == "linux":` in both `_rdp_clipboard_get` and `_rdp_clipboard_paste`, preventing a crash on Windows/macOS before the platform branch was reached.
- **PowerShell clipboard injection** — `Set-Clipboard` now reads text from stdin (`[Console]::In.ReadToEnd() | Set-Clipboard`) instead of interpolating `repr(text)` into the command string, eliminating injection risk via specially crafted clipboard content.

### Security
- **shlex.quote() in agent deploy script** — `server_url` and `agent_key` are now wrapped with `shlex.quote()` before interpolation into the remote bash install script, preventing shell metacharacter injection.
- **SSRF IP blocklist in `BaseIntegration.validate_url()`** — Integration URLs pointing to private (RFC 1918), loopback, or link-local addresses are now rejected at configuration time using the `ipaddress` module.
- **Short-lived WebSocket handshake tokens (`POST /api/ws-token`)** — New endpoint issues 30-second one-time tokens for WebSocket connections. All three WS endpoints (`/api/terminal`, `/api/agents/{host}/terminal`, `/api/agents/{host}/rdp`) now consume (validate + invalidate atomically) these tokens instead of long-lived session tokens, reducing session token exposure in server/proxy access logs.
- **Uniform login error messages** — The login handler now returns `"Invalid credentials"` unconditionally for all 401 failures, preventing username enumeration via differentiated rate-limit vs. wrong-password messages.
- **Complete RFC 4515 LDAP filter escaping** — `_ldap_escape()` now escapes all RFC 4515 special characters (`& | = ~ !` added alongside the existing `\ * ( ) \x00`). Constant moved to module level.
- **Path separator check in backup restore** — Forbidden-path check uses `os.sep` suffix to prevent `/etc2` from incorrectly matching `/etc`. Extracted into testable `_check_restore_path()` helper; error message no longer reveals which protected path was matched.

### Fixed
- **RDP Wayland input injection** — Mouse and keyboard input from the RDP viewer now works on GNOME Wayland via a persistent Mutter `RemoteDesktop` D-Bus session. A long-lived subprocess holds the `RemoteDesktop`+`ScreenCast` session and routes `NotifyPointerMotionAbsolute`, `NotifyPointerButton`, `NotifyPointerAxisDiscrete`, and `NotifyKeyboardKeycode` calls via D-Bus (GNOME 46 API). Linux kernel BTN codes (272/273/274) used for mouse buttons. The old XTest (libXtst) path is used as fallback on X11 only. Agent v2.4.26.
- **RDP mouse coordinate denormalization** — `NotifyPointerMotionAbsolute` expects pixel coordinates but the frontend sends normalized 0–1 values. The subprocess now multiplies by stream width/height (updated on every captured frame) before the D-Bus call. Agent v2.4.26.
- **RDP performance improvements** — Default FPS raised from 5→10. D-Bus call timeout reduced from 500→100ms to unblock the capture loop faster on transient failures. Mousemove coalescing in the subprocess command loop drains stale queued events and keeps only the latest, preventing D-Bus call accumulation under load. Agent v2.4.27.
- **RDP JPEG encoding via Pillow** — Frame encoding path replaced from pure-Python PNG to Pillow JPEG when available (~15× faster encode, ~80% smaller frames). The subprocess now sends raw RGB bytes directly (NOBR protocol) instead of PNG-encoding internally, eliminating the double encode/decode cycle. Frontend sniffs magic bytes to select the correct MIME type. Falls back to pure-Python PNG on systems without Pillow. Agent v2.4.28.
- **RDP coordinate accuracy in non-fullscreen** — Canvas uses `object-fit: contain` which letterboxes content inside the CSS box; `getBoundingClientRect()` returned full box dimensions. Fixed by computing actual content bounds with aspect-ratio arithmetic, giving accurate click/move coords at any zoom level.
- **RDP stdin race condition** — Capture thread and input injection handler both wrote to the subprocess stdin pipe without synchronization, corrupting the command stream. Writes are now serialized with `_mutter_io_lock`; the lock is released before the blocking PNG read so injection is never blocked for the full capture cycle.
- **RDP session stability** — Single transient capture failure no longer terminates the RDP session. A consecutive-failure counter allows up to 8 retries before sending `rdp_unavailable`, absorbing momentary subprocess restarts.
- **RDP `inputEnabled` always false** — `ref(auth.isOperator)` captured `false` at component init since `userRole` defaults to `'viewer'` until `fetchUserInfo()` resolves async. Changed to a writable `computed` that stays reactive to the auth store.
- **CSP `font-src data:`** — The RDP viewer's font icons (data URI woff2) were blocked by the `font-src 'self'` Content Security Policy. Added `data:` to `font-src`.
- **RDP capture READY race condition** — The persistent Mutter subprocess previously signalled READY when the GStreamer pipeline entered PLAYING state, but the first frame hadn't arrived yet. READY is now deferred until `_on_sample` fires with the first real frame, eliminating the immediate NONE response on first CAPTURE.
- **Agent `struct` import missing** — `_capture_screen_pipewire()` called `struct.unpack` without importing `struct`, causing `NameError: name 'struct' is not defined` on every RDP capture attempt. Fixed by adding `import struct` alongside the existing `import select`.
- **Agent version badge on Agents page** — Agent version is now displayed as a monospace badge next to each agent's name, providing a quick visual confirmation that agents are running the expected version.
- **RDP viewer embedded in app chrome** — Remote Desktop viewer now opens as a fully standalone full-screen page (no sidebar, header, or modals) by adding `meta: { standalone: true }` to the route and conditionally skipping app chrome in `App.vue`. The viewer fills the entire new tab.
- **RDP new tab blocked by popup blocker** — `window.open()` in `RemoteView.vue` now omits the features string, causing Chrome/Firefox to open it as a new tab (never blocked) rather than a popup window.
- **`window.opener` crash in Vue template** — `window.opener` is not accessible in Vue 3 template expressions. Moved the check to `<script setup>` as `const isPopup = !!window.opener` and referenced the ref in the template. The crash was breaking the SSE connection on every render tick.

### Security
- **XXE vulnerability patched** — RSS feed scheduler now uses `defusedxml.ElementTree` instead of `xml.etree.ElementTree` to prevent XML External Entity attacks and XML bombs.

### Added
- **Pi-hole version labeling** — Pi-hole DNS settings now clearly distinguish between v5 (API Token) and v6 (App Password) with version badges and helper text. Users can immediately identify which field applies to their Pi-hole version.
- **Integration token editing** — Added edit button to managed integration instances in Settings. Users can now update API tokens, URLs, and auth config for existing integrations without deleting and recreating them. The setup wizard opens in edit mode with pre-filled fields (platform/category locked), and uses PATCH API to update only changed fields. Security: existing token values are never displayed; users must enter new values.
- **Database migration framework** (`server/db/migrations.py`) — Schema version tracking with up/down migrations, rollback capability, and auto-migration on startup. Ready for future schema evolution.
- **SSE stream testing** (`dev/smoke.py`) — SSE endpoints (`/api/stream/*`) now tested with timeout-based connection validation instead of being skipped.
- **Workflow group cancellation** — `JobRunner` now supports `cancel_group(automation_id)`, allowing the UI to terminate all active subprocesses associated with a parallel or sequential workflow run.
- **Collector health watchdog** — `BackgroundCollector` now tracks heartbeat pulses. The `/api/stats` and `/api/stream` endpoints report `collector_status: "stalled"` if background updates hang, enabling UI-level alerts.
- **556 new backend tests** — Auth router (136), automations router (137), integration drivers (178), healing modules (115), db/core (65). Total test count: 3,143.
- **21 new Vue sub-components** — Split 5 oversized views (AutomationsView, InfrastructureView, MonitoringView, LogsView, DashboardView) into focused tab components.
- **Backend constants module** (`server/constants.py`) — Centralized 16 magic numbers from routers and healing modules.
- **Frontend constants module** (`constants.js`) — Centralized 15 timing/limit values from stores and components.
- **14 CSS utility classes** — Table cell, border, spacing, and typography utilities replacing 208 inline style attributes.
- **`.dockerignore`** — Excludes `.git`, `node_modules`, `__pycache__`, `tests/`, `.venv` from Docker build context.

### Fixed
- **Services tab showing "unknown" for all services** — `ServiceList.vue` was reading `svc.active`/`svc.sub` (systemd raw fields) but the SSE collector sends `svc.status`. Fixed to use `svc.status` throughout status badge, class, and button disabled logic. Also fixed a service worker cache version bump (`noba-v4` → `noba-v5`) and deployment sync issue where the installed server served stale pre-build assets.
- **Login page layout collapsed to 220px** — App layout grid was auto-placing the unauthenticated router-view into the sidebar column. Added `'no-sidebar'` class binding on `App.vue` when unauthenticated, and an explicit `router.push('/login')` fallback in `onMounted` for fresh-load cases.
- **AI / LLM Max Tokens field blank** — Added `placeholder="4096"` to the Max Tokens input so users see the default value when their saved config doesn't include the key.
- **Proxmox snapshot and console buttons unresponsive** — Dashboard Proxmox card buttons now call correct API endpoints (`/api/proxmox/nodes/{node}/vms/{vmid}/snapshot` and `/api/proxmox/nodes/{node}/vms/{vmid}/console`). Added toast notifications for feedback and permission checks (admin for snapshots, operator for console).
- **Token persistence failures invisible** — Token DB operations (insert, delete, load, cleanup) now logged as `warning` instead of `debug`. Critical authentication failures now visible in production logs.
- **Health score computation failures silent** — Health category computations (monitoring, certificates, updates, uptime, capacity, backup) now logged as `warning` instead of `debug`. Operators can now detect degraded monitoring.
- **Integration fetch failures not logged** — Service status, ping checks, WAN/LAN health, and BMC sentinel checks now log failures with context instead of silently swallowing exceptions.
- **Agent path traversal vulnerability** — `_safe_path()` hardened with `realpath()` resolution, `normpath()` normalization, and explicit `..` detection. Defense-in-depth against symlink and traversal attacks.
- **Memory progress bar** — Core System card now correctly displays memory percentage by falling back to the `memPercent` SSE field when the `memory` object is a pre-formatted string.
- **Hardware card empty** — CPU and GPU model names were missing because `hwCpu`/`hwGpu` keys weren't declared in the dashboard store's reactive object, causing SSE data to be silently dropped.
- **Agent "Last seen: --"** — SSE agent list now includes `last_seen_s` field, matching the REST API. Online agents now show "7s ago" instead of "--".
- **GPU model `<br>` literal** — Backend no longer injects HTML `<br>` into GPU model string; frontend uses `white-space: pre-line` for multi-GPU line breaks.
- **Pi-hole unauthorized state** — Pi-hole card now shows a clean "API Key Required" badge with a settings link instead of rendering broken empty metric boxes with raw JSON errors.
- **Tailscale "localhost" names** — Devices reporting `HostName: "localhost"` (Android/TV devices) now fall back to `DNSName` for proper identification (e.g., "samsung-sm-s938b", "google-tv-streamer-1").
- **Infrastructure Services tab empty** — Collector now reads `monitoredServices` from YAML config as fallback when SSE query params don't include the service list.
- **Healing approval timestamps** — Approvals tab now correctly maps `requested_at` field from the API instead of the non-existent `ts` field. Also fixed column header "Trust" → "Trigger" and field mapping for `automation_id`.
- **Security findings deduplication** — Re-scans now replace old findings for the host instead of appending, preventing duplicated entries in the findings table.
- **HTTPException guards** — Added `except HTTPException: raise` before generic `except Exception` across all 11 routers (79 locations) to prevent swallowing HTTP errors.
- **Blocking docker commands** — Wrapped remaining sync subprocess calls in `routers/containers.py` with `asyncio.to_thread()` to avoid blocking the FastAPI event loop.

### Added
- **AI Ops Assistant chat panel** — Floating robot FAB button (bottom-right, visible when AI is enabled) opens a slide-in chat panel backed by `/api/ai/chat`. Supports full conversation history (up to 20 turns), markdown/code formatting, and action chips extracted from AI responses (`[ACTION:cmd:host:params]`). Action chips populate the input with a confirmation prompt rather than auto-executing. Panel uses pre-existing CSS (`ai-panel`, `ai-fab`, `ai-messages`, `ai-action-btn`) that was designed but never wired to a component.
- **AI / LLM Test Connection button** — Settings > Integrations > AI / LLM now shows a "Test Connection" button (when AI is enabled) that calls `/api/ai/test` and displays a success/failure message inline. Lets operators verify Ollama/Anthropic/OpenAI connectivity without leaving the settings page.

### Improved
- **Type safety** — Replaced `Any` types with proper `Database` and `threading.Lock` types in `iac_export.py` for better IDE support and type checking.
- **Version consistency** — `pyproject.toml` version synced to `2.0.0` (matches `config.py`).
- **Test code quality** — Fixed 20+ unused variable warnings across test files, updated lock type tests for `RLock`, fixed import order in `conftest.py`.
- **Dashboard integration cards** — Empty "No data available" integration cards are now collapsed into a single "N unconfigured integrations" button, drastically reducing scroll depth.
- **Log severity coloring** — System log viewer now color-codes lines: errors in red, warnings in yellow, debug dimmed — making critical issues immediately visible.
- **Healing table labels** — Effectiveness Summary table now shows human-friendly names (Total, Verified, Failed, Pending, Success Rate) instead of raw database column names.
- **Security score consistency** — Unified color thresholds across aggregate donut and per-agent badges (green ≥80, yellow ≥60, red <60).
- **Monitoring tab badges** — SLA, Incidents, and Endpoints tabs now show data count badges, indicating which tabs have content at a glance.
- **Infrastructure service map** — Service Map cards now display CPU/RAM/uptime health indicators when available from the collector.
- **Disk Health card** — Drive list is now collapsed by default with a "Show N drives" toggle, keeping the card compact while preserving detail on demand.
- **Theme renamed** — Default theme renamed from "Operator" to "Command" to avoid confusion with the authentication role of the same name.
- **Quick Links** — Renamed "Homelab Bookmarks/Links" to "Quick Links" across dashboard card, settings label, and visibility toggle to align with NOBA's production positioning.
- **Automation form validation** — Added frontend validation to the automation modal to ensure required fields (script paths, URLs, cron) are populated before submission.
- **Mobile horizontal tab bar** — Refactored navigation tabs to use a horizontally scrollable strip on small viewports, recovering vertical space and preventing button stacking.
- **Accessibility hardening** — Added `aria-label` attributes to multiple icon-only buttons, including the settings search clear and audit log pagination controls.
- **Infrastructure UI unification** — Migrated the Infrastructure view and Kubernetes browser to the `AppTabBar` component, ensuring consistent navigation and styling across all system views.
- **Modernized scaling interaction** — Replaced native browser `prompt()` with a non-blocking `AppModal` for Kubernetes deployment scaling, providing a safer and theme-consistent user experience.
- **Custom chart optimization** — Refactored the Custom Charts builder to use the `ChartWrapper` component, leveraging incremental update performance and reducing redundant code.
- **UI input standardization** — Swept the Traffic and Kubernetes tabs to replace inconsistent inline styles with global `.field-input` and `.field-select` utility classes.
- **Unified tab navigation** — Created a reusable `AppTabBar` component to standardize navigation across Logs, Monitoring, Healing, Infrastructure, and Settings views.
- **Interactive security feedback** — Added per-host scan status indicators in the Security view, providing immediate visual confirmation of dispatched scan requests.
- **Healing consistency** — Standardized trust promotion actions using the global `modals.confirm()` store and implemented actionable empty states for the healing ledger.
- **Workflow builder dirty guard** — Implemented an "unsaved changes" warning in the `WorkflowBuilder`. Users are now prompted before closing the modal if modifications were made to the graph, preventing accidental data loss.
- **Automation bulk action safety** — Standardized bulk actions (Enable, Disable, Delete) in the Automations view using the new Selection Bar pattern. Physically separates destructive actions from global navigation and filters.
- **Agent bulk action safety** — Moved bulk actions (Update, Remove) into a dedicated, visually distinct Selection Bar in the Agents view. Separates destructive actions from the "Select All" button to prevent accidental mass deletions.
- **Workflow canvas panning** — Implemented mouse-drag panning and a "Reset View" control in the `WorkflowBuilder`. Improves navigation for complex multi-node automation graphs.
- **Settings search/filter** — Added a real-time filter to the Settings view, allowing users to quickly locate specific integration or system categories among 11+ tabs.
- **Metric tooltips** — Added contextual hover hints to agent metrics (CPU, Memory, Disk) in the `AgentDetailModal`, providing immediate detail on current utilization and capacity.
- **Modal accessibility & UX** — Added global Escape key listener and body scroll locking to all modals. Prevents background scrolling and ensures consistent keyboard interaction.
- **Manual modal refresh** — Added a sync button to the `AgentDetailModal` header, allowing users to re-trigger data fetching for the active tab without re-opening the modal.
- **Enhanced command feedback** — Host output tabs in the Command Palette now display activity spinners while commands are in flight, providing clearer feedback for broadcast operations.
- **Form field standardization** — Refactored Maintenance Window forms to use global CSS classes, ensuring consistent styling and focus behavior across all management screens.
- **Reliable metrics rollups** — Refactored `rollup_to_1m` and `rollup_to_1h` to be gap-aware. Background tasks now automatically identify and fill missing historical data points after server outages or high-load delays.
...
- **Mobile header optimization** — Collapsed the search bar and status pills on mobile viewports to prevent overcrowding and ensure critical controls remain accessible.
- **Stalled collector awareness** — Added a warning banner to the header that appears if background data collection hangs, showing the time since the last successful refresh.
- **Unified confirmations** — Standardized all destructive actions (delete, wipe, bulk toggle) to use the global `modals.confirm()` store, replacing local dialog components and improving UI consistency.
- **Actionable empty states** — Refactored "No data" screens in Users and Integrations tabs to include direct call-to-action buttons for creating the first record.
- **Interactive log tailer polish** — Enhanced `LogStreamModal` with smart auto-scroll logic and a "New logs below" button that appears when scrolled up.
- **Plugin execution watchdog** — Implemented strict timeouts for plugin `collect()` and `render()` calls using `ThreadPoolExecutor`. Prevents misbehaving plugins from hanging background threads.
- **`_cleanup_transfers` resilience** — Added inner exception guards to the file transfer cleanup loop to prevent silent task death on transient I/O errors.
- **Unified integration error handling** — Standardized 40+ service integrations to differentiate between `ConfigError` (auth/URL) and `TransientError` (network/5xx). Detailed failure reasons are now propagated to the collector and UI.
- **`DriftChecker` async dispatch** — Fixed event loop anti-pattern by using `asyncio.run_coroutine_threadsafe` for WebSocket command delivery from background threads.
- **Frontend reactivity optimization** — Switched high-volume Pinia stores (`dashboard`, `healing`) to use `shallowRef` and `shallowReactive`, reducing CPU/memory overhead for large metric and log datasets.
- **`ChartWrapper` performance** — Refactored to use incremental updates via `chart.update()` instead of full instance recreation on every data change.
- **`api_agent_report()` refactored** — 173-line blob handler decomposed into 10 focused helpers; WebSocket handlers also split. Shared helpers between HTTP and WS paths.
- **Dockerfile hardened** — Added `SHELL` directive for `bash -euo pipefail`, OCI metadata labels, pinned pip versions from pyproject.toml.
- **Shell script portability** — Hardcoded `/tmp` paths replaced with `${TMPDIR:-/tmp}` across 6 scripts (24 replacements). Log libraries consolidated into `noba-lib.sh` with portable `printf` (no `echo -e`).
- **Return type hints** — Added to 11 router functions across 6 files.
- **Accessibility** — 8 fixes: clickable divs get `role="button"` + keyboard handlers, icon-only buttons get `aria-label`.
- **Dependency sync** — `requirements.txt` now includes `websocket-client>=1.7` matching pyproject.toml.

### Fixed
- **`linked_providers` read-connection crash** — `get_linked_providers()` called `CREATE TABLE` via the read-only connection, causing `OperationalError: attempt to write a readonly database`. Table now created during schema init; read functions handle missing table gracefully.
- **IntegrationsTab broken HTML** — 4 social provider `<div>` tags missing closing `>` brackets, causing build failures.
- **3 `console.error` calls** left in production Vue code (LogsView, LogStreamModal, CommandPalette) — removed.

### Added (continued)
- **Bulk Agent Management** — Selection system for agent cards with bulk update (self-update) and bulk remove capabilities.
- **Bulk Automation Management** — Multi-select for automations with bulk enable, disable, and delete actions.
- **Terminal Fullscreen Mode** — Added a maximize toggle to the Terminal modal and `Alt+Enter` keyboard shortcut for better visibility of dense command outputs.
- **Log Stream Flow Control** — Added Pause/Resume functionality to the live log stream and a floating "Jump to Bottom" indicator that appears when new logs arrive while auto-scroll is disabled.
- **Trust state initialization** — `PUT /api/healing/trust/{rule_id}` endpoint to seed trust states directly. Previously only promote/demote existed, requiring a pre-existing state.
- **IaC export auto-discovery** — `?discover=true` query parameter on all 3 export endpoints (Ansible, Docker Compose, shell script). Dispatches `discover_services` + `container_list` to the target agent, waits for WebSocket results, and merges into agent data before generating output. Warnings returned via `X-Noba-Discovery-Warning` header.
- **Remote agent healing** — Healing executor now dispatches actions to remote agents via WebSocket when the alert rule specifies a `target` hostname. Maps `restart_container` → `container_control` and `restart_service` → agent commands. Falls back to local execution if target is not an online agent.
- **First-run onboarding** — New users see a guided setup checklist instead of an unconfigured dashboard. Steps: Core Monitoring (auto-complete), Connect Services (integration wizard modal), Set Up Notifications (channel picker modal), Deploy Agents (deploy modal), Add Users (user creation modal). Progress tracked with checkmarks. Dismissible with "Continue to Dashboard".
- **Docker update flow** — Update check detects Docker containers and shows pull/recreate instructions instead of the bare-metal apply button. GHCR workflow publishes images on push to main and tags.
- **Zero CDN dependencies** — Font Awesome, Chakra Petch, and JetBrains Mono are now bundled locally via npm. No external requests needed — works fully offline and fixes font/icon rendering issues in Docker.
- **Self-update system** — Check for updates and apply them from the UI (Settings → General). Backend: `GET /api/system/update/check` compares local version to remote via git, `POST /api/system/update/apply` pulls, rebuilds frontend, re-installs, and restarts the service.
- Agent v2.1.0 with new commands: `security_scan`, `network_discover`, `discover_services`, `follow_logs`, `stop_stream`, `get_stream`, `endpoint_check`, `verify_backup`, `dns_lookup`, `network_config`, `network_stats`
- Risk-tiered command authorization (low/medium/high) with role-based permissions
- Agent capability registry with version-aware command validation
- Parameter validation for all 32+ command types with regex, length, and denylist checks
- Agent registry SQLite table for persistence across server restarts
- Bulk command support (send to multiple agents at once)
- Command history persistence in SQLite with status tracking

### Improved
- **Dashboard Layout Persistence** — Reordered cards are now saved to backend user preferences using SortableJS `store` sync. Layouts persist across different browsers and devices.
- **Keyboard-First Command Palette** — Enhanced `Ctrl+K` search with full keyboard navigation (ArrowUp/Down to highlight, Enter to select).
- **Global Dialog Accessibility** — Implemented `Enter` key listener for all global confirmation dialogs to streamline destructive workflows.
- **Persistent Sidebar State** — Manual sidebar collapse/expand states are now synced to user preferences and restored on login.
- **Log Stream Stability** — Optimized line buffering logic to prevent memory bloat during high-volume log ingest.
- **SQLite read/write lock separation** — Read operations now use a separate connection with its own lock, allowing concurrent reads under WAL mode without blocking writers. Write operations keep the existing exclusive lock. ~60 read-only methods switched to the read path. `PRAGMA query_only=ON` on the read connection prevents accidental writes.
- **Linked providers persisted to DB** — Social login account links (Google, GitHub, etc.) are now stored in a `linked_providers` table instead of an in-memory dict. Links survive service restarts.
- **Credential encryption at rest** — Integration secrets in `config.yaml` (passwords, tokens, API keys) are now encrypted using Fernet symmetric encryption. Master key stored separately at `~/.config/noba/.master.key` (mode 0600). Existing plaintext configs are transparently encrypted on next save. `cryptography` added as a required dependency.
- **Agent sidebar badge** — Now shows `online/total` count instead of hiding when all agents are offline. Warning color when some are down.
- **API failure visibility** — Header shows a banner when background API requests are silently failing, with failure count and last error. Prevents the "everything looks fine but nothing is updating" trap.
- **Setup wizard reset** — "Re-run Setup Wizard" button in Settings → General clears the welcome dismissal so onboarding can be re-triggered.
- **Integration card empty states** — "configure in Settings" messages are now clickable links that navigate directly to the Integrations settings tab.
- **Maintenance badge clickable** — Header maintenance window indicator now navigates to Settings → Maintenance on click.
- **Theme-safe colors** — WorkflowBuilder node type colors and RunOutput console now use CSS theme variables instead of hardcoded hex values.
- Agent reports now trigger persistence on every report cycle (not just on command completion)

### Security
- **CLI command hardening** — Hardened `cmd_run` and `cmd_exec` in `noba-cli.sh` against JSON injection by switching to native Python encoding for all POST request bodies.
- **Database foreign key enforcement** — Enabled `PRAGMA foreign_keys = ON` for all database connections. Ensures relational integrity and prevents orphaned records in the audit and healing trails.
- **API input validation hardened** — Eliminated 18 bare `int()` casts on query parameters across the backend routers. Standardized on `_safe_int` and `_int_param` helpers to prevent unhandled 500 errors on invalid user input.
- **Plugin read-only enforcement** — Refactored `PluginContext.query()` to use the dedicated read-only database connection and lock. Strictly prevents write operations (DELETE/DROP) via the plugin API.
- **Thread-safe process creation** — Replaced unsafe `preexec_fn=os.setsid` with `start_new_session=True` in terminal and agent PTY handlers to prevent deadlocks in multi-threaded environments.
- **Shell CLI injection fix** — Hardened `noba-cli.sh` against Python code injection in `_json_val` and JSON breakage in `cmd_login`. Switched to `sys.argv` and native JSON encoding for payloads.
- **`_safe_remove` path traversal hardening** — Added directory separator termination to prefix checks to prevent sibling directory bypass in file deletion helpers.
- **SSRF via redirect** — Shared httpx client now uses `follow_redirects=False` to prevent integration endpoints from being redirected to internal/cloud metadata IPs.
- **Webhook DNS rebinding** — `_is_safe_webhook_url()` now resolves hostnames via `socket.getaddrinfo()` and checks all resulting IPs against private/loopback/link-local ranges. Previously only checked string-based IP parsing.
- **Run command argument validation** — `_handle_run` now validates all arguments after the allowed prefix against `[a-zA-Z0-9@._/:-]` to prevent abuse of the allowlisted command prefixes.
- **OpenAPI docs disabled by default** — `/api/docs`, `/api/redoc`, and `/api/openapi.json` are now hidden unless `NOBA_DEV=1` is set, preventing API schema disclosure to unauthenticated users.
- **CSP tightened** — Removed `unsafe-eval` and `unsafe-inline` from `script-src`, stripped all external CDN allowances (fonts/icons already bundled). Service worker registration moved from inline script to the main JS bundle.
- **TLS verification configurable** — All integration HTTP calls (K8s, Proxmox, UniFi, UniFi Protect) now respect per-integration `verifySsl` settings instead of hardcoded `verify=False`. Integration instances have a `verify_ssl` DB column and UI checkbox. Supports CA bundle file paths for custom certificates.
- **Script automation shell escalation blocked** — Automations with custom `command` fields now require admin role, preventing operator→shell privilege escalation.
- **Automation variable injection blocked** — Operator-supplied variables substituted into `command` strings via `format_map` are now sanitized with `shlex.quote()`, preventing shell metacharacter injection.
- **Agent key timing attack mitigated** — Agent key validation now uses `secrets.compare_digest` for constant-time comparison.
- **Prometheus label injection prevented** — Service names and mount points in `/api/prometheus` metrics are now escaped per the exposition format spec.
- **OAuth2/OIDC CSRF protection** — All social login and OIDC flows now generate and validate a cryptographic `state` parameter, preventing login CSRF attacks.
- **OAuth token leak fixed** — Account linking no longer passes the NOBA session token as the OAuth `state` parameter. Tokens are stored server-side with a random nonce.
- **Healing `run` action restricted** — Command execution via the healing pipeline is now restricted to an allowlist of safe prefixes (systemctl, docker, podman, restic, rclone, certbot).
- **API key expiry enforced** — Expired API keys are now rejected at authentication time.
- **Webhook SSRF protection** — Remediation webhook handler blocks requests to private networks, loopback, link-local, reserved ranges, and cloud metadata endpoints.
- **SSRF DNS resolution validation** — Integration instance URL validation now resolves hostnames and checks resolved IPs against private ranges.
- **LDAP filter injection fix** — Username escaping now uses proper RFC 4515 encoding instead of partial character replacement.
- **Terminal audit logging** — PTY sessions now log start/end events with user, role, IP, and duration to the audit trail.
- **SSH key validation** — Rejects authorized_keys entries with embedded options (`command=`, `from=`, etc.).
- **SQL column allowlist** — Integration instance updates validate field names against an explicit allowlist.
- **HTTPException guards** — Added `except HTTPException: raise` across all routers to prevent HTTP errors from being swallowed as 500s.
- **Journal regex validation** — Grep patterns are pre-validated with `re.compile()` before passing to `journalctl`.
- **Auth level corrections** — TOTP setup upgraded to operator, stream-logs downgraded from admin to operator, update check upgraded to operator, social link endpoint validates tokens.
- **Async event loop safety** — 20+ `subprocess.run()` calls in async routes wrapped in `asyncio.to_thread()` to prevent blocking the event loop.

### Fixed
- **Alert condition validation** — Malformed conditions (bare operators, missing thresholds, garbage strings) are now rejected at creation time with clear error messages. Validation applied to create, update, and batch save endpoints.
- **Heal action params double-nesting** — Legacy single-action alert rules were wrapping params inside an extra `params` key, causing heal execution to fail after approval. Fixed chain wrapper to extract params correctly.
- **Graylog user/password auth** — Graylog search integration now supports both API token (`token:token`) and user/password (`user:password`) Basic auth. Added `X-Requested-By: noba` header required by Graylog v7+. New settings: `graylogUser`, `graylogPassword`.
- **Agent capability fallback for newer versions** — Agents reporting a version not explicitly in the capability registry fell back to the v1.1.0 baseline. Now any agent ≥ v2.0.0 gets full v2 capabilities automatically.
- **Endpoint monitor self-referential deadlock** — Monitors targeting the same NOBA instance deadlocked the uvicorn process. Now detects self-referential URLs and returns `skipped` status.
- **Healing dry-run ignores maintenance windows** — The `/api/healing/dry-run` endpoint did not check active maintenance windows. Now queries the maintenance manager before simulation.
- **Proxmox API token double-prefix** — Detected full token IDs and uses them directly.
- **Healing effectiveness always 0%** — Endpoint queried non-existent `outcome` field; now uses `verified`/`action_success`.
- **Circuit breaker never tripped** — Query limit equalled threshold (3). Now looks back 50 entries.
- **LedgerTimeline timestamps** — Unix seconds passed to `new Date()` without ×1000.
- **Expired tokens accepted from DB** — Token fallback path promoted expired tokens to memory without checking expiry.
- **Double JSON encoding** — `evidence` field in health trigger suggestions was pre-serialized then re-serialized.
- **Dict passed as string** — Canary dry-run passed a dict to `suggested_action`.
- **`total_agents` NameError** — Variable undefined if monitoring coverage section threw.
- **Rollback bypassed DB write lock** — Used raw `_get_conn()` outside lock.
- **Dead code in `get_heal_outcomes`** — Redundant LIMIT 0 query + double lock acquire removed.
- **`_active_alerts` leak** — Targets added during suppressed paths stayed in the set forever. Split into TTL-based `_active_alerts` and `_active_heals` set.
- **Alert rules save was a no-op** — "Save Rules" in Settings sent the wrong payload. Added `PUT /api/alert-rules` batch endpoint.
- **Uptime card always showed 0%** — Backend now computes and returns percent.
- **Expired token crash** — DB fallback returned bare `None` instead of `(None, None)`.
- **Agent policy version always 0** — Now uses a SHA-256 content hash.
- **DNS flush hardcoded `pihole-FTL`** — Now reads `dnsService` from config.
- **Health score trigger** — Scheduler was passing Database object instead of health score categories.
- **Masonry grid after welcome dismiss** — Re-initializes ResizeObserver.
- **Self-update install step** — Added `--skip-deps` and `--no-restart` to install.sh invocation.
- **Trust level naming** — Fixed `"suggest"` to `"approve"` in `db/healing.py` trust level constants.

## [2.0.0] - 2026-03-19

### Added
- Full remote agent management platform (Phase 1 complete)
- WebSocket real-time communication with HTTP polling fallback
- 32 command types across system, service, file, container, network, and user management
- File transfer (push/pull) with chunked upload and SHA256 verification
- Streaming output for long-running commands via WebSocket
- One-click agent deployment from dashboard via SSH
- Windows agent support (PowerShell installer)
- Agent metric persistence with per-agent CPU/RAM/disk history
- SLA dashboard with 7d/30d/90d uptime percentages
- Sidebar navigation with global search (Ctrl+K)
- 10 standout features: network discovery, security scoring, IaC export, traffic analysis
- Ops center elevation: 11 features across 4 implementation waves
- Service dependency topology with impact analysis
- Configuration drift detection
- Predictive disk intelligence with SMART trend analysis
- AI Ops assistant (multi-provider LLM)
- Public status page (no auth required)
- Initial release: system monitoring dashboard with 40+ integrations
- Real-time SSE with polling fallback
- Multi-user RBAC (admin/operator/viewer)
- Plugin system for custom dashboard cards
- Alert rules with composite conditions and self-healing actions
- Anomaly detection with Z-score analysis
- PWA support with push notifications
- 6 color themes
- Automation engine with 9 action types
- Developer toolkit (screenshots, E2E tests, smoke tests, cross-reference validator)

## [1.0.0] - 2026-03-17

### Added
- Historical base release.
