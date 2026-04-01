# Enterprise → CE Back-Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Back-port 52 bug fixes, security hardening, and UX improvements from the enterprise repo to the CE edition

**Architecture:** All fixes are adapted to CE's monolithic file structure (auth.py, admin.py stay as single files). No enterprise-only features (multi-tenancy, RBAC, license, AD sync, SAML extensions, PostgreSQL, branding). Each task produces a self-contained commit.

**Tech Stack:** Python 3.11+ (FastAPI, SQLite), Vue 3 (Vite, Pinia), Bash (libexec/)

**Reference:** Enterprise repo at `~/noba-enterprise/` for verification

---

## Task 1: PBKDF2 Security Upgrade + TOTP Fix

**Files:**
- Modify: `share/noba-web/server/auth.py:24,28-32,49-68,83-89`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Update PBKDF2 iteration count**

In `share/noba-web/server/auth.py`, change line 24:

```python
# OLD:
_PBKDF2_ITERS = 200_000

# NEW:
_PBKDF2_ITERS = 600_000  # OWASP minimum for PBKDF2-HMAC-SHA256
```

- [ ] **Step 2: Update pbkdf2_hash to include iteration count in format**

In `share/noba-web/server/auth.py`, change line 32 (inside `pbkdf2_hash`):

```python
# OLD:
    return f"pbkdf2:{salt}:{dk.hex()}"

# NEW:
    return f"pbkdf2:{_PBKDF2_ITERS}:{salt}:{dk.hex()}"
```

- [ ] **Step 3: Replace verify_password with backward-compatible version**

In `share/noba-web/server/auth.py`, replace lines 49-68 (entire `verify_password` function):

```python
def verify_password(stored: str, password: str, *, username: str = "") -> bool:
    if not stored:
        return False
    if stored.startswith("pbkdf2:"):
        parts = stored.split(":")
        if len(parts) == 4:
            # New format: pbkdf2:iterations:salt:hash
            _, iters_str, salt, expected = parts
            iters = int(iters_str)
        elif len(parts) == 3:
            # Legacy format: pbkdf2:salt:hash (200k iterations)
            _, salt, expected = parts
            iters = 200_000
        else:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iters)
        match = secrets.compare_digest(expected, dk.hex())
        # Auto-upgrade to current iteration count on successful login
        if match and iters < _PBKDF2_ITERS and username:
            try:
                new_hash = pbkdf2_hash(password)
                users.update_password(username, new_hash)
                logging.getLogger("noba").info(
                    "Upgraded PBKDF2 iterations for %s: %d→%d",
                    username, iters, _PBKDF2_ITERS,
                )
            except Exception:
                pass
        return match
    # legacy sha256 format: salt:hexhash — auto-migrate to pbkdf2 on success
    if ":" not in stored:
        return False
    salt, expected = stored.split(":", 1)
    actual = hashlib.sha256((salt + password).encode()).hexdigest()
    if secrets.compare_digest(expected, actual):
        if username:
            _migrate_legacy_hash(username, password)
        return True
    return False
```

- [ ] **Step 4: Fix generate_totp_secret to fail-fast**

In `share/noba-web/server/auth.py`, replace lines 83-89:

```python
def generate_totp_secret() -> str:
    """Generate a new TOTP secret for 2FA setup."""
    try:
        import pyotp  # noqa: PLC0415
        return pyotp.random_base32()
    except ImportError as exc:
        raise RuntimeError(
            "pyotp package is required for TOTP 2FA but not installed"
        ) from exc
```

- [ ] **Step 5: Run tests**

Run: `cd ~/noba && python -m pytest tests/test_auth.py -v -x`
Expected: All auth tests pass. Existing hashes in 3-part format still verify correctly.

- [ ] **Step 6: Ruff check**

Run: `cd ~/noba && ruff check share/noba-web/server/auth.py --fix`
Expected: Clean

- [ ] **Step 7: Commit**

```bash
git add share/noba-web/server/auth.py
git commit -m "security: upgrade PBKDF2 to 600k iterations (OWASP minimum)

- Hash format now includes iteration count: pbkdf2:{iters}:{salt}:{hash}
- Backward-compatible with legacy 3-part format (200k assumed)
- Auto-upgrades password hash on successful login
- generate_totp_secret fails fast when pyotp missing"
```

---

## Task 2: Security Headers + Exception Suppression + Error Handlers

**Files:**
- Modify: `share/noba-web/server/config.py:144-156`
- Modify: `share/noba-web/server/deps.py:37,47,54,58,88,99`
- Modify: `share/noba-web/server/app.py:7,212-243`

- [ ] **Step 1: Harden security headers in config.py**

In `share/noba-web/server/config.py`, replace lines 144-156 (entire `SECURITY_HEADERS` dict):

```python
SECURITY_HEADERS = {
    "X-Content-Type-Options":            "nosniff",
    "X-Frame-Options":                   "DENY",
    "X-XSS-Protection":                  "0",
    "Referrer-Policy":                   "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' wss: ws:; "
        "frame-ancestors 'none'"
    ),
    "Permissions-Policy":                "geolocation=(), microphone=(), camera=()",
    "Strict-Transport-Security":         "max-age=63072000; includeSubDomains",
    "Cross-Origin-Opener-Policy":        "same-origin",
    "Cross-Origin-Embedder-Policy":      "credentialless",
    "Cross-Origin-Resource-Policy":      "same-site",
}
```

- [ ] **Step 2: Add `from None` to deps.py exception raises**

In `share/noba-web/server/deps.py`:

Line 37 — change:
```python
        raise HTTPException(400, f"Invalid {name} parameter")
```
to:
```python
        raise HTTPException(400, f"Invalid {name} parameter") from None
```

Line 54 — change:
```python
        raise HTTPException(413, "Request body too large")
```
to:
```python
        raise HTTPException(413, "Request body too large") from None
```

Line 58 — change:
```python
        raise HTTPException(400, "Invalid JSON")
```
to:
```python
        raise HTTPException(400, "Invalid JSON") from None
```

Line 88 (async handle_errors) — change:
```python
                raise HTTPException(status_code=500, detail="Internal server error")
```
to:
```python
                raise HTTPException(status_code=500, detail="Internal server error") from None
```

Line 99 (sync handle_errors) — change:
```python
                raise HTTPException(status_code=500, detail="Internal server error")
```
to:
```python
                raise HTTPException(status_code=500, detail="Internal server error") from None
```

- [ ] **Step 3: Fix client IP fallback in deps.py**

Line 47 — change:
```python
    return request.client.host if request.client else "0.0.0.0"
```
to:
```python
    return request.client.host if request.client else "unknown"
```

