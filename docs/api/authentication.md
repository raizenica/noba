# Authentication

## Login

```
POST /api/login
```

Rate limited: 5 attempts per 60 seconds per IP. Exceeding the limit triggers a 300-second lockout.

**Request:**
```json
{
  "username": "admin",
  "password": "yourpassword"
}
```

**Response `200`:**
```json
{
  "token": "abc123def456...",
  "role": "admin",
  "username": "admin"
}
```

**Response `401`:** `{ "error": "Invalid credentials" }`

**Response `429`:** `{ "error": "Too many login attempts. Try again in 287 seconds." }`

## Bearer Token

Pass the token in the `Authorization` header on all subsequent requests:

```
Authorization: Bearer <token>
```

Tokens are 256-bit random hex strings. They expire after **24 hours**. A cleanup job purges expired tokens every 5 minutes.

## SSE / EventSource

`EventSource` (used for SSE streams) cannot set custom headers. Pass the token as a query parameter instead:

```
GET /api/stream?token=<token>
```

The server accepts `?token=` on all endpoints as a fallback to the `Authorization` header.

## Logout

```
POST /api/logout
```

Revokes the current session token immediately.

**Response `200`:** `{ "status": "ok" }`

## Current User

```
GET /api/me
```

**Response `200`:**
```json
{
  "username": "admin",
  "role": "admin"
}
```

## TOTP Two-Factor Authentication

If 2FA is enabled for a user, the login flow requires a second step:

**Step 1** — standard login returns a `totp_required` field:
```json
{
  "totp_required": true,
  "partial_token": "temp_abc123"
}
```

**Step 2** — submit the TOTP code:
```
POST /api/login/totp
```
```json
{
  "partial_token": "temp_abc123",
  "code": "123456"
}
```

Returns the full session token on success.

Enable 2FA for a user in **Settings → Users → Security → Enable 2FA**. Scan the displayed QR code with an authenticator app (Google Authenticator, Aegis, etc.).

## OIDC Single Sign-On

Configure OIDC in `config.yaml`:

```yaml
web:
  oidc:
    enabled: true
    issuer: "https://auth.example.com"
    client_id: "noba"
    client_secret: "xxxx"
    redirect_uri: "http://noba.example.com:8080/api/auth/oidc/callback"
    scopes: ["openid", "profile", "email"]
    role_claim: "noba_role"  # JWT claim to map to NOBA role
    role_map:
      admin: "noba-admin"
      operator: "noba-operator"
      viewer: "noba-viewer"
```

The OIDC flow:
1. `GET /api/auth/oidc/authorize` — redirects to the identity provider.
2. After authentication, the IdP redirects to `/api/auth/oidc/callback`.
3. NOBA exchanges the code for tokens, maps the role, and issues a session token.

## Roles

| Role | `Depends(...)` guard | Access |
|------|---------------------|--------|
| `viewer` | `_get_auth` | Read-only: stats, history, monitoring |
| `operator` | `_require_operator` | Viewer + automations, agent commands, service control |
| `admin` | `_require_admin` | Operator + user management, settings, security, audit log |

## Health Check (Unauthenticated)

```
GET /api/status/public
```

Returns server status without requiring a token. Used by Docker health checks and load balancers.

**Response `200`:**
```json
{
  "status": "ok",
  "version": "3.0.0",
  "uptime_s": 3723
}
```
