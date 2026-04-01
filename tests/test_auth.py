"""Tests for auth module: passwords, tokens, rate limiting, user store."""
import hashlib
import secrets
from datetime import datetime, timedelta
from unittest import mock

from server.auth import (
    pbkdf2_hash, verify_password, valid_username, check_password_strength,
    TokenStore, RateLimiter,
)


# ── Password hashing ────────────────────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_format(self):
        h = pbkdf2_hash("password123")
        parts = h.split(":")
        assert parts[0] == "pbkdf2"
        assert len(parts) == 4  # pbkdf2:iterations:salt:hash
        assert parts[1] == "600000"
        assert len(parts[2]) == 32  # 16 bytes hex

    def test_verify_correct(self):
        h = pbkdf2_hash("MySuperSecret1!")
        assert verify_password(h, "MySuperSecret1!")

    def test_verify_wrong(self):
        h = pbkdf2_hash("MySuperSecret1!")
        assert not verify_password(h, "WrongPassword")

    def test_verify_empty_stored(self):
        assert not verify_password("", "anything")

    def test_verify_legacy_sha256(self):
        salt = secrets.token_hex(8)
        pw = "legacypass"
        h = hashlib.sha256((salt + pw).encode()).hexdigest()
        stored = f"{salt}:{h}"
        assert verify_password(stored, pw)
        assert not verify_password(stored, "wrongpass")

    def test_hashes_are_unique(self):
        h1 = pbkdf2_hash("SamePass1!")
        h2 = pbkdf2_hash("SamePass1!")
        assert h1 != h2

    def test_explicit_salt_deterministic(self):
        h1 = pbkdf2_hash("Pass1!", salt="deadsalt")
        h2 = pbkdf2_hash("Pass1!", salt="deadsalt")
        assert h1 == h2

    def test_verify_legacy_3part_pbkdf2(self):
        """Legacy 3-part format (pbkdf2:salt:hash) with 200k iterations still verifies."""
        salt = secrets.token_hex(16)
        pw = "LegacyPbkdf2Pass1!"
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000)
        stored = f"pbkdf2:{salt}:{dk.hex()}"
        assert verify_password(stored, pw)
        assert not verify_password(stored, "WrongPassword")

    def test_verify_new_4part_format(self):
        """New 4-part format (pbkdf2:iters:salt:hash) verifies correctly."""
        h = pbkdf2_hash("NewFormat1!")
        assert verify_password(h, "NewFormat1!")
        assert not verify_password(h, "WrongPassword")

    def test_auto_upgrade_legacy_pbkdf2(self):
        """Legacy 3-part hash (200k iters) is upgraded to 4-part (600k) on login."""
        import server.auth as auth_module

        salt = secrets.token_hex(16)
        pw = "UpgradeMe1!"
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000)
        stored = f"pbkdf2:{salt}:{dk.hex()}"

        with mock.patch.object(auth_module.users, "update_password") as mock_update:
            result = verify_password(stored, pw, username="testuser")

        assert result is True
        mock_update.assert_called_once()
        call_args = mock_update.call_args
        assert call_args[0][0] == "testuser"
        upgraded_hash = call_args[0][1]
        parts = upgraded_hash.split(":", 3)
        assert len(parts) == 4
        assert parts[0] == "pbkdf2"
        assert parts[1] == "600000"

    def test_malformed_iters_returns_false(self):
        """Non-integer iteration count in stored hash returns False without crashing."""
        stored = "pbkdf2:notanumber:somesalt:somehash"
        assert verify_password(stored, "anypassword") is False


# ── Password strength ───────────────────────────────────────────────────────

class TestPasswordStrength:
    def test_too_short(self):
        err = check_password_strength("Ab1!")
        assert err and "8" in err

    def test_no_uppercase(self):
        err = check_password_strength("password1!")
        assert err and "uppercase" in err

    def test_no_digit_or_symbol(self):
        assert check_password_strength("Passwordonly") is not None

    def test_valid(self):
        assert check_password_strength("MyPass1!") is None
        assert check_password_strength("Secure123") is None

    def test_boundary_length(self):
        assert check_password_strength("Abc12345") is None  # exactly 8
        assert check_password_strength("Abc1234") is not None  # 7


# ── Username validation ─────────────────────────────────────────────────────

