# Contributing to NOBA // Command Center

Thank you for your interest in contributing! NOBA is an open-source infrastructure management platform and we welcome contributions of all kinds: bug fixes, new integrations, documentation improvements, and more.

---

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Getting Started](#getting-started)
3. [Development Setup](#development-setup)
4. [Project Structure](#project-structure)
5. [Making Changes](#making-changes)
6. [Coding Standards](#coding-standards)
7. [Testing](#testing)
8. [Submitting a Pull Request](#submitting-a-pull-request)
9. [Reporting Bugs](#reporting-bugs)

---

## Code of Conduct

Be respectful, constructive, and inclusive. Patience is appreciated on all sides.

---

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork:
   ```bash
   git clone https://github.com/<your-username>/noba.git
   cd noba
   ```
3. **Create a branch** for your work:
   ```bash
   git checkout -b fix/my-bug-description
   # or
   git checkout -b feat/my-new-feature
   ```

---

## Development Setup

### Backend (FastAPI + Python 3.11+)

```bash
# Install Python dependencies
pip install fastapi 'uvicorn[standard]' psutil pyyaml httpx

# Run the server
python3 share/noba-web/server/main.py
# or via the installed launcher
noba-web
```

Environment variables for development:
```bash
export PORT=8080
export NOBA_CONFIG=~/.config/noba/config.yaml
```

### Frontend (Vue 3 + Vite)

```bash
cd share/noba-web/frontend

# Install dependencies
npm ci

# Dev server with hot reload
npm run dev

# Build for production
npm run build
# Output goes to share/noba-web/static/dist/
```

### Full install (bare metal)

```bash
bash install.sh
```

### Docker

```bash
docker compose up --build
```

---

## Project Structure

```
noba/
├── share/noba-web/
│   ├── server/                → FastAPI backend (13 routers, 235+ API routes)
│   │   ├── app.py             → Application setup, lifespan, middleware
│   │   ├── routers/           → API route modules
│   │   ├── db/                → SQLite database layer (split by domain)
│   │   ├── healing/           → Self-healing pipeline (20+ modules)
│   │   ├── integrations/      → Integration platform handlers
│   │   ├── metrics/           → System metric collectors
│   │   ├── auth.py            → Authentication, tokens, rate limiting
│   │   ├── config.py          → Constants and configuration
│   │   ├── collector.py       → Background stats collector
│   │   ├── scheduler.py       → Cron scheduler, endpoint checker, drift checker
│   │   ├── workflow_engine.py → Workflow execution engine
│   │   └── runner.py          → Concurrent job runner
│   ├── frontend/
│   │   ├── src/
│   │   │   ├── views/         → Page-level Vue components (10 views)
│   │   │   ├── components/    → Reusable components (80+)
│   │   │   ├── stores/        → Pinia state stores
│   │   │   ├── composables/   → Vue composables (useApi, useIntervals, useHealing)
│   │   │   └── assets/styles/ → Global CSS with theme variables
│   │   ├── package.json
│   │   └── vite.config.js
│   └── static/dist/           → Built Vue app (committed, served by FastAPI)
├── share/noba-agent/          → Remote agent + installers (Linux, Windows)
├── libexec/                   → Shell automation scripts
├── scripts/                   → Build and utility scripts
├── tests/                     → pytest backend test suite (2187+ tests)
├── install.sh                 → Installer
├── Dockerfile                 → Docker build
└── docs/                      → Documentation
```

---

## Making Changes

### Adding a new API endpoint

1. Add the route to the appropriate router in `share/noba-web/server/routers/`.
2. Use proper auth decorators:
   - `Depends(_get_auth)` for read access
   - `Depends(_require_operator)` for control operations
   - `Depends(_require_admin)` for admin-only
3. Add audit logging for state-changing operations.
4. Add tests in `tests/`.

### Adding a new dashboard integration

1. Add the integration handler in `share/noba-web/server/integrations/`.
2. Register it in `share/noba-web/server/healing/integration_registry.py` if it supports heal operations.
3. Add the card component in `share/noba-web/frontend/src/components/cards/`.
4. Add a card template in `share/noba-web/frontend/src/data/cardTemplates.js`.
5. Document new settings in `docs/configuration.md`.

### Adding a new frontend view

1. Create the view in `share/noba-web/frontend/src/views/`.
2. Add the route in `share/noba-web/frontend/src/router/index.js`.
3. Add the sidebar link in `share/noba-web/frontend/src/components/layout/AppSidebar.vue`.
4. Use `<script setup>` with Composition API.
5. Use `useApi()` for authenticated API calls.
6. Use the notifications store for user feedback — never use `alert()` or native `confirm()`.

---

## Coding Standards

### Python

- Run `ruff check --fix` after editing `.py` files.
- Use `from __future__ import annotations` in all modules.
- Threading: always use locks when mutating module-level state.
- Catch `HTTPException` before generic `Exception` in route handlers.
- Use `db.execute_write()` or `db.transaction()` for writes — never access `_get_conn()` directly.

### JavaScript (Vue 3)

- Vue 3 `<script setup>` with Composition API — no Options API.
- Pinia stores for shared state.
- `useApi()` composable for all authenticated API calls.
- `useModalsStore().confirm()` for destructive action confirmation — never use native `confirm()`.
- Toast notifications via `useNotificationsStore().addToast()` — never use `alert()`.
- `v-model.number` for numeric select inputs.

### HTML / CSS

- Use existing CSS classes from `global.css` — check before inventing new ones.
- 7 themes via CSS variables (default, dracula, nord, tokyo, catppuccin, gruvbox, bloodmoon).
- Role gating: `v-if="authStore.isOperator"` or `v-if="authStore.isAdmin"`.

### Shell Scripts

- `set -euo pipefail` at the top.
- Never `source` untrusted files — use safe key-value parsing.
- Add cleanup traps for temp files.
- Use `--verbose` flag pattern (default quiet).

---

## Testing

### Backend (pytest)

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_auth.py -v

# Lint all Python
ruff check share/noba-web/server/
```

### Frontend (Vitest)

```bash
cd share/noba-web/frontend

# Run all tests
npm test

# Run specific test
npx vitest run src/__tests__/stores/auth.test.js
```

### Build verification

```bash
# Build frontend
cd share/noba-web/frontend && npm run build
```

All tests must pass before submitting a PR.

---

## Submitting a Pull Request

1. **Ensure tests pass** locally before pushing.
2. **Keep PRs focused** — one feature or fix per PR.
3. **Write a clear PR description** — explain what, why, and how to test it.
4. **Reference related issues** — use `Closes #123` in the PR description.
5. **Update documentation** if your change affects user-facing behaviour.
6. **Update CHANGELOG.md** with a summary of your changes.

### PR title conventions

| Prefix | Use for |
|--------|---------|
| `fix:` | Bug fixes |
| `feat:` | New features |
| `docs:` | Documentation only |
| `chore:` | Maintenance, CI, dependencies |
| `refactor:` | Code restructuring without behaviour change |
| `test:` | Adding or improving tests |

---

## Reporting Bugs

Open an issue with:
- NOBA version (shown in Settings or `GET /api/system/info`)
- Deployment method (Docker / bare-metal)
- Steps to reproduce
- Browser console errors (if frontend issue)
- Relevant log output (`journalctl --user -u noba-web`)

---

## Questions?

Open a [GitHub Discussion](https://github.com/raizenica/noba-ce/discussions) for general questions, ideas, and show-and-tell. Reserve Issues for confirmed bugs and concrete feature requests.
