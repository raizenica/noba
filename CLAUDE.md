# NOBA Command Center

## Stack
- **Backend**: FastAPI (Python 3.11+), SQLite WAL, psutil, httpx
- **Frontend**: Vue 3 + Vite + Vue Router + Pinia, Chart.js
- **Scripts**: Bash (libexec/)
- **Build step**: `cd share/noba-web/frontend && npm run build` (output committed to `static/dist/`)

## Project Layout
```
share/noba-web/server/       → Python backend modules (13 routers)
share/noba-web/frontend/     → Vue 3 source (src/views/, src/components/, src/stores/)
share/noba-web/static/dist/  → Built Vue app (committed, served by FastAPI)
share/noba-web/static/       → Legacy static assets (favicon, style.css)
scripts/build-frontend.sh    → Frontend build script (npm ci + vite build)
libexec/                     → Shell scripts
install.sh                   → Installer
Dockerfile                   → Docker build
tests/                       → pytest backend test suite
```

## Coding Conventions

### Python
- Run `ruff check --fix` after editing `.py` files
- Use `from __future__ import annotations` in all modules
- Threading: always use locks when mutating module-level state
- Auth: `Depends(_get_auth)` for read, `Depends(_require_operator)` for controls, `Depends(_require_admin)` for admin
- Catch `HTTPException` before generic `Exception` in route handlers
- Keep integration functions self-contained (no shared mutable state between them)
- Use dedicated httpx clients for integrations that set cookies (UniFi, qBittorrent)
- DB functions use `(conn, lock, ...)` pattern in `db/automations.py`, with delegation wrappers in `db/core.py`

### JavaScript (Vue 3)
- Vue 3 `<script setup>` with Composition API
- Pinia stores for shared state (auth, dashboard, settings, notifications, approvals, modals)
- `useApi()` composable for authenticated API calls
- `useIntervals()` composable for interval lifecycle management
- `v-model.number` for numeric select inputs
- `||0` guards on numeric values from API that could be null/undefined

### HTML/CSS
- Modal structure: `AppModal` component with `show` prop, `close` emit, `#footer` slot
- Role gating: `v-if="authStore.isOperator"` or `v-if="authStore.isAdmin"`
- Use existing CSS classes from `global.css` — check before inventing new ones
- 6 themes via CSS variables (default, dracula, nord, tokyo, catppuccin, gruvbox)

### Shell Scripts
- Never `source` untrusted files — use safe key-value parsing
- Always add cleanup traps for temp files
- Use `--verbose` flag pattern (default quiet)

## Testing
```bash
# Run all backend tests
pytest tests/ -v

# Run specific test file
pytest tests/test_auth.py -v

# Syntax check all Python
ruff check share/noba-web/server/

# Run frontend tests
cd share/noba-web/frontend && npm test

# Build frontend
cd share/noba-web/frontend && npm run build
```

## Protected Files — DO NOT EDIT
- `~/.config/noba-web/auth.conf` — legacy auth credentials
- `~/.config/noba-web/users.conf` — user database
- `~/.local/share/noba-history.db` — SQLite database
- `.env` files, `*.db` files, credential files

## Common Pitfalls
- SSE (EventSource) cannot set custom headers — use `_get_auth_sse` which falls back to query param token
- `sys.stdout.reconfigure` crashes in non-standard environments — always wrap in try/except
- SQLite VACUUM must run outside any transaction — acquire lock separately after commit
- localStorage `select` values are strings — use `v-model.number` or parseInt
- Vue Router uses hash-based history (`createWebHashHistory`) — URLs are `/#/dashboard`
- FastAPI SPA fallback route (`/{rest:path}`) must be registered AFTER all API routes
