# Self-Healing Pipeline Design

**Date:** 2026-03-22
**Status:** Draft
**Approach:** Layered Heal Pipeline (Approach B)

## Overview

Overhaul NOBA's self-healing capabilities from a reactive, inline alert handler into a composable, layered pipeline with:

- Post-heal verification against the original alert condition (not just "is it running?")
- Escalation chains that progress through increasingly aggressive actions
- Alert correlation to prevent duplicate healing for the same root cause
- Outcome-based learning that tracks effectiveness and adapts behavior
- Predictive/proactive healing using the existing prediction and anomaly engines
- Agent-autonomous healing for local fast-path actions when the server is unreachable
- Graduated trust where new rules start conservative and earn autonomy

## Module Structure

```
server/healing/
├── __init__.py          # exports handle_heal_event pipeline entry point
├── models.py            # shared dataclasses
├── condition_eval.py    # extracted _safe_eval + metric flattening (shared utility)
├── correlation.py       # HealEvent → HealRequest grouping
├── planner.py           # HealRequest → HealPlan (escalation + adaptive)
├── executor.py          # HealPlan → HealOutcome (action + verification)
├── ledger.py            # outcome recording, effectiveness queries, suggestions
├── governor.py          # trust state, promotion/demotion
└── agent_runtime.py     # policy builder, agent report ingestion

db/healing.py            # DB functions following (conn, lock, ...) pattern
routers/healing.py       # API endpoints
```

## Cross-Cutting Concerns

### Threading and Locking

All modules that hold mutable state must use locks per CLAUDE.md ("always use locks when mutating module-level state"):

- `correlation.py`: `_lock = threading.Lock()` guarding the correlation dict
- `governor.py`: `_lock = threading.Lock()` guarding any cached trust state
- `healing/__init__.py`: the pipeline entry point `handle_heal_event` may be called from multiple threads (alert evaluator, prediction engine, agent report processing) — all mutable state access within the pipeline is lock-protected at the layer level

Follows the existing `AlertState` pattern from `alerts.py`.

### Condition Evaluation (extracted utility)

**Module:** `server/healing/condition_eval.py`

Extract `_safe_eval`, `_safe_eval_single`, and the metric flattening logic from `alerts.py` into a standalone module with no dependencies on `alerts.py` or any healing module. This prevents circular imports since both `alerts.py` and `healing/executor.py` need condition evaluation.

```python
# condition_eval.py — no imports from alerts.py or healing/

def flatten_metrics(stats: dict) -> dict:
    """Flatten nested collector stats into a flat dict for condition evaluation.

    Handles: scalar values directly, list-of-dict structures like disks[0].percent,
    services[1].status, etc. Same logic currently inline in alerts.evaluate_alert_rules.
    """

def safe_eval(condition_str: str, flat: dict) -> bool:
    """Evaluate a condition string supporting AND/OR composites."""

def safe_eval_single(condition_str: str, flat: dict) -> bool:
    """Evaluate a single metric comparison (e.g. 'cpu_percent > 90')."""
```

After extraction, `alerts.py` and `workflow_engine.py` import from `condition_eval` instead of using the private `_safe_eval`.

### DB Pattern

All new DB operations follow the existing `(conn, lock, ...)` pattern in a new `db/healing.py` module, with delegation wrappers added to the `Database` class in `db/core.py`. This matches `db/automations.py`, `db/alerts.py`, etc.

```python
# db/healing.py
def insert_heal_outcome(conn, lock, ...) -> int: ...
def get_heal_outcomes(conn, lock, ...) -> list[dict]: ...
def get_success_rate(conn, lock, ...) -> float: ...
def insert_trust_state(conn, lock, ...) -> None: ...
# etc.

# db/core.py — Database class additions
def insert_heal_outcome(self, **kwargs) -> int:
    return _insert_heal_outcome(self._get_conn(), self._lock, **kwargs)
```

## Data Models

Shared dataclasses in `models.py`:

