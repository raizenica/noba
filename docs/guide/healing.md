# Self-Healing Pipeline

NOBA's self-healing pipeline automatically detects, diagnoses, and resolves infrastructure issues through a layered architecture.

## Overview

When an alert fires, instead of just notifying you, NOBA can automatically take corrective action — restarting services, scaling containers, flushing DNS, running scripts, and more. The pipeline ensures actions are **verified** (did the fix actually work?) and **graduated** (start cautious, earn trust over time).

## Pipeline Architecture

Events flow through six stages:

1. **Correlation** — Deduplicates rapid-fire alerts for the same target using an absorption window (default 60s)
2. **Planning** — Selects the best action from an escalation chain, skipping actions with low historical success rates
3. **Execution** — Runs the action asynchronously, waits for settle time, then re-evaluates the original condition
4. **Verification** — Confirms the issue is actually resolved, not just that the action succeeded
5. **Ledger** — Records every outcome for effectiveness tracking and suggestion generation
6. **Trust Governor** — Manages graduated trust levels with automatic promotion and circuit breaker protection

## Trust Levels

Each healing rule starts at the lowest trust level and earns promotion based on track record:

| Level | Behavior | Promotion Criteria |
|-------|----------|-------------------|
| **Observation** | Track "would have fired" count, no events emitted | Manual promotion |
| **Dry-Run** | Full pipeline simulation, no execution | Manual promotion |
| **Notify** | Alert only, no action taken | 10+ triggers over 7 days |
| **Approve** | Queued for operator approval | 85%+ verified success rate over 10+ executions |
| **Execute** | Fully automatic | — |

### Circuit Breaker

If 3 consecutive heal attempts fail verification within 1 hour, the trust governor automatically demotes the rule back to **notify** and creates a suggestion for review.

## Dependency Graph & Root Cause Analysis

Define service dependencies so NOBA heals the root cause, not symptoms:

```yaml
dependencies:
  - target: "isp:site-a"
    type: external            # NOBA cannot heal this — notify only
    site: site-a
  - target: truenas
    depends_on: ["network:site-a"]
    type: service
  - target: plex
    depends_on: [truenas]
    type: service
```

When multiple alerts fire, the pipeline walks UP the dependency graph to find the root cause. If TrueNAS is down, Plex healing is suppressed — only TrueNAS gets healed. If the ISP goes down, ALL healing at that site is suppressed (services are fine locally, just unreachable).

The system also auto-discovers dependencies by analyzing co-failure patterns over time, surfacing them as suggestions for operator confirmation.

## Maintenance Windows

Pause or queue healing during planned maintenance:

```yaml
# Via API
POST /api/healing/maintenance
{"target": "plex", "duration": "2h", "reason": "upgrading", "action": "suppress"}
```

Actions: `suppress` (drop events), `queue` (re-evaluate after window), `notify_only` (override trust to notify).

## Rollback & State Snapshots

Before executing any heal action, the system captures a state snapshot (container config, service status, etc.). If the heal fails verification and the action is reversible, it auto-rolls back to the pre-heal state.

Manual rollback: `POST /api/healing/rollback/{ledger_id}` (admin only).

## Healing Dashboard

Navigate to **Healing** in the sidebar. Six tabs:

### Overview
Pipeline status bar (Active/Paused/Degraded) + effectiveness charts (success rate, MTTR, per-rule breakdown).

### Ledger
Vertical timeline of heal outcomes. Expandable entries show full context: metrics before/after, approval info, rollback status. Filter by rule, target, result. Export as JSON.

### Dependencies
Interactive SVG graph showing service dependencies. Nodes colored by health status. Click to inspect recent heals and trust state.

### Trust
Visual trust progression bars (observation → dry-run → notify → approve → execute). Circuit breaker indicators. Admin promote/demote buttons.

### Approvals
Pending approval queue with full context cards, countdown timers, and approve/deny/defer actions.

### Maintenance
Active windows with countdown, scheduled windows, quick-create form.

Also available: **Capability Matrix** (per-agent tool manifest view) and **Suggestions** panel.

## Escalation Chains

Configure multi-step escalation in alert rules:

```yaml
alertRules:
  - id: cpu_high
    condition: "cpu_percent > 90"
    severity: warning
    action:
      type: restart_service
      target: nginx
    escalation_chain:
      - action: restart_service
        params: { service: nginx }
      - action: scale_container
        params: { container: nginx, mem_limit: "4g" }
      - action: run
        params: { command: "systemctl restart docker" }
```

If the first action doesn't resolve the condition, the pipeline automatically escalates to the next step.

## Supported Action Types (55)

