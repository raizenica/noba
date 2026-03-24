# Changelog

All notable changes to NOBA Command Center are documented in this file.

## [Unreleased]

### Fixed
- **Alert condition validation** — Malformed conditions (bare operators, missing thresholds, garbage strings) are now rejected at creation time with clear error messages. Validation applied to create, update, and batch save endpoints.
- **Heal action params double-nesting** — Legacy single-action alert rules were wrapping params inside an extra `params` key, causing heal execution to fail after approval. Fixed chain wrapper to extract params correctly.
- **Graylog user/password auth** — Graylog search integration now supports both API token (`token:token`) and user/password (`user:password`) Basic auth. Added `X-Requested-By: noba` header required by Graylog v7+. New settings: `graylogUser`, `graylogPassword`.

### Added
- **Trust state initialization** — `PUT /api/healing/trust/{rule_id}` endpoint to seed trust states directly. Previously only promote/demote existed, requiring a pre-existing state.
- **IaC export auto-discovery** — `?discover=true` query parameter on all 3 export endpoints (Ansible, Docker Compose, shell script). Dispatches `discover_services` + `container_list` to the target agent, waits for WebSocket results, and merges into agent data before generating output. Warnings returned via `X-Noba-Discovery-Warning` header.
- **Remote agent healing** — Healing executor now dispatches actions to remote agents via WebSocket when the alert rule specifies a `target` hostname. Maps `restart_container` → `container_control` and `restart_service` → agent commands. Falls back to local execution if target is not an online agent. Live-tested: stopped container on remote PVE, NOBA auto-restarted it via agent WebSocket in < 25 seconds.

### Improved
- **SQLite read/write lock separation** — Read operations now use a separate connection with its own lock, allowing concurrent reads under WAL mode without blocking writers. Write operations keep the existing exclusive lock. ~60 read-only methods switched to the read path. `PRAGMA query_only=ON` on the read connection prevents accidental writes.
- **Linked providers persisted to DB** — Social login account links (Google, GitHub, etc.) are now stored in a `linked_providers` table instead of an in-memory dict. Links survive service restarts.
- **Credential encryption at rest** — Integration secrets in `config.yaml` (passwords, tokens, API keys) are now encrypted using Fernet symmetric encryption. Master key stored separately at `~/.config/noba/.master.key` (mode 0600). Existing plaintext configs are transparently encrypted on next save. `cryptography` added as a required dependency.

### Improved
- **Agent sidebar badge** — Now shows `online/total` count instead of hiding when all agents are offline. Warning color when some are down.
- **API failure visibility** — Header shows a banner when background API requests are silently failing, with failure count and last error. Prevents the "everything looks fine but nothing is updating" trap.
- **Setup wizard reset** — "Re-run Setup Wizard" button in Settings → General clears the welcome dismissal so onboarding can be re-triggered.
- **Integration card empty states** — "configure in Settings" messages are now clickable links that navigate directly to the Integrations settings tab.
- **Maintenance badge clickable** — Header maintenance window indicator now navigates to Settings → Maintenance on click.
- **Theme-safe colors** — WorkflowBuilder node type colors and RunOutput console now use CSS theme variables instead of hardcoded hex values.

### Added
- **First-run onboarding** — New users see a guided setup checklist instead of an unconfigured dashboard. Steps: Core Monitoring (auto-complete), Connect Services (integration wizard modal), Set Up Notifications (channel picker modal), Deploy Agents (deploy modal), Add Users (user creation modal). Progress tracked with checkmarks. Dismissible with "Continue to Dashboard".
- **Docker update flow** — Update check detects Docker containers and shows pull/recreate instructions instead of the bare-metal apply button. GHCR workflow publishes images on push to main and tags.
- **Zero CDN dependencies** — Font Awesome, Chakra Petch, and JetBrains Mono are now bundled locally via npm. No external requests needed — works fully offline and fixes font/icon rendering issues in Docker.