- [ ] **Step 4: Add global exception handlers in app.py**

In `share/noba-web/server/app.py`, add after the import of `HTTPException` (or add `HTTPException` to the FastAPI import on line 10), then add these handlers after the `app = FastAPI(...)` creation (after the lifespan block, before middleware):

First, update line 10 to ensure HTTPException is imported:
```python
from fastapi import FastAPI, HTTPException, Request
```

Then add after the `app = FastAPI(...)` line (find it, it's around line 246-250):

```python
@app.exception_handler(500)
async def _handle_500(request: Request, exc: Exception):
    logging.getLogger("noba").error("Unhandled 500: %s %s — %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(422)
async def _handle_422(request: Request, exc: Exception):
    logging.getLogger("noba").warning("Validation error: %s %s — %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=422, content={"detail": "Validation error"})
```

Also add `JSONResponse` import near line 12:
```python
from fastapi.responses import FileResponse, JSONResponse
```

- [ ] **Step 5: Fix shutdown ordering in app.py**

In `share/noba-web/server/app.py`, update the imports on line 7 to include `suppress`:
```python
from contextlib import asynccontextmanager, suppress
```

Then replace the shutdown section (lines 212-243) with flag-first ordering:

```python
    yield
    # Signal collector threads FIRST to prevent port-bind on restart
    get_shutdown_flag().set()
    # Close HTTP client early
    with suppress(Exception):
        from .integrations import _client as _http_client
        _http_client.close()
    _cleanup_task.cancel()
    _transfer_cleanup_task.cancel()
    for component in [rss_watcher, endpoint_checker, drift_checker, fs_watcher, scheduler]:
        with suppress(Exception):
            component.stop()
    job_runner.shutdown()
    plugin_manager.stop()
    db.audit_log("system_stop", "system", "Server stopping")
    # Close all agent WebSocket connections
    from .agent_store import _agent_websockets, _agent_ws_lock
    with _agent_ws_lock:
        ws_list = list(_agent_websockets.items())
        _agent_websockets.clear()
    for _ws_hostname, ws_conn in ws_list:
        with suppress(Exception):
            await ws_conn.close(code=1001, reason="Server shutting down")
    with suppress(Exception):
        os.unlink(PID_FILE)
```

- [ ] **Step 6: Run tests + ruff**

Run: `cd ~/noba && ruff check share/noba-web/server/config.py share/noba-web/server/deps.py share/noba-web/server/app.py --fix`
Run: `cd ~/noba && python -m pytest tests/ -v -x --timeout=60`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add share/noba-web/server/config.py share/noba-web/server/deps.py share/noba-web/server/app.py
git commit -m "security: harden headers, exception handling, shutdown ordering

- OWASP security headers: X-Frame-Options DENY, HSTS, COOP, COEP, CORP
- CSP frame-ancestors 'none' prevents clickjacking
- from None on all deps.py exception raises (info disclosure)
- Client IP fallback 0.0.0.0 → unknown
- Global 500/422 handlers log detail, return generic message
- Shutdown flag set FIRST to prevent port-bind failures"
```

---

## Task 3: Hostname Validation + Error Sanitization Across All Routers

**Files:**
- Modify: `share/noba-web/server/routers/agents.py:265-266,381-384`
- Modify: `share/noba-web/server/routers/integrations.py` (11 lines)
- Modify: `share/noba-web/server/routers/operations.py` (4 lines)
- Modify: `share/noba-web/server/routers/infrastructure.py` (8 lines)
- Modify: `share/noba-web/server/routers/intelligence.py` (5 lines)
- Modify: `share/noba-web/server/routers/containers.py` (6 lines)
- Modify: `share/noba-web/server/routers/dashboards.py` (2 lines)
- Modify: `share/noba-web/server/collector.py:321,324`

- [ ] **Step 1: Add hostname validation to agents.py**

In `share/noba-web/server/routers/agents.py`, ensure `import re` is present in the imports section (add if missing).

At line 265-266 (report endpoint), add validation after hostname truncation:
```python
    hostname = body.get("hostname", "unknown")[:253]
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$', hostname):
        raise HTTPException(400, "Invalid hostname")
    body["_received"] = time.time()
```

At line 382 (WebSocket connect), change:
```python
    if not hostname:
        await ws.close(code=4002, reason="No hostname")
```
to:
```python
    if not hostname or not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,252}$', hostname):
        await ws.close(code=4002, reason="Invalid or missing hostname")
