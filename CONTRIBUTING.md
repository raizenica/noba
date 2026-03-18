# Contributing to NOBA // Command Center

Thank you for your interest in contributing! NOBA is a homelab-focused project and we welcome contributions of all kinds: bug fixes, new integrations, documentation improvements, and more.

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

Be respectful, constructive, and inclusive. This is a homelab project maintained in spare time — patience is appreciated on all sides.

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

### Backend (Python server)

No build step required. The server uses Python stdlib only.

```bash
# Run the server directly during development
python3 share/noba-web/server.py

# Or via the launcher
bash bin/noba-web
```

Environment variables for development:
```bash
export PORT=8080
export NOBA_CONFIG=./data/config/config.yaml
export NOBA_SCRIPT_DIR=./libexec/noba
```

### Frontend

No build step. Edit `share/noba-web/index.html` and `share/noba-web/static/app.js` directly and reload the browser.

### Automation Scripts

```bash
# Test a script with dry-run
bash libexec/backup-to-nas.sh --dry-run --verbose

# Run the full test harness
bash libexec/test-all.sh
```

### Docker development

```bash
docker compose up --build
```

The `docker-compose.yml` mounts `./data/config` into the container for live config editing.

---

## Project Structure

```
noba/
├── bin/
│   ├── noba               # CLI entry point / command router
│   └── noba-web           # Web dashboard launcher
├── libexec/
│   ├── lib/
│   │   └── noba-lib.sh    # Shared Bash library (logging, config, utils)
│   ├── backup-to-nas.sh   # Incremental rsync backup
│   ├── cloud-backup.sh    # rclone cloud sync
│   ├── disk-sentinel.sh   # Disk space monitor
│   ├── config-check.sh    # Dependency / config validator
│   ├── noba-update.sh     # Git pull + system update
│   └── ...                # Other automation scripts
├── share/noba-web/
│   ├── server.py          # Python backend (single file, no deps)
│   ├── index.html         # Frontend SPA (Alpine.js)
│   └── static/
│       ├── app.js         # Alpine.js dashboard component
│       └── style.css      # Theme system
├── systemd/               # Systemd user timer/service units
├── tests/
│   ├── test_checksum.bats # BATS test suite
│   └── test_server.py     # Python unit tests
├── docs/
│   ├── user-guide.md
│   ├── configuration.md
│   ├── api.md
│   └── troubleshooting.md
├── install.sh             # Installer
└── docker-compose.yml
```

---

## Making Changes

### Adding a new automation script

1. Create `libexec/my-script.sh`.
2. Source the shared library at the top:
   ```bash
   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
   source "$SCRIPT_DIR/lib/noba-lib.sh"
   ```
3. Implement test harness compliance (required for CI):
   ```bash
   if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
   if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
       echo "Usage: my-script.sh [OPTIONS]"; exit 0
   fi
   if [[ "${1:-}" == "--version" ]]; then
       echo "my-script.sh version 1.0.0"; exit 0
   fi
   ```
4. Add `--dry-run` and `--verbose` flags where applicable.
5. Add a BATS test in `tests/`.
6. Register the alias in `bin/noba` if appropriate.

### Adding a new dashboard integration

1. Add the data-fetching function in `server.py` following the pattern of existing integrations (e.g. `get_pihole()`):
   - Return a dict with consistent keys
   - Handle errors gracefully (return `None` or an empty dict on failure)
   - Use `TTLCache` for expensive or rate-limited calls
2. Call the function from `collect_stats()` inside the `ThreadPoolExecutor`.
3. Surface the data in the SSE/stats JSON payload.
4. Add the card UI to `index.html` with an `x-show` condition.
5. Add the Alpine.js data properties and fetch logic to `app.js`.
6. Add the URL/key settings to the **Settings → Integrations** tab.
7. Add the integration settings to `WEB_KEYS` in `server.py`.
8. Document the new settings in `docs/configuration.md`.

### Modifying the settings system

The settings flow:
1. Frontend sends `POST /api/settings` with a JSON object.
2. `server.py` writes the values to `config.yaml` using `yq`.
3. On next stats collection, settings are read via `read_yaml_settings()`.

If you add a new setting key, add it to:
- `WEB_KEYS` in `server.py`
- `SETTINGS_KEYS` in `app.js`
- `docs/configuration.md`

---

## Coding Standards

### Bash scripts

- Use `set -euo pipefail` at the top of every script.
- Source `noba-lib.sh` and use its logging functions (`log_info`, `log_error`, etc.) — do not use raw `echo` for status output.
- All scripts must pass `shellcheck -S warning`.
- Use `--dry-run` flag pattern consistently.
- No hardcoded paths — always resolve relative to `SCRIPT_DIR` or read from config.

### Python (server.py)

- No third-party dependencies. Python standard library only.
- Thread safety: use the existing locks (`_tokens_lock`, `users_db_lock`, `_state_lock`).
- Handle all network calls with timeouts and `try/except`.
- Never expose secrets in the stats/SSE payload — only the backend should see API keys.
- New endpoints should follow the existing pattern:
  ```python
  if path == '/api/my-endpoint':
      username, role = authenticate_request(self.headers, qs)
      if not username:
          self._json({'error': 'Unauthorized'}, 401)
          return
      # ... handler logic
      audit_log('my_action', username, 'details', ip)
      self._json({'result': ...})
      return
  ```

### Frontend (JavaScript / HTML)

- Keep it within the Alpine.js `dashboard()` component — no new global state.
- Use the `LIVE_DATA_KEYS` allowlist when merging SSE data.
- No `eval()` or `innerHTML` with untrusted content.
- Test in both light/dark themes and at least two viewport widths.

---

## Testing

### Run Python unit tests

```bash
python3 -m unittest tests/test_server.py -v
```

### Run BATS shell tests

```bash
# Install bats-core if not present
sudo dnf install bats   # or apt install bats

bats tests/
```

### Run ShellCheck

```bash
shellcheck -S warning libexec/*.sh bin/noba bin/noba-web install.sh
```

### Run the full test harness

```bash
bash libexec/test-all.sh --verbose
```

CI runs all of the above on every pull request (see `.github/workflows/`).

---

## Submitting a Pull Request

1. **Ensure tests pass** locally before pushing.
2. **Keep PRs focused** — one feature or fix per PR. Avoid combining unrelated changes.
3. **Write a clear PR description** — explain what, why, and how to test it.
4. **Reference related issues** — use `Closes #123` in the PR description.
5. **Update documentation** if your change adds, removes, or changes user-facing behaviour.

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

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml). Include:
- NOBA version
- Deployment method (Docker / bare-metal)
- Steps to reproduce
- Relevant log output (`~/.local/share/noba-web-server.log`)

---

## Questions?

Open a [GitHub Discussion](https://github.com/raizenica/noba/discussions) for general questions, ideas, and show-and-tell. Reserve Issues for confirmed bugs and concrete feature requests.