```python
@dataclass
class HealEvent:
    source: str          # "alert", "prediction", "agent", "anomaly"
    rule_id: str
    condition: str
    target: str          # container name, service, hostname
    severity: str
    timestamp: float
    metrics: dict        # snapshot of relevant metrics at trigger time

@dataclass
class HealRequest:
    correlation_key: str
    events: list[HealEvent]
    primary_target: str
    severity: str        # highest severity from grouped events
    created_at: float

@dataclass
class HealPlan:
    request: HealRequest
    action_type: str
    action_params: dict
    escalation_step: int
    trust_level: str       # "execute", "approve", "notify"
    reason: str            # human-readable explanation of why this action was chosen
    skipped_actions: list  # actions skipped due to low effectiveness

@dataclass
class HealOutcome:
    plan: HealPlan
    action_success: bool | None  # None for notify/approve paths where no action ran
    verified: bool | None        # None for notify/approve paths
    verification_detail: str     # "cpu_percent dropped from 94 to 62" or "queued for approval"
    duration_s: float
    metrics_before: dict         # snapshot at trigger time (from HealEvent)
    metrics_after: dict | None   # snapshot after settle time (None if no action ran)
    approval_id: int | None      # set for approve path, links to approval_queue

@dataclass
class HealSuggestion:
    category: str        # "recurring_issue", "low_effectiveness", "trust_promotion", "new_rule"
    severity: str        # "info", "warning"
    message: str
    rule_id: str | None
    suggested_action: dict | None   # optional config change to apply
    evidence: dict       # stats backing the suggestion

@dataclass
class AgentHealPolicy:
    rules: list[AgentHealRule]
    version: int              # bumped on change, agent skips re-parse if same
    fallback_mode: str        # default policy-level fallback

@dataclass
class AgentHealRule:
    rule_id: str
    condition: str            # simple metric comparison, same syntax as alert rules
    action_type: str          # limited to low-risk: restart_service, restart_container, clear_cache
    action_params: dict
    max_retries: int
    cooldown_s: int
    trust_level: str
    fallback_mode: str | None # per-rule override; None = use policy default
```

## Layer 1: Heal Correlation

**Module:** `correlation.py`

**Purpose:** Prevent the same root issue from triggering multiple independent heal actions. If a container is dying, a CPU alert, a service-down alert, and an endpoint-down alert should not each try to heal independently.

**Mechanism: immediate-on-first with duplicate absorption.**

- The first event for a given correlation key immediately emits a `HealRequest` and starts the heal pipeline.
- Subsequent events with the same correlation key within the absorption window (default 60s) are absorbed — `correlate()` returns `None`. These events are recorded in the ledger as "correlated/absorbed" for auditing but do not trigger new heal actions.
- The correlation key is derived from the target: `f"{target}:{action_context}"` where `action_context` groups related conditions (e.g., all memory-related alerts for the same container share a key).
- After the absorption window expires, the key is removed and the next event starts a new group.

This is simpler and more predictable than a debounce (which would delay healing by the full window). The trade-off is that the first event's condition drives action selection, but since the planner considers the full escalation chain, this is acceptable.

**State is in-memory only.** Correlation windows are short (60s) and the consequence of losing state on restart is merely that one duplicate heal might fire — acceptable for a homelab. No DB persistence needed.

**Threading:** All access to the correlation dict is guarded by `_lock = threading.Lock()`.

**Interface:**

```python
def correlate(event: HealEvent) -> HealRequest | None:
```

Returns `None` if the event was absorbed into an existing group. Returns a `HealRequest` when this is the first event for this target within the window.

## Layer 2: Heal Planner

**Module:** `planner.py`

**Purpose:** Given a correlated `HealRequest`, decide what action to take. Owns escalation chains, adaptive scoring, and predictive trigger handling.

### Escalation State

The planner holds in-memory escalation state: `{correlation_key: current_step}` guarded by a lock. This tracks which step is active for a given target. If a new event fires for a target that already has an escalation chain in progress, the new event is ignored (the existing chain handles it). The state entry is cleared when the chain completes (success or exhaustion). This prevents parallel chains for the same target.

