# Agent Enhancement Phase 1a: Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the NOBA agent from 9 to 32 commands, add agent persistence in SQLite, enforce risk-tiered authorization, and add version-to-capability mapping — all while keeping the agent as a single file with zero external dependencies.

**Architecture:** Add 23 new command handlers to `agent.py` (organized with a handler registry pattern), add an `agent_registry` SQLite table for persistence, update the server command endpoint to enforce risk levels per user role, and add a bulk command API endpoint.

**Tech Stack:** Python stdlib (agent), FastAPI + SQLite (server), existing test patterns (pytest + httpx TestClient)

**Spec:** `docs/superpowers/specs/2026-03-20-agent-enhancement-design.md`

**Branch:** Create `feat/agent-enhancement` from current `refactor/maintainability-overhaul`

---

## File Structure

### Agent-side (single file, expanded):
- Modify: `share/noba-agent/agent.py` — add 23 new `_cmd_*` handlers, platform detection, path validation

### Server-side:
- Create: `share/noba-web/server/db/agents.py` — agent registry DB functions (persistence)
- Modify: `share/noba-web/server/db/core.py` — add `agent_registry` table + delegation methods
- Modify: `share/noba-web/server/db/__init__.py` — re-export if needed
- Modify: `share/noba-web/server/routers/system.py` — update command endpoint with risk enforcement, add bulk command endpoint, add uninstall endpoint, persist agents on report
- Create: `share/noba-web/server/agent_config.py` — risk levels dict, capability registry, validation helpers

### Tests:
- Create: `tests/test_agent_commands.py` — test new agent command handlers
- Create: `tests/test_agent_risk.py` — test risk enforcement + capability mapping
- Create: `tests/test_agent_persistence.py` — test agent registry DB operations

---

### Task 1: Agent persistence — SQLite table + DB functions

**Files:**
- Create: `share/noba-web/server/db/agents.py`
- Modify: `share/noba-web/server/db/core.py`

- [ ] **Step 1: Create `db/agents.py` with standalone functions**

```python
"""Noba – Agent registry persistence."""
from __future__ import annotations

import json
import time


def upsert_agent(conn, lock, hostname, ip, platform_name, arch, agent_version):
    """Insert or update agent in registry."""
    now = int(time.time())
    with lock:
        existing = conn.execute(
            "SELECT first_seen FROM agent_registry WHERE hostname = ?", (hostname,)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE agent_registry
                SET ip = ?, platform = ?, arch = ?, agent_version = ?, last_seen = ?
                WHERE hostname = ?
            """, (ip, platform_name, arch, agent_version, now, hostname))
        else:
            conn.execute("""
                INSERT INTO agent_registry (hostname, ip, platform, arch, agent_version, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (hostname, ip, platform_name, arch, agent_version, now, now))
        conn.commit()


def get_all_agents(conn, lock):
    """Load all agents from registry."""
    with lock:
        rows = conn.execute(
            "SELECT hostname, ip, platform, arch, agent_version, first_seen, last_seen, config_json "
            "FROM agent_registry"
        ).fetchall()
    return [
        {
            "hostname": r[0], "ip": r[1], "platform": r[2], "arch": r[3],
            "agent_version": r[4], "first_seen": r[5], "last_seen": r[6],
            "config": json.loads(r[7] or "{}"),
        }
        for r in rows
    ]


def delete_agent(conn, lock, hostname):
    """Remove agent from registry."""
    with lock:
        conn.execute("DELETE FROM agent_registry WHERE hostname = ?", (hostname,))
        conn.commit()


def update_agent_config(conn, lock, hostname, config):
    """Update per-agent config JSON."""
    with lock:
        conn.execute(
            "UPDATE agent_registry SET config_json = ? WHERE hostname = ?",
            (json.dumps(config), hostname),
        )
        conn.commit()
```

- [ ] **Step 2: Add `agent_registry` table to `db/core.py` schema**

In `_init_schema()`, add after the existing table definitions:
```sql
CREATE TABLE IF NOT EXISTS agent_registry (
    hostname TEXT PRIMARY KEY,
    ip TEXT,
    platform TEXT,
    arch TEXT,
    agent_version TEXT,
    first_seen INTEGER,
    last_seen INTEGER,
    config_json TEXT DEFAULT '{}'
);
```

Add delegation methods to `Database` class:
```python
def upsert_agent(self, hostname, ip, platform_name, arch, agent_version):
    from .agents import upsert_agent
    upsert_agent(self._conn, self._lock, hostname, ip, platform_name, arch, agent_version)

def get_all_agents(self):
    from .agents import get_all_agents
    return get_all_agents(self._conn, self._lock)

def delete_agent(self, hostname):
    from .agents import delete_agent
    delete_agent(self._conn, self._lock, hostname)

def update_agent_config(self, hostname, config):
    from .agents import update_agent_config
    update_agent_config(self._conn, self._lock, hostname, config)
```

- [ ] **Step 3: Verify**

Run: `ruff check share/noba-web/server/db/agents.py share/noba-web/server/db/core.py`
Run: `pytest tests/ -x -q`

- [ ] **Step 4: Commit**

```
git add share/noba-web/server/db/agents.py share/noba-web/server/db/core.py
git commit -m "feat(agent): add agent_registry SQLite table for persistence"
```

---

### Task 2: Agent config module — risk levels, capabilities, validation

**Files:**
- Create: `share/noba-web/server/agent_config.py`

- [ ] **Step 1: Create `agent_config.py`**

