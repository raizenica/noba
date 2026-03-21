# Security

The Security section provides per-host security scanning, a posture score, finding management, and RBAC role configuration.

## Security Scans

Navigate to **Security → Scans** to run or schedule security scans against your agents.

### Scan Types

| Scan | Description |
|------|-------------|
| **Package CVE** | Cross-references installed packages against the OSV/NVD database |
| **Open Ports** | Lists listening ports and flags unexpected services |
| **SSH Hardening** | Checks `sshd_config` against CIS benchmarks |
| **File Permissions** | Flags world-writable files and SUID/SGID binaries in key paths |
| **User Audit** | Lists users with UID 0, empty passwords, or recent additions |
| **Service Exposure** | Identifies services bound to `0.0.0.0` unnecessarily |

Click **Run Scan** on any agent to start an ad-hoc scan. Results are stored in the database and displayed in the Findings panel.

## Security Score

Each agent receives a security score (0–100):

| Score | Rating |
|-------|--------|
| 90–100 | Excellent |
| 75–89 | Good |
| 50–74 | Fair |
| Below 50 | Poor |

The score is derived from the number and severity of open findings. Resolving or suppressing findings improves the score.

## Findings

Navigate to **Security → Findings** to see all open findings across all agents.

| Column | Description |
|--------|-------------|
| Severity | `critical`, `high`, `medium`, `low`, `info` |
| Agent | Which host the finding is on |
| Category | Scan type that raised the finding |
| Summary | Short description |
| First Seen | When the finding was first detected |
| Status | `open`, `suppressed`, `resolved` |

### Suppressing a Finding

If a finding is a known false positive or an accepted risk, click **Suppress** and enter a reason. Suppressed findings are excluded from the security score but remain visible (greyed out) for audit purposes.

## RBAC Roles

NOBA uses three-tier Role-Based Access Control:

| Role | Permissions |
|------|-------------|
| `viewer` | Read-only: dashboard, stats, history, monitoring status |
| `operator` | Viewer + run automations, send agent commands, service control |
| `admin` | Operator + user management, settings, security scans, audit log |

Roles are assigned per user in **Settings → Users** (admin only).

### Route-Level Enforcement

Every API route declares its minimum required role:

- `Depends(_get_auth)` — any authenticated user (viewer+)
- `Depends(_require_operator)` — operator or admin
- `Depends(_require_admin)` — admin only

UI controls for operator/admin actions are hidden from viewers using `v-if="userRole !== 'viewer'"`.

## Authentication Security

- Passwords are hashed with **PBKDF2-HMAC-SHA256** (200,000 iterations, per-user random salt).
- Session tokens are 256-bit random hex strings, valid for 24 hours.
- Login is rate-limited: 5 attempts per 60 seconds per IP; 300-second lockout on breach.
- **TOTP 2FA** can be enabled per user in **Settings → Users → Security**.
- **OIDC** single sign-on is supported; see [Authentication](/api/authentication).
- Content Security Policy (`default-src 'self'`) is set on all responses.
- Integration API keys are stored server-side in `config.yaml` and never sent to the browser.
