# Enterprise v2 — Phase 1 Design: Auth Triad + API Key Scoping

**Date:** 2026-03-27
**Branch:** `enterprise-v2` (off `main`, pushed to ``private-enterprise-repo``)
**Scope:** SAML 2.0 SP, WebAuthn/FIDO2 + MFA backup codes, SCIM 2.0 provisioning, API key scoping/IP restriction/rate limiting

---

## Context

The original `enterprise-uplift` branch (+12,844 lines across 3 phase commits) was built on the pre-modularisation monolith. `main` has since undergone a 7-target modularisation: `db/core.py` split into 22 domain modules, `integrations/simple.py` split into 6 category files, Vue components decomposed. A direct rebase or cherry-pick would produce hundreds of conflicts.

`enterprise-v2` starts fresh off current `main` and ports enterprise features by adapting them to the new architecture. Enterprise-uplift serves as the logic reference; the structure follows `main`'s patterns.

**Phase sequence decided:**
- Phase 1 (this spec): Auth triad + API key scoping, SQLite only
- Phase 2: PostgreSQL pluggable backend
- Phase 3: HA + Redis sessions, multi-tenancy, immutable audit
- Phase 4: Frontend UI for enterprise features

---

## Branch Strategy

```
main (raizenica/noba-ce)
  └── enterprise-v2 (`private-enterprise-repo`)
```

- Community fixes flow up: `git merge origin/main` periodically
- Enterprise work never flows back to community `main`
- Git remotes in `~/noba`: `origin` → raizenica/noba-ce, `enterprise` → `private-enterprise-repo`
- Create branch: `git checkout -b enterprise-v2 main && git push enterprise enterprise-v2`

---

## File Map

### New files

```
share/noba-web/server/
  routers/saml.py          — SAML 2.0 SP: login redirect, ACS callback, metadata
  routers/webauthn.py      — WebAuthn/FIDO2 registration + auth + backup codes
  routers/scim.py          — SCIM 2.0 Users CRUD + discovery endpoints
  db/saml.py               — _SamlMixin: saml_sessions table
  db/webauthn.py           — _WebAuthnMixin: credentials, challenges, backup_codes tables
  db/scim.py               — _ScimMixin: scim_tokens, provision_log tables
  logging_config.py        — Structured JSON logging (NOBA_LOG_LEVEL env var)

tests/
  test_saml.py             — ported + adapted from enterprise-uplift
  test_webauthn.py         — ported + adapted
  test_scim.py             — ported + adapted
```

### Modified files

| File | Change |
|---|---|
| `server/auth.py` | Add `SamlProvider`, `WebAuthnStore` classes |
| `server/deps.py` | Add `_get_auth_scim()`, `_check_api_key_scope()` |
| `server/db/core.py` | Register `_SamlMixin`, `_WebAuthnMixin`, `_ScimMixin` |
| `server/db/tokens.py` | Add `scope`, `allowed_ips`, `rate_limit` columns to api_keys via ALTER |
| `server/app.py` | Register `saml_router`, `webauthn_router`, `scim_router` |
| `server/main.py` | Import `logging_config.setup_logging()` before app creation |

---

## SAML 2.0 SP

### Routes

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/saml/login` | none | Build AuthnRequest, redirect to IdP SSO URL |
| POST | `/api/saml/acs` | none (IdP-posted) | Validate assertion, issue session token, redirect to `/#/dashboard` |
| GET | `/api/saml/metadata` | none | Return SP metadata XML |

SP-initiated SSO only. IdP-initiated (unsolicited response) is rejected — it enables CSRF attacks on the SSO flow.

### Config (YAML settings, `saml:` block)

```yaml
saml:
  enabled: true
  entity_id: "https://noba.example.com"
  sso_url: "https://idp.example.com/sso"
  idp_certificate: "-----BEGIN CERTIFICATE-----\n..."
  sp_certificate: "-----BEGIN CERTIFICATE-----\n..."   # optional, for signed requests
  sp_private_key: "-----BEGIN PRIVATE KEY-----\n..."   # optional
  role_attribute: "noba_role"    # IdP attribute → NOBA role; absent = "viewer"
  name_id_format: "emailAddress" # or "persistent", "unspecified"
```

### Session integration

On valid assertion: `token_store.add(token, username, role)` (same call as password login) — same bearer token as password login. Frontend sees no difference post-login. SAML users coexist with local users; if a SAML `nameID` matches an existing local username the same account is used. If no local account exists, one is auto-created (disabled password, role from `role_attribute` or default `viewer`).

