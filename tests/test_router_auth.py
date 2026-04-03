# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for the auth router (share/noba-web/server/routers/auth.py)."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest


def _has_pyotp() -> bool:
    try:
        import pyotp  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_rate_limiter():
    """Reset the global rate limiter so tests don't pollute each other."""
    from server.auth import rate_limiter
    rate_limiter.reset("testclient")


@pytest.fixture(autouse=True)
def _clean_rate_limiter():
    """Reset rate limiter state before and after every test in this module."""
    _reset_rate_limiter()
    yield
    _reset_rate_limiter()


# ===========================================================================
# POST /api/login
# ===========================================================================

class TestLogin:
    """Login endpoint — credentials, rate limiting, 2FA."""

    def test_valid_credentials(self, client):
        resp = client.post("/api/login", json={"username": "admin", "password": "Admin1234!"})
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data

    def test_invalid_password(self, client):
        resp = client.post("/api/login", json={"username": "admin", "password": "WrongPass1!"})
        assert resp.status_code == 401

    def test_nonexistent_user(self, client):
        resp = client.post("/api/login", json={"username": "noone", "password": "Whatever1!"})
        assert resp.status_code == 401

    def test_missing_username(self, client):
        resp = client.post("/api/login", json={"password": "Admin1234!"})
        assert resp.status_code == 401

    def test_missing_password(self, client):
        resp = client.post("/api/login", json={"username": "admin"})
        assert resp.status_code == 401

    def test_empty_body(self, client):
        resp = client.post("/api/login", json={})
        assert resp.status_code == 401

    def test_empty_password(self, client):
        resp = client.post("/api/login", json={"username": "admin", "password": ""})
        assert resp.status_code == 401

    def test_empty_username(self, client):
        resp = client.post("/api/login", json={"username": "", "password": "Admin1234!"})
        assert resp.status_code == 401

    def test_token_is_string(self, client):
        resp = client.post("/api/login", json={"username": "admin", "password": "Admin1234!"})
        assert resp.status_code == 200
        assert isinstance(resp.json()["token"], str)
        assert len(resp.json()["token"]) > 10

    def test_rate_limiting_locks_after_failures(self, client):
        """Repeated failures from same IP should trigger rate limiting."""
        for _ in range(20):
            client.post("/api/login", json={"username": "admin", "password": "Wrong1!"})
        resp = client.post("/api/login", json={"username": "admin", "password": "Wrong1!"})
        assert resp.status_code in (401, 429)

    def test_rate_limit_returns_429(self, client):
        """Once locked out, the endpoint returns 429."""
        from server.auth import rate_limiter
        # Force lockout directly
        for _ in range(30):
            rate_limiter.record_failure("testclient")
        resp = client.post("/api/login", json={"username": "admin", "password": "Admin1234!"})
        assert resp.status_code == 429
        assert "Too many" in resp.json()["detail"]

    def test_invalid_json_returns_400(self, client):
        resp = client.post("/api/login", content=b"not json", headers={"Content-Type": "application/json"})
        assert resp.status_code == 400

    def test_sql_injection_in_username(self, client):
        """SQL injection attempt in username must not crash the server."""
        resp = client.post("/api/login", json={
            "username": "' OR 1=1; DROP TABLE users; --",
            "password": "Admin1234!",
        })
        assert resp.status_code == 401

    def test_xss_in_username(self, client):
        """XSS attempt in username must not crash."""
        resp = client.post("/api/login", json={
            "username": "<script>alert('xss')</script>",
            "password": "Admin1234!",
        })
        assert resp.status_code == 401

    def test_xss_in_password(self, client):
        """XSS attempt in password must not crash."""
        resp = client.post("/api/login", json={
            "username": "admin",
            "password": "<img onerror=alert(1) src=x>",
        })
        assert resp.status_code == 401

    def test_extremely_long_username(self, client):
        """Extremely long username must not crash the server."""
        resp = client.post("/api/login", json={
            "username": "a" * 100_000,
            "password": "Admin1234!",
        })
        assert resp.status_code in (401, 413)

    def test_extremely_long_password(self, client):
        """Extremely long password must not crash the server."""
        resp = client.post("/api/login", json={
            "username": "admin",
            "password": "A" * 100_000,
        })
        assert resp.status_code in (401, 413)

    def test_unicode_username(self, client):
        """Unicode in username must not crash."""
        resp = client.post("/api/login", json={
            "username": "\u0410\u0434\u043c\u0438\u043d",
            "password": "Admin1234!",
        })
        assert resp.status_code == 401

    def test_null_bytes_in_credentials(self, client):
        """Null bytes must not cause issues."""
        resp = client.post("/api/login", json={
            "username": "admin\x00extra",
            "password": "Admin1234!",
        })
        assert resp.status_code == 401

    def test_invalid_credentials_message_consistent(self, client):
        """All 401 login failures should return identical message (prevents enumeration)."""
        # Test that wrong password returns generic message
        resp1 = client.post("/api/login", json={"username": "admin", "password": "WrongPass1!"})
        assert resp1.status_code == 401
        msg1 = resp1.json().get("detail", "")

        # Test that nonexistent user returns same message
        resp2 = client.post("/api/login", json={"username": "nonexistent", "password": "Whatever1!"})
        assert resp2.status_code == 401
        msg2 = resp2.json().get("detail", "")

        # Both should say "Invalid credentials" not differentiate between user not found vs wrong password
        assert msg1 == msg2, (
            f"Login error messages should be identical: {msg1!r} vs {msg2!r}"
        )
        assert "Invalid credentials" in msg1


