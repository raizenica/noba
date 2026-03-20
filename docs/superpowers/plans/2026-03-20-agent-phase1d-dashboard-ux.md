# Agent Enhancement Phase 1d: Dashboard UX — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the basic agent command text input with a structured command palette, overhaul the agent list with filters and bulk select, add a tabbed output panel with streaming, add command history, and build an agent detail modal with Overview/Services/History tabs.

**Architecture:** All frontend work uses Alpine.js (existing pattern). New command palette is a structured form (category → command → dynamic params). Output panel shows tabbed results per agent. Command history stored in SQLite with a new API endpoint. Agent detail modal reuses existing agent data + history endpoint.

**Tech Stack:** Alpine.js, vanilla CSS (existing patterns), Chart.js, FastAPI, SQLite

**Spec:** `docs/superpowers/specs/2026-03-20-agent-enhancement-design.md` — Phase 1d section

---

## File Structure

### Server-side:
- Modify: `share/noba-web/server/db/core.py` — add `agent_command_history` table
- Create: `share/noba-web/server/db/command_history.py` — history DB functions
- Modify: `share/noba-web/server/routers/system.py` — command history endpoint, record commands on execute

### Frontend:
- Modify: `share/noba-web/index.html` — new command palette, agent list, output panel, history table, detail modal
- Modify: `share/noba-web/static/integration-actions.js` — command palette logic, history fetch, detail modal
- Modify: `share/noba-web/static/app.js` — new state variables
- Modify: `share/noba-web/static/style.css` — new component styles

### Tests:
- Create: `tests/test_command_history.py` — history endpoint and DB tests

---

### Task 1: Command history database table

**Files:**
- Modify: `share/noba-web/server/db/core.py`
- Create: `share/noba-web/server/db/command_history.py`

- [ ] **Step 1: Add table to schema**

In `core.py`, add the `agent_command_history` table creation:

```sql
CREATE TABLE IF NOT EXISTS agent_command_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cmd_id TEXT UNIQUE,
    hostname TEXT NOT NULL,
    cmd_type TEXT NOT NULL,
    params_json TEXT DEFAULT '{}',
    status TEXT DEFAULT 'queued',
    queued_by TEXT,
    queued_at INTEGER,
    completed_at INTEGER,
    duration_ms INTEGER,
    result_json TEXT,
    risk_level TEXT
);
CREATE INDEX IF NOT EXISTS idx_cmd_history_host ON agent_command_history(hostname, queued_at);
CREATE INDEX IF NOT EXISTS idx_cmd_history_time ON agent_command_history(queued_at);
```

- [ ] **Step 2: Create `command_history.py`**

```python
"""Noba – Agent command history persistence."""
from __future__ import annotations

import json
import time


def record_command(conn, lock, cmd_id, hostname, cmd_type, params, queued_by, risk_level):
    """Record a queued command in history."""
    now = int(time.time())
    with lock:
        conn.execute("""
            INSERT OR IGNORE INTO agent_command_history
            (cmd_id, hostname, cmd_type, params_json, status, queued_by, queued_at, risk_level)
            VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)
        """, (cmd_id, hostname, cmd_type, json.dumps(params), queued_by, now, risk_level))
        conn.commit()


def complete_command(conn, lock, cmd_id, status, result):
    """Mark a command as completed with result."""
    now = int(time.time())
    with lock:
        row = conn.execute(
            "SELECT queued_at FROM agent_command_history WHERE cmd_id = ?", (cmd_id,)
        ).fetchone()
        duration = (now - row[0]) * 1000 if row else 0
        conn.execute("""
            UPDATE agent_command_history
            SET status = ?, completed_at = ?, duration_ms = ?, result_json = ?
            WHERE cmd_id = ?
        """, (status, now, duration, json.dumps(result), cmd_id))
        conn.commit()


def get_history(conn, lock, hostname=None, limit=50, offset=0):
    """Get command history, optionally filtered by hostname."""
    with lock:
        if hostname:
            rows = conn.execute("""
                SELECT cmd_id, hostname, cmd_type, params_json, status,
                       queued_by, queued_at, completed_at, duration_ms, result_json, risk_level
                FROM agent_command_history
                WHERE hostname = ?
                ORDER BY queued_at DESC LIMIT ? OFFSET ?
            """, (hostname, limit, offset)).fetchall()
        else:
            rows = conn.execute("""
                SELECT cmd_id, hostname, cmd_type, params_json, status,
                       queued_by, queued_at, completed_at, duration_ms, result_json, risk_level
                FROM agent_command_history
                ORDER BY queued_at DESC LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()
    return [
        {
            "cmd_id": r[0], "hostname": r[1], "cmd_type": r[2],
            "params": json.loads(r[3] or "{}"), "status": r[4],
            "queued_by": r[5], "queued_at": r[6], "completed_at": r[7],
            "duration_ms": r[8], "result": json.loads(r[9] or "null"),
            "risk_level": r[10],
        }
        for r in rows
    ]
```