A hard cap of `MAX_ESCALATION_DEPTH = 6` is enforced regardless of chain definition length — cheap safety net against malformed YAML.

### Escalation Chains

A rule can define an ordered list of actions with increasing severity:

```yaml
escalation_chain:
  - action: restart_container
    params: { container: "frigate" }
    verify_timeout: 30
  - action: scale_container
    params: { container: "frigate", mem_limit: "4g" }
    verify_timeout: 30
  - action: run_playbook
    params: { playbook_id: "frigate-full-recovery" }
    verify_timeout: 120
```

The planner tracks which escalation step is active per correlation key. If the executor reports verification failed, the planner advances to the next step.

### Adaptive Scoring

For each candidate action, the planner queries the ledger for historical success rate on this condition+target pair. If an action's success rate drops below a configurable threshold (default 30%), it is skipped in favor of the next action in the chain. The chain is advisory — the planner reorders based on effectiveness.

### Predictive Triggers

Events with `source="prediction"` come from the prediction engine when a metric is trending toward a threshold. Predictive heal plans are always one trust level more conservative than the rule's current trust level.

**Interface:**

```python
def select_action(request: HealRequest, ledger: HealLedger, governor: TrustGovernor) -> HealPlan:
def advance(plan: HealPlan, outcome: HealOutcome) -> HealPlan | None:
```

`advance()` returns `None` when the escalation chain is exhausted.

### HealPlan.reason

The `reason` field carries a human-readable explanation: "Skipped restart_container (18% success rate), selected scale_container (step 2 of 3)". This feeds into notifications and the UI.

## Layer 3: Heal Executor

**Module:** `executor.py`

**Purpose:** Run the planned action and verify it actually fixed the problem by re-evaluating the original alert condition, not just checking process state.

### Asynchronous Execution Model

The executor runs each action in a daemon thread to avoid blocking the caller. The pipeline entry point (`handle_heal_event`) returns immediately after dispatching to the executor. This is critical because `handle_heal_event` is called from the alert evaluator thread (via `evaluate_alert_rules`), and blocking it would cause metric collection gaps and missed alerts.

```python
def execute(plan: HealPlan, on_complete: Callable[[HealOutcome], None]) -> None:
    """Run action in a background thread. Calls on_complete with the outcome."""
    threading.Thread(
        target=_execute_and_verify,
        args=(plan, on_complete),
        daemon=True,
        name=f"heal-{plan.request.correlation_key}",
    ).start()
```

The `on_complete` callback is how the executor feeds results back to the ledger and triggers escalation. This matches the pattern used by `workflow_engine._run_workflow` with `job_runner.submit(on_complete=...)`.

### Execution Flow

```
execute(plan, on_complete) → spawn thread → run action → wait settle_time →
    flatten metrics → re-evaluate conditions → build outcome → on_complete(outcome)
```

### Settle Time vs Execution Timeout

These are distinct concepts:
- **Execution timeout** (`remediation.ACTION_TYPES[...]["timeout_s"]`): max time the action itself can run (e.g., 30s for restart, 600s for playbook). Enforced by `remediation.execute_action()`.
- **Settle time**: delay *after* the action completes before re-evaluating conditions. Gives the system time to stabilize.

Total worst-case time per escalation step = execution timeout + settle time. For `run_playbook`: 600s + 120s = 720s. The escalation chain is bounded by step count (typically 2-4 steps).

Settle times per action type:
- `restart_container`, `restart_service`: 15s
- `scale_container`, `clear_cache`, `flush_dns`: 15s
- `run_playbook`: 120s
- `trigger_backup`: 60s
- `run`, `webhook`, `automation`: 15s
- `agent_command`: 30s

### Verification Mechanism