class TestUsernameValidation:
    def test_valid(self):
        for name in ("admin", "user1", "john.doe", "alice-bob"):
            assert valid_username(name), f"Expected valid: {name}"

    def test_invalid(self):
        for name in ("", " admin", "user:name", "a/b", "a\\b", "a" * 65):
            assert not valid_username(name), f"Expected invalid: {name}"


# ── Token store ──────────────────────────────────────────────────────────────

class TestTokenStore:
    def test_generate_and_validate(self):
        ts = TokenStore()
        token = ts.generate("alice", "admin")
        username, role = ts.validate(token)
        assert username == "alice"
        assert role == "admin"

    def test_invalid_token(self):
        ts = TokenStore()
        username, role = ts.validate("nonexistent")
        assert username is None

    def test_revoke(self):
        ts = TokenStore()
        token = ts.generate("bob", "viewer")
        ts.revoke(token)
        assert ts.validate(token) == (None, None)

    def test_expired_token(self):
        ts = TokenStore()
        token = secrets.token_urlsafe(32)
        ts._tokens[token] = ("alice", "admin", datetime.now() - timedelta(seconds=1))
        assert ts.validate(token) == (None, None)

    def test_list_sessions(self):
        ts = TokenStore()
        ts.generate("alice", "admin")
        ts.generate("bob", "viewer")
        sessions = ts.list_sessions()
        assert len(sessions) == 2
        usernames = {s["username"] for s in sessions}
        assert usernames == {"alice", "bob"}

    def test_revoke_by_prefix(self):
        ts = TokenStore()
        token = ts.generate("alice", "admin")
        prefix = token[:8]
        assert ts.revoke_by_prefix(prefix)
        assert ts.validate(token) == (None, None)

    def test_cleanup_removes_expired(self):
        ts = TokenStore()
        token = secrets.token_urlsafe(32)
        ts._tokens[token] = ("alice", "admin", datetime.now() - timedelta(hours=1))
        ts.cleanup()
        assert token not in ts._tokens


# ── Rate limiter ─────────────────────────────────────────────────────────────

class TestRateLimiter:
    def test_not_locked_initially(self):
        rl = RateLimiter(max_attempts=3, window_s=60, lockout_s=30)
        assert not rl.is_locked("1.2.3.4")

    def test_lockout_after_max(self):
        rl = RateLimiter(max_attempts=3, window_s=60, lockout_s=30)
        for _ in range(3):
            rl.record_failure("1.2.3.4")
        assert rl.is_locked("1.2.3.4")

    def test_reset_clears_lockout(self):
        rl = RateLimiter(max_attempts=2, window_s=60, lockout_s=30)
        rl.record_failure("1.2.3.4")
        rl.record_failure("1.2.3.4")
        assert rl.is_locked("1.2.3.4")
        rl.reset("1.2.3.4")
        assert not rl.is_locked("1.2.3.4")

    def test_independent_ips(self):
        rl = RateLimiter(max_attempts=2, window_s=60, lockout_s=30)
        rl.record_failure("1.1.1.1")
        rl.record_failure("1.1.1.1")
        assert rl.is_locked("1.1.1.1")
        assert not rl.is_locked("2.2.2.2")

    def test_cleanup(self):
        rl = RateLimiter(max_attempts=5, window_s=0, lockout_s=0)
        rl.record_failure("1.1.1.1")
        rl.cleanup()
        # After cleanup with window_s=0, timestamps are stale
        assert not rl._attempts.get("1.1.1.1")


# ── LDAP escaping ───────────────────────────────────────────────────────────

class TestLdapEscape:
    """_ldap_escape covers all RFC 4515 special characters."""

    def test_escapes_backslash(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a\\b") == "a\\5cb"

    def test_escapes_null(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a\x00b") == "a\\00b"

    def test_escapes_star(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a*b") == "a\\2ab"

    def test_escapes_parens(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("(foo)") == "\\28foo\\29"

    def test_escapes_ampersand(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a&b") == "a\\26b"

    def test_escapes_pipe(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a|b") == "a\\7cb"

    def test_escapes_equals(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a=b") == "a\\3db"

    def test_escapes_tilde(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a~b") == "a\\7eb"

    def test_escapes_exclamation(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("a!b") == "a\\21b"

    def test_normal_string_unchanged(self):
        from server.auth import _ldap_escape
        assert _ldap_escape("alice123") == "alice123"

    def test_unicode_encoded(self):
        from server.auth import _ldap_escape
        result = _ldap_escape("caf\u00e9")
        assert "\\c3\\a9" in result