### `db/saml.py` — `_SamlMixin`

```sql
CREATE TABLE IF NOT EXISTS saml_sessions (
  id          TEXT PRIMARY KEY,
  name_id     TEXT NOT NULL,
  session_idx TEXT,
  username    TEXT NOT NULL,
  issued_at   REAL NOT NULL,
  expires_at  REAL NOT NULL
);
```

Used for SLO (single logout) — IdP can terminate sessions by session index.

### `auth.py` additions — `SamlProvider`

```python
class SamlProvider:
    """Parses YAML saml: config, builds AuthnRequests, validates Responses."""
    def is_enabled(self) -> bool: ...
    def build_authn_request(self) -> tuple[str, str]: ...  # (redirect_url, relay_state)
    def validate_response(self, saml_response: str) -> tuple[str, str]: ...  # (username, role)
```

Crypto: XML signature verification via `cryptography` (already in requirements). No new deps.

---

## WebAuthn / FIDO2 + MFA Backup Codes

### Routes

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/webauthn/register/begin` | `_get_auth` | Generate registration challenge |
| POST | `/api/webauthn/register/complete` | `_get_auth` | Verify attestation, store credential |
| POST | `/api/webauthn/authenticate/begin` | none | Generate authentication challenge (body: `{"username": "..."}`) |
| POST | `/api/webauthn/authenticate/complete` | none | Verify assertion, issue session token |
| POST | `/api/webauthn/backup-codes/generate` | `_get_auth` | Generate 10 one-time backup codes |
| POST | `/api/webauthn/backup-codes/consume` | none | Validate backup code, issue session token |

### `db/webauthn.py` — `_WebAuthnMixin`

```sql
CREATE TABLE IF NOT EXISTS webauthn_credentials (
  id             TEXT PRIMARY KEY,
  username       TEXT NOT NULL,
  credential_id  BLOB NOT NULL UNIQUE,
  public_key     BLOB NOT NULL,
  sign_count     INTEGER NOT NULL DEFAULT 0,
  created_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS webauthn_challenges (
  id         TEXT PRIMARY KEY,
  username   TEXT NOT NULL,
  challenge  BLOB NOT NULL,
  type       TEXT NOT NULL,   -- "registration" or "authentication"
  expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS mfa_backup_codes (
  id         TEXT PRIMARY KEY,
  username   TEXT NOT NULL,
  code_hash  TEXT NOT NULL,   -- SHA-256 of the plaintext code
  used_at    REAL            -- NULL = unused
);
```

### `auth.py` additions — `WebAuthnStore`

```python
class WebAuthnStore:
    """CBOR/COSE parsing and P-256 verification — zero external WebAuthn deps."""
    def generate_challenge(self, username: str, type_: str) -> bytes: ...
    def verify_attestation(self, credential_json: dict, challenge: bytes) -> tuple[bytes, bytes, int]: ...
    def verify_assertion(self, assertion_json: dict, stored_key: bytes, stored_count: int) -> int: ...
```

Implementation ported from enterprise-uplift (uses `cryptography` for P-256 EC verification and `struct` for CBOR decoding — no `cbor2` dependency).

---

## SCIM 2.0 User Provisioning

### Routes (`/api/scim/v2/` prefix, auth via `_get_auth_scim()`)

| Method | Path | Description |
|---|---|---|
| GET | `/Users` | List users (paginated, filter support) |
| POST | `/Users` | Create user |
| GET | `/Users/{id}` | Get user |
| PUT | `/Users/{id}` | Replace user |
| PATCH | `/Users/{id}` | Update user (SCIM patch ops) |
| DELETE | `/Users/{id}` | Delete/disable user |
| GET | `/ServiceProviderConfig` | SCIM capability discovery |
| GET | `/ResourceTypes` | Resource type discovery |
| GET | `/Schemas` | Schema discovery |

### Auth

Dedicated SCIM provisioning token — separate from session bearer tokens. Admin generates via `POST /api/admin/scim-token` (added to existing `routers/admin.py`, returns plaintext once, never stored). Token hash stored in `db/scim.py`. `_get_auth_scim()` in `deps.py` validates it.

### User mapping

| SCIM attribute | NOBA field |
|---|---|
| `userName` | `username` |
| `active` | account enabled/disabled |
| `roles[0].value` | NOBA role (`viewer`/`operator`/`admin`) |
| `name.formatted` | display name (stored in user record) |

On SCIM `POST /Users`: generates a random 32-char initial password. User must authenticate via SAML or WebAuthn on first login (or admin resets password).

### `db/scim.py` — `_ScimMixin`

```sql
CREATE TABLE IF NOT EXISTS scim_tokens (
  id           TEXT PRIMARY KEY,
  token_hash   TEXT NOT NULL UNIQUE,
  created_at   REAL NOT NULL,
  last_used_at REAL
);

CREATE TABLE IF NOT EXISTS scim_provision_log (
  id         TEXT PRIMARY KEY,
  action     TEXT NOT NULL,   -- "create", "update", "delete", "disable"
  scim_id    TEXT,
  username   TEXT,
  timestamp  REAL NOT NULL,
  result     TEXT NOT NULL    -- "ok" or error message
);
```

---

## API Key Scoping

### Schema change — `db/tokens.py`

Three new columns added to `api_keys` via `ALTER TABLE IF NOT EXISTS`:

```sql
ALTER TABLE api_keys ADD COLUMN scope TEXT DEFAULT '';
ALTER TABLE api_keys ADD COLUMN allowed_ips TEXT DEFAULT '[]';
ALTER TABLE api_keys ADD COLUMN rate_limit INTEGER DEFAULT 0;
```

- `scope`: comma-separated resource prefixes (e.g. `"metrics,agents"`). Empty = unrestricted.
- `allowed_ips`: JSON array of CIDR strings (e.g. `["10.0.0.0/8", "192.168.1.5/32"]`). Empty array = unrestricted.
- `rate_limit`: max requests per minute. 0 = unrestricted.

### Enforcement — `deps.py`

`_check_api_key_scope(key_row, path, client_ip)` called in the API key auth path:

1. If `scope` is non-empty: request path must start with one of the scope prefixes → 403 if not.
2. If `allowed_ips` is non-empty: client IP must match a CIDR → 403 if not.
3. If `rate_limit > 0`: rolling 60s window tracked in `defaultdict(deque)` keyed by key ID → 429 if exceeded.

The in-memory rate limit resets on server restart (acceptable for API key use case — persistent rate limiting requires Redis, which is Phase 3).

### API changes

Existing `GET/POST/DELETE /api/admin/api-keys` extended to accept and return `scope`, `allowed_ips`, `rate_limit` fields. No new routes.

---

## Structured JSON Logging

`logging_config.py` (~50 lines) — ported directly from enterprise-uplift.

- `setup_logging()` called from `main.py` before app creation
- Reads `NOBA_LOG_LEVEL` env var (default: `INFO`)
- If `NOBA_LOG_FORMAT=json`: emits structured JSON (level, timestamp, logger, message, exc_info)
- Otherwise: standard human-readable format (unchanged from community)
- No new deps — uses stdlib `logging`

---

## Testing Strategy

Port enterprise-uplift test files, adapting to main's fixtures (`client`, `admin_headers`, `viewer_headers`, `operator_headers`).

| File | Est. tests | Coverage |
|---|---|---|
| `test_saml.py` | ~45 | AuthnRequest format, ACS validation, signature verification, role mapping, SLO, config disabled |
| `test_webauthn.py` | ~60 | Registration flow, authentication flow, sign count increment, replay rejection, backup codes |
| `test_scim.py` | ~55 | Full CRUD, patch ops, filter/pagination, token auth, provision log, discovery endpoints |
| API key scoping (in `test_router_admin.py`) | ~20 | Scope enforcement, IP restriction, rate limit |

**Target: ~180 new tests. Full suite (3181 + 180 = ~3361) must pass with zero regressions.**

---

## Implementation Order

1. Create `enterprise-v2` branch, push to enterprise remote
2. `db/saml.py`, `db/webauthn.py`, `db/scim.py` — new DB modules + registration in `db/core.py`
3. `db/tokens.py` — ALTER TABLE additions for API key scoping
4. `auth.py` — `SamlProvider`, `WebAuthnStore` classes
5. `deps.py` — `_get_auth_scim()`, `_check_api_key_scope()`
6. `routers/saml.py`, `routers/webauthn.py`, `routers/scim.py` — new routers
7. `app.py` — register new routers
8. `logging_config.py` + `main.py` hook
9. Tests — `test_saml.py`, `test_webauthn.py`, `test_scim.py`, API key scoping additions
10. Full test suite run
11. Rsync to live server + smoke test

Each step is independently committable. Steps 2–5 (backend foundations) unblock steps 6–8 (routers).
