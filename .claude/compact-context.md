# NOBA Command Center — Compact Context

## Project
- **Stack**: FastAPI (Python) backend + Alpine.js frontend, single-page dashboard
- **Purpose**: Homelab monitoring/automation suite (Nobara Linux)
- **Repo**: github.com/raizenica/noba-ce, branch: main

## Architecture
- `share/noba-web/server/` — Python backend (app.py, auth.py, db.py, collector.py, metrics.py, integrations.py, alerts.py, plugins.py, config.py, yaml_config.py)
- `share/noba-web/static/` — JS frontend (app.js, auth-mixin.js, actions-mixin.js)
- `share/noba-web/index.html` — Full UI template (Alpine.js)
- `libexec/` — Shell scripts (backup, cloud, disk, organize, etc.)
- `install.sh` — Installer

## Key Patterns
- 3-tier RBAC: viewer (read-only), operator (controls), admin (full)
- Backend auth: `Depends(_get_auth)`, `Depends(_require_operator)`, `Depends(_require_admin)`
- Frontend: Alpine.js with spread mixins (`...authMixin()`, `...actionsMixin()`)
- SQLite WAL mode with threading locks for all writes
- ThreadPoolExecutor for concurrent stats collection
- SSE for live data, polling fallback
- Settings stored in YAML (`~/.config/noba/config.yaml`)

## Current State
- All 5 improvement rounds + feature round complete (PR #1-#6 merged)
- 38 bugs fixed across 2 squash rounds
- Features: plugin system, multi-user roles, 10+ integrations, PWA, alerts, anomaly detection, session management, capacity planning