**Low-risk** (auto-execute eligible): `restart_container`, `restart_service`, `service_reload`, `service_reset_failed`, `container_pause`, `container_image_pull`, `process_kill`, `nice_adjust`, `log_rotate`, `temp_cleanup`, `clear_cache`, `flush_dns`, `dns_cache_clear`, `journal_vacuum`, `package_cache_clean`, `disk_cleanup`, `webhook`

**Medium-risk** (auto-execute + notification): `container_recreate`, `service_dependency_restart`, `storage_cleanup`, `cert_renew`, `vpn_reconnect`, `zfs_scrub`, `btrfs_scrub`, `backup_verify`, `servarr_queue_cleanup`, `media_library_scan`, `network_interface_restart`, `compose_restart`, `memory_pressure_relief`, `scale_container`, `trigger_backup`, `automation`, `agent_command`

**High-risk** (requires approval): `host_reboot`, `vm_restart`, `vm_migrate`, `package_security_patch`, `snapshot_rollback`, `firewall_rule_add`, `raid_rebuild`, `run_playbook`, `run`, `failover_dns`

All actions use **capability-based dispatch** — the agent reports what tools are available (systemctl, docker, apt, powershell, etc.) and the executor picks the right handler via fallback chains. No OS guessing.

## Default Escalation Chains

These work out of the box — no configuration needed:

| Scenario | Steps |
|----------|-------|
| CPU > 90% | Kill top process → nice adjust → clear cache |
| Disk >= 90% | Temp cleanup → journal vacuum → log rotate → storage cleanup |
| Service failed | Reset failed → restart service → restart with deps |
| Container down | Restart container → recreate container |
| Memory > 90% | Clear cache → memory relief → kill top consumer |
| DNS down | Flush DNS → restart service → restart container |
| VPN disconnected | Reconnect VPN |
| Backup stale | Trigger backup → verify backup |

All defaults start at **notify** trust and must earn promotion.

## Agent-Side Healing

Agents probe 22+ tools on startup and report a capability manifest. The server distributes heal policies to agents containing actions appropriate for each host's capabilities. Agents heal locally when the server is unreachable and report outcomes on reconnect.

## Predictive Healing

Every 15 minutes, the prediction engine evaluates capacity forecasts. If a metric is trending toward a threshold:
- **Within 24h**: warning-level heal event (low-risk actions only)
- **Within 72h**: info-level suggestion

Anomaly detection feeds into the pipeline similarly. All predictive events are trust-capped one level below the rule's current trust.

## Chaos Testing

12 built-in scenarios for validating the pipeline responds correctly:

```bash
# List scenarios
GET /api/healing/chaos/scenarios

# Run in dry-run mode (safe)
POST /api/healing/chaos/run {"scenario": "container_crash_recovery", "dry_run": true}
```

## Dry-Run Simulation

Test any heal event without executing:

```bash
POST /api/healing/dry-run
{"event": {"source": "test", "rule_id": "test", "condition": "cpu > 95",
           "target": "host1", "severity": "warning", "metrics": {"cpu": 97}}}
```

Returns what would happen: correlation, dependency analysis, action selection, pre-flight result, rollback plan.

## API Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/healing/ledger` | read | Recent outcomes |
| GET | `/api/healing/effectiveness` | read | Per-action success rates |
| GET | `/api/healing/suggestions` | read | Active suggestions |
| POST | `/api/healing/suggestions/{id}/dismiss` | operator | Dismiss a suggestion |
| GET | `/api/healing/trust` | read | Trust states |
| POST | `/api/healing/trust/{rule_id}/promote` | admin | Manual promotion |
| POST | `/api/healing/trust/{rule_id}/demote` | admin | Manual demotion |
| GET | `/api/healing/dependencies` | read | Dependency graph |
| POST | `/api/healing/dependencies/validate` | read | Validate dependency config |
| GET | `/api/healing/maintenance` | read | Active maintenance windows |
| POST | `/api/healing/maintenance` | operator | Create maintenance window |
| DELETE | `/api/healing/maintenance/{id}` | operator | End window early |
| POST | `/api/healing/rollback/{ledger_id}` | admin | Manual rollback |
| GET | `/api/healing/capabilities/{hostname}` | read | Agent capability manifest |
| POST | `/api/healing/capabilities/{hostname}/refresh` | operator | Force capability re-probe |
| POST | `/api/healing/dry-run` | operator | Simulate heal event |
| GET | `/api/healing/chaos/scenarios` | read | List chaos scenarios |
| POST | `/api/healing/chaos/run` | admin | Execute chaos test |
| GET | `/api/healing/health` | read | Pipeline health status |
