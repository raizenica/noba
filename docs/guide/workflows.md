# Workflows

The visual workflow builder lets you design multi-step automation sequences with conditional branching, parallel execution, human approval gates, and delays.

## Opening the Builder

Navigate to **Automations → Workflows** and click **New Workflow** or open an existing one.

The builder is a node-based canvas. Drag nodes from the palette on the left onto the canvas and connect them by drawing edges between output and input ports.

## Node Types

### Action

Executes an automation (script, webhook, agent command, service control).

```yaml
type: action
automation_id: "backup-nas"
on_failure: continue  # or: stop, retry
retries: 2
```

### Condition

Branches the workflow based on a boolean expression.

```yaml
type: condition
expression: "last_result.exit_code == 0"
true_branch: next-step
false_branch: notify-failure
```

Available variables in expressions: `last_result`, `context`, `metrics`, `agent`.

### Approval

Pauses the workflow and sends a notification requesting human approval.

```yaml
type: approval
message: "Approve production deployment?"
approvers:
  - admin
  - ops-lead
timeout_minutes: 60
on_timeout: reject  # or: approve
```

See [Approvals](/guide/approvals) for the approval queue UI.

### Parallel

Runs multiple branches simultaneously and waits for all to complete before continuing.

```yaml
type: parallel
branches:
  - backup-db
  - backup-files
  - notify-start
```

### Delay

Waits a fixed duration before proceeding.

```yaml
type: delay
duration_seconds: 300
```

### Notify

Sends a notification to one or more channels.

```yaml
type: notify
channels: [telegram, slack]
message: "Workflow {workflow_name} completed at {timestamp}"
```

### Loop

Iterates over a list and runs a sub-workflow for each item.

```yaml
type: loop
items: "{{ agents.online }}"
variable: agent
body: run-agent-scan
max_iterations: 50
```

## Playbook Templates

The workflow library includes pre-built playbooks:

| Template | Description |
|----------|-------------|
| **Incident Response** | Alert → assess → notify on-call → open war room |
| **Deploy Approval** | Build → test → approval gate → deploy → smoke test |
| **Nightly Maintenance** | Enable maintenance window → run tasks → disable window → report |
| **Security Remediation** | Scan → triage findings → auto-fix low severity → notify for high |
| **DR Failover** | Health check → switch DNS → restart services → verify → notify |

Click **Use Template** to create a copy in your workspace.

## Running Workflows

- **Manual** — click **Run** on the workflow card.
- **Scheduled** — attach a cron schedule in the workflow settings.
- **Triggered** — link a workflow to an alert rule or monitoring event.
- **API** — `POST /api/automations/workflows/{id}/run`

## Execution History

Click **History** on any workflow to see past runs with:
- Start/end time and total duration
- Per-node execution status and output
- Variable values at each step (for debugging)

Failed workflow runs are highlighted in red. Click **Replay** to re-run from a specific failed node (preserving the original context).