```python
"""Noba – Agent command risk classification, capability registry, and validation."""
from __future__ import annotations

import re

# ── Risk levels ──────────────────────────────────────────────────────────────
# Low: viewer can see results, operator can execute
# Medium: operator can execute
# High: admin only
RISK_LEVELS: dict[str, str] = {
    "ping": "low", "check_service": "low", "get_logs": "low",
    "network_test": "low", "package_updates": "low", "system_info": "low",
    "disk_usage": "low", "list_services": "low", "list_users": "low",
    "file_read": "low", "file_list": "low", "file_checksum": "low",
    "file_stat": "low", "container_list": "low", "container_logs": "low",
    "dns_lookup": "low", "network_config": "low",

    "restart_service": "medium", "set_interval": "medium",
    "service_control": "medium", "file_transfer": "medium",
    "file_push": "medium", "container_control": "medium",

    "exec": "high", "file_write": "high", "file_delete": "high",
    "update_agent": "high", "package_install": "high", "package_remove": "high",
    "user_manage": "high", "uninstall_agent": "high", "reboot": "high",
    "process_kill": "high",
}

# ── Version capabilities ─────────────────────────────────────────────────────
AGENT_CAPABILITIES: dict[str, set[str]] = {
    "1.1.0": {"exec", "restart_service", "update_agent", "set_interval", "ping",
              "get_logs", "check_service", "network_test", "package_updates"},
    "2.0.0": set(RISK_LEVELS.keys()),
}

# ── Validation patterns ──────────────────────────────────────────────────────
_SERVICE_RE = re.compile(r"^[a-zA-Z0-9@._-]+$")
_PACKAGE_RE = re.compile(r"^[a-zA-Z0-9._+-]+$")
_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]*$")
_DANGEROUS_GROUPS = frozenset({"sudo", "wheel", "root", "adm", "admin"})

# Agent-side path deny list (also enforced server-side for defense in depth)
PATH_DENYLIST = frozenset({
    "/etc/shadow", "/etc/gshadow", "/proc/kcore",
})
PATH_DENY_PATTERNS = (
    "/.ssh/id_",
)


def check_role_permission(role: str, risk: str) -> bool:
    """Check if a role can execute a command at the given risk level."""
    if role == "admin":
        return True
    if role == "operator":
        return risk in ("low", "medium")
    if role == "viewer":
        return False
    return False


def get_agent_capabilities(version: str) -> set[str]:
    """Get supported command set for a given agent version."""
    # Exact match first
    if version in AGENT_CAPABILITIES:
        return AGENT_CAPABILITIES[version]
    # Try major.minor match (strip patch)
    parts = version.split(".")
    if len(parts) >= 2:
        major_minor = f"{parts[0]}.{parts[1]}"
        for v, caps in AGENT_CAPABILITIES.items():
            if v.startswith(major_minor):
                return caps
    # Unknown version — assume v1 capabilities
    return AGENT_CAPABILITIES.get("1.1.0", set())


def validate_command_params(cmd_type: str, params: dict) -> str | None:
    """Validate command parameters. Returns error string or None if valid."""
    if cmd_type in ("restart_service", "check_service", "service_control"):
        svc = params.get("service", "")
        if not svc or not _SERVICE_RE.match(svc):
            return f"Invalid service name: {svc!r}"
        if cmd_type == "service_control":
            action = params.get("action", "")
            if action not in ("start", "stop", "enable", "disable", "restart"):
                return f"Invalid action: {action!r}"

    elif cmd_type in ("package_install", "package_remove"):
        packages = params.get("packages", [])
        if not packages:
            return "No packages specified"
        for p in packages:
            if not _PACKAGE_RE.match(p):
                return f"Invalid package name: {p!r}"

    elif cmd_type == "user_manage":
        username = params.get("username", "")
        if not username or not _USERNAME_RE.match(username):
            return f"Invalid username: {username!r}"
        action = params.get("action", "")
        if action not in ("create", "delete", "modify"):
            return f"Invalid action: {action!r}"
        groups = params.get("groups", [])
        for g in groups:
            if g in _DANGEROUS_GROUPS:
                return f"Dangerous group '{g}' — requires explicit admin override"

    elif cmd_type in ("file_read", "file_write", "file_delete", "file_stat",
                       "file_list", "file_checksum", "file_transfer", "file_push"):
        path = params.get("path", "")
        if not path:
            return "No path specified"
        if "\0" in path:
            return "Null byte in path"
        if ".." in path.split("/"):
            return "Path traversal (..) not allowed"
        # Check deny list
        for denied in PATH_DENYLIST:
            if path == denied or path.startswith(denied + "/"):
                return f"Path is denied: {path}"
        for pattern in PATH_DENY_PATTERNS:
            if pattern in path:
                return f"Path matches deny pattern: {pattern}"

    elif cmd_type == "disk_usage":
        path = params.get("path", "/")
        if "\0" in path or ".." in path.split("/"):
            return "Invalid path"

    elif cmd_type == "container_control":
        action = params.get("action", "")
        if action not in ("start", "stop", "restart"):
            return f"Invalid container action: {action!r}"

    elif cmd_type == "process_kill":
        pid = params.get("pid")
        name = params.get("name")
        if not pid and not name:
            return "Either pid or name required"

    elif cmd_type == "reboot":
        delay = params.get("delay", 60)
        if not isinstance(delay, int) or delay < 0:
            return "Delay must be a non-negative integer"

    elif cmd_type == "uninstall_agent":
        if not params.get("confirm"):
            return "Uninstall requires confirm=true"

    elif cmd_type == "dns_lookup":
        domain = params.get("domain", "")
        if not domain:
            return "No domain specified"

    elif cmd_type == "network_test":
        target = params.get("target", "")
        if not target:
            return "No target specified"

    return None  # Valid
```

