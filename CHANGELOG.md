# Changelog

All notable changes to NOBA Command Center are documented in this file.

## [Unreleased]

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