- [ ] **Step 3: Wire into db/core.py**

Import and re-export the functions. Add delegation methods to the DB class if that pattern is used.

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/db/
git commit -m "feat(agent): add command history SQLite table and functions"
```

---

### Task 2: Command history API endpoint + recording

**Files:**
- Modify: `share/noba-web/server/routers/system.py`

- [ ] **Step 1: Add history endpoint**

```python
@router.get("/api/agents/command-history")
def api_command_history(request: Request, auth=Depends(_get_auth)):
    """Get recent command history."""
    hostname = request.query_params.get("hostname")
    limit = min(int(request.query_params.get("limit", "50")), 200)
    offset = int(request.query_params.get("offset", "0"))
    return db.get_command_history(hostname=hostname, limit=limit, offset=offset)
```

- [ ] **Step 2: Record commands when queued**

In `api_agent_command()`, after the command is created but before returning:

```python
db.record_command(cmd_id, hostname, cmd_type, params, username, risk)
```

Same in `api_bulk_command()`.

- [ ] **Step 3: Complete commands when results arrive**

In `api_agent_report()`, when processing `_cmd_results`, update history:

```python
for result in cmd_results:
    cmd_id = result.get("id", "")
    status = result.get("status", "unknown")
    if cmd_id:
        db.complete_command(cmd_id, status, result)
```

- [ ] **Step 4: Run lint and tests**

```bash
ruff check share/noba-web/server/ --fix
pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add share/noba-web/server/routers/system.py
git commit -m "feat(agent): add command history endpoint and recording"
```

---

### Task 3: Frontend state for command palette and history

**Files:**
- Modify: `share/noba-web/static/app.js`

- [ ] **Step 1: Add new state variables**

Add to the data section of the `dashboard()` function:

```javascript
// Command palette state
cmdPalette: {
    targets: [],          // Selected agent hostnames
    category: '',         // System, Services, Files, etc.
    command: '',          // Selected command type
    params: {},           // Dynamic params for selected command
    sending: false,
    risk: '',             // Current command risk level
},

// Command categories and their commands (static config)
cmdCategories: {
    'System':     ['system_info', 'disk_usage', 'reboot', 'process_kill', 'exec'],
    'Services':   ['list_services', 'service_control', 'restart_service', 'check_service'],
    'Files':      ['file_read', 'file_write', 'file_delete', 'file_list', 'file_checksum', 'file_stat', 'file_transfer', 'file_push'],
    'Network':    ['network_test', 'network_config', 'dns_lookup', 'ping'],
    'Packages':   ['package_updates'],
    'Users':      ['list_users', 'user_manage'],
    'Containers': ['container_list', 'container_control', 'container_logs'],
    'Agent':      ['set_interval', 'update_agent', 'uninstall_agent', 'get_logs'],
},

// Risk levels (mirrors server)
cmdRiskLevels: {
    ping: 'low', check_service: 'low', get_logs: 'low', network_test: 'low',
    package_updates: 'low', system_info: 'low', disk_usage: 'low',
    list_services: 'low', list_users: 'low', file_read: 'low', file_list: 'low',
    file_checksum: 'low', file_stat: 'low', container_list: 'low',
    container_logs: 'low', dns_lookup: 'low', network_config: 'low',
    restart_service: 'medium', set_interval: 'medium', service_control: 'medium',
    file_transfer: 'medium', file_push: 'medium', container_control: 'medium',
    exec: 'high', file_write: 'high', file_delete: 'high', update_agent: 'high',
    user_manage: 'high', uninstall_agent: 'high', reboot: 'high', process_kill: 'high',
},