- [ ] **Step 2: Verify**

Run: `ruff check share/noba-web/server/agent_config.py`

- [ ] **Step 3: Commit**

```
git add share/noba-web/server/agent_config.py
git commit -m "feat(agent): add risk levels, capability registry, and command validation"
```

---

### Task 3: Update server command endpoint with risk enforcement

**Files:**
- Modify: `share/noba-web/server/routers/system.py`

- [ ] **Step 1: Update `api_agent_command` endpoint (line ~1070)**

Replace the hardcoded `valid_types` set and admin-only auth with risk-tiered enforcement:

```python
from ..agent_config import RISK_LEVELS, check_role_permission, get_agent_capabilities, validate_command_params
```

Update the handler:
```python
@router.post("/api/agents/{hostname}/command")
async def api_agent_command(hostname: str, request: Request, auth=Depends(_get_auth)):
    """Queue a command for an agent. Risk-tiered authorization."""
    import secrets
    username, role = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    cmd_type = body.get("type", "")
    params = body.get("params", {})

    # Validate command type exists
    risk = RISK_LEVELS.get(cmd_type)
    if not risk:
        raise HTTPException(400, f"Unknown command type: {cmd_type!r}")

    # Check role permission
    if not check_role_permission(role, risk):
        raise HTTPException(403, f"Insufficient permissions: {cmd_type} requires {risk} access")

    # Check agent version supports this command
    with _agent_data_lock:
        agent = _agent_data.get(hostname)
    if agent:
        version = agent.get("agent_version", "1.1.0")
        caps = get_agent_capabilities(version)
        if cmd_type not in caps:
            raise HTTPException(400, f"Agent v{version} does not support '{cmd_type}'")

    # Validate parameters
    err = validate_command_params(cmd_type, params)
    if err:
        raise HTTPException(400, err)

    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": cmd_type, "params": params,
           "queued_by": username, "queued_at": int(time.time())}
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)
    db.audit_log("agent_command", username, f"host={hostname} type={cmd_type} id={cmd_id}", ip)
    return {"status": "queued", "id": cmd_id}
```

Note: auth changes from `Depends(_require_admin)` to `Depends(_get_auth)` — the risk enforcement handles authorization.

- [ ] **Step 2: Update `api_agent_report` to persist agents (line ~992)**

After storing in-memory data (`_agent_data[hostname] = body`), add:
```python
try:
    db.upsert_agent(
        hostname=hostname,
        ip=body.get("_ip", ""),
        platform_name=body.get("platform", ""),
        arch=body.get("arch", ""),
        agent_version=body.get("agent_version", ""),
    )
except Exception:
    pass  # Don't fail report on persistence error
```

- [ ] **Step 3: Load persisted agents on startup**

In `share/noba-web/server/app.py` lifespan, after `db.catchup_rollups()`, add:
```python
# Load persisted agents (show as offline until they report)
from .agent_store import _agent_data, _agent_data_lock
try:
    for agent in db.get_all_agents():
        with _agent_data_lock:
            if agent["hostname"] not in _agent_data:
                _agent_data[agent["hostname"]] = {
                    "_received": agent["last_seen"],
                    "_ip": agent["ip"],
                    "platform": agent["platform"],
                    "arch": agent["arch"],
                    "agent_version": agent["agent_version"],
                    "hostname": agent["hostname"],
                }
except Exception:
    pass
```

- [ ] **Step 4: Add bulk command endpoint**

```python
@router.post("/api/agents/bulk-command")
async def api_bulk_command(request: Request, auth=Depends(_get_auth)):
    """Send a command to multiple agents at once."""
    import secrets
    username, role = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    hostnames = body.get("hostnames", [])
    cmd_type = body.get("type", "")
    params = body.get("params", {})

    risk = RISK_LEVELS.get(cmd_type)
    if not risk:
        raise HTTPException(400, f"Unknown command type: {cmd_type!r}")
    if not check_role_permission(role, risk):
        raise HTTPException(403, f"Insufficient permissions: {cmd_type} requires {risk} access")
    err = validate_command_params(cmd_type, params)
    if err:
        raise HTTPException(400, err)

    if not hostnames:
        # "all" — target every known agent
        with _agent_data_lock:
            hostnames = list(_agent_data.keys())

    results = {}
    for hostname in hostnames:
        cmd_id = secrets.token_hex(8)
        cmd = {"id": cmd_id, "type": cmd_type, "params": params,
               "queued_by": username, "queued_at": int(time.time())}
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)
        results[hostname] = cmd_id
    db.audit_log("agent_bulk_command", username,
                 f"type={cmd_type} targets={len(hostnames)}", ip)
    return {"status": "queued", "commands": results}
```

- [ ] **Step 5: Add uninstall shortcut endpoint**

```python
@router.post("/api/agents/{hostname}/uninstall")
async def api_agent_uninstall(hostname: str, request: Request, auth=Depends(_require_admin)):
    """Queue uninstall command for an agent and remove from registry."""
    import secrets
    username, _ = auth
    ip = _client_ip(request)
    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": "uninstall_agent", "params": {"confirm": True},
           "queued_by": username, "queued_at": int(time.time())}
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)
    db.audit_log("agent_uninstall", username, f"host={hostname} id={cmd_id}", ip)
    return {"status": "queued", "id": cmd_id}
```

