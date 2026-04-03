// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
// Noba -- Centralized constants for timing and limit values used across the frontend.

// ── Dashboard SSE / polling ─────────────────────────────────────────────────
export const SSE_HEARTBEAT_TIMEOUT_MS = 15000    // SSE heartbeat timeout before fallback
export const POLLING_INTERVAL_MS = 5000          // dashboard polling interval

// ── Logs view ───────────────────────────────────────────────────────────────
export const LOG_AUTO_REFRESH_MS = 5000          // auto-refresh interval for system logs
export const STREAM_DEFAULT_BACKLOG = 50         // default backlog lines for live stream
export const STREAM_BUFFER_MAX_LINES = 2000      // max lines to keep in live stream buffer

// ── Healing view ────────────────────────────────────────────────────────────
export const HEALING_FETCH_ALL_INTERVAL_MS = 30000  // healing store fetchAll interval

// ── Command palette ─────────────────────────────────────────────────────────
export const CMD_POLL_FIRST_MS = 4000            // first poll after command dispatch
export const CMD_POLL_SECOND_MS = 12000          // second poll
export const CMD_POLL_THIRD_MS = 30000           // third (final) poll

// ── Uptime card ─────────────────────────────────────────────────────────────
export const UPTIME_FETCH_INTERVAL_MS = 30000    // uptime card refresh interval

// ── Remote terminal ─────────────────────────────────────────────────────────
export const TERMINAL_RECONNECT_MS = 3000        // reconnect delay after disconnect

// ── Settings: general tab ───────────────────────────────────────────────────
export const UPDATE_RELOAD_DELAY_MS = 5000       // page reload delay after self-update

// ── Settings: users tab ─────────────────────────────────────────────────────
export const USER_ACTION_MSG_TIMEOUT_MS = 3000   // action message auto-clear timeout

// ── Network devices ─────────────────────────────────────────────────────────
export const NETWORK_DISCOVER_FETCH_DELAY_MS = 3000  // delay before re-fetching after discover

// ── Healing components: query limits ────────────────────────────────────────
export const APPROVAL_QUEUE_LIMIT = 100          // ledger fetch limit in ApprovalQueue
export const LEDGER_TIMELINE_LIMIT = 100         // ledger fetch limit in LedgerTimeline
export const INCIDENT_LIST_LIMIT = 100           // incident query limit