// Command parameter definitions (what fields each command needs)
cmdParamDefs: {
    exec: [{name: 'command', type: 'text', label: 'Command', required: true}],
    restart_service: [{name: 'service', type: 'text', label: 'Service name', required: true}],
    service_control: [
        {name: 'service', type: 'text', label: 'Service name', required: true},
        {name: 'action', type: 'select', label: 'Action', options: ['start','stop','restart','enable','disable','status'], required: true},
    ],
    get_logs: [
        {name: 'unit', type: 'text', label: 'Unit (optional)'},
        {name: 'lines', type: 'number', label: 'Lines', default: 50},
        {name: 'priority', type: 'select', label: 'Priority', options: ['','emerg','alert','crit','err','warning','notice','info','debug']},
    ],
    file_read: [{name: 'path', type: 'text', label: 'File path', required: true}, {name: 'lines', type: 'number', label: 'Max lines'}],
    file_write: [{name: 'path', type: 'text', label: 'File path', required: true}, {name: 'content', type: 'textarea', label: 'Content', required: true}],
    file_delete: [{name: 'path', type: 'text', label: 'File path', required: true}],
    file_list: [{name: 'path', type: 'text', label: 'Directory', default: '/'}, {name: 'pattern', type: 'text', label: 'Glob pattern', default: '*'}],
    file_checksum: [{name: 'path', type: 'text', label: 'File path', required: true}, {name: 'algorithm', type: 'select', label: 'Algorithm', options: ['sha256','md5']}],
    file_stat: [{name: 'path', type: 'text', label: 'File path', required: true}],
    disk_usage: [{name: 'path', type: 'text', label: 'Path', default: '/'}],
    network_test: [{name: 'target', type: 'text', label: 'Target host', required: true}, {name: 'mode', type: 'select', label: 'Mode', options: ['ping','trace']}],
    dns_lookup: [{name: 'host', type: 'text', label: 'Hostname', required: true}, {name: 'type', type: 'select', label: 'Record type', options: ['A','AAAA','MX','NS','TXT','CNAME']}],
    process_kill: [{name: 'pid', type: 'number', label: 'PID'}, {name: 'name', type: 'text', label: 'Process name'}, {name: 'signal', type: 'select', label: 'Signal', options: ['TERM','KILL','HUP','INT']}],
    set_interval: [{name: 'interval', type: 'number', label: 'Seconds (5-86400)', required: true}],
    reboot: [{name: 'delay', type: 'number', label: 'Delay (minutes)', default: 0}],
    container_control: [{name: 'container', type: 'text', label: 'Container name', required: true}, {name: 'action', type: 'select', label: 'Action', options: ['start','stop','restart'], required: true}],
    container_logs: [{name: 'container', type: 'text', label: 'Container name', required: true}, {name: 'tail', type: 'number', label: 'Tail lines', default: 100}],
    user_manage: [{name: 'action', type: 'select', label: 'Action', options: ['add','delete','modify'], required: true}, {name: 'username', type: 'text', label: 'Username', required: true}, {name: 'groups', type: 'text', label: 'Groups (comma-separated)'}],
    uninstall_agent: [{name: 'confirm', type: 'hidden', value: true}],
},

// Output panel
cmdOutputTabs: {},       // hostname -> [{id, type, status, output, timestamp}]
cmdOutputActiveTab: '',  // Current tab hostname

// Command history
cmdHistory: [],
cmdHistoryLoading: false,