- [ ] **Step 6: Verify**

Run: `ruff check share/noba-web/server/routers/system.py share/noba-web/server/app.py`
Run: `pytest tests/ -x -q`

- [ ] **Step 7: Commit**

```
git add share/noba-web/server/routers/system.py share/noba-web/server/app.py
git commit -m "feat(agent): risk-tiered command auth, persistence on report, bulk commands"
```

---

### Task 4: Add new command handlers to agent.py (system + services + network)

**Files:**
- Modify: `share/noba-agent/agent.py`

- [ ] **Step 1: Update VERSION to 2.0.0**

Change line 30: `VERSION = "2.0.0"`

- [ ] **Step 2: Add platform detection helper near the top of the file**

```python
# ── Platform detection ───────────────────────────────────────────────────────
_PLATFORM = platform.system().lower()  # "linux", "darwin", "freebsd", "windows"
_HAS_SYSTEMD = os.path.isdir("/run/systemd/system") if _PLATFORM == "linux" else False


def _detect_container_runtime() -> str | None:
    """Detect available container runtime (docker or podman)."""
    for rt in ("podman", "docker"):
        if os.path.isfile(f"/usr/bin/{rt}") or os.path.isfile(f"/usr/local/bin/{rt}"):
            return rt
    return None


def _detect_pkg_manager() -> str | None:
    """Detect system package manager."""
    for mgr in ("apt-get", "dnf", "yum", "pkg", "brew", "winget"):
        for d in ("/usr/bin", "/usr/local/bin", "/usr/sbin"):
            if os.path.isfile(f"{d}/{mgr}"):
                return mgr.replace("-get", "")
    return None
```

- [ ] **Step 3: Add new command handlers — system group**

Add after the existing `_cmd_package_updates`:

