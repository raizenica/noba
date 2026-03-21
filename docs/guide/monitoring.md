# Monitoring

NOBA's Monitoring section provides endpoint health checks, uptime tracking, SLA reporting, and incident management.

## Endpoint Monitors

Navigate to **Monitoring → Endpoints** to manage monitors.

### Create a Monitor

Click **Add Monitor** and fill in:

| Field | Description |
|-------|-------------|
| Name | Display label |
| URL | Target URL (HTTP/HTTPS) or host:port for TCP |
| Type | `http`, `tcp`, `ping`, `keyword` |
| Interval | Check frequency in seconds (minimum 30) |
| Timeout | Request timeout in seconds |
| Expected Status | HTTP status code to treat as up (default 200) |
| Keyword | For `keyword` type: string that must be present in the response body |
| Retries | Number of retries before marking down (default 1) |
| Tags | Comma-separated labels for grouping |

### Edit and Delete

Click a monitor row to open its detail panel. Use **Edit** to change settings or **Delete** to remove it and all associated uptime history.

## SLA Dashboard

Navigate to **Monitoring → SLA** to see uptime percentages across configurable time windows:

- Last 24 hours
- Last 7 days
- Last 30 days
- Last 90 days

SLA is calculated as `(total_up_checks / total_checks) * 100`. Maintenance windows (see [Maintenance](/guide/maintenance)) are excluded from SLA calculations.

## Incidents

When a monitor transitions from up to down, NOBA creates an incident. Navigate to **Monitoring → Incidents** to view:

- Open incidents (currently down)
- Resolved incidents (back up, with downtime duration)
- MTTD (Mean Time to Detect) and MTTR (Mean Time to Resolve) statistics

### War Room

Click **Open War Room** on any open incident to enter the War Room view. This focused view shows:

- Live status of the affected monitor
- Related monitors (same tag group)
- Incident timeline
- Action panel to run automations directly from the incident

## Health Score

Each monitored endpoint has a health score (0–100) derived from:

- Recent uptime percentage (weighted 60%)
- Average response time vs. baseline (weighted 25%)
- Certificate expiry days remaining (weighted 15%, HTTPS only)

The aggregate health score across all monitors appears in the Monitoring section header.

## Status Page

NOBA generates a public status page at `/status` (no authentication required). The status page shows:

- Current status of all monitors tagged `public`
- 90-day uptime history as incident bars
- Active and resolved incidents

Configure which monitors appear on the status page using the `public` tag.