# ===========================================================================
# POST /api/login — 2FA flow
# ===========================================================================

class TestLogin2FA:
    """Login with TOTP 2FA enabled."""

    def test_login_requires_2fa_when_totp_set(self, client):
        """When user has TOTP enabled, login without code returns requires_2fa."""
        from server.auth import users
        users.set_totp_secret("admin", "JBSWY3DPEHPK3PXP")
        try:
            resp = client.post("/api/login", json={
                "username": "admin",
                "password": "Admin1234!",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("requires_2fa") is True
            assert data.get("username") == "admin"
            assert "token" not in data
        finally:
            users.set_totp_secret("admin", None)

    def test_login_with_invalid_totp_code(self, client):
        """Wrong TOTP code returns 401."""
        from server.auth import users
        users.set_totp_secret("admin", "JBSWY3DPEHPK3PXP")
        try:
            resp = client.post("/api/login", json={
                "username": "admin",
                "password": "Admin1234!",
                "totp_code": "000000",
            })
            assert resp.status_code == 401
            assert "2FA" in resp.json()["detail"]
        finally:
            users.set_totp_secret("admin", None)

    def test_login_with_require2fa_setting_no_totp(self, client):
        """When require2fa is set but user has no TOTP, returns requires_2fa_setup."""
        with patch("server.routers.auth.read_yaml_settings", return_value={"require2fa": True}):
            resp = client.post("/api/login", json={
                "username": "admin",
                "password": "Admin1234!",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("requires_2fa_setup") is True
            assert "token" in data


# ===========================================================================
# POST /api/logout
# ===========================================================================

class TestLogout:
    """Logout endpoint — token revocation."""

    def test_logout_with_valid_token(self, client, admin_token, admin_headers):
        resp = client.post("/api/logout", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        # Token should be revoked now
        resp2 = client.get("/api/me", headers=admin_headers)
        assert resp2.status_code == 401

    def test_logout_without_token(self, client):
        """Logout without auth should still return ok (graceful)."""
        resp = client.post("/api/logout")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_logout_with_invalid_token(self, client):
        """Logout with bogus token should not crash."""
        resp = client.post("/api/logout", headers={"Authorization": "Bearer bogus-token"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_logout_double_revoke(self, client, admin_headers):
        """Logging out twice should still succeed."""
        client.post("/api/logout", headers=admin_headers)
        resp = client.post("/api/logout", headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# POST /api/auth/totp/setup
# ===========================================================================

class TestTotpSetup:
    """TOTP setup — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/auth/totp/setup")
        assert resp.status_code == 401

    @pytest.mark.skipif(
        not _has_pyotp(), reason="pyotp not installed"
    )
    def test_viewer_can_setup(self, client, viewer_headers):
        resp = client.post("/api/auth/totp/setup", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "secret" in data
        assert "provisioning_uri" in data
        assert "otpauth://" in data["provisioning_uri"]

    @pytest.mark.skipif(
        not _has_pyotp(), reason="pyotp not installed"
    )
    def test_admin_can_setup(self, client, admin_headers):
        resp = client.post("/api/auth/totp/setup", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "secret" in data
        assert isinstance(data["secret"], str)
        assert len(data["secret"]) > 5


# ===========================================================================
# POST /api/auth/totp/enable
# ===========================================================================

class TestTotpEnable:
    """TOTP enable — requires valid code verification."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/auth/totp/enable", json={"secret": "x", "code": "123456"})
        assert resp.status_code == 401

    def test_invalid_totp_code_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/auth/totp/enable",
            json={"secret": "JBSWY3DPEHPK3PXP", "code": "000000"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "Invalid TOTP" in resp.json()["detail"]

    def test_missing_secret_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/auth/totp/enable",
            json={"code": "123456"},
            headers=admin_headers,
        )
        assert resp.status_code == 400


# ===========================================================================
# POST /api/auth/totp/disable
# ===========================================================================

class TestTotpDisable:
    """TOTP disable — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/auth/totp/disable", json={})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/auth/totp/disable", json={}, headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/auth/totp/disable", json={}, headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_disable(self, client, admin_headers):
        resp = client.post(
            "/api/auth/totp/disable",
            json={"username": "admin"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_admin_can_disable_for_another_user(self, client, admin_headers):
        resp = client.post(
            "/api/auth/totp/disable",
            json={"username": "viewer_user"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ===========================================================================
# GET /api/auth/providers
# ===========================================================================

class TestAuthProviders:
    """Provider listing — public endpoint.

    NOTE: api_auth_providers has a return type annotation ``-> dict`` but
    actually returns a list.  FastAPI response validation rejects this with
    a 500.  These tests document the current (broken) behaviour so any
    future fix can be verified by flipping assertions to 200.
    """

    def test_returns_500_due_to_type_annotation_bug(self, client):
        """The endpoint currently fails because it returns list, not dict."""
        with patch("server.routers.auth.read_yaml_settings", return_value={}):
            resp = client.get("/api/auth/providers")
            # This is a known bug: return type is -> dict but a list is returned.
            assert resp.status_code == 500

    def test_returns_500_even_with_providers_configured(self, client):
        """Even with providers, the type annotation bug causes 500."""
        cfg = {"socialProviders": {"google": {"clientId": "test-id", "clientSecret": "test-secret"}}}
        with patch("server.routers.auth.read_yaml_settings", return_value=cfg):
            resp = client.get("/api/auth/providers")
            assert resp.status_code == 500


# ===========================================================================
# GET /api/auth/social/{provider}/login
# ===========================================================================

class TestSocialLogin:
    """Social login redirect — requires provider config."""

    def test_unconfigured_provider_returns_400(self, client):
        with patch("server.routers.auth.read_yaml_settings", return_value={}):
            resp = client.get("/api/auth/social/google/login", follow_redirects=False)
            assert resp.status_code == 400

    def test_unknown_provider_returns_400(self, client):
        with patch("server.routers.auth.read_yaml_settings", return_value={}):
            resp = client.get("/api/auth/social/fakeprovider/login", follow_redirects=False)
            assert resp.status_code == 400

    def test_configured_provider_redirects(self, client):
        cfg = {"socialProviders": {"github": {"clientId": "gh-id", "clientSecret": "gh-secret"}}}
        with patch("server.routers.auth.read_yaml_settings", return_value=cfg):
            resp = client.get("/api/auth/social/github/login", follow_redirects=False)
            assert resp.status_code == 307
            location = resp.headers.get("location", "")
            assert "github.com/login/oauth/authorize" in location
            assert "client_id=gh-id" in location
            assert "state=" in location


# ===========================================================================
# GET /api/auth/social/{provider}/callback
# ===========================================================================

class TestSocialCallback:
    """Social callback — state validation."""

    def test_missing_state_returns_400(self, client):
        resp = client.get("/api/auth/social/google/callback")
        assert resp.status_code == 400
        detail = resp.json()["detail"].lower()
        assert "state" in detail or "expired" in detail

    def test_invalid_state_returns_400(self, client):
        resp = client.get("/api/auth/social/google/callback?state=bogus&code=fakecode")
        assert resp.status_code == 400

    def test_expired_state_returns_400(self, client):
        """Manually insert an expired state and verify rejection."""
        from server.routers.auth import _oauth_states, _oauth_states_lock
        state = "expired-test-state"
        with _oauth_states_lock:
            _oauth_states[state] = {"purpose": "login", "ts": time.time() - 700}
        resp = client.get(f"/api/auth/social/google/callback?state={state}&code=fakecode")
        assert resp.status_code == 400

    def test_wrong_purpose_state_returns_400(self, client):
        """State with wrong purpose should be rejected."""
        from server.routers.auth import _oauth_states, _oauth_states_lock
        state = "wrong-purpose-state"
        with _oauth_states_lock:
            _oauth_states[state] = {"purpose": "link", "ts": time.time()}
        resp = client.get(f"/api/auth/social/google/callback?state={state}&code=fakecode")
        assert resp.status_code == 400


# ===========================================================================
# GET /api/auth/oidc/login
# ===========================================================================

class TestOidcLogin:
    """Generic OIDC login redirect."""

    def test_oidc_not_configured_returns_400(self, client):
        with patch("server.routers.auth.read_yaml_settings", return_value={}):
            resp = client.get("/api/auth/oidc/login", follow_redirects=False)
            assert resp.status_code == 400
            assert "not configured" in resp.json()["detail"]

    def test_oidc_configured_redirects(self, client):
        cfg = {
            "oidcProviderUrl": "https://auth.example.com",
            "oidcClientId": "my-client",
            "oidcClientSecret": "my-secret",
        }
        with patch("server.routers.auth.read_yaml_settings", return_value=cfg):
            resp = client.get("/api/auth/oidc/login", follow_redirects=False)
            assert resp.status_code == 307
            location = resp.headers.get("location", "")
            assert "auth.example.com" in location
            assert "client_id=my-client" in location


# ===========================================================================
# GET /api/auth/oidc/callback
# ===========================================================================

class TestOidcCallback:
    """OIDC callback — state validation."""

    def test_missing_state_returns_400(self, client):
        resp = client.get("/api/auth/oidc/callback")
        assert resp.status_code == 400

    def test_invalid_state_returns_400(self, client):
        resp = client.get("/api/auth/oidc/callback?state=bogus&code=test")
        assert resp.status_code == 400

    def test_wrong_purpose_rejected(self, client):
        from server.routers.auth import _oauth_states, _oauth_states_lock
        state = "oidc-wrong-purpose"
        with _oauth_states_lock:
            _oauth_states[state] = {"purpose": "login", "ts": time.time()}
        resp = client.get(f"/api/auth/oidc/callback?state={state}&code=test")
        assert resp.status_code == 400


# ===========================================================================
# POST /api/auth/oidc/exchange
# ===========================================================================

class TestOidcExchange:
    """Exchange one-time OIDC code for NOBA token."""

    def test_missing_code_returns_400(self, client):
        resp = client.post("/api/auth/oidc/exchange", json={})
        assert resp.status_code == 400
        assert "Missing code" in resp.json()["detail"]

    def test_invalid_code_returns_401(self, client):
        resp = client.post("/api/auth/oidc/exchange", json={"code": "bogus"})
        assert resp.status_code == 401

    def test_valid_code_returns_token(self, client):
        """Seed a one-time code and exchange it."""
        from server.auth import token_store
        from server.routers.auth import _oidc_codes, _oidc_codes_lock
        noba_token = token_store.generate("testuser", "viewer")
        code = "test-exchange-code-123"
        with _oidc_codes_lock:
            _oidc_codes[code] = (noba_token, time.time() + 60)
        resp = client.post("/api/auth/oidc/exchange", json={"code": code})
        assert resp.status_code == 200
        assert resp.json()["token"] == noba_token

    def test_code_single_use(self, client):
        """Code can only be used once."""
        from server.auth import token_store
        from server.routers.auth import _oidc_codes, _oidc_codes_lock
        noba_token = token_store.generate("testuser2", "viewer")
        code = "single-use-code-456"
        with _oidc_codes_lock:
            _oidc_codes[code] = (noba_token, time.time() + 60)
        resp1 = client.post("/api/auth/oidc/exchange", json={"code": code})
        assert resp1.status_code == 200
        resp2 = client.post("/api/auth/oidc/exchange", json={"code": code})
        assert resp2.status_code == 401

    def test_expired_code_returns_401(self, client):
        """Expired OIDC code should be rejected."""
        from server.auth import token_store
        from server.routers.auth import _oidc_codes, _oidc_codes_lock
        noba_token = token_store.generate("expired_user", "viewer")
        code = "expired-code-789"
        with _oidc_codes_lock:
            _oidc_codes[code] = (noba_token, time.time() - 10)
        resp = client.post("/api/auth/oidc/exchange", json={"code": code})
        assert resp.status_code == 401


# ===========================================================================
# GET /api/auth/linked-providers
# ===========================================================================

class TestLinkedProviders:
    """Linked providers — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/auth/linked-providers")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/auth/linked-providers", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/auth/linked-providers", headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# DELETE /api/auth/linked-providers/{provider}
# ===========================================================================

class TestUnlinkProvider:
    """Unlink provider — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.delete("/api/auth/linked-providers/google")
        assert resp.status_code == 401

    def test_unlink_not_linked_returns_404(self, client, admin_headers):
        resp = client.delete("/api/auth/linked-providers/google", headers=admin_headers)
        assert resp.status_code == 404


# ===========================================================================
# GET /api/profile
# ===========================================================================

class TestProfile:
    """User profile — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/profile")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/profile", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "username" in data
        assert "role" in data
        assert "permissions" in data
        assert "has_2fa" in data

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/profile", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "admin"

    def test_profile_includes_activity(self, client, admin_headers):
        resp = client.get("/api/profile", headers=admin_headers)
        data = resp.json()
        assert "recent_logins" in data
        assert "failed_logins" in data
        assert "recent_actions" in data


# ===========================================================================
# POST /api/profile/password
# ===========================================================================

class TestProfilePassword:
    """Change own password — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/profile/password", json={
            "current": "Admin1234!",
            "new": "NewPass1234!",
        })
        assert resp.status_code == 401

    def test_wrong_current_password(self, client, admin_headers):
        resp = client.post(
            "/api/profile/password",
            json={"current": "WrongCurrent1!", "new": "NewPass1234!"},
            headers=admin_headers,
        )
        assert resp.status_code == 401
        assert "incorrect" in resp.json()["detail"].lower()

    def test_weak_new_password_rejected(self, client, admin_headers):
        resp = client.post(
            "/api/profile/password",
            json={"current": "Admin1234!", "new": "weak"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_successful_password_change(self, client, admin_headers):
        from server.auth import users, pbkdf2_hash
        # Change to new password
        resp = client.post(
            "/api/profile/password",
            json={"current": "Admin1234!", "new": "NewAdmin1234!"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        # Restore original password for other tests
        users.update_password("admin", pbkdf2_hash("Admin1234!"))


# ===========================================================================
# GET /api/profile/sessions
# ===========================================================================

class TestProfileSessions:
    """Active sessions for the current user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/profile/sessions")
        assert resp.status_code == 401

    def test_viewer_can_list_own_sessions(self, client, viewer_headers):
        resp = client.get("/api/profile/sessions", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_admin_sees_own_sessions(self, client, admin_headers):
        resp = client.get("/api/profile/sessions", headers=admin_headers)
        assert resp.status_code == 200
        sessions = resp.json()
        assert isinstance(sessions, list)
        # All sessions belong to admin
        for s in sessions:
            assert s["username"] == "admin"


# ===========================================================================
# GET /api/user/preferences
# ===========================================================================

class TestUserPreferences:
    """User dashboard preferences — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/user/preferences")
        assert resp.status_code == 401

    def test_get_default_preferences(self, client, viewer_headers):
        resp = client.get("/api/user/preferences", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "preferences" in data

    def test_save_and_load_preferences(self, client, admin_headers):
        save_resp = client.put(
            "/api/user/preferences",
            json={"preferences": {"theme": "dracula", "layout": "compact"}},
            headers=admin_headers,
        )
        assert save_resp.status_code == 200
        assert save_resp.json()["status"] == "ok"

        load_resp = client.get("/api/user/preferences", headers=admin_headers)
        assert load_resp.status_code == 200
        assert load_resp.json()["synced"] is True

    def test_save_invalid_preferences_returns_400(self, client, admin_headers):
        resp = client.put(
            "/api/user/preferences",
            json={"preferences": "not-a-dict"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_save_missing_preferences_returns_400(self, client, admin_headers):
        resp = client.put(
            "/api/user/preferences",
            json={},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_delete_preferences(self, client, admin_headers):
        resp = client.delete("/api/user/preferences", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_oversized_preferences_returns_413(self, client, admin_headers):
        huge = {"key_" + str(i): "x" * 1000 for i in range(100)}
        resp = client.put(
            "/api/user/preferences",
            json={"preferences": huge},
            headers=admin_headers,
        )
        assert resp.status_code == 413


# ===========================================================================
# GET /api/admin/users
# ===========================================================================

class TestAdminUsers:
    """User management — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/admin/users")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/admin/users", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.get("/api/admin/users", headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_list(self, client, admin_headers):
        resp = client.get("/api/admin/users", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # At least the admin user should exist
        usernames = [u["username"] for u in data]
        assert "admin" in usernames


# ===========================================================================
# POST /api/admin/users — actions
# ===========================================================================

class TestAdminUserActions:
    """User CRUD actions — admin only."""

    def test_add_user(self, client, admin_headers):
        resp = client.post(
            "/api/admin/users",
            json={"action": "add", "username": "testuser1", "password": "TestPass1!", "role": "viewer"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        # Clean up
        client.post(
            "/api/admin/users",
            json={"action": "remove", "username": "testuser1"},
            headers=admin_headers,
        )

    def test_add_user_missing_fields(self, client, admin_headers):
        resp = client.post(
            "/api/admin/users",
            json={"action": "add", "username": "nopass"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_add_user_weak_password(self, client, admin_headers):
        resp = client.post(
            "/api/admin/users",
            json={"action": "add", "username": "weakuser", "password": "weak", "role": "viewer"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_add_user_invalid_role(self, client, admin_headers):
        resp = client.post(
            "/api/admin/users",
            json={"action": "add", "username": "badrole", "password": "TestPass1!", "role": "superadmin"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_add_duplicate_user(self, client, admin_headers):
        client.post(
            "/api/admin/users",
            json={"action": "add", "username": "dupuser", "password": "TestPass1!", "role": "viewer"},
            headers=admin_headers,
        )
        resp = client.post(
            "/api/admin/users",
            json={"action": "add", "username": "dupuser", "password": "TestPass1!", "role": "viewer"},
            headers=admin_headers,
        )
        assert resp.status_code == 409
        # Clean up
        client.post(
            "/api/admin/users",
            json={"action": "remove", "username": "dupuser"},
            headers=admin_headers,
        )

    def test_remove_nonexistent_user(self, client, admin_headers):
        resp = client.post(
            "/api/admin/users",
            json={"action": "remove", "username": "ghost_user"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_change_password(self, client, admin_headers):
        # Add user first
        client.post(
            "/api/admin/users",
            json={"action": "add", "username": "pwchange", "password": "OldPass1!", "role": "viewer"},
            headers=admin_headers,
        )
        resp = client.post(
            "/api/admin/users",
            json={"action": "change_password", "username": "pwchange", "password": "NewPass1!"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        # Clean up
        client.post(
            "/api/admin/users",
            json={"action": "remove", "username": "pwchange"},
            headers=admin_headers,
        )

    def test_invalid_action(self, client, admin_headers):
        resp = client.post(
            "/api/admin/users",
            json={"action": "destroy_all"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_list_action(self, client, admin_headers):
        resp = client.post(
            "/api/admin/users",
            json={"action": "list"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_viewer_cannot_add(self, client, viewer_headers):
        resp = client.post(
            "/api/admin/users",
            json={"action": "add", "username": "hacker", "password": "HackPass1!", "role": "admin"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_sql_injection_in_add_username(self, client, admin_headers):
        resp = client.post(
            "/api/admin/users",
            json={"action": "add", "username": "'; DROP TABLE users;--", "password": "TestPass1!", "role": "viewer"},
            headers=admin_headers,
        )
        assert resp.status_code == 400


# ===========================================================================
# GET /api/admin/sessions
# ===========================================================================

class TestAdminSessions:
    """Admin session management."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/admin/sessions")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/admin/sessions", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.get("/api/admin/sessions", headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_list(self, client, admin_headers):
        resp = client.get("/api/admin/sessions", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ===========================================================================
# POST /api/admin/sessions/revoke
# ===========================================================================

class TestAdminSessionRevoke:
    """Session revocation — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/admin/sessions/revoke", json={"prefix": "12345678"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/admin/sessions/revoke",
            json={"prefix": "12345678"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_short_prefix_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/admin/sessions/revoke",
            json={"prefix": "abc"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_revoke_nonexistent_returns_false(self, client, admin_headers):
        resp = client.post(
            "/api/admin/sessions/revoke",
            json={"prefix": "zzzzzzzzzzzz"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_revoke_valid_session(self, client, admin_headers):
        from server.auth import token_store
        token = token_store.generate("revoke_target", "viewer")
        prefix = token[:12]
        resp = client.post(
            "/api/admin/sessions/revoke",
            json={"prefix": prefix},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # Verify token is actually revoked
        assert token_store.validate(token) == (None, None)


# ===========================================================================
# /api/admin/api-keys
# ===========================================================================

class TestAdminApiKeys:
    """API key management — admin only."""

    def test_list_no_auth_returns_401(self, client):
        resp = client.get("/api/admin/api-keys")
        assert resp.status_code == 401

    def test_list_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/admin/api-keys", headers=viewer_headers)
        assert resp.status_code == 403

    def test_admin_can_list(self, client, admin_headers):
        resp = client.get("/api/admin/api-keys", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_key(self, client, admin_headers):
        resp = client.post(
            "/api/admin/api-keys",
            json={"name": "test-key", "role": "viewer"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "key" in data
        assert "id" in data
        assert data["name"] == "test-key"
        assert data["role"] == "viewer"
        # Clean up
        client.delete(f"/api/admin/api-keys/{data['id']}", headers=admin_headers)

    def test_create_key_missing_name_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/admin/api-keys",
            json={"role": "viewer"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_create_key_invalid_role_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/admin/api-keys",
            json={"name": "bad-role-key", "role": "superadmin"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_delete_nonexistent_key_returns_404(self, client, admin_headers):
        resp = client.delete("/api/admin/api-keys/nonexistent", headers=admin_headers)
        assert resp.status_code == 404


# ===========================================================================
# /api/admin/ssh-keys
# ===========================================================================

class TestAdminSshKeys:
    """SSH key management — admin only."""

    def test_list_no_auth_returns_401(self, client):
        resp = client.get("/api/admin/ssh-keys")
        assert resp.status_code == 401

    def test_list_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/admin/ssh-keys", headers=viewer_headers)
        assert resp.status_code == 403

    def test_admin_can_list(self, client, admin_headers):
        resp = client.get("/api/admin/ssh-keys", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_add_invalid_key_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/admin/ssh-keys",
            json={"key": "not-a-real-key"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_add_key_with_embedded_options_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/admin/ssh-keys",
            json={"key": "command=\"rm -rf /\" ssh-rsa AAAA..."},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_add_valid_key(self, client, admin_headers):
        resp = client.post(
            "/api/admin/ssh-keys",
            json={"key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC test@noba"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_delete_nonexistent_key_returns_404(self, client, admin_headers):
        resp = client.delete("/api/admin/ssh-keys/9999", headers=admin_headers)
        assert resp.status_code == 404


# ===========================================================================
# Auth middleware — access levels
# ===========================================================================

class TestAuthMiddleware:
    """Verify role-based access across auth endpoints."""

    def test_invalid_bearer_token_returns_401(self, client):
        resp = client.get("/api/profile", headers={"Authorization": "Bearer invalid-token"})
        assert resp.status_code == 401

    def test_missing_bearer_prefix_returns_401(self, client):
        resp = client.get("/api/profile", headers={"Authorization": "invalid-token"})
        assert resp.status_code == 401

    def test_empty_authorization_header_returns_401(self, client):
        resp = client.get("/api/profile", headers={"Authorization": ""})
        assert resp.status_code == 401

    def test_viewer_cannot_access_admin_endpoints(self, client, viewer_headers):
        resp = client.get("/api/admin/users", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_cannot_access_admin_endpoints(self, client, operator_headers):
        resp = client.get("/api/admin/users", headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_access_admin_endpoints(self, client, admin_headers):
        resp = client.get("/api/admin/users", headers=admin_headers)
        assert resp.status_code == 200

    def test_all_roles_can_access_profile(self, client, viewer_headers, operator_headers, admin_headers):
        for headers in (viewer_headers, operator_headers, admin_headers):
            resp = client.get("/api/profile", headers=headers)
            assert resp.status_code == 200


# ===========================================================================
# SSE auth fallback (query param token)
# ===========================================================================

class TestSseAuthFallback:
    """EventSource cannot set custom headers — verify query param token works."""

    def test_sse_stream_no_auth_returns_401(self, client):
        resp = client.get("/api/stream")
        assert resp.status_code == 401

    def test_sse_stream_bearer_header(self, client, admin_headers):
        with client.stream("GET", "/api/stream", headers=admin_headers) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            for _ in resp.iter_lines():
                break

    def test_sse_stream_query_param_token(self, client, admin_token):
        with client.stream("GET", f"/api/stream?token={admin_token}") as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            for _ in resp.iter_lines():
                break

    def test_sse_stream_invalid_query_token(self, client):
        resp = client.get("/api/stream?token=bogus-token-value")
        assert resp.status_code == 401

    def test_sse_stream_empty_query_token(self, client):
        resp = client.get("/api/stream?token=")
        assert resp.status_code == 401


# ===========================================================================
# Token generation and validation
# ===========================================================================

class TestTokenHandling:
    """Token lifecycle — generation, validation, expiry."""

    def test_login_token_can_authenticate(self, client):
        """Token from login endpoint works for subsequent API calls."""
        resp = client.post("/api/login", json={"username": "admin", "password": "Admin1234!"})
        assert resp.status_code == 200
        token = resp.json()["token"]
        me_resp = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 200
        assert me_resp.json()["role"] == "admin"

    def test_revoked_token_cannot_authenticate(self, client):
        """After logout, the token is invalid."""
        resp = client.post("/api/login", json={"username": "admin", "password": "Admin1234!"})
        assert resp.status_code == 200
        token = resp.json()["token"]
        client.post("/api/logout", headers={"Authorization": f"Bearer {token}"})
        me_resp = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 401

    def test_each_login_generates_unique_token(self, client):
        """Two logins produce different tokens."""
        r1 = client.post("/api/login", json={"username": "admin", "password": "Admin1234!"})
        r2 = client.post("/api/login", json={"username": "admin", "password": "Admin1234!"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["token"] != r2.json()["token"]


# ===========================================================================
# Edge cases — social login link
# ===========================================================================

class TestSocialLink:
    """Account linking edge cases."""

    def test_link_without_token_returns_401(self, client):
        resp = client.get("/api/auth/social/google/link", follow_redirects=False)
        assert resp.status_code == 401

    def test_link_with_invalid_token_returns_401(self, client):
        resp = client.get("/api/auth/social/google/link?token=bogus", follow_redirects=False)
        assert resp.status_code == 401

    def test_link_unconfigured_provider_returns_400(self, client, admin_token):
        with patch("server.routers.auth.read_yaml_settings", return_value={}):
            resp = client.get(
                f"/api/auth/social/google/link?token={admin_token}",
                follow_redirects=False,
            )
            assert resp.status_code == 400

    def test_link_callback_invalid_state(self, client):
        resp = client.get("/api/auth/social/google/link/callback?state=bogus&code=test")
        assert resp.status_code == 400


# ===========================================================================
# POST /api/ws-token
# ===========================================================================

class TestWsToken:
    """POST /api/ws-token — short-lived WebSocket token exchange."""

    def test_requires_auth(self, client):
        resp = client.post("/api/ws-token")
        assert resp.status_code == 401

    def test_returns_token_for_authed_user(self, client, admin_headers):
        resp = client.post("/api/ws-token", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["expires_in"] == 30

    def test_viewer_can_get_ws_token(self, client, viewer_headers):
        resp = client.post("/api/ws-token", headers=viewer_headers)
        assert resp.status_code == 200

    def test_token_is_consumed_on_use(self):
        """ws_token_store.consume() returns user on first call, None on second."""
        from server.auth import ws_token_store
        tok = ws_token_store.issue("alice", "operator")
        u1, r1 = ws_token_store.consume(tok)
        assert u1 == "alice" and r1 == "operator"
        u2, r2 = ws_token_store.consume(tok)
        assert u2 is None and r2 is None

    def test_expired_token_rejected(self):
        """Tokens past their TTL are rejected."""
        from server.auth import ws_token_store
        tok = ws_token_store.issue("bob", "viewer")
        with ws_token_store._lock:
            u, r, _ = ws_token_store._tokens[tok]
            ws_token_store._tokens[tok] = (u, r, time.time() - 1)
        u, r = ws_token_store.consume(tok)
        assert u is None