// Agent detail modal
agentDetailHost: null,
agentDetailTab: 'overview',  // overview, services, history
agentDetailServices: [],
agentDetailHistory: [],
```

- [ ] **Step 2: Commit**

```bash
git add share/noba-web/static/app.js
git commit -m "feat(agent): add command palette and history state variables"
```

---

### Task 4: Command palette HTML + JS

**Files:**
- Modify: `share/noba-web/index.html`
- Modify: `share/noba-web/static/integration-actions.js`

- [ ] **Step 1: Replace existing agent command input**

In `index.html`, replace the existing exec input section (around line 5110-5124) with the new command palette. The palette has:
- Multi-select target dropdown (online agents + "All")
- Category dropdown
- Command dropdown (filtered by category, grayed if role can't execute)
- Dynamic parameter fields (generated from `cmdParamDefs`)
- Risk badge (green/yellow/red)
- Run button

```html
<!-- Command Palette -->
<div class="cmd-palette" x-show="userRole !== 'viewer'">
    <div class="cmd-palette-header">
        <i class="fas fa-terminal"></i> Command Palette
    </div>
    <div class="cmd-palette-row">
        <!-- Target selection -->
        <div class="cmd-field">
            <label>Target</label>
            <select x-model="cmdPalette.targets" multiple class="cmd-select-multi">
                <option value="__all__">All Online Agents</option>
                <template x-for="a in (agents||[]).filter(a => a.online)" :key="a.hostname">
                    <option :value="a.hostname" x-text="a.hostname"></option>
                </template>
            </select>
        </div>
        <!-- Category -->
        <div class="cmd-field">
            <label>Category</label>
            <select x-model="cmdPalette.category" @change="cmdPalette.command = ''; cmdPalette.params = {}">
                <option value="">Select...</option>
                <template x-for="cat in Object.keys(cmdCategories)" :key="cat">
                    <option :value="cat" x-text="cat"></option>
                </template>
            </select>
        </div>
        <!-- Command -->
        <div class="cmd-field">
            <label>Command</label>
            <select x-model="cmdPalette.command" @change="cmdPalette.params = {}; cmdPalette.risk = cmdRiskLevels[cmdPalette.command] || ''">
                <option value="">Select...</option>
                <template x-for="cmd in (cmdCategories[cmdPalette.category] || [])" :key="cmd">
                    <option :value="cmd" x-text="cmd.replace(/_/g, ' ')"
                            :disabled="cmdRiskLevels[cmd] === 'high' && userRole !== 'admin'"></option>
                </template>
            </select>
        </div>
        <!-- Risk badge -->
        <div class="cmd-field cmd-risk" x-show="cmdPalette.risk">
            <span class="risk-badge" :class="'risk-' + cmdPalette.risk"
                  x-text="cmdPalette.risk"></span>
        </div>
    </div>
    <!-- Dynamic params -->
    <div class="cmd-palette-params" x-show="cmdPalette.command && cmdParamDefs[cmdPalette.command]">
        <template x-for="param in (cmdParamDefs[cmdPalette.command] || [])" :key="param.name">
            <div class="cmd-field" x-show="param.type !== 'hidden'">
                <label x-text="param.label"></label>
                <template x-if="param.type === 'text'">
                    <input type="text" x-model="cmdPalette.params[param.name]"
                           :placeholder="param.label" :required="param.required">
                </template>
                <template x-if="param.type === 'number'">
                    <input type="number" x-model.number="cmdPalette.params[param.name]"
                           :placeholder="param.default || ''">
                </template>
                <template x-if="param.type === 'textarea'">
                    <textarea x-model="cmdPalette.params[param.name]"
                              :placeholder="param.label" rows="4"></textarea>
                </template>
                <template x-if="param.type === 'select'">
                    <select x-model="cmdPalette.params[param.name]">
                        <option value="">Select...</option>
                        <template x-for="opt in (param.options || [])" :key="opt">
                            <option :value="opt" x-text="opt"></option>
                        </template>
                    </select>
                </template>
            </div>
        </template>
    </div>
    <!-- Run button -->
    <div class="cmd-palette-actions">
        <button class="btn btn-accent" @click="runPaletteCommand()"
                :disabled="!cmdPalette.command || cmdPalette.targets.length === 0 || cmdPalette.sending">
            <i class="fas" :class="cmdPalette.sending ? 'fa-spinner fa-spin' : 'fa-play'"></i>
            <span x-text="cmdPalette.sending ? 'Running...' : 'Run Command'"></span>
        </button>
    </div>
</div>
```

- [ ] **Step 2: Add `runPaletteCommand()` in integration-actions.js**

```javascript
async runPaletteCommand() {
    if (!this.cmdPalette.command || this.cmdPalette.targets.length === 0) return;
    this.cmdPalette.sending = true;

    const targets = this.cmdPalette.targets.includes('__all__')
        ? (this.agents || []).filter(a => a.online).map(a => a.hostname)
        : this.cmdPalette.targets;

    // Build clean params (remove empty values)
    const params = {};
    for (const [k, v] of Object.entries(this.cmdPalette.params)) {
        if (v !== '' && v !== null && v !== undefined) params[k] = v;
    }
    // Add hidden params
    const defs = this.cmdParamDefs[this.cmdPalette.command] || [];
    for (const def of defs) {
        if (def.type === 'hidden') params[def.name] = def.value;
    }

    for (const hostname of targets) {
        try {
            const resp = await fetch(`/api/agents/${hostname}/command`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'Authorization': `Bearer ${this.token}`},
                body: JSON.stringify({type: this.cmdPalette.command, params}),
            });
            const data = await resp.json();
            if (!this.cmdOutputTabs[hostname]) this.cmdOutputTabs[hostname] = [];
            this.cmdOutputTabs[hostname].unshift({
                id: data.id, type: this.cmdPalette.command,
                status: 'pending', output: null,
                timestamp: Date.now(), websocket: data.websocket || false,
            });
            this.cmdOutputActiveTab = hostname;
            // Poll for results
            this.pollCommandResult(hostname, data.id);
        } catch (e) {
            console.error(`Command to ${hostname} failed:`, e);
        }
    }
    this.cmdPalette.sending = false;
},

async pollCommandResult(hostname, cmdId) {
    const delays = [2000, 5000, 10000, 20000, 30000];
    for (const delay of delays) {
        await new Promise(r => setTimeout(r, delay));
        try {
            const resp = await fetch(`/api/agents/${hostname}/results`, {
                headers: {'Authorization': `Bearer ${this.token}`},
            });
            const results = await resp.json();
            const match = results.find(r => r.id === cmdId);
            if (match) {
                const tab = (this.cmdOutputTabs[hostname] || []).find(t => t.id === cmdId);
                if (tab) {
                    tab.status = match.status || 'completed';
                    tab.output = match;
                }
                return;
            }
        } catch (e) { /* retry */ }
    }
},
```

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/index.html share/noba-web/static/integration-actions.js
git commit -m "feat(agent): add command palette UI with dynamic parameter forms"
```

