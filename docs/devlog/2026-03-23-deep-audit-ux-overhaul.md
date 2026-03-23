# Session: Deep Audit, UX Overhaul & Release Pipeline

**Date:** 2026-03-23
**Scope:** Backend correctness audit, frontend UX overhaul, self-update system, CI/CD pipeline, documentation rewrite, v2.0.0 release

---

## What Was Done

### Backend Correctness (app.py, db/, workflow_engine.py, runner.py, scheduler.py)

**Critical fixes:**
- `_transfer_lock` converted from `threading.Lock` to `asyncio.Lock` — was blocking the FastAPI event loop. All 8 usages across `agent_store.py`, `app.py`, and `routers/agents.py` updated to `async with`.
- Graph workflow cycle detection added — `_execute_node` now tracks visited nodes and enforces a depth limit of 200, preventing stack overflow from cyclic workflow graphs.
- `JobRunner.submit()` race condition fixed — capacity check and slot registration moved into a single atomic lock scope. Previously two threads could both pass the capacity check simultaneously.
- API key expiry check added — `get_api_key()` was not checking `expires_at`, so expired API keys still authenticated. Added `AND (expires_at IS NULL OR expires_at > ?)`.
- `_execute_delay_node` moved to background thread — was calling `time.sleep()` directly, blocking the entire scheduler thread.

**Infrastructure improvements:**
- Cleanup loop backoff fixed — sleep moved to end of loop so backoff actually affects retry frequency.
- Agent command polling replaced with `threading.Condition` signaling — `_agent_cmd_ready` condition variable added to `agent_store.py`. Producers notify on result arrival, consumers wake instantly instead of busy-waiting with `time.sleep(0.5)`.
- Transfer cleanup optimized — `os.listdir` hoisted outside per-transfer loop, file deletion moved outside the lock.
- Plugin/scheduler startup wrapped in try/except for failure isolation.
- SPA fallback now returns 404 for `api/` paths instead of serving `index.html`.
- Security header matching changed from `startswith()` to exact `not in` check.
- Cache policy split: 1-year for hashed `/assets`, 5-minute for mutable `/static`.
- Health check now uses `execute_write(SELECT 1)` testing connection, lock, and WAL.

**Database improvements:**
- `transaction()` method added to `Database` class for atomic multi-step writes with rollback.
- Missing indexes added: `idx_audit_ts`, `idx_audit_user_action`, `idx_api_keys_hash`.
- `save_user_dashboard` changed from `INSERT OR REPLACE` (which wiped unset columns) to `ON CONFLICT ... COALESCE` upsert.
- `_get_conn` docstring updated with safety warning about lock requirements.

### Frontend UX Overhaul (21 files changed)

**Error handling:**
- `useApi.js` now returns human-readable error messages ("Permission denied", "Connection lost", "Server error") instead of raw "HTTP 403". Includes `TypeError` catch for network failures.
- Toast durations made context-aware: 8s for errors, 6s for warnings, 4s for success.
- 50+ silent `catch {}` blocks replaced with contextual error toasts across SecurityView, LogsView, AgentsView.

**Confirmation dialogs:**
- Global confirm dialog added via Pinia `modals` store — `modals.confirm('message')` returns a Promise, no template refs needed.
- All 16 native `confirm()` calls replaced with themed `ConfirmDialog` across 14 files.
- `App.vue` renders the global confirm modal.

**Empty states:**
- AgentsView: icon + explanation + "Deploy Agent" button when no agents.
- AutomationsView: guidance text + "Create Automation" button, filter-aware messaging.
- HealingView: trust states and effectiveness data explain when data will appear.

**Settings feedback:**
- GeneralTab save/restore/download all use toast notifications instead of mixed `alert()`/inline messages.

**Test fixes:**
- 2 pre-existing LoginView test failures fixed: loading state mock updated for auth store flow, SSO test updated for dynamic provider UI.
- All frontend tests: 91/91 passing.

### Self-Update System

**Backend (`routers/operations.py`):**
- `GET /api/system/update/check` — runs `git fetch`, compares `HEAD..origin/main`, parses remote VERSION from config.py, extracts commit log as changelog.
- `POST /api/system/update/apply` — admin-only. Runs `git pull --ff-only` → `scripts/build-frontend.sh` → `install.sh --auto-approve` → schedules `systemctl --user restart noba-web` after 2s delay.
- Auto-detects repo location via `NOBA_REPO_DIR` env var, `~/noba`, `~/projects/noba`, or source tree relative path.

**Frontend:**
- Glowing accent-colored update pill in header (admin-only, checks every 6 hours).
- Full update UI in Settings → General: current version, remote version, commits behind, scrollable changelog, "Check for Updates" and "Update Now" buttons.
- Confirmation dialog before applying. Auto-reloads page after 5s on restart.

### CI/CD Pipeline

**Workflows rewritten:**
- `test.yml` — now runs pytest (backend), vitest (frontend), and shellcheck in parallel. Was referencing BATS tests and `test-all.sh` that no longer exist.
- `docs.yml` — new workflow for VitePress docs site. GitHub Pages switched from legacy (raw markdown) to Actions deployment. Docs site live at raizenica.github.io/noba.
- `release.yml` — multi-distro package builds: RPM (Fedora container), DEB (dpkg-deb), Arch (makepkg), universal tarball. All uploaded to GitHub Release on tag push.
- `shellcheck.yml` — removed, merged into `test.yml`.
- `rpm-build.yml` — removed, replaced by `release.yml`.

**Cleanup:**
- All failed workflow runs deleted from GitHub.
- ShellCheck warning in `install.sh` fixed (single-item loop flattened).
- Dependabot alert dismissed (esbuild already patched).
- `LICENSE` file created (MIT — was referenced in README but missing).

### Documentation Rewrite

**Fully rewritten:**
- `CONTRIBUTING.md` — was referencing Alpine.js, single-file server.py, BATS tests, `noba-lib.sh`. Now covers FastAPI, Vue 3, pytest, Pinia, ruff.
- `docs/README.md` — was completely obsolete (Alpine.js, admin/admin, placeholder image).
- `docs/user-guide.md` — full rewrite covering all current features (agents, healing, workflows, self-update, 7 themes).

**Updated:**
- `README.md` — removed "homelab" from tagline, added self-update and 7th theme.
- `docs/api.md` — added operator role, API group table, Swagger UI reference.
- `docs/configuration.md` — added missing env vars (NOBA_REPO_DIR, NOBA_REDIS_URL, NOBA_CORS_ORIGINS).
- `docs/troubleshooting.md` — fixed server.py refs, admin/admin refs, version-specific language.
- `docs/index.md`, `docs/package.json`, `docs/.vitepress/config.js` — "homelab" → "infrastructure".
- `noba.spec` — updated for current stack, MIT license, correct description.
- `CHANGELOG.md` — full entry for all changes in this session.

### v2.0.0 Release

Tag `v2.0.0` pushed, release pipeline built all 4 packages:
- `noba-2.0.0.tar.gz` (2.1 MB)
- `noba-2.0.0-1.fc43.noarch.rpm` (771 KB)
- `noba_2.0.0_all.deb` (732 KB)
- `noba-2.0.0-1-any.pkg.tar.zst` (961 KB)

---

## Files Changed

**38 files** in the main audit+UX commit, plus docs, CI, and release files. Total across session: ~55 files.

## Test Results

- Backend: 2187/2187 passed
- Frontend: 91/91 passed
- ShellCheck: clean
- All CI workflows: green