After the settle time, the executor:
1. Fetches a fresh metrics snapshot from `bg_collector.get()`
2. **Flattens the metrics** using `condition_eval.flatten_metrics()` — converts nested structures like `disks[0].percent` into flat keys, matching what `evaluate_alert_rules` does
3. Re-evaluates each original condition from the `HealRequest.events` using `condition_eval.safe_eval()`
4. If all conditions are now `False` (no longer firing), the heal is verified
5. Records `metrics_before` (from the HealEvent) and `metrics_after` (fresh snapshot) for ledger analysis

### Verification Outcomes

- `action_success=True, verified=True`: the heal resolved the root issue.
- `action_success=True, verified=False`: the action ran but the problem persists — triggers escalation.
- `action_success=False`: the action itself failed — also triggers escalation.

### Action Type Coverage

The executor delegates to `remediation.execute_action()` for the 8 types it handles. However, the current `alerts._execute_heal` also handles 4 additional types that are NOT in `remediation.py`:

- `run` — arbitrary shell command
- `webhook` — fire a webhook automation
- `automation` — trigger a stored automation
- `agent_command` — send command to remote agent

**Migration requirement:** As part of this work, migrate these 4 action types from `alerts._execute_heal` into `remediation.py` (adding them to `ACTION_TYPES` and `_HANDLERS`). This consolidates all heal actions into one registry and ensures nothing is lost when `_execute_heal` is replaced.

### Escalation via Callback

When `on_complete` fires with `verified=False`, the pipeline advances the escalation:

```python
def _on_heal_complete(outcome: HealOutcome) -> None:
    ledger.record(outcome)
    if not outcome.verified and outcome.plan.escalation_step < chain_length - 1:
        next_plan = planner.advance(outcome.plan, outcome)
        if next_plan:
            executor.execute(next_plan, on_complete=_on_heal_complete)
```

Each escalation step runs in its own daemon thread — no recursive blocking. Bounded by chain length, `MAX_ESCALATION_DEPTH`, and circuit breaker via the Trust Governor.

**Note on daemon threads:** Executor threads are daemon threads, meaning in-progress heal actions are killed on process shutdown without recording their outcome. This is acceptable for a homelab — the action will simply re-trigger on the next alert evaluation after restart. Non-daemon threads with graceful shutdown would add complexity for minimal benefit.

## Layer 4: Heal Ledger

**Module:** `ledger.py` (business logic) + `db/healing.py` (DB operations)

**Purpose:** Record every healing outcome and compute effectiveness scores. Powers the adaptive planner and the suggestion engine.

### Storage

New SQLite tables (created in `db/core.py` migration):

```sql
CREATE TABLE heal_ledger (
    id INTEGER PRIMARY KEY,
    correlation_key TEXT,
    rule_id TEXT,
    condition TEXT,
    target TEXT,
    action_type TEXT,
    action_params TEXT,       -- JSON
    escalation_step INTEGER,
    action_success INTEGER,   -- 1/0/NULL (NULL for notify/approve with no execution)
    verified INTEGER,         -- 1/0/NULL
    duration_s REAL,
    metrics_before TEXT,      -- JSON snapshot
    metrics_after TEXT,       -- JSON snapshot
    trust_level TEXT,
    source TEXT,              -- "alert", "prediction", "agent"
    approval_id INTEGER,      -- links to approval_queue for approve path
    created_at INTEGER
);
CREATE INDEX idx_heal_ledger_lookup
    ON heal_ledger(rule_id, condition, target, created_at);
```

The existing `action_audit` table stays for general audit logging.

### Recording All Trust Levels

The ledger records outcomes for ALL trust levels, not just `execute`:

- **`execute`**: full outcome with `action_success`, `verified`, metrics snapshots
- **`approve`**: records with `action_success=NULL, verified=NULL, approval_id=<id>`. Updated when the approval is decided and executed (see Approval Integration below).
- **`notify`**: records with `action_success=NULL, verified=NULL`. Tracks trigger frequency for governor promotion decisions.

This ensures the governor has complete data for promotion criteria at every trust level.

### Effectiveness Queries