---

### Task 5: Output panel HTML

**Files:**
- Modify: `share/noba-web/index.html`

- [ ] **Step 1: Add tabbed output panel below command palette**

```html
<!-- Output Panel -->
<div class="cmd-output-panel" x-show="Object.keys(cmdOutputTabs).length > 0">
    <div class="cmd-output-tabs">
        <template x-for="[host, results] in Object.entries(cmdOutputTabs)" :key="host">
            <button class="cmd-output-tab"
                    :class="{'active': cmdOutputActiveTab === host}"
                    @click="cmdOutputActiveTab = host">
                <span x-text="host"></span>
                <span class="cmd-output-count" x-text="results.length"></span>
            </button>
        </template>
    </div>
    <div class="cmd-output-body">
        <template x-for="entry in (cmdOutputTabs[cmdOutputActiveTab] || []).slice(0, 20)" :key="entry.id">
            <div class="cmd-result-entry" :class="{'error': entry.status === 'error'}">
                <div class="cmd-result-header">
                    <span class="cmd-result-type" x-text="entry.type.replace(/_/g, ' ')"></span>
                    <span class="cmd-result-status" :class="'status-' + entry.status" x-text="entry.status"></span>
                    <span class="cmd-result-time" x-text="new Date(entry.timestamp).toLocaleTimeString()"></span>
                    <button class="icon-btn" @click="navigator.clipboard.writeText(JSON.stringify(entry.output, null, 2))" title="Copy"><i class="fas fa-copy"></i></button>
                </div>
                <pre class="cmd-result-output" x-show="entry.output"
                     x-text="typeof entry.output === 'object' ? JSON.stringify(entry.output, null, 2) : entry.output"></pre>
            </div>
        </template>
    </div>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add share/noba-web/index.html
git commit -m "feat(agent): add tabbed output panel for command results"
```

---

### Task 6: Command history UI

**Files:**
- Modify: `share/noba-web/index.html`
- Modify: `share/noba-web/static/integration-actions.js`

- [ ] **Step 1: Add history table in agents modal**

```html
<!-- Command History Section -->
<div class="section-header" style="margin-top:1rem;">
    <i class="fas fa-history"></i> Command History
    <button class="icon-btn" @click="fetchCommandHistory()" title="Refresh">
        <i class="fas fa-sync-alt"></i>
    </button>
</div>
<div class="cmd-history-table" x-show="cmdHistory.length > 0">
    <table class="data-table">
        <thead>
            <tr>
                <th>Time</th><th>Target</th><th>Command</th><th>Risk</th>
                <th>Status</th><th>Duration</th><th>By</th><th></th>
            </tr>
        </thead>
        <tbody>
            <template x-for="h in cmdHistory" :key="h.cmd_id">
                <tr>
                    <td x-text="new Date(h.queued_at * 1000).toLocaleString()"></td>
                    <td x-text="h.hostname"></td>
                    <td x-text="h.cmd_type.replace(/_/g, ' ')"></td>
                    <td><span class="risk-badge" :class="'risk-' + h.risk_level" x-text="h.risk_level"></span></td>
                    <td><span :class="'status-' + h.status" x-text="h.status"></span></td>
                    <td x-text="h.duration_ms ? (h.duration_ms / 1000).toFixed(1) + 's' : '—'"></td>
                    <td x-text="h.queued_by"></td>
                    <td>
                        <button class="icon-btn" title="Re-run"
                                @click="cmdPalette.command = h.cmd_type; cmdPalette.params = {...h.params}; cmdPalette.targets = [h.hostname]">
                            <i class="fas fa-redo"></i>
                        </button>
                    </td>
                </tr>
            </template>
        </tbody>
    </table>
</div>
```

- [ ] **Step 2: Add `fetchCommandHistory()` in integration-actions.js**

