# Monitoring API

All monitoring endpoints are under `/api/monitoring`. Requires authentication.

## List Monitors

```
GET /api/monitoring/endpoints
```

**Response `200`:**
```json
[
  {
    "id": "mon_abc123",
    "name": "Homepage",
    "url": "https://example.com",
    "type": "http",
    "interval": 60,
    "status": "up",
    "response_time_ms": 142,
    "last_check": 1718000000,
    "uptime_24h": 99.9,
    "tags": ["production", "public"]
  }
]
```

## Create Monitor

```
POST /api/monitoring/endpoints
```

Requires `operator` role.

**Request:**
```json
{
  "name": "API Health",
  "url": "https://api.example.com/health",
  "type": "http",
  "interval": 60,
  "timeout": 10,
  "expected_status": 200,
  "retries": 1,
  "tags": ["api", "public"]
}
```

**Response `201`:** `{ "id": "mon_xyz", "status": "created" }`

## Update Monitor

```
PUT /api/monitoring/endpoints/{id}
```

**Response `200`:** `{ "status": "updated" }`

## Delete Monitor

```
DELETE /api/monitoring/endpoints/{id}
```

Requires `admin` role.

**Response `200`:** `{ "status": "deleted" }`

## Monitor Uptime History

```
GET /api/monitoring/endpoints/{id}/history
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `range_h` | `24` | Hours of history |
| `resolution` | `300` | Bucket size in seconds |

**Response `200`:**
```json
[
  { "time": 1718000000, "status": "up", "response_time_ms": 142 },
  { "time": 1718000300, "status": "up", "response_time_ms": 138 }
]
```

## SLA Report

```
GET /api/monitoring/sla
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `days` | `30` | Time window in days |

**Response `200`:**
```json
[
  {
    "monitor_id": "mon_abc123",
    "name": "Homepage",
    "uptime_percent": 99.95,
    "total_checks": 43200,
    "downtime_minutes": 21.6
  }
]
```

## Health Score

```
GET /api/monitoring/health-score
```

Returns the aggregate health score (0–100) across all monitors.

```
GET /api/monitoring/endpoints/{id}/health-score
```

Returns the health score for a single monitor with component breakdown.

## Incidents

```
GET /api/monitoring/incidents
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `status` | `all` | `open`, `resolved`, or `all` |
| `limit` | `50` | Maximum incidents to return |

**Response `200`:**
```json
[
  {
    "id": "inc_abc123",
    "monitor_id": "mon_abc123",
    "monitor_name": "Homepage",
    "started": 1718000000,
    "resolved": 1718003600,
    "duration_minutes": 60,
    "cause": "HTTP 503",
    "status": "resolved"
  }
]
```

## War Room

```
GET /api/monitoring/incidents/{id}/war-room
```

Returns the war room context for an incident: affected monitor, related monitors (same tags), recent events, and suggested automations.

## Status Page Data

```
GET /api/monitoring/status-page
```

Unauthenticated. Returns current status for all monitors tagged `public`, plus 90-day incident history.

**Response `200`:**
```json
{
  "overall": "operational",
  "monitors": [
    {
      "name": "Homepage",
      "status": "up",
      "uptime_90d": 99.95,
      "incidents": []
    }
  ],
  "active_incidents": []
}
```

This endpoint powers the public status page at `/status`.