```python
def success_rate(action_type: str, condition: str, target: str | None,
                 window_hours: int = 720) -> float:
    """Percentage of times this action verified-resolved this condition."""

def mean_time_to_resolve(condition: str, target: str | None,
                         window_hours: int = 720) -> float | None:
    """Average seconds from heal trigger to verified resolution."""

def escalation_frequency(rule_id: str, window_hours: int = 720) -> dict:
    """How often each escalation step gets reached.
    Returns {step_0: 45, step_1: 12, step_2: 3}."""
```

### Suggestion Engine

Runs hourly (via scheduler) or on-demand via API. Produces `HealSuggestion` entries:

- **recurring_issue**: "Container `frigate` has been restarted 18 times in 30 days for `mem_percent > 85`. Consider a scheduled restart or memory limit increase."
- **low_effectiveness**: "Action `restart_service` has a 15% success rate for `cpu_percent > 90` on host `proxmox-1`. Consider removing it from the escalation chain."
- **trust_promotion**: "Rule `disk-cleanup` has been auto-healed 40 times with 95% effectiveness. Eligible for promotion to `execute`."
- **new_rule**: Pattern-based detection of recurring issues without heal rules configured.

Suggestions are stored in a `heal_suggestions` table and surfaced via API and notifications. They are informational — the operator decides whether to act.

```sql
CREATE TABLE heal_suggestions (
    id INTEGER PRIMARY KEY,
    category TEXT,
    severity TEXT,
    message TEXT,
    rule_id TEXT,
    suggested_action TEXT,    -- JSON
    evidence TEXT,            -- JSON
    dismissed INTEGER DEFAULT 0,
    created_at INTEGER,
    updated_at INTEGER,
    UNIQUE(category, rule_id) ON CONFLICT REPLACE
);
```

The `UNIQUE(category, rule_id)` constraint with `ON CONFLICT REPLACE` prevents duplicate active suggestions. When the same suggestion is regenerated hourly, it updates rather than duplicates.

## Layer 5: Agent Heal Runtime

**Module:** `agent_runtime.py`

**Purpose:** Allow agents to heal locally and autonomously when the NOBA server is unreachable, or for fast-path actions that should not wait for a server round-trip.

### Rule Distribution

The server pushes a lightweight heal policy to each agent during the regular heartbeat/poll cycle. The policy is a subset of full heal rules, filtered to what is relevant for that host.

Policy is delivered as part of the existing agent command/heartbeat flow — included in the `api_agent_report` response alongside `commands`. No new transport needed.

### Safety Constraints

- Only **low-risk** action types are eligible for agent-side execution: `restart_container`, `restart_service`, `clear_cache`, `flush_dns`.
- High-risk actions (`failover_dns`, `run_playbook`, `scale_container`) always go through the server.
- Agents report every local heal outcome back to the server on next successful connection — the ledger stays complete.
- `fallback_mode` controls behavior when server is unreachable. Configurable per-policy (default) and per-rule (override):
  - `execute_local`: evaluate and act on the pushed policy
  - `queue_for_server`: record the event, submit when reconnected
  - `notify_only`: send notification only

### Server-Side Management

```python
def build_agent_policy(hostname: str, rules: list, ledger: HealLedger) -> AgentHealPolicy:
    """Filter and simplify heal rules for a specific agent."""

def ingest_agent_heal_reports(hostname: str, reports: list[dict]) -> None:
    """Process heal outcomes reported by agents, feed into ledger."""
```

Policy version is bumped on rule changes; agents skip re-parse if version matches.

## Layer 6: Trust Governor

**Module:** `governor.py`

**Purpose:** Manage graduated trust. New rules and adaptive suggestions start conservative and earn autonomy based on track record.

### Trust Lifecycle

```
notify → approve → execute
```

Every heal rule has an effective trust level that the governor can override. The rule's configured autonomy is the ceiling — the governor can only downgrade or promote up to that ceiling.

**Note on YAML-defined rules:** Alert rules are defined in the YAML settings file with `rule.get("id")`. If a rule is removed from YAML and re-added, its trust state persists in the DB. This is intentional — trust is earned and should survive config edits.

### Promotion Criteria