```

- [ ] **Step 2: Add `from None` to integrations.py (11 raises)**

In `share/noba-web/server/routers/integrations.py`, add ` from None` to the end of each of these lines:

- Line 39: `raise HTTPException(502, "Failed to fetch snapshot")` → append ` from None`
- Line 145: `raise HTTPException(502, f"HA service call failed: {e}")` → change to `raise HTTPException(502, "HA service call failed") from None` and add `logger.error("HA service call failed: %s", e)` on the line before
- Line 205: `raise HTTPException(502, f"HA toggle failed: {e}")` → change to `raise HTTPException(502, "HA toggle failed") from None` and add `logger.error("HA toggle failed: %s", e)` before
- Line 228: `raise HTTPException(502, f"Scene activation failed: {e}")` → change to `raise HTTPException(502, "Scene activation failed") from None` and add `logger.error("Scene activation failed: %s", e)` before
- Line 260: `raise HTTPException(502, f"Pi-hole toggle failed: {e}")` → change to `raise HTTPException(502, "Pi-hole toggle failed") from None` and add `logger.error("Pi-hole toggle failed: %s", e)` before
- Line 335: `raise HTTPException(504, "Command timed out")` → append ` from None`
- Line 337: `raise HTTPException(424, "rclone not found")` → append ` from None`
- Line 354: `raise HTTPException(424, "rclone not found")` → append ` from None`
- Line 382: `raise HTTPException(504, "Connection timed out (15s)")` → append ` from None`
- Line 384: `raise HTTPException(424, "rclone not found on this system")` → append ` from None`
- Line 389: `raise HTTPException(500, "Cloud test error")` → change to `raise HTTPException(500, "Cloud test error") from None` and add `logger.error("Cloud test error: %s", e)` before

Ensure `logger = logging.getLogger("noba")` exists near the top of the file. Add `import logging` if missing.

- [ ] **Step 3: Add `from None` to operations.py (4 raises)**

- Line 162: `raise HTTPException(400, "Invalid regex pattern")` → append ` from None`
- Line 169: `raise HTTPException(504, "Journal query timed out")` → append ` from None`
- Line 838: `raise HTTPException(500, "Update step timed out")` → append ` from None`
- Line 841: `raise HTTPException(500, f"Update failed: {exc}")` → change to:
  ```python
  logger.error("System update failed: %s", exc)
  raise HTTPException(500, "Update failed — check server logs") from None
  ```

- [ ] **Step 4: Add `from None` to infrastructure.py (8 raises) + sanitize messages**

- Line 88: append ` from None`
- Line 238: `raise HTTPException(502, f"K8s API error: {e}")` → `logger.error("K8s API error: %s", e)` + `raise HTTPException(502, "K8s API error") from None`
- Line 286: same pattern as 238
- Line 315: `raise HTTPException(502, f"K8s log fetch failed: {e}")` → `logger.error(...)` + `raise HTTPException(502, "K8s log fetch failed") from None`
- Line 347: same pattern as 238
- Line 379: `raise HTTPException(502, f"K8s scale failed: {e}")` → `logger.error(...)` + `raise HTTPException(502, "K8s scale failed") from None`
- Line 457: `raise HTTPException(502, f"Proxmox API error: {e}")` → `logger.error(...)` + `raise HTTPException(502, "Proxmox API error") from None`
- Line 490: `raise HTTPException(502, f"Snapshot creation failed: {e}")` → `logger.error(...)` + `raise HTTPException(502, "Snapshot creation failed") from None`

- [ ] **Step 5: Add `from None` to intelligence.py (5 raises) + sanitize**

- Line 429: `raise HTTPException(502, f"LLM request failed: {e}")` → `logger.error("LLM request failed: %s", e)` + `raise HTTPException(502, "LLM request failed") from None`
- Lines 468, 500, 539: same pattern
- Line 572: `raise HTTPException(502, f"LLM connection test failed: {e}")` → `logger.error(...)` + `raise HTTPException(502, "LLM connection test failed") from None`

- [ ] **Step 6: Add `from None` to containers.py (6 raises)**

- Line 51: append ` from None`
- Line 73: append ` from None`
- Line 151: append ` from None`
- Line 216: append ` from None`
- Line 231: append ` from None`
- Line 253: append ` from None`

- [ ] **Step 7: Add `from None` to dashboards.py (2 raises)**

- Line 41: append ` from None`
- Line 76: append ` from None`

- [ ] **Step 8: Sanitize collector.py error messages**

In `share/noba-web/server/collector.py`:

- Line 321: `return {"status": "unauthorized", "error": str(e)}` → `return {"status": "unauthorized", "error": "Configuration error"}`
- Line 324: `return {"status": "offline", "error": str(e)}` → `return {"status": "offline", "error": "Connection failed"}`

- [ ] **Step 9: Run tests + ruff on all changed files**

Run: `cd ~/noba && ruff check share/noba-web/server/routers/agents.py share/noba-web/server/routers/integrations.py share/noba-web/server/routers/operations.py share/noba-web/server/routers/infrastructure.py share/noba-web/server/routers/intelligence.py share/noba-web/server/routers/containers.py share/noba-web/server/routers/dashboards.py share/noba-web/server/collector.py --fix`
Run: `cd ~/noba && python -m pytest tests/ -v -x --timeout=60`
Expected: All pass

- [ ] **Step 10: Commit**

```bash
git add share/noba-web/server/routers/agents.py share/noba-web/server/routers/integrations.py share/noba-web/server/routers/operations.py share/noba-web/server/routers/infrastructure.py share/noba-web/server/routers/intelligence.py share/noba-web/server/routers/containers.py share/noba-web/server/routers/dashboards.py share/noba-web/server/collector.py
git commit -m "security: hostname validation + error sanitization across all routers

- Hostname regex on WebSocket connect and agent report endpoint
- from None on 36 HTTPException raises across 6 routers
- Error messages sanitized: log detail server-side, return generic to client
- collector.py error messages obfuscated"
```

---

## Task 4: Agent Deploy Hardening

**Files:**
- Modify: `share/noba-web/server/routers/agent_deploy.py:104-106,185-189,204-269`

- [ ] **Step 1: Fix install-script endpoint localhost detection**

In `share/noba-web/server/routers/agent_deploy.py`, replace lines 104-106:

```python
# OLD:
    host = request.headers.get("X-Forwarded-Host", request.headers.get("Host", "localhost:8080"))
    scheme = request.headers.get("X-Forwarded-Proto", "http")
    server_url = f"{scheme}://{host}"

# NEW:
    cfg = _agents_mod.read_yaml_settings()
    server_url = cfg.get("serverUrl", "").strip()
    if not server_url:
        host = request.headers.get("X-Forwarded-Host", request.headers.get("Host", ""))
        scheme = "https" if cfg.get("sslEnabled") else request.headers.get("X-Forwarded-Proto", "http")
        if host:
            host_part = host.split(":")[0]
            if host_part in ("localhost", "127.0.0.1", "::1"):
                raise HTTPException(400,
                    "Cannot generate install script when accessing via localhost. "
                    "Set 'serverUrl' in Settings or access NOBA via its network address.")
            server_url = f"{scheme}://{host}"
        else:
            raise HTTPException(400, "Server URL could not be determined.")
```

- [ ] **Step 2: Fix deploy endpoint localhost detection + scheme**

Replace lines 185-189:

```python
# OLD:
    server_url = cfg.get("serverUrl", "").strip()
    if not server_url:
        host_header = request.headers.get("Host", "localhost:8080")
        server_url = f"http://{host_header}"

# NEW:
    server_url = body.get("server_url", "").strip() or cfg.get("serverUrl", "").strip()
    if not server_url:
        host_header = request.headers.get("Host", "")
        scheme = "https" if cfg.get("sslEnabled") else "http"
        if host_header:
            host_part = host_header.split(":")[0]
            if host_part in ("localhost", "127.0.0.1", "::1"):
                raise HTTPException(400,
                    "Cannot deploy agents when accessing NOBA via localhost. "
                    "Enter your server's reachable address in the Server URL field "
                    "(e.g. https://noba.example.com:8080).")
            server_url = f"{scheme}://{host_header}"
        else:
            raise HTTPException(400, "Server URL is required for agent deployment.")
```

- [ ] **Step 3: Add SSL verify detection + SSH config fix**

Before the `_ssh_common` line (around line 204), add:

```python
    # Determine if agent should skip SSL verification (IP-based URLs can't match domain certs)
    try:
        from urllib.parse import urlparse as _urlparse
        _host = _urlparse(server_url).hostname or ""
        _agent_verify_ssl = not bool(re.match(r'^\d+\.\d+\.\d+\.\d+$', _host))
    except Exception:
        _agent_verify_ssl = True