### Fixed
- **Agent capability fallback for newer versions** — Agents reporting a version not explicitly in the capability registry (e.g. v2.3.0 when registry only listed up to v2.1.0) fell back to the v1.1.0 baseline (9 commands). Now any agent ≥ v2.0.0 gets full v2 capabilities (42 commands) automatically.
- **Endpoint monitor self-referential deadlock** — Monitors targeting the same NOBA instance (`localhost:8080`) deadlocked the uvicorn process. Now detects self-referential URLs and returns `skipped` status with a clear error message.
- **Healing dry-run ignores maintenance windows** — The `/api/healing/dry-run` endpoint did not check active maintenance windows, reporting full healing actions even for suppressed targets. Now queries the maintenance manager before simulation.
- **Proxmox API token double-prefix** — When `proxmoxTokenName` was stored as a full token ID (`root@pam!noba-api`), the auth header prepended the user again, producing an invalid `PVEAPIToken=root@pam!root@pam!noba-api=...`. Now detects full token IDs and uses them directly.
- **Healing effectiveness always 0%** — Endpoint queried non-existent `outcome` field; now uses `verified`/`action_success` and returns `verified_count`/`failed_count`/`pending_count` matching the frontend chart.
- **Circuit breaker never tripped** — Query limit equalled threshold (3), so any intermittent success prevented trip. Now looks back 50 entries within the time window.
- **LedgerTimeline timestamps** — Unix seconds passed to `new Date()` without ×1000; all entries showed epoch dates.
- **Expired tokens accepted from DB** — Token fallback path promoted expired tokens to memory without checking expiry.
- **Double JSON encoding** — `evidence` field in health trigger suggestions was pre-serialized then re-serialized by `insert_heal_suggestion`.
- **Dict passed as string** — Canary dry-run passed a dict to `suggested_action` (typed `str | None`); now serialized with `json.dumps()`.
- **`total_agents` NameError** — Variable undefined if monitoring coverage section threw; now initialized before the try block.
- **Rollback bypassed DB write lock** — Used raw `_get_conn()` outside lock; now uses `db.get_snapshot_by_ledger_id()` wrapper.
- **Dead code in `get_heal_outcomes`** — Redundant LIMIT 0 query + double lock acquire removed.
- **`_active_alerts` leak** — Targets added during suppressed paths (site isolation, root cause, maintenance, canary) stayed in the set forever, permanently blocking downstream healing. Split into TTL-based `_active_alerts` dict (dependency-graph signal, 5-min expiry, refreshed on every event) and `_active_heals` set (execution lifecycle, precise add/remove).
- **Alert rules save was a no-op** — "Save Rules" in Settings sent the wrong payload to a single-rule endpoint. Added `PUT /api/alert-rules` batch endpoint; frontend now uses it. Rule IDs use `crypto.randomUUID()` to prevent duplicates.
- **Uptime card always showed 0%** — Backend returned a flat list but frontend expected `{items, percent}`. Backend now computes and returns percent.
- **Expired token crash** — DB fallback returned bare `None` instead of `(None, None)` tuple, causing TypeError on every expired-token request.
- **Agent policy version always 0** — `_policy_version` was never incremented. Now uses a SHA-256 content hash so agents can detect policy changes.
- **DNS flush hardcoded `pihole-FTL`** — Now reads `dnsService` from config with regex validation, defaults to `pihole-FTL`.
- **Health score trigger** — Scheduler was passing Database object instead of health score categories to `evaluate_health_thresholds`. Now uses cached results from the last health score computation.
- **Masonry grid after welcome dismiss** — Re-initializes ResizeObserver after the welcome screen is dismissed so cards lay out correctly.
- **Self-update install step** — Added `--skip-deps` and `--no-restart` to install.sh invocation during self-update, preventing failure under `NoNewPrivileges=true` systemd environments and double-restart race condition.

### Added
- **Self-update system** — Check for updates and apply them from the UI (Settings → General). Backend: `GET /api/system/update/check` compares local version to remote via git, `POST /api/system/update/apply` pulls, rebuilds frontend, re-installs, and restarts the service. Frontend: glowing update pill in the header notifies admins when an update is available, with changelog preview and one-click apply.

