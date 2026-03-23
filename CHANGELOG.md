# Changelog

All notable changes to NOBA Command Center are documented in this file.

## [Unreleased]

### Added
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
