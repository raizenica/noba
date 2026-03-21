# Automations API

All automation endpoints are under `/api/automations`. Requires authentication. Write operations require `operator` role or higher.

## List Automations

```
GET /api/automations
```

**Response `200`:**
```json
[
  {
    "id": "auto_backup_nas",
    "name": "NAS Backup",
    "type": "script",
    "icon": "fa-database",
    "schedule": "0 3 * * *",
    "last_run": 1718000000,
    "last_status": "done"
  }
]
```

## Create Automation

```
POST /api/automations
```

**Request:**
```json
{
  "name": "Restart nginx",
  "type": "service_control",
  "params": {
    "service": "nginx",
    "action": "restart"
  }
}
```

**Response `201`:** `{ "id": "auto_xyz", "status": "created" }`

## Update Automation

```
PUT /api/automations/{id}
```

**Request:** same shape as create. Returns `{ "status": "updated" }`.

## Delete Automation

```
DELETE /api/automations/{id}
```

**Response `200`:** `{ "status": "deleted" }`

## Run Automation

```
POST /api/automations/{id}/run
```

Executes the automation immediately, regardless of any schedule.

**Response `200`:**
```json
{
  "run_id": "run_abc123",
  "status": "running"
}
```

## Run Status

```
GET /api/automations/runs/{run_id}
```

**Response `200`:**
```json
{
  "run_id": "run_abc123",
  "automation_id": "auto_backup_nas",
  "status": "done",
  "started": 1718000000,
  "finished": 1718000042,
  "output": "Backup completed successfully.\n..."
}
```

## Run Log Stream

```
GET /api/automations/runs/{run_id}/stream?token=<token>
```

SSE stream of log output for a running automation.

## Templates

```
GET /api/automations/templates
```

Returns the built-in template library.

```
POST /api/automations/templates/{template_id}/apply
```

Creates a new automation from a template.

## Export

```
GET /api/automations/export
```

Returns all automations as a JSON array for backup or migration.

## Import

```
POST /api/automations/import
Content-Type: application/json
```

Body: JSON array from a previous export. IDs are regenerated on import.

**Response `200`:** `{ "imported": 12 }`

## Webhook Trigger

```
POST /api/automations/webhook/{id}
```

Triggers an automation via an inbound webhook. The `id` is the automation's webhook token (distinct from its internal ID).

No authentication required for webhook endpoints — the token in the URL acts as the secret.

## Approval Queue

```
GET /api/approvals
```

Returns all pending approval requests.

```
POST /api/approvals/{request_id}/approve
```

Approves a pending request. Optionally include a comment:
```json
{ "comment": "Approved for deployment window" }
```

```
POST /api/approvals/{request_id}/reject
```

Rejects a pending request.

Both require `operator` role or higher and the user must be in the `approvers` list for the request (or be an admin).

## Maintenance Windows

```
GET /api/maintenance
```

Returns all maintenance windows.

```
POST /api/maintenance
```

Creates a maintenance window.

```json
{
  "name": "Weekly reboot",
  "start": "2026-03-22T03:00:00",
  "end": "2026-03-22T04:00:00",
  "recurring": "0 3 * * 0",
  "scope": ["monitor_abc", "agent_xyz"],
  "autonomy_override": "disabled"
}
```

```
POST /api/maintenance/{id}/activate
```

Activates a window immediately.

```
POST /api/maintenance/{id}/deactivate
```

Deactivates an active window early.

```
DELETE /api/maintenance/{id}
```

Deletes a maintenance window.
