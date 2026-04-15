# NOBA Ops Center Elevation — Design Spec

**Date:** 2026-03-20
**Goal:** Close the remaining gaps to transform NOBA from a monitoring dashboard into a complete ops center — where you can see, diagnose, AND fix your infrastructure from a single pane.

---

## Current State (surprisingly mature)

Already built:
- Alert engine with self-healing actions, anomaly detection (Z-score), escalation policies, circuit breakers
- Workflow engine with sequential/parallel execution, 8 action types, cron + filesystem + RSS triggers
- 32 agent commands with WebSocket, file transfer, risk-tiered auth
- Tiered metric storage (raw → 1min → 1hour) with 30-day retention, trend analysis
- Public status page (basic, metric-driven)
- Backup lifecycle tracking with health checks, history, diffing
- 6 notification channels (email, Telegram, Discord, Slack, Pushover, Gotify)

**The single biggest missing link:** Alerts and workflows can execute shell commands and webhooks, but **cannot trigger agent commands**. Everything else below builds on closing this gap.

---

## Feature 1: Agent Command Automation Type

**The keystone feature.** Add `agent_command` as a new automation/alert action type.

### How it works

Alert self-healing action:
```yaml
alertRules:
  - name: "High CPU on DNS servers"
    condition: "cpu_percent > 90"
    severity: critical
    healing:
      action: agent_command
      hostname: host-a
      command: restart_service
      params:
        service: unbound
```

Workflow step:
```yaml
automations:
  - name: "Weekly agent update"
    type: workflow
    schedule: "0 3 * * 0"
    config:
      mode: parallel
      steps:
        - type: agent_command
          hostname: __all__
          command: update_agent
          params: {}
```

### Implementation

**Server (`workflow_engine.py`):**
- Add `agent_command` to the action type handler switch
- Handler calls the existing `api_agent_command` logic (queue command, try WebSocket, fallback to HTTP)
- Support `hostname: __all__` for broadcast to all online agents
- Wait for result (poll `_agent_cmd_results` with timeout) and return success/failure
- Log execution in `job_runs` table

**Server (`alerts.py`):**
- Add `agent_command` to the `_execute_healing_action` switch
- Same mechanism as workflow: queue command, poll for result

**Frontend:**
- Add "Agent Command" option in automation builder
- Hostname dropdown (from live agent list), command dropdown (from CMD_CATALOG), dynamic params

### Files
- Modify: `share/noba-web/server/workflow_engine.py`
- Modify: `share/noba-web/server/alerts.py`
- Modify: `share/noba-web/server/agent_store.py` (add helper to queue + wait for result)
- Modify: `share/noba-web/index.html` (automation builder UI)

---

## Feature 2: Real-time Log Streaming

Live tail from one or multiple agents simultaneously via WebSocket.

### How it works

User navigates to Logs page, selects an agent and unit (optional), clicks "Stream". Output appears line-by-line in real-time via the existing WebSocket channel.

### Implementation

**Agent (`agent.py`):**
- Add `follow_logs` command: runs `journalctl -f` (or `tail -f`) via `subprocess.Popen`, streams output line-by-line via WebSocket `stream` messages
- Support `unit` filter, `priority` filter, `lines` backlog count
- Killable via a `stop_stream` command that terminates the subprocess

**Server (`routers/system.py`):**
- Add `POST /api/agents/{hostname}/stream-logs` — sends `follow_logs` command via WebSocket
- Add `DELETE /api/agents/{hostname}/stream-logs` — sends `stop_stream` command
- Stream results already stored via existing `_stream_{hostname}_{cmd_id}` mechanism

**Frontend (Logs page):**
- Add "Live Stream" tab to the Logs page
- Agent selector + unit filter + priority filter + start/stop buttons
- Auto-scrolling log output area (monospace, color-coded by priority)
- Multi-agent split view (side-by-side log streams)

### Files
- Modify: `share/noba-agent/agent.py` (add `_cmd_follow_logs`, `_cmd_stop_stream`)
- Modify: `share/noba-web/server/routers/system.py` (stream endpoints)
- Modify: `share/noba-web/index.html` (Logs page live stream tab)
- Modify: `share/noba-web/static/integration-actions.js` (stream control functions)

---

