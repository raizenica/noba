# Changelog

All notable changes to NOBA Command Center are documented in this file.

## [Unreleased]

### Fixed
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

### Changed
- **README** — Added Docker section with docker compose instructions, volume table, port/TZ customization, and Podman note.
- **Troubleshooting docs** — Added 3 new sections: agent commands stuck in queued, dashboard layout corruption, and stale browser cache after updates.
- **`.gitignore`** — Added `.claude/worktrees/`, `.claude/agents/`, `.claude/skills/` to prevent local tooling state from being committed.

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