```javascript
async fetchCommandHistory(hostname = null) {
    this.cmdHistoryLoading = true;
    try {
        let url = '/api/agents/command-history?limit=50';
        if (hostname) url += `&hostname=${hostname}`;
        const resp = await fetch(url, {
            headers: {'Authorization': `Bearer ${this.token}`},
        });
        this.cmdHistory = await resp.json();
    } catch (e) {
        console.error('Failed to fetch command history:', e);
    }
    this.cmdHistoryLoading = false;
},
```

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/index.html share/noba-web/static/integration-actions.js
git commit -m "feat(agent): add command history table with re-run support"
```

---

### Task 7: Agent detail modal

**Files:**
- Modify: `share/noba-web/index.html`
- Modify: `share/noba-web/static/integration-actions.js`

- [ ] **Step 1: Add agent detail modal HTML**

3 tabs: Overview (OS, kernel, IPs, uptime, version, CPU/RAM/disk charts), Services (scrollable list with toggle switches), History (command history for this agent).

```html
<!-- Agent Detail Modal -->
<div class="modal-overlay" x-show="agentDetailHost" @click.self="agentDetailHost = null" x-cloak>
    <div class="modal-box modal-lg">
        <div class="modal-title">
            <i class="fas" :class="getAgentOsIcon(agentDetailHost)"></i>
            <span x-text="agentDetailHost?.hostname || ''"></span>
            <span class="badge" :class="agentDetailHost?.online ? 'badge-ok' : 'badge-fail'"
                  x-text="agentDetailHost?.online ? 'Online' : 'Offline'"></span>
            <button class="modal-close" @click="agentDetailHost = null"><i class="fas fa-times"></i></button>
        </div>

        <!-- Tabs -->
        <div class="tab-bar">
            <button class="tab-btn" :class="{'active': agentDetailTab === 'overview'}" @click="agentDetailTab = 'overview'">Overview</button>
            <button class="tab-btn" :class="{'active': agentDetailTab === 'services'}" @click="agentDetailTab = 'services'; fetchAgentServices()">Services</button>
            <button class="tab-btn" :class="{'active': agentDetailTab === 'history'}" @click="agentDetailTab = 'history'; fetchCommandHistory(agentDetailHost?.hostname)">History</button>
        </div>

        <!-- Overview Tab -->
        <div class="modal-body" x-show="agentDetailTab === 'overview'">
            <div class="detail-grid">
                <div class="detail-item"><label>Hostname</label><span x-text="agentDetailHost?.hostname"></span></div>
                <div class="detail-item"><label>Platform</label><span x-text="agentDetailHost?.platform"></span></div>
                <div class="detail-item"><label>Architecture</label><span x-text="agentDetailHost?.arch"></span></div>
                <div class="detail-item"><label>Agent Version</label><span x-text="agentDetailHost?.agent_version"></span></div>
                <div class="detail-item"><label>IP</label><span x-text="agentDetailHost?.ip || agentDetailHost?._ip"></span></div>
                <div class="detail-item"><label>Last Seen</label><span x-text="agentDetailHost?.last_seen_s ? agentDetailHost.last_seen_s + 's ago' : '—'"></span></div>
            </div>
            <!-- CPU/RAM/Disk bars -->
            <div class="detail-meters">
                <div class="meter-row">
                    <label>CPU</label>
                    <div class="meter"><div class="meter-fill" :style="'width:' + (agentDetailHost?.cpu_percent||0) + '%'" :class="(agentDetailHost?.cpu_percent||0) > 90 ? 'fail' : (agentDetailHost?.cpu_percent||0) > 70 ? 'warn' : 'ok'"></div></div>
                    <span x-text="(agentDetailHost?.cpu_percent||0).toFixed(1) + '%'"></span>
                </div>
                <div class="meter-row">
                    <label>RAM</label>
                    <div class="meter"><div class="meter-fill" :style="'width:' + (agentDetailHost?.mem_percent||0) + '%'" :class="(agentDetailHost?.mem_percent||0) > 90 ? 'fail' : (agentDetailHost?.mem_percent||0) > 70 ? 'warn' : 'ok'"></div></div>
                    <span x-text="(agentDetailHost?.mem_percent||0).toFixed(1) + '%'"></span>
                </div>
            </div>
            <!-- History chart -->
            <div style="margin-top:1rem;">
                <canvas id="agentDetailChart" height="120"></canvas>
            </div>
        </div>

        <!-- Services Tab -->
        <div class="modal-body" x-show="agentDetailTab === 'services'">
            <div class="services-list" x-show="agentDetailServices.length > 0">
                <template x-for="svc in agentDetailServices" :key="svc.name">
                    <div class="service-row">
                        <span class="svc-indicator" :class="svc.active ? 'svc-active' : 'svc-inactive'"></span>
                        <span class="svc-name" x-text="svc.name"></span>
                        <span class="svc-status" x-text="svc.status"></span>
                        <button class="icon-btn" x-show="userRole !== 'viewer'"
                                @click="runPaletteCommandDirect(agentDetailHost.hostname, 'service_control', {service: svc.name, action: svc.active ? 'stop' : 'start'})"
                                :title="svc.active ? 'Stop' : 'Start'">
                            <i class="fas" :class="svc.active ? 'fa-stop' : 'fa-play'"></i>
                        </button>
                    </div>
                </template>
            </div>
            <p x-show="agentDetailServices.length === 0" style="opacity:.5">Loading services...</p>
        </div>

        <!-- History Tab -->
        <div class="modal-body" x-show="agentDetailTab === 'history'">
            <!-- Reuse cmdHistory table filtered to this agent -->
            <template x-for="h in cmdHistory.filter(h => h.hostname === agentDetailHost?.hostname)" :key="h.cmd_id">
                <div class="cmd-result-entry">
                    <span x-text="new Date(h.queued_at * 1000).toLocaleTimeString()"></span>
                    <span x-text="h.cmd_type.replace(/_/g, ' ')"></span>
                    <span :class="'status-' + h.status" x-text="h.status"></span>
                </div>
            </template>
        </div>

        <div class="modal-footer">
            <button class="btn" @click="agentDetailHost = null">Close</button>
        </div>
    </div>