### Changed
- **Auth level corrections** — Container stats and compose projects downgraded to viewer (monitoring data). K8s scale, service discovery, and recovery actions downgraded from admin to operator. IaC exports downgraded from admin to operator. Custom reports upgraded to operator. Graylog search upgraded to operator (log data is sensitive). TOTP setup lowered to viewer so all users can enable 2FA.

### Security
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

### Improved
- **DB module split** — `db/automations.py` (1468 lines) split into 5 focused modules: `automations.py`, `api_keys.py`, `notifications.py`, `user_dashboards.py`, `tokens.py`.
- **Frontend consistency** — 3 components migrated from raw `fetch()` to `useApi()` composable. 8 unused imports removed. Duplicate reactive keys fixed in dashboard store.
- **Shell script safety** — Added cleanup trap for temp files in `noba-dashboard.sh`.
- **Test coverage** — Added 344 new tests (2187 → 2531): admin router (178), stats router (57), integration instances (51), collector (22), healing governor (+22), healing executor (+13), remediation allowlist (+1).

### Fixed
- **Event loop safety** — Converted `_transfer_lock` from `threading.Lock` to `asyncio.Lock` across agent store, app.py, and routers/agents.py. All 8 usages now use `async with` instead of blocking the event loop.
- **Cleanup loop backoff** — Moved sleep to end of loop so backoff actually affects retry frequency instead of adding noise after the fixed 300s wait.
- **Graph workflow cycle protection** — Added visited-node tracking and depth limit (200) to prevent stack overflow from cyclic workflow graphs.
- **JobRunner race condition** — Moved capacity check and slot registration into a single atomic lock scope, preventing concurrent submits from exceeding max_concurrent.
- **API key expiry** — `get_api_key` now checks `expires_at` — expired API keys no longer authenticate.
- **SPA fallback masking API errors** — Routes starting with `api/` now return 404 instead of the frontend index.html.
- **Security header matching** — Changed `startswith()` to exact `not in` match to prevent false prefix matches on docs paths.
- **Transfer cleanup performance** — Hoisted `os.listdir` outside the per-transfer loop and moved file deletion outside the lock.
- **Agent polling latency** — Replaced `time.sleep(0.5)` busy-wait polling with `threading.Condition` signaling across endpoint checker, drift checker, agent verify, and command wait. Responses now wake consumers instantly.
- **Dashboard save data loss** — `save_user_dashboard` changed from `INSERT OR REPLACE` (which wiped unset columns) to `ON CONFLICT ... COALESCE` upsert preserving existing values.
- **Plugin/scheduler startup isolation** — Each component wrapped in try/except so one failure doesn't block the rest.
- **Cache policy** — Hashed `/assets` now get 1-year cache, mutable `/static` gets 5-minute cache.
- **Health check** — Now uses `execute_write(SELECT 1)` testing connection, lock, and WAL path instead of a read-only query.
- **LoginView test failures** — Fixed 2 pre-existing test bugs: loading state mock now matches auth store flow, SSO test updated for dynamic provider UI.

### Improved
- **UX: Error handling** — `useApi` now returns human-readable error messages ("Permission denied", "Connection lost") instead of raw HTTP status codes. Error toasts stay 8s, warnings 6s, success 4s.
- **UX: Confirm dialogs** — Replaced all 16 native `confirm()` calls with themed `ConfirmDialog` via global Pinia store. Accessible, keyboard-friendly, matches app theme.
- **UX: Empty states** — AgentsView, AutomationsView, and HealingView now show contextual guidance with action buttons when no data exists.
- **UX: Error visibility** — Replaced 50+ silent `catch {}` blocks with contextual error toasts across SecurityView, LogsView, AgentsView, and settings tabs.
- **UX: Settings feedback** — All save/restore/download operations now use toast notifications instead of mixed `alert()`/inline messages.
- **DB: Transaction support** — Added `transaction()` method to Database for atomic multi-step writes with rollback on error.
- **DB: Missing indexes** — Added `idx_audit_ts`, `idx_audit_user_action`, and `idx_api_keys_hash` for frequently queried tables.