```

Change the `_ssh_common` line to add `-F /dev/null`:
```python
    _ssh_common = ["-F", "/dev/null", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
```

Ensure `import re` is at the top of the file.

- [ ] **Step 4: Replace install_cmds with preflight checks + enhanced deployment**

Replace the `install_cmds` string (lines ~222-249) with:

```python
    install_cmds = f"""
set -e

# ── Pre-flight checks ────────────────────────────────────────────────
PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
if [ -z "$PYTHON" ]; then
    echo "PREFLIGHT_FAIL: python3 not found on this host"
    exit 1
fi
PY_VER=$($PYTHON --version 2>&1)
echo "PREFLIGHT_OK: $PY_VER at $PYTHON"

if [ "$(id -u)" -ne 0 ]; then
    if ! sudo -n true 2>/dev/null; then
        echo "PREFLIGHT_FAIL: sudo access required but not available (try deploying as root)"
        exit 1
    fi
fi

if systemctl is-active noba-agent >/dev/null 2>&1; then
    echo "DEPLOY_INFO: stopping existing agent"
    sudo systemctl stop noba-agent 2>/dev/null || true
fi

# ── Install ──────────────────────────────────────────────────────────
sudo mkdir -p /opt/noba-agent
sudo cp /tmp/noba-agent.pyz /opt/noba-agent/agent.pyz
sudo chmod +x /opt/noba-agent/agent.pyz

command -v apt-get >/dev/null && sudo apt-get install -y python3-psutil 2>/dev/null || true
command -v dnf >/dev/null && sudo dnf install -y python3-psutil 2>/dev/null || true
command -v apk >/dev/null && sudo apk add --no-cache py3-psutil 2>/dev/null || true

# ── Configure ────────────────────────────────────────────────────────
sudo tee /etc/noba-agent.yaml > /dev/null <<AGENTCFG
server: {shlex.quote(server_url)}
api_key: {shlex.quote(agent_key)}
interval: 30
hostname: $(hostname)
verify_ssl: {"true" if _agent_verify_ssl else "false"}
AGENTCFG

sudo tee /etc/systemd/system/noba-agent.service > /dev/null <<SVC
[Unit]
Description=NOBA Agent
After=network-online.target
[Service]
Type=simple
ExecStart=$PYTHON /opt/noba-agent/agent.pyz --config /etc/noba-agent.yaml
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
SVC

sudo systemctl daemon-reload
sudo systemctl enable --now noba-agent 2>&1

# ── Verify ───────────────────────────────────────────────────────────
sleep 2
if systemctl is-active noba-agent >/dev/null 2>&1; then
    echo "AGENT_STATUS: active"
else
    echo "AGENT_STATUS: failed"
    journalctl -u noba-agent -n 5 --no-pager 2>/dev/null || true
fi
"""
```

- [ ] **Step 5: Update response handling with preflight detection + connectivity check**

Replace the result-handling block (lines ~250-269) with:

```python
    result = await asyncio.to_thread(
        subprocess.run,
        ssh_cmd + [target, "bash", "-s"],
        input=install_cmds, capture_output=True, text=True,
        timeout=90, env=env,
    )
    output = result.stdout + result.stderr

    # Check for pre-flight failures
    if "PREFLIGHT_FAIL:" in output:
        fail_msg = ""
        for line in output.splitlines():
            if "PREFLIGHT_FAIL:" in line:
                fail_msg = line.split("PREFLIGHT_FAIL:", 1)[1].strip()
                break
        db.audit_log("agent_deploy", username, f"host={target_host} preflight_fail={fail_msg}", ip)
        return {"status": "error", "step": "preflight", "error": fail_msg}

    success = "AGENT_STATUS: active" in output

    # Post-deploy connectivity check
    connectivity = ""
    if success:
        try:
            check_cmd = f"curl -ksf --connect-timeout 5 {shlex.quote(server_url)}/health 2>&1 || echo UNREACHABLE"
            check_result = await asyncio.to_thread(
                subprocess.run,
                ssh_cmd + [target, "bash", "-c", check_cmd],
                capture_output=True, text=True, timeout=15, env=env,
            )
            if "UNREACHABLE" in check_result.stdout or check_result.returncode != 0:
                connectivity = (
                    f"Agent installed but cannot reach {server_url} from the remote host. "
                    f"Check firewall rules, DNS resolution, and that the server URL is correct."
                )
        except Exception:
            connectivity = "Could not verify connectivity from remote host."

    db.audit_log("agent_deploy", username, f"host={target_host} user={ssh_user} ok={success}", ip)
    resp: dict = {
        "status": "ok" if success else "error",
        "host": target_host,
        "output": result.stdout[:DEPLOY_OUTPUT_TRUNCATE],
        "error": result.stderr[:DEPLOY_ERROR_TRUNCATE] if not success else "",
    }
    if connectivity:
        resp["warning"] = connectivity
    return resp
```

- [ ] **Step 6: Fix deploy error handler + hostname validation**

Find the generic `except Exception as e` at the end of the deploy function (~line 268-269) and change:
```python
# OLD:
    except Exception as e:
        return {"status": "error", "error": str(e)}

# NEW:
    except Exception as e:
        logger.error("Agent deploy failed: %s", e)
        return {"status": "error", "error": "Deployment failed"} 
```

Add hostname validation near the top of the deploy function (after extracting `target_host`):
```python
    if not re.match(r'^[a-zA-Z0-9._:-]+$', target_host):
        raise HTTPException(400, "Invalid hostname")
```

- [ ] **Step 7: Run tests + ruff**

Run: `cd ~/noba && ruff check share/noba-web/server/routers/agent_deploy.py --fix`
Run: `cd ~/noba && python -m pytest tests/ -v -x --timeout=60`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add share/noba-web/server/routers/agent_deploy.py
git commit -m "fix: agent deploy hardening — localhost detection, preflight checks, connectivity verify

- Reject localhost/127.0.0.1/::1 in both install-script and deploy endpoints
- SSH preflight: Python3, sudo, existing agent stop
- -F /dev/null avoids distro ssh_config issues
- verify_ssl auto-disabled for IP-based URLs
- Post-deploy connectivity check warns if agent can't reach server
- Alpine apk support, timeout 60s→90s
- Hostname validation on deploy target"
```

---

## Task 5: Backend Module Fixes (Remediation, Workflow, Healing)

**Files:**
- Modify: `share/noba-web/server/remediation.py:718,722,765,796,799-804,881`
- Modify: `share/noba-web/server/workflow_engine.py:144-156`
- Modify: `share/noba-web/server/runner.py` (error message lines)
- Modify: `share/noba-web/server/plugins.py` (error message lines)
- Modify: `share/noba-web/server/healing/agent_verify.py:58`
- Modify: `share/noba-web/server/healing/snapshots.py:98`

- [ ] **Step 1: Fix remediation.py error messages + DNS failover**

In `share/noba-web/server/remediation.py`:

Sanitize error messages — for each `str(e)` or `str(exc)` in error returns, replace with generic message and add `logger.error()` before:

Line 718 (in execute_action except block): change `error=str(e)` to `error="Action execution failed"` and add `logger.error("Healing action failed: %s", e)` before the ledger write.

Line 722: change `"error": str(e)` to `"error": "Action execution failed"`

Line 765 (flush_dns): change `return {"success": False, "output": str(e)}` to:
```python
        logger.error("DNS flush failed: %s", e)
        return {"success": False, "output": "DNS flush failed"}
```

Line 796 (trigger_backup): change `return {"success": False, "output": str(e)}` to:
```python
        logger.error("Backup trigger failed: %s", e)
        return {"success": False, "output": "Backup trigger failed"}
```

Line 881 (webhook): change `return {"success": False, "output": str(e)}` to:
```python
        logger.error("Webhook delivery failed: %s", e)
        return {"success": False, "output": "Webhook delivery failed"}
```

Replace the DNS failover stub (lines 799-804):
```python
def _handle_failover_dns(params):
    primary = params.get("primary", "")
    secondary = params.get("secondary", "")
    if not primary or not secondary:
        return {"success": False, "output": "Both primary and secondary DNS required"}
    resolv = Path("/etc/resolv.conf")
    try:
        content = resolv.read_text()
        new_content = content.replace(f"nameserver {primary}", f"nameserver {secondary}")
        if new_content == content:
            return {"success": False, "output": f"Primary DNS {primary} not found in resolv.conf"}
        resolv.write_text(new_content)
        logger.info("DNS failover: %s → %s", primary, secondary)
        return {"success": True, "output": f"DNS failover: {primary} → {secondary}"}
    except Exception as e:
        logger.error("DNS failover failed: %s", e)
        return {"success": False, "output": "DNS failover failed"}
```

Add `from pathlib import Path` to imports if not present.

- [ ] **Step 2: Add webhook HMAC signing to workflow_engine.py**

In `share/noba-web/server/workflow_engine.py`, add to imports:
```python
import hashlib
import hmac
```

In the `_build_auto_webhook_process` function (around line 144), before the HTTP request is sent, add signature computation:

```python
    # Sign request if webhook has a secret configured
    secret = config.get("secret", "")
    if secret and body:
        body_bytes = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        sig = "sha256=" + hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        headers["X-Noba-Signature"] = sig
```

- [ ] **Step 3: Fix healing module bugs**

In `share/noba-web/server/healing/agent_verify.py` line 58, change:
```python
# OLD:
    "type": "check_service",
# NEW:
    "command": "check_service",
```

In `share/noba-web/server/healing/snapshots.py` line 98, change:
```python
# OLD:
        return {"success": False, "error": str(exc)}
# NEW:
        logger.error("Rollback failed: %s", exc)
        return {"success": False, "error": "Rollback execution failed"}
```

- [ ] **Step 4: Fix runner.py and plugins.py error messages**

Find any `str(e)` or `str(exc)` patterns in error returns and replace with generic messages. Add `logger.error()` calls before each.

- [ ] **Step 5: Run tests + ruff**

Run: `cd ~/noba && ruff check share/noba-web/server/remediation.py share/noba-web/server/workflow_engine.py share/noba-web/server/healing/ share/noba-web/server/runner.py share/noba-web/server/plugins.py --fix`
Run: `cd ~/noba && python -m pytest tests/ -v -x --timeout=60`

- [ ] **Step 6: Commit**

```bash
git add share/noba-web/server/remediation.py share/noba-web/server/workflow_engine.py share/noba-web/server/runner.py share/noba-web/server/plugins.py share/noba-web/server/healing/
git commit -m "fix: backend module hardening — error sanitization, DNS failover, webhook signing

- Error messages obfuscated in remediation, runner, plugins, healing
- DNS failover now actually modifies /etc/resolv.conf
- Webhook HMAC-SHA256 signing (X-Noba-Signature header)
- healing/agent_verify: type→command key fix
- healing/snapshots: rollback error sanitization"
```

---

## Task 6: Frontend Bug Fixes — API Paths + Component Fixes

**Files:**
- Modify: `share/noba-web/frontend/src/constants.js:10`
- Modify: `share/noba-web/frontend/src/main.js:20`
- Modify: `share/noba-web/frontend/src/components/healing/HealingApprovalTab.vue:41`
- Modify: `share/noba-web/frontend/src/views/RemoteDesktopView.vue:84`
- Modify: `share/noba-web/frontend/src/components/logs/SystemLogTab.vue:1-2,39-41`
- Modify: `share/noba-web/frontend/src/components/infrastructure/TopologyTab.vue:43,51-54,68`
- Modify: `share/noba-web/frontend/src/components/infrastructure/CrossSiteSyncTab.vue:13`
- Modify: `share/noba-web/frontend/src/components/monitoring/IncidentList.vue:57`
- Modify: `share/noba-web/frontend/src/components/welcome/NotificationSetup.vue:47`
- Modify: `share/noba-web/frontend/src/components/cards/QuickActionsCard.vue:20`
- Modify: `share/noba-web/frontend/src/components/dashboard/HealthScoreGauge.vue:35-51`
- Modify: `share/noba-web/frontend/src/components/dashboard/DashboardToolbar.vue`
- Modify: `share/noba-web/frontend/src/views/HealingView.vue` (if modal refs missing)

- [ ] **Step 1: Fix constants.js stream buffer**

In `share/noba-web/frontend/src/constants.js`, find the STREAM_BUFFER_MAX_LINES line and change:
```javascript
// OLD:
export const STREAM_BUFFER_MAX_LINES = -2000

// NEW:
export const STREAM_BUFFER_MAX_LINES = 2000      // max lines to keep in live stream buffer
```

- [ ] **Step 2: Fix main.js service worker registration**

In `share/noba-web/frontend/src/main.js`, find the service worker line and change:
```javascript
// OLD:
  navigator.serviceWorker.register('/service-worker.js')

// NEW:
  navigator.serviceWorker.register('/service-worker.js').catch(() => {})
```

- [ ] **Step 3: Fix HealingApprovalTab timestamp field**

In `share/noba-web/frontend/src/components/healing/HealingApprovalTab.vue` line 41, change:
```html
<!-- OLD: -->
{{ fmtTs(row.requested_at) }}

<!-- NEW: -->
{{ fmtTs(row.created_at) }}
```

- [ ] **Step 4: Fix RemoteDesktopView JSON.parse crash**

In `share/noba-web/frontend/src/views/RemoteDesktopView.vue`, replace line 84:
```javascript
// OLD:
    const msg = JSON.parse(e.data)

// NEW:
    let msg
    try { msg = JSON.parse(e.data) } catch { return }
```

- [ ] **Step 5: Fix SystemLogTab nextTick shim**

In `share/noba-web/frontend/src/components/logs/SystemLogTab.vue`:

Add `nextTick` to the Vue import (line 2):
```javascript
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
```

Delete the custom nextTick function (lines 39-41):
```javascript
// DELETE these lines:
function nextTick() {
  return new Promise(r => setTimeout(r, 0))
}
```

- [ ] **Step 6: Fix TopologyTab API paths**

In `share/noba-web/frontend/src/components/infrastructure/TopologyTab.vue`:

Line 43: change `/api/topology/impact/` to `/api/dependencies/impact/`
```javascript
    const data = await get(`/api/dependencies/impact/${encodeURIComponent(service)}`)
```

Lines 51-54: change path and field names:
```javascript
    await post('/api/dependencies', {
      source: topoNewSource.value.trim(),
      target: topoNewTarget.value.trim(),
      type: topoNewType.value || 'runtime',
```

Line 68: change path:
```javascript
    await del(`/api/dependencies/${id}`)
```

If there's a discover call, change `/api/agents/{hostname}/discover-services` to `/api/dependencies/discover/{hostname}`.

- [ ] **Step 7: Fix CrossSiteSyncTab API path**

In `share/noba-web/frontend/src/components/infrastructure/CrossSiteSyncTab.vue` line 13:
```javascript
// OLD:
    const data = await get('/api/site-sync/status')
// NEW:
    const data = await get('/api/sites/sync-status')
```

- [ ] **Step 8: Fix IncidentList API path**

In `share/noba-web/frontend/src/components/monitoring/IncidentList.vue` line 57:
```javascript
// OLD:
    const data = await get('/api/users')
// NEW:
    const data = await get('/api/admin/users')
```

- [ ] **Step 9: Fix NotificationSetup API path**

In `share/noba-web/frontend/src/components/welcome/NotificationSetup.vue` line 47:
```javascript
// OLD:
    await post('/api/admin/test-notifications')
// NEW:
    await post('/api/notifications/test')
```

- [ ] **Step 10: Fix QuickActionsCard API path**

In `share/noba-web/frontend/src/components/cards/QuickActionsCard.vue` line 20:
```javascript
// OLD:
    const res = await post('/api/run-script', { script: scriptName, args })
// NEW:
    const res = await post('/api/run', { script: scriptName, args })
```

- [ ] **Step 11: Fix HealthScoreGauge missing fetch on mount**

In `share/noba-web/frontend/src/components/dashboard/HealthScoreGauge.vue`, add `fetchHealthScore()` call in onMounted (after line 37):

```javascript
onMounted(async () => {
  tickRelative()
  tickInterval = setInterval(tickRelative, 1000)
  fetchHealthScore()    // ← ADD THIS LINE
  try {
```

Also improve the fetchHealthScore error handling (replace lines 48-52):
```javascript
async function fetchHealthScore() {
  try {
    const result = await get('/api/health-score')
    healthScore.value = result
  } catch (e) {
    console.warn('[HealthScoreGauge] fetch failed:', e.message || e)
  }
}
```

- [ ] **Step 12: Fix DashboardToolbar missing onMounted**

In `share/noba-web/frontend/src/components/dashboard/DashboardToolbar.vue`, add onMounted import and hook:

Add `onMounted` to the Vue import:
```javascript
import { ref, onMounted } from 'vue'
```

Add after the `fetchDashboards` function definition:
```javascript
onMounted(() => { fetchDashboards() })
```

- [ ] **Step 13: Run frontend tests**

Run: `cd ~/noba/share/noba-web/frontend && npm test -- --run 2>&1 | tail -20`
Expected: All pass

- [ ] **Step 14: Commit**

```bash
git add share/noba-web/frontend/src/
git commit -m "fix: 15 frontend bugs — API path corrections, component fixes, missing initializations

- constants.js: STREAM_BUFFER_MAX_LINES sign fix
- main.js: service worker error suppression
- 5 API endpoint path corrections (topology→dependencies, site-sync, users, notifications, run)
- RemoteDesktopView: JSON.parse crash guard on WebSocket messages
- SystemLogTab: use native Vue nextTick instead of setTimeout shim
- HealingApprovalTab: correct timestamp field name
- HealthScoreGauge: missing fetchHealthScore on mount
- DashboardToolbar: missing fetchDashboards on mount"
```

---

## Task 7: Frontend UX Improvements + Security

**Files:**
- Modify: `share/noba-web/frontend/src/App.vue`
- Modify: `share/noba-web/frontend/src/views/DashboardView.vue`
- Modify: `share/noba-web/frontend/src/components/welcome/WelcomeSetup.vue`
- Modify: `share/noba-web/frontend/src/components/modals/AiChatPanel.vue`
- Modify: `share/noba-web/frontend/src/components/agents/DeployModal.vue`
- Modify: Various components (code cleanup)

- [ ] **Step 1: Fix App.vue theme persistence**

In `share/noba-web/frontend/src/App.vue`, find the theme binding (around line 121) and the script section.

Add a computed `activeTheme` in the script:
```javascript
const _lsTheme = localStorage.getItem('noba-theme') || 'default'
const activeTheme = computed(() =>
  settings.preferences?.theme || settings.preferences?.preferences?.theme || _lsTheme
)
```

Add `computed` to the Vue import if not present.

Change the template binding from:
```html
:data-theme="settings.preferences.theme || 'default'"
```
to:
```html
:data-theme="activeTheme"
```

Add a watcher to persist theme to localStorage:
```javascript
watch(activeTheme, (t) => { localStorage.setItem('noba-theme', t) })
```

Add `watch` to the Vue import if not present.

- [ ] **Step 2: Add MutationObserver to DashboardView masonry**

In `share/noba-web/frontend/src/views/DashboardView.vue`, find the masonry section (around lines 128-147). Add a MutationObserver alongside the existing ResizeObserver to detect new cards added by SSE:

After the existing observer declarations, add:
```javascript
let _masonryChildObserver = null
```

In the `initMasonry` function, after the ResizeObserver setup, add:
```javascript
  // Watch for new cards added by SSE data
  const grid = document.querySelector('.masonry-grid')
  if (grid) {
    _masonryChildObserver = new MutationObserver(() => {
      requestAnimationFrame(() => {
        grid.querySelectorAll('.masonry-card').forEach(card => {
          if (!masonryObserver.value) return
          masonryObserver.value.observe(card)
        })
      })
    })
    _masonryChildObserver.observe(grid, { childList: true })
  }
```

In `onUnmounted`, add cleanup:
```javascript
  if (_masonryChildObserver) _masonryChildObserver.disconnect()
```

- [ ] **Step 3: Improve WelcomeSetup modal UX**

In `share/noba-web/frontend/src/components/welcome/WelcomeSetup.vue`:

Change the step card click binding (around line 144) from:
```html
@click="!step.done && !step.auto && openStep(step.key)"
```
to:
```html
@click="!step.auto && openStep(step.key)"
```

Change the step button text — find where it shows "Done" for completed steps and change to "Edit":
Find `step.done` related button text and update so completed steps show "Edit" instead of being disabled.

- [ ] **Step 4: Add DOMPurify XSS protection to AiChatPanel**

First install DOMPurify:
```bash
cd ~/noba/share/noba-web/frontend && npm install dompurify
```

In `share/noba-web/frontend/src/components/modals/AiChatPanel.vue`:

Add import:
```javascript
import DOMPurify from 'dompurify'
```

In the `formatMessage` function (around lines 42-55), wrap the return with DOMPurify:

```javascript
function formatMessage(text) {
  if (!text) return ''
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  // Markdown-like formatting
  html = html
    .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['pre', 'code', 'strong', 'br'],
    ALLOWED_ATTR: ['class'],
  })
}
```

- [ ] **Step 5: Add server URL validation to DeployModal**

In `share/noba-web/frontend/src/components/agents/DeployModal.vue`, add after the existing refs:

```javascript
const serverUrl = ref(window.location.origin)

const urlWarnings = computed(() => {
  const url = serverUrl.value.trim()
  if (!url) return [{ level: 'error', msg: 'Server URL is required' }]
  const warnings = []
  try {
    const parsed = new URL(url)
    const host = parsed.hostname
    if (['localhost', '127.0.0.1', '::1'].includes(host))
      return [{ level: 'error', msg: "Agents cannot reach localhost — use your server's network address" }]
    if (!host.includes('.') && !/^\d+\.\d+\.\d+\.\d+$/.test(host))
      warnings.push({ level: 'warn', msg: `"${host}" is a short hostname — use FQDN or IP instead.` })
    if (parsed.protocol === 'http:')
      warnings.push({ level: 'warn', msg: 'HTTP sends agent credentials in cleartext. Use HTTPS in production.' })
    if (parsed.protocol === 'https:' && /^\d+\.\d+\.\d+\.\d+$/.test(host))
      warnings.push({ level: 'info', msg: "IP-based HTTPS — SSL verification will be auto-disabled for the agent." })
  } catch {
    return [{ level: 'error', msg: 'Invalid URL format' }]
  }
  return warnings
})
const hasUrlError = computed(() => urlWarnings.value.some(w => w.level === 'error'))
```

Add `computed` to Vue import. Update `canDeploy` to include `&& !hasUrlError.value`.

In the deploy POST data, add `server_url: serverUrl.value`.

In the template, add a Server URL input field before the Deploy button with warning display.

- [ ] **Step 6: Frontend code cleanup**

Remove unused imports/refs across these files:
- `views/RemoteView.vue`: remove unused `useRouter` import
- `views/AutomationsView.vue`: remove unused `useAuthStore` import
- `components/healing/ApprovalQueue.vue`: remove unused `timers` ref
- `components/welcome/UserSetup.vue`: remove unused error parameter in catch
- `components/automations/AutomationRow.vue`: remove `const props =` from defineProps
- `components/automations/AutomationStatusBadge.vue`: same
- `components/automations/WorkflowBuilder.vue`: add `'close'` to defineEmits
- `components/automations/AutonomySelector.vue`: add `type: String` to defineModel
- `components/modals/TerminalModal.vue`: remove unused store imports
- `stores/dashboard.js`: remove unused `shallowRef` import

- [ ] **Step 7: Run frontend tests + build**

Run: `cd ~/noba/share/noba-web/frontend && npm test -- --run 2>&1 | tail -20`
Run: `cd ~/noba/share/noba-web/frontend && npm run build`
Expected: All pass, build succeeds

- [ ] **Step 8: Commit**

```bash
git add share/noba-web/frontend/
git commit -m "fix: frontend UX improvements + XSS protection + code cleanup

- App.vue: theme persistence with localStorage fallback
- DashboardView: MutationObserver for masonry card reflow on SSE
- WelcomeSetup: completed steps show Edit, all steps clickable
- AiChatPanel: DOMPurify XSS sanitization on AI chat output
- DeployModal: server URL validation (localhost, HTTP, IP warnings)
- Code cleanup: remove unused imports/refs across 10 components"
```

---

## Task 8: Shell Scripts + Infrastructure

**Files:**
- Modify: `libexec/lib/noba-lib.sh:370-380,422-426,579-634`
- Modify: `libexec/noba-tui.sh:60-147`
- Modify: `install.sh:10-12,512-524`
- Modify: `Dockerfile:5,19-21`

- [ ] **Step 1: Fix noba-lib.sh PBKDF2 iterations + hash format**

In `libexec/lib/noba-lib.sh`, find the `hash_password()` function (around line 370) and update:

```bash
hash_password() {
    local raw_password="$1"
    python3 - "$raw_password" <<'PYEOF'
import hashlib, secrets, sys
password = sys.argv[1]
salt = secrets.token_hex(16)
iters = 600_000
dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iters)
print(f"pbkdf2:{iters}:{salt}:{dk.hex()}")
PYEOF
}
```

- [ ] **Step 2: Fix noba-lib.sh temp file security**

Find all temp file patterns using `.tmp` suffix (around lines 422-426, 579-634) and replace with mktemp + trap:

For each occurrence of the pattern:
```bash
# OLD:
local tmp="$auth_dir/auth.conf.tmp"
touch "$tmp"
chmod 600 "$tmp"
printf "%s:%s:admin\n" "$username" "$hash" > "$tmp"
mv "$tmp" "$auth_dir/auth.conf"

# NEW:
local tmp
tmp=$(mktemp "${auth_dir}/auth.conf.XXXXXX")
trap 'rm -f "$tmp"' RETURN
chmod 600 "$tmp"
printf "%s:%s:admin\n" "$username" "$hash" > "$tmp"
mv "$tmp" "$auth_dir/auth.conf"
```

Apply the same pattern to `add_user()`, `remove_user()`, and `change_password()` functions.

- [ ] **Step 3: Quote $DIALOG in noba-tui.sh**

In `libexec/noba-tui.sh`, change every unquoted `$DIALOG` to `"$DIALOG"`:

Lines 60, 65, 68, 73, 87, 125, 130, 144, 147 — each `$DIALOG` becomes `"$DIALOG"`.

- [ ] **Step 4: Fix install.sh sudo detection + dependencies**

In `install.sh`, after the root check (around line 12), add sudo capability detection:

```bash
CAN_SUDO=true
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    if ! command -v sudo &>/dev/null || ! sudo -n true 2>/dev/null; then
        CAN_SUDO=false
        echo "Note: Running without sudo — some features (systemd service, port 443) will be skipped."
    fi
fi
```

In the pip dependencies array (around line 512), add missing packages:
```bash
_py_deps=(fastapi "uvicorn[standard]" psutil pyyaml httpx websocket-client cryptography defusedxml python-multipart lxml)
```

After the pip install line, add fallback for Python 3.11+ externally-managed environments:
```bash
python3 -m pip install --user "${_py_deps[@]}" 2>/dev/null \
  || python3 -m pip install --user --break-system-packages "${_py_deps[@]}" 2>/dev/null \
  || pip3 install --user "${_py_deps[@]}" 2>/dev/null \
  || true
```

- [ ] **Step 5: Fix Dockerfile — non-root user + dependencies**

In `Dockerfile`:

Update Python version (line 5):
```dockerfile
FROM python:3.14-slim
```

Update pip install (lines 19-21) to add missing packages:
```dockerfile
RUN pip install --no-cache-dir \
    'fastapi>=0.110.0' 'uvicorn[standard]>=0.27.1' 'psutil>=5.9.8' \
    'pyyaml>=6.0' 'httpx>=0.27' 'websocket-client>=1.7' 'cryptography>=41.0' \
    'python-multipart>=0.0.9' 'lxml>=5.0' 'defusedxml>=0.7'
```

Add non-root user before the COPY commands:
```dockerfile
RUN useradd --create-home --shell /bin/bash noba
```

Before the final CMD, add:
```dockerfile
RUN chown -R noba:noba /app
USER noba
```

- [ ] **Step 6: Commit**

```bash
git add libexec/ install.sh Dockerfile
git commit -m "fix: shell script hardening + Dockerfile security

- noba-lib.sh: PBKDF2 600k iterations, mktemp+trap for temp files
- noba-tui.sh: quote \$DIALOG throughout
- install.sh: sudo detection, python-multipart+lxml deps, --break-system-packages fallback
- Dockerfile: Python 3.14, non-root user, additional dependencies"
```

---

## Task 9: Final Verification + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Run full backend test suite**

Run: `cd ~/noba && python -m pytest tests/ -v --timeout=60 2>&1 | tail -30`
Expected: All pass

- [ ] **Step 2: Run ruff on entire backend**

Run: `cd ~/noba && ruff check share/noba-web/server/ --fix`
Expected: Clean

- [ ] **Step 3: Run frontend tests + build**

Run: `cd ~/noba/share/noba-web/frontend && npm test -- --run 2>&1 | tail -20`
Run: `cd ~/noba/share/noba-web/frontend && npm run build`
Expected: All pass, build succeeds

- [ ] **Step 4: Update CHANGELOG.md**

Add under `[Unreleased]`:

```markdown
### Security
- Upgrade PBKDF2 to 600,000 iterations (OWASP minimum) with auto-upgrade on login
- TOTP setup fails fast when pyotp not installed (no silent fallback)
- Security headers: X-Frame-Options DENY, HSTS, COOP, COEP, CORP, CSP frame-ancestors
- Exception chain suppression (`from None`) on 40+ HTTPException raises across all routers
- Error message sanitization: log details server-side, return generic to client
- Hostname regex validation on WebSocket connect and agent report endpoint
- Global 500/422 exception handlers prevent stack trace leaks
- Agent deploy: hostname validation, error message obfuscation
- AiChatPanel: DOMPurify XSS sanitization on AI chat output
- Collector error messages obfuscated

### Fixed
- Agent deploy: reject localhost/127.0.0.1 with clear error message
- Agent deploy: SSH preflight checks (Python3, sudo, existing agent cleanup)
- Agent deploy: `-F /dev/null` avoids broken distro ssh_config
- Agent deploy: `verify_ssl` auto-disabled for IP-based server URLs
- Agent deploy: post-deploy connectivity check warns if agent unreachable
- Agent deploy: Alpine Linux (apk) package manager support
- 5 frontend API path mismatches causing 404s (topology, site-sync, users, notifications, run)
- HealthScoreGauge: missing data fetch on mount
- DashboardToolbar: missing dashboard list fetch on mount
- RemoteDesktopView: JSON.parse crash on malformed WebSocket messages
- SystemLogTab: use native Vue nextTick instead of setTimeout shim
- HealingApprovalTab: correct timestamp field (requested_at → created_at)
- constants.js: STREAM_BUFFER_MAX_LINES sign fix (buffer was unbounded)
- main.js: service worker registration error suppression
- DNS failover: now actually modifies /etc/resolv.conf
- Webhook HMAC-SHA256 signing (X-Noba-Signature header)
- healing/agent_verify: command key typo fix
- Shutdown ordering: flag set first to prevent port-bind failures on restart
- noba-lib.sh: PBKDF2 synced to 600k, mktemp+trap for temp file security
- noba-tui.sh: $DIALOG variable quoted throughout
- install.sh: sudo detection, python-multipart+lxml deps

### Improved
- App.vue: theme persistence with localStorage fallback
- DashboardView: MutationObserver for masonry card reflow on SSE updates
- WelcomeSetup: completed steps show Edit button, all steps clickable
- DeployModal: server URL validation with localhost/HTTP/IP warnings
- Removed unused imports/refs across 10+ frontend components
- Dockerfile: Python 3.14, non-root user, additional dependencies
```

- [ ] **Step 5: Commit CHANGELOG + built frontend**

```bash
git add CHANGELOG.md share/noba-web/static/dist/
git commit -m "docs: update changelog for enterprise back-port fixes"
```

- [ ] **Step 6: Final verification**

Run: `cd ~/noba && python -m pytest tests/ -v --timeout=60 2>&1 | tail -5`
Expected: All pass, zero failures
