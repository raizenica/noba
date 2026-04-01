# Enterprise → CE Back-Port: Design Spec

**Date:** 2026-04-01
**Scope:** Back-port 52 bug fixes, security hardening, and UX improvements from the enterprise repo to CE
**Excluded:** Multi-tenancy, PostgreSQL, RBAC, SAML/SCIM/WebAuthn extensions, license system, AD sync, branding, invites, UserStore field expansion, router file splitting

## Categories

### Security Fixes (13 items)
- S1: PBKDF2 200k→600k with new hash format + auto-upgrade on login
- S2: generate_totp_secret raises RuntimeError instead of silent fallback
- S3: Security headers (X-Frame-Options DENY, HSTS, COOP, COEP, CORP, CSP frame-ancestors)
- S4: deps.py `from None` on 4 HTTPException raises
- S5: Client IP fallback "0.0.0.0" → "unknown"
- S6: Hostname regex validation on WS connect + report endpoint
- S7: Global 500/422 exception handlers in app.py
- S8: Shutdown flag set FIRST before cleanup
- S9: `from None` + error sanitization across 36 raises in 6 routers
- S10: collector.py error message obfuscation
- S11: AiChatPanel.vue DOMPurify XSS sanitization
- S12: agent_deploy.py hostname validation
- S13: agent_deploy.py error logging + generic message on failure

### Backend Bug Fixes (14 items)
- B1-B6: agent_deploy.py (localhost detection, preflight checks, SSH config, verify_ssl, connectivity check, Alpine support)
- B7: remediation.py error obfuscation + DNS failover implementation
- B8: remediation.py backup trigger searches automations DB
- B9: workflow_engine.py webhook HMAC-SHA256 signing
- B10-B11: runner.py + plugins.py error obfuscation
- B12: healing/agent_verify.py "type"→"command" typo
- B13: healing/chaos.py _evaluate_expectation implementation
- B14: healing/snapshots.py system state capture

### Frontend Bug Fixes (20 items)
- F1: constants.js STREAM_BUFFER_MAX_LINES sign fix
- F2: main.js service worker .catch
- F3: HealingView.vue missing modal imports/refs
- F4: HealingApprovalTab.vue requested_at→created_at
- F5: RemoteDesktopView.vue JSON.parse try/catch
- F6: SystemLogTab.vue native nextTick
- F7-F11: 5 API endpoint path corrections
- F12-F13: HealthScoreGauge + DashboardToolbar missing onMounted
- F14: DeployModal.vue server URL validation
- F15: App.vue theme persistence
- F16: DashboardView.vue MutationObserver for masonry
- F17: WelcomeSetup.vue modal UX improvements
- F18-F19: Settings keyword search
- F20: Code cleanup across 11 components

### Shell & Infrastructure (5 items)
- I1: noba-lib.sh PBKDF2 sync to 600k
- I2: noba-lib.sh mktemp + trap for temp files
- I3: noba-tui.sh quote $DIALOG
- I4: install.sh sudo detection + deps
- I5: Dockerfile non-root user + deps