- **Integration instance management** — Full CRUD API for managing integration instances (`/api/integrations/instances`). Connection test endpoint verifies platform reachability before saving. Integration catalog API lists all 29 categories and their platforms from the registry. Instance group management API. User-friendly 4-step setup wizard in Settings → Integrations: pick category → pick platform → configure URL/auth/site/tags → test connection → save. Managed instances listed with health status badges and delete buttons. IntegrationCards auto-rendered on the dashboard for all configured instances. Template-driven card rendering supports 12+ platform templates with status badges, percent bars, temperature, age, and bytes metric types.

- **Self-healing validation (Phase 6)** — Component watchdog for internal resilience: subsystems register heartbeats, watchdog thread detects stalls, triggers recovery callbacks, enters degraded mode when 3+ components fail simultaneously. Dry-run pipeline simulation: `POST /api/healing/dry-run` runs the full pipeline (correlation, dependency analysis, trust resolution, plan selection, pre-flight, rollback classification) without executing any action — returns detailed report of what would happen. Chaos testing framework with 12 built-in scenarios (container crash recovery, dependency cascade suppression, escalation chain walk, site isolation, heal storm circuit breaker, stale metrics guard, capability mismatch, maintenance suppression, approval timeout, rollback on failure, power flicker debounce, manual fix race). Canary rollout mode: new trust levels `observation` (track "would have fired" without emitting events) and `dry_run` (full pipeline simulation without execution) below the existing notify→approve→execute chain. New API endpoints: dry-run simulation, chaos scenario listing and execution, pipeline health status. Three new modules: `watchdog.py`, `dry_run.py`, `chaos.py`.

- **Self-healing interface (Phase 5)** — Complete healing dashboard rebuild with 6-tab layout: Overview (pipeline status bar + effectiveness charts), Ledger (vertical timeline with expandable entries, filters, JSON export, rollback buttons), Dependencies (interactive SVG graph with layered node layout, health-colored nodes, click-to-inspect), Trust (visual progression bars notify→approve→execute, circuit breaker indicators, promote/demote), Approvals (pending queue with full context cards, approve/deny/defer, countdown timers, escalation badges), Maintenance (active window list with countdown, quick-create form, scheduled windows). Capability Matrix view showing per-agent tool manifests with refresh. Template-driven IntegrationCard component renders any platform using metric templates (status badges, percent bars, temperature, age, bytes). Card template registry with 12+ platform definitions. Healing settings tab (pipeline config, approval policy, predictive settings, notification routing). Maintenance settings tab. New Pinia healing store centralizing all healing state. useHealing composable for API calls. Trust demote API endpoint. Built frontend committed to static/dist.

- **Self-healing predictive (Phase 4)** — Prediction engine wired into the healing pipeline: 15-minute scheduler cycle evaluates capacity forecasts and emits `HealEvent(source="prediction")` when metrics approach thresholds (24h=warning, 72h=info). Anomaly detection wired similarly with `source="anomaly"`. Conservative trust cap: prediction/anomaly/health_score events are automatically capped one trust level below the rule's current trust (execute→approve, approve→notify). Stale data guard blocks all predictive evaluation when collector data is older than 2x the collection interval. Health score integration: category thresholds (capacity, certificates, backup, monitoring, uptime, updates) trigger heal suggestions and lightweight heal events when degraded. Enriched notification formatting: every heal notification now includes trigger condition, source rule, risk level, escalation step, duration, before/after metrics, rollback availability, and skipped actions. Approval notifications show full context with risk level and reversibility. Hourly digest format for low-risk batching. Four new modules: `predictive.py`, `health_triggers.py`, `notifications.py`.

