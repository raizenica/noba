# Maintenance Windows

Maintenance windows suppress alerts and modify automation autonomy during planned work. They prevent false-positive notifications when you are intentionally taking systems offline.

## Creating a Maintenance Window

Navigate to **Automations → Maintenance** and click **New Window**.

| Field | Description |
|-------|-------------|
| Name | Display label (e.g. "Weekly NAS reboot") |
| Start | Date and time the window begins |
| End | Date and time the window ends |
| Recurring | Optional cron expression for repeating windows |
| Scope | Which monitors and agents the window applies to |
| Autonomy Override | Override agent autonomy level during the window |

## Alert Suppression

While a maintenance window is active:

- Monitors in scope show status **Maintenance** instead of Down.
- Alert rule evaluations still run, but notifications are **not sent**.
- The SLA calculation excludes the window duration (uptime is not penalised).
- Incidents are still created and logged but are tagged `maintenance`.

## Autonomy Override

Set **Autonomy Override** to `disabled` to prevent any automations from running during the window (useful when a core system is offline). Set to `execute` to allow automations to run without approval gates (useful for automated maintenance tasks).

## Activating a Window Early

Click **Activate Now** to start a window immediately, regardless of its scheduled start time.

## Deactivating a Window

Click **End Now** to close an active window early. Monitors return to their normal evaluation state within the next check cycle.

## Recurring Windows

Use a cron expression to create repeating maintenance windows:

| Expression | Meaning |
|-----------|---------|
| `0 3 * * 0` | Every Sunday at 03:00 |
| `0 2 1 * *` | First day of every month at 02:00 |
| `30 1 * * 1-5` | Weekdays at 01:30 |

The window duration is inferred from the original start/end times. For example, a window from 03:00 to 04:00 on a `0 3 * * 0` schedule will recur as a 1-hour window every Sunday.

## Active Window Indicator

When a maintenance window is active, a banner appears at the top of the dashboard indicating which window is in effect and when it is scheduled to end.

## Maintenance and Workflows

Link a maintenance window to a workflow using the **Nightly Maintenance** playbook template, which automatically:

1. Activates the window at the start of the workflow.
2. Performs the maintenance tasks.
3. Deactivates the window at the end.
4. Sends a completion report.

See [Workflows](/guide/workflows) for details.
