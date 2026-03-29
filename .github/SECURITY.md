# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 2.x.x   | Yes                |
| < 2.0   | No                 |

## Reporting a Vulnerability

**Please do NOT report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability in NOBA, please report it responsibly:

1. **Email:** Send details to **security@noba.app** (or open a [private security advisory](https://github.com/raizenica/noba/security/advisories/new) on GitHub)
2. **Include:**
   - Description of the vulnerability
   - Steps to reproduce
   - Affected version(s)
   - Potential impact
   - Suggested fix (if any)

## Response Timeline

- **Acknowledgment:** Within 48 hours
- **Initial assessment:** Within 5 business days
- **Fix timeline:** Depends on severity
  - Critical/High: Patch within 7 days
  - Medium: Patch within 30 days
  - Low: Next scheduled release

## Security Measures

NOBA implements the following security baseline:

- **Authentication:** PBKDF2-HMAC-SHA256 password hashing, per-IP rate limiting with automatic lockout
- **Authorization:** Three-tier RBAC (viewer / operator / admin), enterprise feature gating
- **Transport:** CSP headers, X-Frame-Options, HSTS-ready, no inline scripts
- **Data:** AES-256-GCM vault encryption, encrypted config values (Fernet), parameterized SQL queries
- **SSO:** SAML 2.0 with signature verification, OIDC with PKCE
- **API:** API key authentication with SHA-256 hashing, SCIM 2.0 with Bearer tokens
- **Updates:** Auto-update with rollback safety, post-update health checks

## Scope

The following are in scope for security reports:

- Authentication and authorization bypasses
- Injection vulnerabilities (SQL, command, XSS)
- SSRF or path traversal
- Sensitive data exposure
- Cryptographic weaknesses
- Privilege escalation

The following are out of scope:

- Denial of service (rate limiting is already implemented)
- Issues requiring physical access to the server
- Social engineering
- Issues in dependencies (report those upstream; we monitor Dependabot)

## Recognition

We appreciate responsible disclosure. With your permission, we will acknowledge security researchers in our CHANGELOG and release notes.