```python
def _cmd_system_info(_params: dict, _ctx: dict) -> dict:
    """Detailed system information."""
    info = {
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "arch": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "agent_version": VERSION,
        "uptime_s": 0,
    }
    try:
        if _PLATFORM != "windows":
            info["uptime_s"] = int(float(open("/proc/uptime").read().split()[0]))
    except Exception:
        pass
    # IPs
    try:
        ips = []
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 53))
        ips.append(s.getsockname()[0])
        s.close()
        info["ips"] = ips
    except Exception:
        info["ips"] = []
    return {"status": "ok", "info": info}


def _cmd_disk_usage(params: dict, _ctx: dict) -> dict:
    """Disk usage for a specific path."""
    path = params.get("path", "/")
    try:
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        free = st.f_bfree * st.f_frsize
        used = total - free
        return {"status": "ok", "path": path, "total": total, "used": used,
                "free": free, "percent": round(used / total * 100, 1) if total else 0}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_reboot(params: dict, _ctx: dict) -> dict:
    """Schedule system reboot."""
    delay = min(params.get("delay", 60), 3600)
    try:
        if _PLATFORM == "windows":
            _safe_run(["shutdown", "/r", "/t", str(delay)])
        else:
            _safe_run(["sudo", "shutdown", "-r", f"+{max(delay // 60, 1)}"])
        return {"status": "ok", "message": f"Reboot scheduled in {delay}s"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_process_kill(params: dict, _ctx: dict) -> dict:
    """Kill a process by PID or name."""
    import signal as _signal
    pid = params.get("pid")
    name = params.get("name")
    sig = params.get("signal", "TERM")
    sig_num = getattr(_signal, f"SIG{sig}", _signal.SIGTERM)
    try:
        if pid:
            os.kill(int(pid), sig_num)
            return {"status": "ok", "killed_pid": pid}
        elif name:
            result = _safe_run(["pkill", f"-{sig}", name])
            return {"status": "ok", "killed_name": name, "output": result}
        return {"status": "error", "error": "No pid or name"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

- [ ] **Step 4: Add service commands**

```python
def _cmd_list_services(params: dict, _ctx: dict) -> dict:
    """List all system services with their status."""
    filt = params.get("filter", "")
    try:
        if _HAS_SYSTEMD:
            out = _safe_run(["systemctl", "list-units", "--type=service", "--all",
                             "--no-pager", "--no-legend"])
            services = []
            for line in out.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 4:
                    name = parts[0].replace(".service", "")
                    if filt and filt.lower() not in name.lower():
                        continue
                    services.append({"name": name, "load": parts[1],
                                     "active": parts[2], "sub": parts[3]})
            return {"status": "ok", "services": services}
        elif _PLATFORM == "darwin":
            out = _safe_run(["launchctl", "list"])
            services = []
            for line in out.strip().split("\n")[1:]:
                parts = line.split("\t")
                if len(parts) >= 3:
                    name = parts[2]
                    if filt and filt.lower() not in name.lower():
                        continue
                    services.append({"name": name, "pid": parts[0], "status": parts[1]})
            return {"status": "ok", "services": services}
        elif _PLATFORM == "windows":
            out = _safe_run(["sc", "query", "type=", "service", "state=", "all"])
            return {"status": "ok", "raw": out[:MAX_OUTPUT]}
        else:
            return {"status": "error", "error": "not_supported"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_service_control(params: dict, _ctx: dict) -> dict:
    """Start/stop/enable/disable a service."""
    svc = params.get("service", "")
    action = params.get("action", "")
    try:
        if _HAS_SYSTEMD:
            out = _safe_run(["sudo", "systemctl", action, svc])
        elif _PLATFORM == "darwin":
            if action in ("start", "stop"):
                out = _safe_run(["sudo", "launchctl", action, svc])
            else:
                return {"status": "error", "error": f"macOS: {action} not supported via launchctl"}
        elif _PLATFORM == "freebsd":
            out = _safe_run(["sudo", "service", svc, action])
        elif _PLATFORM == "windows":
            win_action = {"start": "start", "stop": "stop"}.get(action)
            if not win_action:
                return {"status": "error", "error": f"Windows: {action} not supported"}
            out = _safe_run(["sc", win_action, svc])
        else:
            return {"status": "error", "error": "not_supported"}
        return {"status": "ok", "output": out}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

- [ ] **Step 5: Add network commands**

```python
def _cmd_network_config(_params: dict, _ctx: dict) -> dict:
    """Full network configuration dump."""
    result = {}
    try:
        if _PLATFORM == "windows":
            result["ipconfig"] = _safe_run(["ipconfig", "/all"])
        else:
            result["ip_addr"] = _safe_run(["ip", "-br", "addr"]) if _PLATFORM == "linux" else _safe_run(["ifconfig"])
            result["ip_route"] = _safe_run(["ip", "route"]) if _PLATFORM == "linux" else _safe_run(["netstat", "-rn"])
            result["dns"] = ""
            try:
                result["dns"] = open("/etc/resolv.conf").read()
            except Exception:
                pass
        return {"status": "ok", **result}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_dns_lookup(params: dict, _ctx: dict) -> dict:
    """DNS resolution from agent's perspective."""
    domain = params.get("domain", "")
    record_type = params.get("type", "A")
    try:
        if record_type in ("A", "AAAA"):
            family = socket.AF_INET6 if record_type == "AAAA" else socket.AF_INET
            results = socket.getaddrinfo(domain, None, family)
            ips = list({r[4][0] for r in results})
            return {"status": "ok", "domain": domain, "type": record_type, "results": ips}
        else:
            out = _safe_run(["nslookup", "-type=" + record_type, domain])
            return {"status": "ok", "domain": domain, "type": record_type, "raw": out}
    except socket.gaierror as e:
        return {"status": "error", "error": f"DNS lookup failed: {e}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

- [ ] **Step 6: Verify agent syntax**

Run: `python3 -m py_compile share/noba-agent/agent.py`

- [ ] **Step 7: Commit**

```
git add share/noba-agent/agent.py
git commit -m "feat(agent): add system, service, and network command handlers"
```

---

### Task 5: Add file + user + container + agent management commands to agent.py

**Files:**
- Modify: `share/noba-agent/agent.py`

- [ ] **Step 1: Add path validation helper and file commands**

```python
# ── Path safety ──────────────────────────────────────────────────────────────
_PATH_DENYLIST = frozenset({"/etc/shadow", "/etc/gshadow", "/proc/kcore"})
_PATH_DENY_PATTERNS = ("/.ssh/id_",)
_BACKUP_DIR = os.path.expanduser("~/.noba-agent/backups")


def _safe_path(path: str) -> str | None:
    """Validate and canonicalize a path. Returns error string or None."""
    if "\0" in path:
        return "Null byte in path"
    real = os.path.realpath(path)
    for denied in _PATH_DENYLIST:
        if real == denied or real.startswith(denied + "/"):
            return f"Denied path: {real}"
    for pat in _PATH_DENY_PATTERNS:
        if pat in real:
            return f"Denied pattern: {pat}"
    return None


def _cmd_file_read(params: dict, _ctx: dict) -> dict:
    path = params.get("path", "")
    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    max_bytes = 65536
    offset = params.get("offset", 0)
    lines_limit = params.get("lines", 0)
    try:
        with open(path, "r", errors="replace") as f:
            if offset:
                f.seek(offset)
            content = f.read(max_bytes)
            if lines_limit:
                content = "\n".join(content.split("\n")[:lines_limit])
        return {"status": "ok", "path": path, "content": content, "size": len(content)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_file_write(params: dict, _ctx: dict) -> dict:
    path = params.get("path", "")
    content = params.get("content", "")
    mode = params.get("mode", "0644")
    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    if len(content) > 1048576:
        return {"status": "error", "error": "Content exceeds 1MB limit"}
    try:
        # Backup existing file
        if os.path.exists(path):
            os.makedirs(_BACKUP_DIR, exist_ok=True)
            import shutil
            backup = os.path.join(_BACKUP_DIR, os.path.basename(path) + f".{int(time.time())}.bak")
            shutil.copy2(path, backup)
        with open(path, "w") as f:
            f.write(content)
        if mode and _PLATFORM != "windows":
            os.chmod(path, int(mode, 8))
        return {"status": "ok", "path": path, "bytes_written": len(content)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_file_delete(params: dict, _ctx: dict) -> dict:
    path = params.get("path", "")
    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    try:
        if os.path.exists(path):
            os.makedirs(_BACKUP_DIR, exist_ok=True)
            import shutil
            backup = os.path.join(_BACKUP_DIR, os.path.basename(path) + f".{int(time.time())}.bak")
            shutil.copy2(path, backup)
            os.remove(path)
            return {"status": "ok", "deleted": path, "backup": backup}
        return {"status": "error", "error": "File not found"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_file_list(params: dict, _ctx: dict) -> dict:
    path = params.get("path", ".")
    recursive = params.get("recursive", False)
    pattern = params.get("pattern", "*")
    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    try:
        import glob as _glob
        if recursive:
            entries = _glob.glob(os.path.join(path, "**", pattern), recursive=True)
        else:
            entries = _glob.glob(os.path.join(path, pattern))
        items = []
        for e in entries[:500]:  # Limit entries
            try:
                st = os.stat(e)
                items.append({"path": e, "size": st.st_size,
                              "is_dir": os.path.isdir(e), "mtime": int(st.st_mtime)})
            except Exception:
                items.append({"path": e, "error": "stat failed"})
        return {"status": "ok", "path": path, "count": len(items), "entries": items}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_file_checksum(params: dict, _ctx: dict) -> dict:
    path = params.get("path", "")
    algo = params.get("algo", "sha256")
    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    try:
        import hashlib
        h = hashlib.new(algo)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return {"status": "ok", "path": path, "algo": algo, "checksum": h.hexdigest()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_file_stat(params: dict, _ctx: dict) -> dict:
    path = params.get("path", "")
    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    try:
        import stat as _stat
        st = os.stat(path)
        return {"status": "ok", "path": path, "size": st.st_size,
                "mode": oct(st.st_mode), "uid": st.st_uid, "gid": st.st_gid,
                "mtime": int(st.st_mtime), "ctime": int(st.st_ctime),
                "is_dir": _stat.S_ISDIR(st.st_mode), "is_link": os.path.islink(path)}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

- [ ] **Step 2: Add user management commands**

```python
def _cmd_list_users(_params: dict, _ctx: dict) -> dict:
    try:
        if _PLATFORM == "windows":
            out = _safe_run(["net", "user"])
            return {"status": "ok", "raw": out}
        users = []
        with open("/etc/passwd", "r") as f:
            for line in f:
                parts = line.strip().split(":")
                if len(parts) >= 7 and int(parts[2]) >= 1000 and parts[6] not in ("/usr/sbin/nologin", "/bin/false"):
                    users.append({"username": parts[0], "uid": int(parts[2]),
                                  "gid": int(parts[3]), "home": parts[5], "shell": parts[6]})
        return {"status": "ok", "users": users}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_user_manage(params: dict, _ctx: dict) -> dict:
    action = params.get("action", "")
    username = params.get("username", "")
    groups = params.get("groups", [])
    try:
        if action == "create":
            cmd = ["sudo", "useradd", "-m"]
            if groups:
                cmd += ["-G", ",".join(groups)]
            cmd.append(username)
            out = _safe_run(cmd)
        elif action == "delete":
            out = _safe_run(["sudo", "userdel", "-r", username])
        elif action == "modify":
            cmd = ["sudo", "usermod"]
            if groups:
                cmd += ["-aG", ",".join(groups)]
            cmd.append(username)
            out = _safe_run(cmd)
        else:
            return {"status": "error", "error": f"Unknown action: {action}"}
        return {"status": "ok", "output": out}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

- [ ] **Step 3: Add container commands**

```python
def _cmd_container_list(params: dict, _ctx: dict) -> dict:
    rt = _detect_container_runtime()
    if not rt:
        return {"status": "error", "error": "No container runtime (docker/podman) found"}
    show_all = params.get("all", False)
    try:
        cmd = [rt, "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"]
        if show_all:
            cmd.insert(2, "-a")
        out = _safe_run(cmd)
        containers = []
        for line in out.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 4:
                containers.append({"id": parts[0], "name": parts[1], "image": parts[2],
                                   "status": parts[3], "ports": parts[4] if len(parts) > 4 else ""})
        return {"status": "ok", "runtime": rt, "containers": containers}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_container_control(params: dict, _ctx: dict) -> dict:
    rt = _detect_container_runtime()
    if not rt:
        return {"status": "error", "error": "No container runtime found"}
    name = params.get("name", "")
    action = params.get("action", "")
    try:
        out = _safe_run([rt, action, name])
        return {"status": "ok", "output": out}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _cmd_container_logs(params: dict, _ctx: dict) -> dict:
    rt = _detect_container_runtime()
    if not rt:
        return {"status": "error", "error": "No container runtime found"}
    name = params.get("name", "")
    lines = min(params.get("lines", 100), 500)
    try:
        out = _safe_run([rt, "logs", "--tail", str(lines), name])
        return {"status": "ok", "name": name, "logs": out}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

- [ ] **Step 4: Add agent management commands**

```python
def _cmd_uninstall_agent(params: dict, ctx: dict) -> dict:
    """Stop and remove the agent from this system."""
    if not params.get("confirm"):
        return {"status": "error", "error": "Uninstall requires confirm=true"}
    try:
        if _HAS_SYSTEMD:
            _safe_run(["sudo", "systemctl", "stop", "noba-agent"])
            _safe_run(["sudo", "systemctl", "disable", "noba-agent"])
            for f in ("/etc/systemd/system/noba-agent.service",
                      "/etc/noba-agent.yaml", "/opt/noba-agent/agent.py"):
                if os.path.exists(f):
                    os.remove(f)
        elif _PLATFORM == "darwin":
            _safe_run(["launchctl", "unload", "/Library/LaunchDaemons/com.noba.agent.plist"])
            for f in ("/Library/LaunchDaemons/com.noba.agent.plist",
                      "/opt/noba-agent/agent.py", "/etc/noba-agent.yaml"):
                if os.path.exists(f):
                    os.remove(f)
        return {"status": "ok", "message": "Agent uninstalled. This is the last response."}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

- [ ] **Step 5: Update the handler registry**

Replace the existing `handlers` dict in `execute_commands()` (line ~561):

```python
    handlers = {
        # Existing (v1.1.0)
        "exec": _cmd_exec,
        "restart_service": _cmd_restart_service,
        "update_agent": _cmd_update_agent,
        "set_interval": _cmd_set_interval,
        "ping": _cmd_ping,
        "get_logs": _cmd_get_logs,
        "check_service": _cmd_check_service,
        "network_test": _cmd_network_test,
        "package_updates": _cmd_package_updates,
        # New — system
        "system_info": _cmd_system_info,
        "disk_usage": _cmd_disk_usage,
        "reboot": _cmd_reboot,
        "process_kill": _cmd_process_kill,
        # New — services
        "list_services": _cmd_list_services,
        "service_control": _cmd_service_control,
        # New — network
        "network_config": _cmd_network_config,
        "dns_lookup": _cmd_dns_lookup,
        # New — files
        "file_read": _cmd_file_read,
        "file_write": _cmd_file_write,
        "file_delete": _cmd_file_delete,
        "file_list": _cmd_file_list,
        "file_checksum": _cmd_file_checksum,
        "file_stat": _cmd_file_stat,
        # New — users
        "list_users": _cmd_list_users,
        "user_manage": _cmd_user_manage,
        # New — containers
        "container_list": _cmd_container_list,
        "container_control": _cmd_container_control,
        "container_logs": _cmd_container_logs,
        # New — agent management
        "uninstall_agent": _cmd_uninstall_agent,
    }
```

Also increase the max commands per cycle from 10 to 20:
```python
    for cmd in commands[:20]:  # Max 20 commands per cycle
```

And increase `MAX_OUTPUT` from 4096 to 65536:
```python
MAX_OUTPUT = 65536   # 64KB max output per command
```

- [ ] **Step 6: Add `_safe_run` helper** (if not already present)

Check if the existing agent has a subprocess helper. If the existing helpers (`_cmd_exec` uses `subprocess.run` directly), add a shared helper:

```python
def _safe_run(cmd: list, timeout: int = 30) -> str:
    """Run a command and return stdout. Raises on failure."""
    import subprocess
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")
```

- [ ] **Step 7: Verify**

Run: `python3 -m py_compile share/noba-agent/agent.py`
Run: `python3 share/noba-agent/agent.py --dry-run 2>&1 | head -20` (should print metrics without crashing)

- [ ] **Step 8: Commit**

```
git add share/noba-agent/agent.py
git commit -m "feat(agent): add file, user, container, and agent management commands (32 total)"
```

---

### Task 6: Tests for new functionality

**Files:**
- Create: `tests/test_agent_commands.py`
- Create: `tests/test_agent_risk.py`
- Create: `tests/test_agent_persistence.py`

- [ ] **Step 1: Write `test_agent_risk.py`**

```python
"""Tests for agent risk classification and capability mapping."""
from __future__ import annotations

from server.agent_config import (
    RISK_LEVELS, check_role_permission, get_agent_capabilities,
    validate_command_params,
)


def test_all_commands_have_risk_level():
    assert len(RISK_LEVELS) == 32


def test_admin_can_execute_all():
    for cmd, risk in RISK_LEVELS.items():
        assert check_role_permission("admin", risk), f"Admin blocked from {cmd}"


def test_operator_blocked_from_high():
    assert not check_role_permission("operator", "high")


def test_operator_can_execute_low_medium():
    assert check_role_permission("operator", "low")
    assert check_role_permission("operator", "medium")


def test_viewer_blocked_from_all():
    assert not check_role_permission("viewer", "low")
    assert not check_role_permission("viewer", "medium")
    assert not check_role_permission("viewer", "high")


def test_v1_capabilities():
    caps = get_agent_capabilities("1.1.0")
    assert "exec" in caps
    assert "ping" in caps
    assert "system_info" not in caps  # v2 only


def test_v2_capabilities():
    caps = get_agent_capabilities("2.0.0")
    assert len(caps) == 32
    assert "system_info" in caps
    assert "uninstall_agent" in caps


def test_unknown_version_defaults_to_v1():
    caps = get_agent_capabilities("0.9.0")
    assert caps == get_agent_capabilities("1.1.0")


def test_validate_service_name():
    assert validate_command_params("restart_service", {"service": "nginx"}) is None
    assert validate_command_params("restart_service", {"service": ""}) is not None
    assert validate_command_params("restart_service", {"service": "rm -rf /"}) is not None


def test_validate_file_path():
    assert validate_command_params("file_read", {"path": "/var/log/syslog"}) is None
    assert validate_command_params("file_read", {"path": "/etc/shadow"}) is not None
    assert validate_command_params("file_read", {"path": "/home/../etc/shadow"}) is not None
    assert validate_command_params("file_read", {"path": ""}) is not None


def test_validate_package_names():
    assert validate_command_params("package_install", {"packages": ["nginx", "curl"]}) is None
    assert validate_command_params("package_install", {"packages": []}) is not None
    assert validate_command_params("package_install", {"packages": ["rm -rf /"]}) is not None


def test_validate_user_manage():
    assert validate_command_params("user_manage", {"action": "create", "username": "testuser"}) is None
    assert validate_command_params("user_manage", {"action": "create", "username": "ROOT"}) is not None
    assert validate_command_params("user_manage", {"action": "modify", "username": "test", "groups": ["sudo"]}) is not None


def test_validate_uninstall_requires_confirm():
    assert validate_command_params("uninstall_agent", {}) is not None
    assert validate_command_params("uninstall_agent", {"confirm": True}) is None
```

- [ ] **Step 2: Write `test_agent_persistence.py`**

```python
"""Tests for agent registry persistence."""
from __future__ import annotations

import time


def test_upsert_and_get_agents(tmp_path):
    from server.db.core import Database
    db = Database(str(tmp_path / "test.db"))
    db.upsert_agent("node1", "192.168.1.10", "linux", "x86_64", "2.0.0")
    db.upsert_agent("node2", "192.168.1.11", "darwin", "arm64", "1.1.0")
    agents = db.get_all_agents()
    assert len(agents) == 2
    names = {a["hostname"] for a in agents}
    assert names == {"node1", "node2"}


def test_upsert_updates_existing(tmp_path):
    from server.db.core import Database
    db = Database(str(tmp_path / "test.db"))
    db.upsert_agent("node1", "192.168.1.10", "linux", "x86_64", "1.1.0")
    db.upsert_agent("node1", "10.0.0.5", "linux", "x86_64", "2.0.0")
    agents = db.get_all_agents()
    assert len(agents) == 1
    assert agents[0]["ip"] == "10.0.0.5"
    assert agents[0]["agent_version"] == "2.0.0"


def test_delete_agent(tmp_path):
    from server.db.core import Database
    db = Database(str(tmp_path / "test.db"))
    db.upsert_agent("node1", "192.168.1.10", "linux", "x86_64", "2.0.0")
    db.delete_agent("node1")
    assert db.get_all_agents() == []


def test_update_agent_config(tmp_path):
    from server.db.core import Database
    db = Database(str(tmp_path / "test.db"))
    db.upsert_agent("node1", "192.168.1.10", "linux", "x86_64", "2.0.0")
    db.update_agent_config("node1", {"tags": ["site-a"], "notes": "Main server"})
    agents = db.get_all_agents()
    assert agents[0]["config"]["tags"] == ["site-a"]
```

- [ ] **Step 3: Write `test_agent_commands.py`**

```python
"""Tests for agent command handlers (import and basic validation)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _load_agent():
    """Import agent.py as a module for testing."""
    agent_path = Path(__file__).parent.parent / "share" / "noba-agent" / "agent.py"
    spec = importlib.util.spec_from_file_location("noba_agent", agent_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_agent_loads():
    agent = _load_agent()
    assert agent.VERSION == "2.0.0"


def test_handler_registry_complete():
    agent = _load_agent()
    # Call execute_commands with empty list to get the handlers dict
    ctx = {"server": "", "api_key": "", "config_path": "", "script_path": ""}
    # The handlers dict is inside execute_commands — test by sending unknown command
    results = agent.execute_commands([{"type": "ping", "id": "test", "params": {}}], ctx)
    assert len(results) == 1
    assert results[0]["status"] == "ok"


def test_system_info_command():
    agent = _load_agent()
    result = agent._cmd_system_info({}, {})
    assert result["status"] == "ok"
    assert "hostname" in result["info"]
    assert "platform" in result["info"]


def test_disk_usage_command():
    agent = _load_agent()
    result = agent._cmd_disk_usage({"path": "/"}, {})
    assert result["status"] == "ok"
    assert result["total"] > 0


def test_file_read_denied_path():
    agent = _load_agent()
    result = agent._cmd_file_read({"path": "/etc/shadow"}, {})
    assert result["status"] == "error"
    assert "Denied" in result["error"]


def test_file_list_command():
    agent = _load_agent()
    result = agent._cmd_file_list({"path": "/tmp"}, {})
    assert result["status"] == "ok"
    assert "entries" in result


def test_dns_lookup_command():
    agent = _load_agent()
    result = agent._cmd_dns_lookup({"domain": "localhost", "type": "A"}, {})
    assert result["status"] == "ok"


def test_list_users_command():
    agent = _load_agent()
    result = agent._cmd_list_users({}, {})
    assert result["status"] == "ok"
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/test_agent_commands.py tests/test_agent_risk.py tests/test_agent_persistence.py -v`
Run: `pytest tests/ -x -q` — ALL tests must pass

- [ ] **Step 5: Commit**

```
git add tests/test_agent_commands.py tests/test_agent_risk.py tests/test_agent_persistence.py
git commit -m "test(agent): add tests for commands, risk enforcement, and persistence"
```

---

### Task 7: Phase 1a Checkpoint

- [ ] **Step 1: Full test suite**

Run: `pytest tests/ -v`

- [ ] **Step 2: Lint**

Run: `ruff check share/noba-web/server/`

- [ ] **Step 3: Agent syntax**

Run: `python3 -m py_compile share/noba-agent/agent.py`

- [ ] **Step 4: Agent dry run**

Run: `python3 share/noba-agent/agent.py --dry-run`
Expected: Prints metrics JSON without errors

- [ ] **Step 5: Verify handler count**

Run: `grep -c "_cmd_" share/noba-agent/agent.py`
Expected: 32+ (one per command handler plus the _cmd prefix in variable names)

- [ ] **Step 6: Reinstall and verify**

Run: `bash install.sh -y --skip-deps`
Run: `systemctl --user restart noba-web.service`
Run: `sleep 3 && curl -s http://localhost:8080/api/health`

- [ ] **Step 7: Commit checkpoint**

```
git commit --allow-empty -m "checkpoint: Phase 1a complete — 32 commands, persistence, risk tiers"
```