- **Self-healing controls (Phase 3)** — Maintenance window system with global and per-target scheduling, ad-hoc windows via API, and event queuing during windows. Tiered approval manager: low-risk auto-executes, medium-risk auto-executes with notification, high-risk requires human approval. Adaptive staffing detects user base (single-admin gets confirmation cooldown, no approvers get auto-deny). Emergency override for critical situations (off by default, configurable per-rule). State snapshot system captures pre-heal state for rollback. Reversible actions auto-rollback on verified failure. Manual rollback via `POST /api/healing/rollback/{ledger_id}`. Extended audit trail: 7 new columns on `heal_ledger` (risk_level, snapshot_id, rollback_status, dependency_root, suppressed_by, maintenance_window_id, instance_id). New API endpoints: maintenance CRUD (`GET/POST/DELETE /api/healing/maintenance`), rollback. Three new healing modules: `approval_manager.py`, `maintenance.py`, `snapshots.py`.

- **Self-healing intelligence (Phase 2)** — Dependency graph with root cause resolution: when multiple targets fail, the pipeline identifies the highest failing ancestor (root cause), heals it, and suppresses downstream noise. Site isolation via connectivity monitor — when an agent is unreachable, all healing for that site is suppressed to prevent false restarts (ISP outage protection). Agent verification module for confirming target state before healing remote services. Co-failure auto-discovery engine runs hourly, detects targets that fail together 85%+ of the time within a 2-minute window, and surfaces dependency suggestions for operator confirmation. New DB table `dependency_graph` with full CRUD. New API endpoints: `GET /api/healing/dependencies`, `POST /api/healing/dependencies/validate`. Four new healing modules: `dependency_graph.py`, `connectivity_monitor.py`, `agent_verify.py`, `auto_discovery.py`.

- **Self-healing foundation (Phase 1)** — Capability-based action dispatch replacing OS detection. Agent probes 22+ tools and reports a capability manifest every 6 hours (or on-demand via `refresh_capabilities` command). Pre-flight check system validates capabilities, maintenance windows, and manifest existence before every heal action. Expanded action registry from 12 to 55 types (15 low-risk, 18 medium-risk, 10 high-risk) with fallback chains for cross-platform dispatch (Linux/Windows/Alpine/macOS). Universal integration registry with 139 abstract heal operations across 29 categories (NAS, hypervisor, media, DNS, security, logging, databases, and more) mapped to platform-specific API handlers. Multi-instance integration support with DB tables for instances, groups, and capability manifests. New API endpoints for capability manifest retrieval and refresh. Executor now runs pre-flight checks before action dispatch — blocks execution when capabilities don't match.

### Fixed
- **Trust level naming** — Fixed `"suggest"` to `"approve"` in `db/healing.py` trust level constants and updated corresponding test. Trust promotion/demotion calculations now work correctly.

### Added
- **Self-healing pipeline** — Replaced inline alert self-healing with a layered pipeline architecture. Six modules in `server/healing/`: correlation (immediate-on-first with absorption window), planner (escalation chains with adaptive scoring that skips low-effectiveness actions), executor (async action execution with condition-based verification), governor (graduated trust with circuit breaker and promotion), ledger (outcome recording with suggestion engine), and agent runtime (policy distribution to remote agents). New DB tables: `heal_ledger`, `trust_state`, `heal_suggestions`. New API router with 6 endpoints (`/api/healing/ledger`, `/api/healing/effectiveness`, `/api/healing/suggestions`, `/api/healing/trust`, dismiss, promote). Hourly scheduler integration for suggestion generation and trust promotion evaluation. 4 new remediation action types: `run`, `webhook`, `automation`, `agent_command`. 58 new tests across 10 test files.
- **Remote terminal** — Full interactive PTY terminal in the agent detail modal using xterm.js. Browser connects via WebSocket to the server, which bridges to the agent's WebSocket. Agent spawns a real PTY shell (`pty.openpty()` on Linux, `subprocess.Popen` on Windows) with live streaming output. Supports interactive commands (`vim`, `htop`, `ssh`, `sudo`), terminal resize, ANSI colors, and cursor positioning.
- **Healing dashboard** — New `/#/healing` view with three tabs: Ledger (filterable outcome table with auto-refresh), Trust (card grid with admin-only promotion), and Suggestions (dismissable cards for operators). Per-agent healing tab in the agent detail modal.
- **Agent auto-update** — Server compares agent-reported version against installed version on each heartbeat. Queues `update_agent` command automatically when a newer version is available.
- **Windows agent support** — Full PowerShell integration for remote terminal, service management (`Get-Service`, `Start/Stop/Restart-Service`), log retrieval (`Get-EventLog`), service listing, DNS flush, and network diagnostics. Heal runtime uses Windows-appropriate commands.