```python
@dataclass
class TrustPolicy:
    min_executions: int = 10        # minimum sample size
    min_success_rate: float = 0.85  # 85% verified success rate
    min_age_hours: int = 168        # 7 days at current level
    auto_promote: bool = False      # if True, promote silently; if False, create suggestion
```

- `notify → approve`: rule has fired 10+ times, operator has manually approved 85%+.
- `approve → execute`: 10+ approved executions with 85%+ verified success, at least 7 days at `approve`.

### Demotion Criteria

- Circuit breaker opens: 3 consecutive verified=False outcomes for the same rule within 1 hour triggers immediate demotion to `notify` and creates a suggestion. The governor owns this logic (replaces the old `AlertState` circuit breaker).
- Success rate drops below 40% over rolling 30-day window: demote one level.
- Predictive-sourced heals are always capped one level below the rule's current trust.

### Storage

```sql
CREATE TABLE trust_state (
    rule_id TEXT PRIMARY KEY,
    current_level TEXT DEFAULT 'notify',
    ceiling TEXT DEFAULT 'execute',
    promoted_at INTEGER,
    demoted_at INTEGER,
    promotion_count INTEGER DEFAULT 0,
    demotion_count INTEGER DEFAULT 0,
    last_evaluated INTEGER
);
```

### Interface

```python
def effective_trust(rule_id: str, source: str, ledger: HealLedger) -> str:
    """Resolve actual trust level considering promotions, demotions, and source."""

def evaluate_promotions(ledger: HealLedger) -> list[HealSuggestion]:
    """Check all rules for promotion/demotion eligibility."""
```

Evaluation runs during the ledger's hourly suggestion cycle — same schedule, no extra timers.

## Pipeline Entry Point

`healing/__init__.py` exports the main pipeline function:

```python
def handle_heal_event(event: HealEvent) -> None:
    """Non-blocking pipeline entry point. Safe to call from any thread."""
    request = correlation.correlate(event)
    if request is None:
        return  # absorbed into existing group

    plan = planner.select_action(request, ledger, governor)

    if plan.trust_level == "notify":
        # Record in ledger for governor promotion tracking, send notification
        ledger.record(HealOutcome(
            plan=plan, action_success=None, verified=None,
            verification_detail="notify only", duration_s=0,
            metrics_before=event.metrics, metrics_after=None, approval_id=None,
        ))
        dispatch_notifications(plan.request.severity, plan.reason, ...)

    elif plan.trust_level == "approve":
        # Insert into existing approval_queue, record ledger entry with approval_id
        # Note: automation_id is reused for the heal rule_id. The approval UI
        # may show this as an "automation" — acceptable since heal rules are
        # conceptually a type of automation trigger. No UI change needed.
        approval_id = db.insert_approval(
            automation_id=plan.request.events[0].rule_id,
            trigger=f"heal:{plan.request.correlation_key}",
            trigger_source="healing_pipeline",
            action_type=plan.action_type,
            action_params=plan.action_params,
            target=plan.request.primary_target,
            requested_by=f"heal:{plan.request.events[0].source}",
        )
        ledger.record(HealOutcome(
            plan=plan, action_success=None, verified=None,
            verification_detail="queued for approval", duration_s=0,
            metrics_before=event.metrics, metrics_after=None,
            approval_id=approval_id,
        ))

    else:  # execute
        def on_complete(outcome: HealOutcome) -> None:
            ledger.record(outcome)
            if not outcome.verified:
                next_plan = planner.advance(outcome.plan, outcome)
                if next_plan:
                    executor.execute(next_plan, on_complete=on_complete)

        executor.execute(plan, on_complete=on_complete)
```

### Approval Integration

When an approval is decided (via existing `api_decide_approval` in the automations router), the approval execution path must re-enter the healing pipeline so verification and ledger recording happen:

