# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the new auth features (TOTP, IP whitelist, API key auth, per-user rate limit)."""
from __future__ import annotations

import pytest


class TestTotpHelpers:
    def test_generate_totp_secret(self):
        from server.auth import generate_totp_secret
        try:
            import pyotp  # noqa: F401
        except ImportError:
            with pytest.raises(RuntimeError, match="pyotp"):
                generate_totp_secret()
            return
        secret = generate_totp_secret()
        assert isinstance(secret, str)
        assert len(secret) > 10

    def test_verify_totp_bad_code(self):
        from server.auth import verify_totp
        assert verify_totp("JBSWY3DPEHPK3PXP", "000000") is False

    def test_verify_totp_no_pyotp(self):
        # If pyotp is not installed, should return False gracefully
        from server.auth import verify_totp
        result = verify_totp("secret", "123456")
        assert isinstance(result, bool)


class TestIpWhitelist:
    def test_empty_whitelist_allows_all(self):
        from server.auth import check_ip_whitelist
        assert check_ip_whitelist("1.2.3.4", lambda: {}) is True
        assert check_ip_whitelist("1.2.3.4", lambda: {"ipWhitelist": ""}) is True

    def test_whitelist_allows_listed_ip(self):
        from server.auth import check_ip_whitelist
        assert check_ip_whitelist("1.2.3.4", lambda: {"ipWhitelist": "1.2.3.4, 5.6.7.8"}) is True

    def test_whitelist_blocks_unlisted_ip(self):
        from server.auth import check_ip_whitelist
        assert check_ip_whitelist("9.9.9.9", lambda: {"ipWhitelist": "1.2.3.4, 5.6.7.8"}) is False


class TestApiKeyAuth:
    def test_authenticate_with_api_key(self):
        from server.auth import authenticate
        # This will fail because no key exists in DB, but it should not crash
        result = authenticate("ApiKey some_key_here")
        assert result == (None, None)  # No key in DB

    def test_authenticate_with_bearer(self):
        from server.auth import authenticate
        result = authenticate("Bearer invalid_token")
        assert result == (None, None)


class TestPerUserRateLimit:
    def test_record_failure_user(self):
        from server.auth import RateLimiter
        rl = RateLimiter(max_attempts=3, window_s=60, lockout_s=300)
        assert rl.record_failure_user("1.2.3.4", "testuser") is False
        assert rl.record_failure_user("1.2.3.4", "testuser") is False
        # Third attempt should lock
        locked = rl.record_failure_user("1.2.3.4", "testuser")
        # Either IP or user should be locked after 3 attempts
        assert rl.is_locked("1.2.3.4") or locked


class TestUserStoreTotp:
    def test_has_totp_default_false(self):
        from server.auth import users
        # Default user shouldn't have TOTP
        assert users.has_totp("nonexistent_user") is False