## Feature 3: Endpoint & Certificate Monitoring

Scheduled HTTP/TLS health checks from agents' perspectives.

### How it works

Admin defines monitors (URL + expected status + interval). The server schedules periodic `endpoint_check` commands to agents. Results are stored as metrics for trending and alerting.

### Data model

```sql
CREATE TABLE IF NOT EXISTS endpoint_monitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    method TEXT DEFAULT 'GET',
    expected_status INTEGER DEFAULT 200,
    check_interval INTEGER DEFAULT 300,  -- seconds
    timeout INTEGER DEFAULT 10,
    agent_hostname TEXT,  -- which agent runs the check (null = server)
    enabled INTEGER DEFAULT 1,
    created_at INTEGER,
    last_checked INTEGER,
    last_status TEXT,  -- 'up', 'down', 'degraded'
    last_response_ms INTEGER,
    cert_expiry_days INTEGER,  -- TLS cert days until expiry
    notify_cert_days INTEGER DEFAULT 14  -- alert N days before expiry
);
```

### Implementation

**Agent (`agent.py`):**
- Add `endpoint_check` command: HTTP GET/HEAD with timing, TLS cert extraction
- Returns: `{status, response_ms, status_code, cert_expiry_days, cert_issuer, error}`

**Server:**
- New scheduler task: iterate enabled monitors, dispatch `endpoint_check` to assigned agents
- Store results in `endpoint_monitors` table + metrics table (for trending)
- Alert integration: auto-create alerts for down endpoints and expiring certs

**Frontend:**
- New "Endpoints" section in Monitoring page
- Table: name, URL, agent, status, response time, cert expiry, last checked
- Add/edit/delete monitors
- Response time sparkline charts
- Cert expiry timeline (visual countdown)

### Files
- Modify: `share/noba-agent/agent.py` (add `_cmd_endpoint_check`)
- Modify: `share/noba-web/server/db/core.py` (add `endpoint_monitors` table)
- Create: `share/noba-web/server/db/endpoints.py` (CRUD functions)
- Modify: `share/noba-web/server/routers/system.py` (endpoint monitor API)
- Modify: `share/noba-web/server/scheduler.py` (periodic check dispatch)
- Modify: `share/noba-web/server/alerts.py` (cert expiry + endpoint down alerts)
- Modify: `share/noba-web/index.html` (Monitoring > Endpoints tab)

---

## Feature 4: Saved Custom Dashboards

Users create custom metric views and save them.

### How it works

The existing multi-chart builder gets a "Save Dashboard" button. Saved dashboards appear as sub-items under a "Dashboards" sidebar section. Each user can have multiple saved dashboards.

### Data model

```sql
CREATE TABLE IF NOT EXISTS custom_dashboards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    owner TEXT NOT NULL,  -- username
    config_json TEXT NOT NULL,  -- chart definitions, layout
    shared INTEGER DEFAULT 0,  -- visible to all users
    created_at INTEGER,
    updated_at INTEGER
);
```

### Implementation

**Server:**
- CRUD API: `/api/dashboards` (list), `/api/dashboards` POST (create), `/api/dashboards/{id}` PUT/DELETE
- Dashboard config stores: metrics array, time range, chart types, layout

**Frontend:**
- "Save" button in the multi-chart builder
- "My Dashboards" list in Monitoring page
- Load dashboard → populate chart builder → render
- Share toggle (visible to other users)

### Files
- Modify: `share/noba-web/server/db/core.py` (add table)
- Create: `share/noba-web/server/db/dashboards.py`
- Modify: `share/noba-web/server/routers/system.py` (dashboard CRUD API)
- Modify: `share/noba-web/index.html` (save/load UI in monitoring page)
- Modify: `share/noba-web/static/system-actions.js` (dashboard persistence functions)

---

## Feature 5: Service Dependency Topology

Visual dependency graph showing what depends on what.

### How it works

