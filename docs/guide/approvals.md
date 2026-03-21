# Approvals

The Approvals system provides human-in-the-loop gates for sensitive automations. Any workflow with an Approval node pauses and waits for an authorised user to approve or reject before continuing.

## Approval Queue

Navigate to **Automations → Approvals** to see all pending approval requests.

| Column | Description |
|--------|-------------|
| Workflow | Name of the workflow that raised the request |
| Message | The prompt configured in the Approval node |
| Requested By | User or trigger that started the workflow |
| Age | How long the request has been waiting |
| Timeout | Auto-decision time remaining |
| Actions | Approve / Reject buttons |

Only users named in the `approvers` list of the Approval node (or admins) can approve or reject.

## Approving a Request

1. Open **Automations → Approvals**.
2. Click the row to see full context (workflow state, last output, variables).
3. Click **Approve** to continue the workflow, or **Reject** to terminate it.
4. Optionally add a comment that is recorded in the workflow execution history.

Approval actions are written to the audit log.

## Autonomy Levels

Each automation and agent has a configurable **autonomy level** that determines whether NOBA can act automatically or must wait for human approval:

| Level | Behaviour |
|-------|-----------|
| `execute` | Run immediately without approval |
| `approve` | Always require approval before running |
| `notify` | Run immediately but send a notification |
| `disabled` | Never run (effectively disabled) |

Set the autonomy level on the automation settings panel or per-agent in the agent detail panel.

## Auto-Approve Timeout

If an Approval node specifies `on_timeout: approve`, the workflow will automatically continue after the timeout expires without a decision. Use this for low-risk automations that should not be blocked indefinitely.

If `on_timeout: reject`, the workflow is terminated and a notification is sent.

The default timeout is 60 minutes. Configure per-node in the workflow builder.

## Notification Routing

When an approval request is raised:

1. A notification is sent to all channels configured in **Settings → Notifications**.
2. The message includes a deep link to the Approvals queue in the NOBA UI.
3. If NOBA is behind a reverse proxy, set `NOBA_BASE_URL` so the deep link resolves correctly.

## Approval History

Click **History** in the Approvals panel to see all past approval decisions with:
- Decision (approved / rejected / timed out)
- Deciding user
- Timestamp
- Comment (if provided)