1. The approval router checks if `trigger_source == "healing_pipeline"`
2. If so, instead of calling `remediation.execute_action()` directly, it calls `executor.execute()` with the original `HealPlan` (reconstructed from the approval's `action_type`, `action_params`, and the linked `heal_ledger` row via `approval_id`)
3. The executor runs the action, verifies, and records the outcome — updating the existing ledger row with `action_success` and `verified` values
4. If denied, the ledger row is updated with `verification_detail="denied by <username>"`

This ensures the ledger has complete data even for the approve path.

## Changes to Existing Code

### alerts.py

Replace the inline `_execute_heal` block in `evaluate_alert_rules()` with a call to `handle_heal_event(HealEvent(...))`. Alert evaluation, condition parsing, and notification dispatch stay in `alerts.py`. The `AlertState` heal tracking (retries, circuit breaker) is superseded by the governor and ledger — can be removed once the pipeline is fully wired.

Update `_safe_eval` imports to use `healing.condition_eval.safe_eval`.

### routers/stats.py

Also imports `_safe_eval` from `alerts.py` — update to use `healing.condition_eval.safe_eval`.

### remediation.py

Migrate 4 action types currently only in `alerts._execute_heal` into `remediation.py`:
- `run` — arbitrary shell command execution
- `webhook` — fire a webhook via URL
- `automation` — trigger a stored automation by ID
- `agent_command` — send command to remote agent

This consolidates all heal actions into one registry. The handlers already exist in `_execute_heal` — they just need to be moved into `_HANDLERS` and `ACTION_TYPES`.

### prediction.py / check_anomalies()

Add a call to `handle_heal_event` with `source="prediction"` when anomalies or trending thresholds are detected.

### workflow_engine.py

Update `_safe_eval` imports to use `healing.condition_eval.safe_eval`.

### scheduler.py

Add the hourly `ledger.generate_suggestions()` + `governor.evaluate_promotions()` call to the scheduler tick or as a separate periodic task.

### routers/agents.py

In `api_agent_report` response: include `heal_policy` alongside existing `commands` key. In the request body processing: handle `_heal_reports` field via `agent_runtime.ingest_agent_heal_reports()`.

### routers/automations.py

In `api_decide_approval`: add check for `trigger_source == "healing_pipeline"` to route approved actions through the heal executor instead of directly calling `remediation.execute_action()`.

### db/core.py

Add `heal_ledger`, `trust_state`, and `heal_suggestions` table creation to the migration path. Add delegation wrappers for `db/healing.py` functions.

## New API Endpoints

New router: `routers/healing.py`

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/healing/ledger` | read | Recent outcomes with filtering |
| GET | `/api/healing/effectiveness` | read | Per-rule/action success rates |
| GET | `/api/healing/suggestions` | read | Active suggestions |
| POST | `/api/healing/suggestions/{id}/dismiss` | operator | Dismiss a suggestion |
| GET | `/api/healing/trust` | read | Trust state per rule |
| POST | `/api/healing/trust/{rule_id}/promote` | admin | Manual trust promotion |

## Future Integration Points

- **Health score:** Add a "healing effectiveness" category to `health_score.py` based on ledger data (success rates, escalation frequency). Not in initial scope.
- **Dry-run endpoint:** `POST /api/healing/test` to run a synthetic HealEvent through the pipeline without executing actions. Useful for debugging.

## Success Criteria

1. An alert-triggered heal verifies the original condition resolved, not just process state.
2. Escalation chains progress automatically when verification fails.
3. Correlated alerts for the same target produce a single heal action, not duplicates.
4. The ledger tracks per-action effectiveness and surfaces suggestions for low-performing rules.
5. Predictive heal events from the anomaly/prediction engine flow through the pipeline.
6. Agents can execute low-risk heal actions locally when the server is unreachable.
7. New rules start at `notify`, earn promotion to `approve` then `execute` based on track record.
8. The existing `remediation.py` action handlers are reused, not duplicated.
9. All 12 action types (8 existing + 4 migrated) are supported through the unified executor.
10. The pipeline never blocks the alert evaluator thread — all execution is asynchronous.
11. Ledger records outcomes for all trust levels (notify, approve, execute) to support governor decisions.