Admin defines service dependencies (or they're auto-discovered from network connections). The service map becomes interactive — clicking a node shows impact analysis ("if this goes down, these services are affected").

### Data model

```sql
CREATE TABLE IF NOT EXISTS service_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_service TEXT NOT NULL,
    target_service TEXT NOT NULL,
    dependency_type TEXT DEFAULT 'requires',  -- requires, optional, network
    auto_discovered INTEGER DEFAULT 0,
    created_at INTEGER
);
```

### Implementation

**Auto-discovery (agent-side):**
- New `discover_services` command: scan listening ports, established connections, systemd dependencies
- Returns: `{services: [{name, port, connections: [{remote_host, remote_port}]}]}`

**Server:**
- Store dependencies in DB
- Impact analysis endpoint: given a service, return all transitively dependent services
- Graph data endpoint: return nodes + edges for visualization

**Frontend (Infrastructure page):**
- Interactive graph using a lightweight JS graph library (vis-network via CDN, or canvas-based)
- Click node → shows impact analysis panel
- Color-coded by health status (green/yellow/red)
- "Discover" button to run auto-discovery on agents

### Files
- Modify: `share/noba-agent/agent.py` (add `_cmd_discover_services`)
- Modify: `share/noba-web/server/db/core.py` (add table)
- Create: `share/noba-web/server/db/dependencies.py`
- Modify: `share/noba-web/server/routers/system.py` (dependency + impact API)
- Modify: `share/noba-web/index.html` (Infrastructure > Topology tab)

---

## Feature 6: Configuration Drift Detection

Compare expected vs. actual state across agents.

### How it works

Admin selects files to track (e.g., `/etc/resolv.conf`, `/etc/hostname`). The system periodically reads those files from all agents and compares. Differences are flagged as "drift".

### Implementation

**Server:**
- New `config_baselines` table: path, expected_hash, agent_group
- Scheduler task: periodically send `file_checksum` commands to agents
- Compare results against baseline
- Alert on drift

**Frontend:**
- New section in Infrastructure page: "Config Drift"
- Table: file path, agents, baseline hash, current hash, status (match/drift)
- Diff viewer (reuse existing diff modal) for drifted files
- "Set Baseline" button to establish expected state from any agent

### Files
- Modify: `share/noba-web/server/db/core.py` (add `config_baselines` table)
- Create: `share/noba-web/server/db/baselines.py`
- Modify: `share/noba-web/server/routers/system.py` (baseline CRUD + drift check API)
- Modify: `share/noba-web/server/scheduler.py` (periodic drift check)
- Modify: `share/noba-web/index.html` (Infrastructure > Config Drift tab)

---

## Feature 7: Enhanced Public Status Page

Upgrade from metric-driven-only to a proper status page with manual incidents.

### Implementation

- Manual incident creation (title, severity, affected services, updates timeline)
- Component groups (e.g., "Core Infrastructure", "Media Stack", "Network")
- Historical uptime chart (90-day bar chart, green/yellow/red per day)
- Subscribable (email notification on status change — uses existing notification channels)
- Standalone page at `/status` with no auth required, own CSS, mobile-friendly

### Files
- Modify: `share/noba-web/server/db/core.py` (add `status_components`, `status_incidents`, `status_updates` tables)
- Create: `share/noba-web/server/db/status_page.py`
- Modify: `share/noba-web/server/routers/system.py` (status page API)
- Create: `share/noba-web/static/status.html` (standalone page, no auth)
- Create: `share/noba-web/static/status.css`

---

## Feature 8: OpenAPI Documentation

Trivial — just enable it.

### Implementation

Change in `app.py`:
```python
app = FastAPI(title="Noba Command Center", version=VERSION, docs_url="/api/docs", redoc_url="/api/redoc")
```

Add auth bypass for docs routes. Add a sidebar link.

### Files
- Modify: `share/noba-web/server/app.py` (enable docs_url, redoc_url)

---

## Feature 9: Push Notifications (PWA)

Web push notifications for alerts so you get notified even when the tab is closed.

### Implementation

- Service worker already exists — add push event handler
- Server generates VAPID keys on first run
- Frontend: "Enable Push Notifications" toggle in Settings
- When alert fires, send push notification via web-push protocol

### Files
- Modify: `share/noba-web/service-worker.js` (add push event handler)
- Modify: `share/noba-web/server/alerts.py` (add web-push notification channel)
- Modify: `share/noba-web/index.html` (push notification toggle in settings)
- Modify: `share/noba-web/static/app.js` (push subscription logic)

---

## Feature 10: Multi-user Dashboard Views

Per-user saved card layouts and visibility preferences.

### Implementation

- Move card visibility (`vis`) and card order from localStorage to server-side per-user storage
- API: `/api/user/preferences` GET/PUT
- On login, fetch and apply user's saved layout
- "Reset to default" option
- Admin can set a "default layout" that new users inherit

### Files
- Modify: `share/noba-web/server/db/core.py` (add `user_preferences` table)
- Modify: `share/noba-web/server/routers/auth.py` (preferences API)
- Modify: `share/noba-web/static/app.js` (load/save preferences from server)

---

## Execution Waves

### Wave 1 — Core Ops (parallel, no conflicts)
1. **Agent command automation type** (workflow_engine.py + alerts.py)
2. **Real-time log streaming** (agent.py + logs page)
3. **Endpoint/cert monitoring** (agent.py + new DB table + monitoring page)
4. **OpenAPI docs** (one-line change in app.py)

### Wave 2 — Enhanced UX (parallel, no conflicts)
5. **Saved custom dashboards** (new DB + monitoring page)
6. **Enhanced status page** (new standalone page + DB tables)
7. **Push notifications** (service worker + alerts.py)

### Wave 3 — Advanced Ops (parallel, no conflicts)
8. **Service dependency topology** (agent.py + infrastructure page)
9. **Configuration drift** (agent.py + infrastructure page)
10. **Multi-user dashboard views** (DB + auth + app.js)

### Wave 4 — Intelligence
11. **LLM integration** (configurable providers + chat interface + smart analysis)

---

## Feature 11: LLM Integration — AI-Powered Ops Assistant

Configurable LLM that understands your infrastructure and can analyze, explain, and act.

### Provider Configuration

Settings page gets an "AI / LLM" section:

```yaml
llm:
  provider: anthropic          # anthropic, openai, ollama, custom
  model: claude-sonnet-4-20250514
  apiKey: sk-ant-...           # stored encrypted like other secrets
  baseUrl: ""                  # custom endpoint (for Ollama: http://localhost:11434)
  maxTokens: 4096
  temperature: 0.3
  enabled: true
  contextWindow: 16000         # max context to send
```

Supported providers (all via HTTP API, no SDK dependency):
- **Anthropic** (Claude) — `https://api.anthropic.com/v1/messages`
- **OpenAI** (GPT-4o, etc.) — `https://api.openai.com/v1/chat/completions`
- **Ollama** (local) — `http://localhost:11434/api/chat`
- **Custom** — any OpenAI-compatible endpoint (LM Studio, vLLM, etc.)

### Capabilities

**1. Ops Chat Interface**
- New "AI Assistant" panel accessible from sidebar or Ctrl+Shift+K
- Chat with context — the LLM sees: current alert state, recent incidents, agent status, metric summaries
- Ask natural language questions: "Why is host-a's CPU high?", "What changed in the last hour?"
- Responses include actionable suggestions with one-click buttons: "Restart nginx on host-a" → executes agent command

**2. Alert Analysis**
- When an alert fires, optionally auto-generate an AI summary
- "Explain this alert" button on each alert/incident
- LLM receives: alert rule, metric history (last 1h), recent related alerts, agent status
- Returns: plain-English explanation + suggested remediation steps

**3. Log Analysis**
- "Analyze Logs" button in the Logs page
- Send last N log lines to LLM with context
- Returns: summary of issues, error patterns, suggested fixes

**4. Incident Summarization**
- Auto-generate incident reports from alert + metric + action data
- "Generate Post-mortem" button after incident resolution

### Implementation

**Server (`share/noba-web/server/llm.py` — new file):**
```python
class LLMClient:
    """Provider-agnostic LLM client using httpx."""

    def __init__(self, config: dict):
        self.provider = config.get("provider", "anthropic")
        self.model = config.get("model", "claude-sonnet-4-20250514")
        self.api_key = config.get("apiKey", "")
        self.base_url = config.get("baseUrl", "")
        self.max_tokens = config.get("maxTokens", 4096)
        self.temperature = config.get("temperature", 0.3)

    async def chat(self, messages: list[dict], system: str = "") -> str:
        """Send messages to configured LLM, return response text."""
        # Route to provider-specific format
        if self.provider == "anthropic":
            return await self._anthropic(messages, system)
        elif self.provider in ("openai", "custom"):
            return await self._openai_compat(messages, system)
        elif self.provider == "ollama":
            return await self._ollama(messages, system)

    async def _anthropic(self, messages, system):
        """Anthropic Messages API."""
        url = self.base_url or "https://api.anthropic.com/v1/messages"
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                    "content-type": "application/json"}
        body = {"model": self.model, "max_tokens": self.max_tokens,
                "temperature": self.temperature, "messages": messages}
        if system:
            body["system"] = system
        # Use existing httpx client
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=body, headers=headers, timeout=60)
            data = resp.json()
            return data.get("content", [{}])[0].get("text", "")

    async def _openai_compat(self, messages, system):
        """OpenAI-compatible API (OpenAI, LM Studio, vLLM, etc.)."""
        url = (self.base_url or "https://api.openai.com/v1") + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"}
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        body = {"model": self.model, "max_tokens": self.max_tokens,
                "temperature": self.temperature, "messages": msgs}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=body, headers=headers, timeout=60)
            data = resp.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    async def _ollama(self, messages, system):
        """Ollama local API."""
        url = (self.base_url or "http://localhost:11434") + "/api/chat"
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        body = {"model": self.model, "messages": msgs, "stream": False,
                "options": {"temperature": self.temperature, "num_predict": self.max_tokens}}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=body, timeout=120)
            data = resp.json()
            return data.get("message", {}).get("content", "")
```

**Server (API endpoints):**
- `POST /api/ai/chat` — send message with infrastructure context
- `POST /api/ai/analyze-alert/{alert_id}` — analyze specific alert
- `POST /api/ai/analyze-logs` — analyze log excerpt
- `POST /api/ai/summarize-incident/{incident_id}` — generate report
- `GET /api/ai/status` — check if LLM is configured and reachable

**Context Builder:**
The system prompt includes live infrastructure state:
```
You are the NOBA ops assistant for {hostname}'s homelab.

Current state:
- {N} agents online: {hostnames}
- Active alerts: {alert_summaries}
- Recent incidents: {incident_summaries}
- CPU: {avg}%, Memory: {avg}%, Disk: {usage}

You can suggest agent commands. Format actionable commands as:
[ACTION:restart_service:host-a:{"service":"nginx"}]
The UI will render these as clickable buttons.
```

**Frontend:**
- AI Assistant panel (slide-out from right side, or sidebar section)
- Chat messages with markdown rendering
- Action buttons extracted from `[ACTION:...]` patterns in responses
- "Analyze" buttons on alerts, incidents, and log viewer
- Settings > AI section for provider configuration
- Token usage display

### Files
- Create: `share/noba-web/server/llm.py` (LLM client)
- Modify: `share/noba-web/server/routers/system.py` (AI API endpoints)
- Modify: `share/noba-web/server/db/core.py` (chat history table if desired)
- Modify: `share/noba-web/index.html` (AI panel, analyze buttons, settings)
- Modify: `share/noba-web/static/app.js` (AI state, chat logic)
- Modify: `share/noba-web/static/integration-actions.js` (AI action functions)
- Modify: `share/noba-web/static/style.css` (AI panel styles)

---

## Constraints

- Zero new Python dependencies (use httpx for LLM API calls — already installed)
- Zero new JS dependencies (use CDN for graph visualization only)
- Agent stays as single file with zero external deps
- All existing 445 tests must pass
- All 6 themes must work with new UI
- Sidebar navigation structure preserved
- Mobile-responsive
- LLM integration is optional — everything works without it configured

---

## Success Criteria

- Alerts can trigger agent commands (restart service on remote host when alert fires)
- Live log tailing from any agent in the browser
- Endpoint monitoring with cert expiry tracking and alerting
- Saved dashboards that persist and can be shared
- Interactive service dependency graph with impact analysis
- Config drift detection across agents
- Public status page with manual incidents and 90-day history
- API documentation at /api/docs
- Push notifications for alerts
- Per-user card layouts synced to server
- LLM-powered ops assistant with configurable provider (Anthropic/OpenAI/Ollama/custom)
- AI alert analysis, log analysis, incident summarization
- Natural language to agent command execution via chat