</div>
```

- [ ] **Step 2: Add detail modal helpers in integration-actions.js**

```javascript
openAgentDetail(hostname) {
    const agent = (this.agents || []).find(a => a.hostname === hostname);
    if (!agent) return;
    this.agentDetailHost = agent;
    this.agentDetailTab = 'overview';
    this.agentDetailServices = [];
    this.agentDetailHistory = [];
    this.fetchAgentHistory(hostname, 'cpu', 24);
},

async fetchAgentServices() {
    if (!this.agentDetailHost) return;
    const hostname = this.agentDetailHost.hostname;
    // Send list_services command and poll result
    await this.sendAgentCmd(hostname, 'list_services', {});
    // Result will come back via pollAgentResult
},

getAgentOsIcon(agent) {
    if (!agent) return 'fa-server';
    const p = (agent.platform || '').toLowerCase();
    if (p.includes('linux')) return 'fa-linux';
    if (p.includes('windows') || p.includes('win')) return 'fa-windows';
    if (p.includes('darwin') || p.includes('mac')) return 'fa-apple';
    if (p.includes('freebsd') || p.includes('bsd')) return 'fa-freebsd';
    return 'fa-server';
},

async runPaletteCommandDirect(hostname, cmdType, params) {
    try {
        const resp = await fetch(`/api/agents/${hostname}/command`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'Authorization': `Bearer ${this.token}`},
            body: JSON.stringify({type: cmdType, params}),
        });
        const data = await resp.json();
        this.pollCommandResult(hostname, data.id);
    } catch (e) {
        console.error(`Direct command to ${hostname} failed:`, e);
    }
},
```

- [ ] **Step 3: Wire agent card clicks to open detail modal**

In the agents list, make each hostname clickable:
```html
<span class="agent-hostname" style="cursor:pointer; text-decoration:underline;"
      @click="openAgentDetail(a.hostname)" x-text="a.hostname"></span>
```

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/index.html share/noba-web/static/integration-actions.js
git commit -m "feat(agent): add agent detail modal with Overview/Services/History tabs"
```

---

### Task 8: CSS styles

**Files:**
- Modify: `share/noba-web/static/style.css`

- [ ] **Step 1: Add command palette and output panel styles**