### Security
- **Role-based terminal access** — PTY sessions enforce least privilege. Admin users get full shell access; operator users get a restricted shell (`su - noba-agent`/`nobody` on Linux, PowerShell Constrained Language Mode on Windows). Role is injected server-side and cannot be spoofed by the browser.

### Security
- **Settings endpoint credential disclosure** — `GET /api/settings` returned all integration credentials (40+ passwords, tokens, API keys) in plaintext to any authenticated user including viewers. Now redacts secret fields for non-admin users using `is_secret_key()`.
- **Agent command auth escalation** — `POST /api/agents/bulk-command` and `POST /api/agents/{hostname}/command` allowed viewer-role users to dispatch agent commands. Raised to `_require_operator`.
- **OIDC token-in-fragment** — Replaced `/#token=...` redirect with one-time code exchange pattern. Backend issues a 60-second single-use code; frontend exchanges it via `POST /api/auth/oidc/exchange`. Prevents token leakage through browser history and Referer headers.
- **OIDC password marker** — Changed `"oidc:external"` to `"!oidc:disabled"` to ensure OIDC-only accounts can never match any password hash format.
- **Proxmox path traversal** — Added regex validation (`^[a-zA-Z0-9][a-zA-Z0-9._-]*$`) on `{node}` path parameter across all 3 Proxmox endpoints. Added `vtype` allowlist validation (`qemu`/`lxc`).
- **qBittorrent cookie leakage** — Login and data requests now use the same dedicated `httpx.Client` context manager instead of leaking cookies to the shared client.
- **Auth level tightening** — Raised 10 under-protected endpoints: agent stream logs, log viewer, action log (→ operator); automations export, IaC exports ×3 (→ admin); dashboard CRUD ×3 (→ operator).
- **HTTP method corrections** — Changed `GET /api/notifications/test` and `GET /api/agents/{hostname}/network-stats` to POST (both trigger side effects).

### Changed
- **Claude Code skills updated for Vue 3** — Deploy and test skills now reference vitest + Vite build instead of deleted Alpine.js files. New `/build-frontend` skill for standalone frontend builds. Security-reviewer agent updated for Vue 3 patterns (v-html, Pinia stores, useApi composable). New api-auditor agent for auth-level and HTTP method consistency audits.

### Changed
- **Predictive intelligence + workflow orchestration (v3 Phase 5)** — Multi-metric capacity prediction with seasonal decomposition and 68%/95% confidence intervals. Per-service weighted health scoring (uptime 40%, latency 25%, error rate 20%, headroom 15%) backed by endpoint check history. Visual workflow builder with conditional branching, approval gates, parallel execution, and delay nodes. 4 pre-built maintenance playbook templates (agent update, DNS restart, backup verify, disk cleanup). Vue UI: prediction dashboard card with confidence band chart, infrastructure prediction panel, workflow builder with SVG canvas, playbook library.
- **Advanced automation engine (v3 Phase 4)** — Added 8 remediation action types (restart_container, restart_service, flush_dns, clear_cache, trigger_backup, failover_dns, scale_container, run_playbook) with validation and health checks. Per-rule autonomy levels (execute/approve/notify/disabled). DB-backed approval queue with auto-approve timeout. Named maintenance windows with alert suppression and autonomy override. Enhanced action audit trail. Vue UI: approval queue with header badge, maintenance window CRUD with active indicator, autonomy selector in alert rules, action audit table.
- **Test coverage + API contracts (v3 Phase 3)** — Added integration tests for all 8 decomposed routers (668 new backend tests, total 1451). OpenAPI schema at `/api/openapi.json` with Swagger UI at `/api/docs`. Frontend test suite: Vitest + Vue Test Utils (81 tests covering Pinia stores and key components).
- **Vue.js migration (v3 Phase 2)** — Replaced Alpine.js frontend (6945-line index.html + 6 JS mixins) with Vue 3 + Vite SPA. 16 pages as lazy-loaded Vue components with Pinia state management. Mobile responsive. PWA service worker updated. Old frontend files deleted.
- **Backend decomposition (v3 Phase 1)** — Decomposed `routers/system.py` (3190 lines, 117 routes) into 8 focused domain routers: `agents.py` (22), `containers.py` (8), `dashboards.py` (4), `infrastructure.py` (19), `intelligence.py` (22), `monitoring.py` (17), `operations.py` (19), `security.py` (6). All route URLs unchanged. `system.py` deleted.

