# API Overview

NOBA exposes a RESTful HTTP API with 235+ endpoints organised across 13 routers. All responses are JSON.

## Base URL

```
http://<host>:<port>
```

Default port: `8080`. Configure with the `PORT` environment variable.

## OpenAPI Schema

Machine-readable OpenAPI 3.1 schema:

```
GET /api/openapi.json
```

## Swagger UI

Interactive API explorer (no authentication required to open):

```
http://<host>:<port>/api/docs
```

## ReDoc

Alternative documentation UI:

```
http://<host>:<port>/api/redoc
```

## Router Overview

| Router | Prefix | Description |
|--------|--------|-------------|
| `auth` | `/api` | Login, logout, token management, OIDC |
| `system` | `/api` | Stats, SSE stream, history, settings |
| `agents` | `/api/agents` | Agent registration, commands, streams |
| `automations` | `/api/automations` | Automation CRUD, runs, webhooks |
| `monitoring` | `/api/monitoring` | Endpoint monitors, uptime, incidents |
| `infrastructure` | `/api/infrastructure` | Services, K8s, Proxmox, drift |
| `intelligence` | `/api/intelligence` | Predictions, health scores |
| `security` | `/api/security` | Scans, findings, scoring |
| `workflows` | `/api/workflows` | Workflow CRUD, node types, execution |
| `approvals` | `/api/approvals` | Approval queue, decisions |
| `maintenance` | `/api/maintenance` | Maintenance windows |
| `plugins` | `/api/plugins` | Plugin catalogue, install/uninstall |
| `admin` | `/api/admin` | Users, audit log, system settings |

## Global Error Codes

| HTTP Status | Meaning |
|-------------|---------|
| `200` | Success |
| `400` | Bad request — invalid parameters |
| `401` | Not authenticated — missing or expired token |
| `403` | Forbidden — insufficient role |
| `404` | Resource not found |
| `409` | Conflict — resource already exists |
| `422` | Validation error — request body schema mismatch |
| `429` | Rate limited |
| `500` | Internal server error |

## Pagination

Endpoints that return lists accept:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `limit` | `100` | Maximum items to return |
| `offset` | `0` | Items to skip |

Responses include `total`, `limit`, and `offset` fields when paginated.

## Versioning

The current API version is **v3**. Breaking changes will be introduced under a new version prefix (e.g. `/api/v4/`). The v3 API has no version prefix — all routes are at `/api/`.