```css
/* ── Command Palette ── */
.cmd-palette { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
.cmd-palette-header { font-weight: 600; margin-bottom: .75rem; display: flex; align-items: center; gap: .5rem; }
.cmd-palette-row { display: flex; gap: .75rem; flex-wrap: wrap; align-items: end; }
.cmd-field { display: flex; flex-direction: column; gap: .25rem; min-width: 140px; flex: 1; }
.cmd-field label { font-size: .75rem; opacity: .6; text-transform: uppercase; letter-spacing: .5px; }
.cmd-field input, .cmd-field select, .cmd-field textarea { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: .4rem .6rem; color: var(--text); font-size: .85rem; }
.cmd-field textarea { font-family: var(--mono); resize: vertical; }
.cmd-select-multi { min-height: 60px; }
.cmd-palette-params { display: flex; gap: .75rem; flex-wrap: wrap; margin-top: .75rem; padding-top: .75rem; border-top: 1px solid var(--border); }
.cmd-palette-actions { margin-top: .75rem; display: flex; justify-content: flex-end; }
.cmd-risk { flex: 0; min-width: auto; justify-content: center; }
.risk-badge { padding: .15rem .5rem; border-radius: 3px; font-size: .75rem; font-weight: 600; text-transform: uppercase; }
.risk-low { background: rgba(46,204,113,.15); color: #2ecc71; }
.risk-medium { background: rgba(241,196,15,.15); color: #f1c40f; }
.risk-high { background: rgba(231,76,60,.15); color: #e74c3c; }

/* ── Output Panel ── */
.cmd-output-panel { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 1rem; }
.cmd-output-tabs { display: flex; border-bottom: 1px solid var(--border); overflow-x: auto; }
.cmd-output-tab { padding: .5rem 1rem; border: none; background: none; color: var(--text); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.cmd-output-tab.active { border-bottom-color: var(--accent); color: var(--accent); }
.cmd-output-count { font-size: .7rem; background: var(--accent-dim); padding: .1rem .4rem; border-radius: 8px; margin-left: .3rem; }
.cmd-output-body { padding: .75rem; max-height: 400px; overflow-y: auto; }
.cmd-result-entry { margin-bottom: .75rem; padding: .5rem; border-radius: 4px; background: var(--bg); }
.cmd-result-entry.error { border-left: 3px solid #e74c3c; }
.cmd-result-header { display: flex; gap: .75rem; align-items: center; margin-bottom: .25rem; font-size: .85rem; }
.cmd-result-type { font-weight: 600; }
.cmd-result-time { opacity: .5; font-size: .75rem; margin-left: auto; }
.cmd-result-output { font-size: .8rem; font-family: var(--mono); max-height: 200px; overflow: auto; white-space: pre-wrap; margin: .25rem 0 0; padding: .5rem; background: rgba(0,0,0,.2); border-radius: 4px; }
.status-ok, .status-completed { color: #2ecc71; }
.status-error { color: #e74c3c; }
.status-queued, .status-pending { color: #f1c40f; }
.status-sent { color: #3498db; }

/* ── Agent Detail Modal ── */
.detail-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: .75rem; }
.detail-item { display: flex; flex-direction: column; }
.detail-item label { font-size: .7rem; opacity: .5; text-transform: uppercase; }
.detail-meters { margin-top: 1rem; }
.meter-row { display: flex; align-items: center; gap: .75rem; margin-bottom: .5rem; }
.meter-row label { min-width: 40px; font-size: .8rem; }
.meter { flex: 1; height: 8px; background: var(--bg); border-radius: 4px; overflow: hidden; }
.meter-fill { height: 100%; border-radius: 4px; transition: width .3s; }
.meter-fill.ok { background: #2ecc71; }
.meter-fill.warn { background: #f1c40f; }
.meter-fill.fail { background: #e74c3c; }

/* ── Services List ── */
.services-list { max-height: 400px; overflow-y: auto; }
.service-row { display: flex; align-items: center; gap: .5rem; padding: .4rem .5rem; border-bottom: 1px solid var(--border); }
.svc-indicator { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.svc-active { background: #2ecc71; }
.svc-inactive { background: #e74c3c; }
.svc-name { flex: 1; font-family: var(--mono); font-size: .85rem; }
.svc-status { font-size: .75rem; opacity: .6; }

/* ── Command History Table ── */
.cmd-history-table { max-height: 300px; overflow-y: auto; }
.cmd-history-table .data-table { width: 100%; font-size: .8rem; }
.cmd-history-table th { position: sticky; top: 0; background: var(--card-bg); }
```

- [ ] **Step 2: JS syntax + visual check**

```bash
node -e "new Function(require('fs').readFileSync('share/noba-web/static/app.js','utf8'))"
```

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/static/style.css
git commit -m "feat(agent): add command palette, output panel, and detail modal CSS"
```

---

### Task 9: Tests

**Files:**
- Create: `tests/test_command_history.py`

- [ ] **Step 1: Write command history tests**

```python
"""Tests for agent command history."""
from __future__ import annotations

import pytest


class TestCommandHistory:
    """Test command history recording and retrieval."""

    def test_history_endpoint_returns_list(self, client, admin_auth):
        resp = client.get("/api/agents/command-history",
                          headers=admin_auth)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_command_recorded_in_history(self, client, admin_auth):
        """Sending a command should create a history entry."""
        # Send a command
        resp = client.post("/api/agents/test-host/command",
                           json={"type": "ping", "params": {}},
                           headers=admin_auth)
        assert resp.status_code == 200

        # Check history
        resp = client.get("/api/agents/command-history?hostname=test-host",
                          headers=admin_auth)
        history = resp.json()
        assert any(h["cmd_type"] == "ping" for h in history)

    def test_history_filter_by_hostname(self, client, admin_auth):
        resp = client.get("/api/agents/command-history?hostname=nonexistent",
                          headers=admin_auth)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_limit(self, client, admin_auth):
        resp = client.get("/api/agents/command-history?limit=5",
                          headers=admin_auth)
        assert resp.status_code == 200
        assert len(resp.json()) <= 5
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_command_history.py
git commit -m "test(agent): add command history tests"
```