### Fixed
- **Collector timeout stacking** — Integration futures were evaluated sequentially with per-future timeouts (3-6s each), meaning the 5-second collection cycle could take 200+ seconds if multiple integrations were offline. Replaced with `concurrent.futures.wait()` using a single 4.5s global deadline — futures that don't finish in time gracefully return defaults.
- **Workflow engine subprocess overhead** — Webhook and HTTP automation steps spawned full `subprocess.Popen(["curl", ...])` OS processes for every request. Replaced with native `httpx` calls wrapped in a Popen-compatible `_HttpResult` class, eliminating process fork overhead while preserving the job_runner contract.
- **Unbounded WAL file growth** — SQLite WAL mode was enabled but never checkpointed. On a 24/7 dashboard the `.db-wal` file would grow indefinitely. Added `PRAGMA wal_checkpoint(TRUNCATE)` to the hourly prune cycle.
- **Unsafe async task cancellation** — `_cleanup_transfers()` had a bare `while True` loop without `CancelledError` handling, risking unclean shutdown if cancelled during file operations. Added graceful catch-and-reraise.
- **Job runner silent hang** — `proc.stdout.readline()` could block indefinitely if a subprocess hung without closing stdout, making `JOB_TIMEOUT` unreachable. Added a `threading.Timer` watchdog that kills the process regardless of readline state.
- **Stop-the-world VACUUM** — `prune_history()` ran `conn.execute("VACUUM")` while holding the global DB lock, freezing the entire application for seconds on large databases. Replaced with `PRAGMA auto_vacuum=INCREMENTAL` and `PRAGMA incremental_vacuum(1000)` which reclaim pages without rebuilding the file.
- **Sequential endpoint checks** — `EndpointChecker._tick()` processed monitors one at a time; 5 offline hosts with 10s timeouts stalled the 60s tick for 50+ seconds. Parallelized with `ThreadPoolExecutor(max_workers=10)`.
- **Livestream logs immediately stopping** — Stream poll endpoint returned a raw list `[]` when no data had arrived yet, causing the frontend to read `!undefined` as truthy for the `active` check and immediately stop the stream. Now returns `{"lines": [], "cursor": 0, "active": true}` while the stream is registered but waiting for agent data.
- **Agent WebSocket result type collision** — Commands sent via WebSocket stayed permanently "queued" because the agent's result message overwrote `{"type": "result"}` with `{"type": "disk_usage"}` during dict unpacking. Agent now sends command type in a separate `cmd` field.
- **Server backward compatibility** — Server now detects old-format agent results (pre-v2.1.0) and reshapes them automatically, so mixed-version deployments work correctly.
- **Command palette scope error** — `runPaletteCommand()` referenced `CMD_CATALOG` as a closure variable instead of `this.CMD_CATALOG`, causing ReferenceError in the mixin scope. Also wrapped in try/finally so the "Sending..." state always clears.
- **Dashboard layout corruption on page navigation** — `initMasonry()` leaked ResizeObservers (never disconnected old ones) and observed ALL `.card` elements globally instead of scoping to the dashboard grid. Navigating from Security to Dashboard caused a large blank area at the top. Fixed by disconnecting old observer, scoping to `#sortable-grid`, and using `offsetParent` for visibility checks.
- **Stacking setInterval in dashboard cards** — System Health and Uptime Status cards used bare `setInterval` in `x-init` without guards. Added re-entry prevention.
- **Database agent methods using raw connection** — `upsert_agent`, `get_all_agents`, `delete_agent`, `update_agent_config` in `db/core.py` used `self._conn` directly instead of `self._get_conn()`, risking NoneType errors if the connection wasn't initialized.
- **Logger shadow in system.py** — Module-level `logger` was reassigned to `"noba.agent.ws"` at line 1178, silently changing the logger for all routes below that point. Renamed to `_ws_logger`.
- **WebSocket stream data memory leak** — Stream messages appended to `_agent_cmd_results` without any size cap. Added 500-entry limit matching existing patterns.
- **HTML null guards** — Added optional chaining for `disk.attributes.*` SMART fields, null guard on `zfs.pools` iteration, and `typeof Chart` guard in `renderMultiChart()`.
- **LDAP injection** — Username interpolated directly into LDAP filter string without escaping, allowing authentication bypass via crafted usernames. Now escapes `*()\\` and null bytes per RFC 4515.
- **Agent endpoint check type mismatch** — `_dispatch_agent_endpoint_check` treated `_agent_cmd_results` list as a dict (`cmd_id in list`), causing agent-based endpoint monitoring to silently fail every time. Now iterates the result list matching by `id` field.
- **Network discovery toast method** — 4 call sites used `this.toast()` instead of `this.addToast()`, silently failing all notification toasts for network discovery actions.
- **SVG topology XSS** — `n.id` and `n.label` injected into SVG `innerHTML` without escaping. A malicious agent name could execute arbitrary JavaScript. Added HTML entity escaping.
- **HA bridge SSE hang** — Home Assistant event bridge used `timeout=None` on httpx stream, hanging forever if HA disconnected without closing the socket. Added 10s connect + 300s read timeout.
- **Rclone config parameter injection** — User-supplied parameter keys were passed directly to `rclone config create` command. Added alphanumeric key validation.
- **Automation format_map injection** — `str.format_map()` with user-controlled variables could access object attributes. Restricted to string/numeric values only.
- **OIDC token URL exposure** — Session token was passed in URL query parameter (`?token=...`), visible in browser history, server logs, and Referer headers. Moved to URL fragment (`#token=...`) which is never sent to the server.
- **Alert rule delete error handling** — `deleteAlertRule()` had no try/catch and no response status check, silently failing on errors.
- **Traefik error count clarity** — Removed redundant `serverStatus != {}` guard (already covered by `any()` returning False on empty iterables).
- **Chart.js memory leak on logout** — Chart instances were not destroyed on logout, leaking canvas memory on re-login. Added cleanup for all 6 chart types.
- **Log stream poll leak on logout** — `_logStreamInterval` used raw `setInterval` bypassing `_registerInterval`, so `_clearAllIntervals()` on logout didn't stop it. Added explicit cleanup.

### Changed
- **README overhaul** — Rewrote with screenshots (dashboard, agents, monitoring, security, infrastructure), emojis, collapsible Docker section, and better visual hierarchy.
- **Troubleshooting docs** — Added 3 new sections: agent commands stuck in queued, dashboard layout corruption, and stale browser cache after updates.
- **`.gitignore`** — Added `.claude/worktrees/`, `.claude/agents/`, `.claude/skills/` to prevent local tooling state from being committed.

### Added
- **Dashboard screenshots** — 7 Playwright-captured screenshots in `docs/images/` for README and documentation.

## [2.1.0] - 2026-03-20

### Added
- Agent v2.1.0 with new commands: `security_scan`, `network_discover`, `discover_services`, `follow_logs`, `stop_stream`, `get_stream`, `endpoint_check`, `verify_backup`, `dns_lookup`, `network_config`, `network_stats`
- Risk-tiered command authorization (low/medium/high) with role-based permissions
- Agent capability registry with version-aware command validation
- Parameter validation for all 32+ command types with regex, length, and denylist checks
- Agent registry SQLite table for persistence across server restarts
- Bulk command support (send to multiple agents at once)
- Command history persistence in SQLite with status tracking

### Changed
- Agent reports now trigger persistence on every report cycle (not just on command completion)

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

## [1.0.0] - 2026-03-17

### Added
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
