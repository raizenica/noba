"""
Unit tests for Noba backend (server.py) — core auth, crypto, and utility functions.

Run with:  python3 -m pytest tests/test_server.py -v
           python3 -m unittest tests/test_server.py -v
"""

import hashlib
import os
import secrets
import sys
import tempfile
import threading
import time
import unittest

# ---------------------------------------------------------------------------
# Make the server module importable without actually binding to a port.
# We redirect HOME to a temp directory so the module's path globals
# (USER_DB, HISTORY_DB, etc.) resolve to temp paths on first exec.
# A minimal users.conf is pre-created so load_users() never needs to call
# save_users() before that function is defined (module-level ordering).
# ---------------------------------------------------------------------------
SERVER_PATH = os.path.join(os.path.dirname(__file__), '..', 'share', 'noba-web', 'server.py')

# Redirect home to an isolated temp tree
_tmp_dir = tempfile.mkdtemp(prefix='noba_test_')
_fake_home = os.path.join(_tmp_dir, 'home')
os.makedirs(_fake_home, exist_ok=True)
os.environ['HOME'] = _fake_home

# Also redirect these env-configurable paths
os.environ['NOBA_CONFIG'] = os.path.join(_fake_home, '.config', 'noba', 'config.yaml')
os.environ['PID_FILE']    = os.path.join(_tmp_dir, 'noba.pid')

# Pre-create a minimal users.conf so load_users() reads it and does NOT
# call save_users() (which is defined after load_users() in the module).
_cfg_dir = os.path.join(_fake_home, '.config', 'noba-web')
os.makedirs(_cfg_dir, exist_ok=True)
import hashlib
_salt = 'testsalt'
_dk   = hashlib.pbkdf2_hmac('sha256', b'Admin1234!', _salt.encode(), 200_000)
_prebuilt_hash = f'pbkdf2:{_salt}:{_dk.hex()}'
with open(os.path.join(_cfg_dir, 'users.conf'), 'w') as _f:
    _f.write(f'admin:{_prebuilt_hash}:admin\n')

# Suppress logging output during tests.
import logging
logging.disable(logging.CRITICAL)

import importlib.util
_spec = importlib.util.spec_from_file_location('server', SERVER_PATH)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
class TestPasswordHashing(unittest.TestCase):

    def test_hash_format(self):
        h = server._pbkdf2_hash('password123')
        parts = h.split(':')
        self.assertEqual(parts[0], 'pbkdf2')
        self.assertEqual(len(parts), 3)
        # salt is 32 hex chars (16 bytes)
        self.assertEqual(len(parts[1]), 32)

    def test_verify_correct_password(self):
        h = server._pbkdf2_hash('MySuperSecret1!')
        self.assertTrue(server.verify_password(h, 'MySuperSecret1!'))

    def test_verify_wrong_password(self):
        h = server._pbkdf2_hash('MySuperSecret1!')
        self.assertFalse(server.verify_password(h, 'WrongPassword'))

    def test_verify_empty_stored(self):
        self.assertFalse(server.verify_password('', 'anything'))

    def test_verify_legacy_sha256(self):
        """Legacy auth.conf format: salt:sha256(salt+password)"""
        salt = secrets.token_hex(8)
        pw = 'legacypass'
        h = hashlib.sha256((salt + pw).encode()).hexdigest()
        stored = f"{salt}:{h}"
        self.assertTrue(server.verify_password(stored, pw))
        self.assertFalse(server.verify_password(stored, 'wrongpass'))

    def test_hashes_are_unique(self):
        """Same password must produce different hashes (random salt)."""
        h1 = server._pbkdf2_hash('SamePass1!')
        h2 = server._pbkdf2_hash('SamePass1!')
        self.assertNotEqual(h1, h2)

    def test_hash_with_explicit_salt(self):
        salt = 'deadsalt'
        h1 = server._pbkdf2_hash('Pass1!', salt=salt)
        h2 = server._pbkdf2_hash('Pass1!', salt=salt)
        self.assertEqual(h1, h2)


# ---------------------------------------------------------------------------
# Password strength validator
# ---------------------------------------------------------------------------
class TestPasswordStrength(unittest.TestCase):

    def test_too_short(self):
        err = server._check_password_strength('Ab1!')
        self.assertIsNotNone(err)
        self.assertIn('8', err)

    def test_no_uppercase(self):
        err = server._check_password_strength('password1!')
        self.assertIsNotNone(err)
        self.assertIn('uppercase', err)

    def test_no_digit_or_symbol(self):
        err = server._check_password_strength('Passwordonly')
        self.assertIsNotNone(err)

    def test_valid_password(self):
        self.assertIsNone(server._check_password_strength('MyPass1!'))
        self.assertIsNone(server._check_password_strength('Secure123'))
        self.assertIsNone(server._check_password_strength('V3ryL0ngP@ssphrase'))

    def test_boundary_length(self):
        # Exactly 8 chars with required complexity
        self.assertIsNone(server._check_password_strength('Abc12345'))
        # 7 chars — should fail
        self.assertIsNotNone(server._check_password_strength('Abc1234'))

    def test_unicode_password(self):
        # Unicode chars count toward length and symbol requirement
        err = server._check_password_strength('Sécure1!')
        self.assertIsNone(err)


# ---------------------------------------------------------------------------
# Username validation
# ---------------------------------------------------------------------------
class TestUsernameValidation(unittest.TestCase):

    def test_valid_usernames(self):
        for name in ('admin', 'user1', 'john.doe', 'alice-bob', 'a' * 64):
            self.assertTrue(server._valid_username(name), f"Expected valid: {name}")

    def test_invalid_usernames(self):
        for name in ('', ' admin', 'user:name', 'a/b', 'a\\b', 'a' * 65):
            self.assertFalse(server._valid_username(name), f"Expected invalid: {name}")


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------
class TestTokenManagement(unittest.TestCase):

    def setUp(self):
        # Clear tokens before each test
        with server._tokens_lock:
            server._tokens.clear()

    def test_generate_and_validate(self):
        token = server.generate_token('alice', 'admin')
        username, role = server.validate_token(token)
        self.assertEqual(username, 'alice')
        self.assertEqual(role, 'admin')

    def test_invalid_token_returns_none(self):
        username, role = server.validate_token('nonexistent-token')
        self.assertIsNone(username)
        self.assertIsNone(role)

    def test_revoke_token(self):
        token = server.generate_token('bob', 'viewer')
        server.revoke_token(token)
        username, role = server.validate_token(token)
        self.assertIsNone(username)

    def test_expired_token(self):
        from datetime import datetime, timedelta
        token = secrets.token_urlsafe(32)
        # Insert already-expired token
        with server._tokens_lock:
            server._tokens[token] = ('alice', 'admin', datetime.now() - timedelta(seconds=1))
        username, role = server.validate_token(token)
        self.assertIsNone(username)
        # Expired token should be cleaned up
        with server._tokens_lock:
            self.assertNotIn(token, server._tokens)

    def test_tokens_are_unique(self):
        t1 = server.generate_token('alice', 'admin')
        t2 = server.generate_token('alice', 'admin')
        self.assertNotEqual(t1, t2)


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
class TestLoginRateLimiter(unittest.TestCase):

    def test_not_locked_initially(self):
        limiter = server.LoginRateLimiter(max_attempts=3, window_s=60, lockout_s=30)
        self.assertFalse(limiter.is_locked('1.2.3.4'))

    def test_lockout_after_max_attempts(self):
        limiter = server.LoginRateLimiter(max_attempts=3, window_s=60, lockout_s=30)
        for _ in range(3):
            limiter.record_failure('1.2.3.4')
        self.assertTrue(limiter.is_locked('1.2.3.4'))

    def test_reset_clears_lockout(self):
        limiter = server.LoginRateLimiter(max_attempts=2, window_s=60, lockout_s=30)
        for _ in range(2):
            limiter.record_failure('1.2.3.4')
        self.assertTrue(limiter.is_locked('1.2.3.4'))
        limiter.reset('1.2.3.4')
        self.assertFalse(limiter.is_locked('1.2.3.4'))

    def test_different_ips_are_independent(self):
        limiter = server.LoginRateLimiter(max_attempts=2, window_s=60, lockout_s=30)
        for _ in range(2):
            limiter.record_failure('1.1.1.1')
        self.assertTrue(limiter.is_locked('1.1.1.1'))
        self.assertFalse(limiter.is_locked('2.2.2.2'))


# ---------------------------------------------------------------------------
# TTL cache
# ---------------------------------------------------------------------------
class TestTTLCache(unittest.TestCase):

    def test_miss_returns_none(self):
        cache = server.TTLCache()
        self.assertIsNone(cache.get('missing_key'))

    def test_set_and_get(self):
        cache = server.TTLCache()
        cache.set('key', 'value')
        self.assertEqual(cache.get('key', ttl=60), 'value')

    def test_expired_entry_is_evicted(self):
        cache = server.TTLCache()
        cache.set('key', 'value')
        # TTL of 0 means immediately stale
        result = cache.get('key', ttl=0)
        self.assertIsNone(result)

    def test_max_size_evicts_oldest(self):
        cache = server.TTLCache(max_size=3)
        cache.set('a', 1)
        time.sleep(0.01)
        cache.set('b', 2)
        time.sleep(0.01)
        cache.set('c', 3)
        time.sleep(0.01)
        # Adding a 4th entry should evict 'a' (oldest)
        cache.set('d', 4)
        self.assertIsNone(cache.get('a', ttl=3600))
        self.assertEqual(cache.get('d', ttl=3600), 4)


# ---------------------------------------------------------------------------
# Alert condition evaluator
# ---------------------------------------------------------------------------
class TestSafeEval(unittest.TestCase):

    def _flat(self, **kwargs):
        return {k: float(v) for k, v in kwargs.items()}

    def test_greater_than_true(self):
        self.assertTrue(server._safe_eval('cpu_percent > 90', self._flat(cpu_percent=95)))

    def test_greater_than_false(self):
        self.assertFalse(server._safe_eval('cpu_percent > 90', self._flat(cpu_percent=80)))

    def test_less_than(self):
        self.assertTrue(server._safe_eval('cpu_temp < 70', self._flat(cpu_temp=50)))

    def test_greater_equal(self):
        self.assertTrue(server._safe_eval('disk_percent >= 85', self._flat(disk_percent=85)))

    def test_less_equal(self):
        self.assertTrue(server._safe_eval('mem_percent <= 50', self._flat(mem_percent=50)))

    def test_equal(self):
        self.assertTrue(server._safe_eval('cpu_percent == 100', self._flat(cpu_percent=100)))

    def test_not_equal(self):
        self.assertTrue(server._safe_eval('cpu_percent != 50', self._flat(cpu_percent=75)))

    def test_missing_metric(self):
        self.assertFalse(server._safe_eval('nonexistent > 0', {}))

    def test_invalid_condition_format(self):
        # Should not raise, just return False
        self.assertFalse(server._safe_eval('import os; os.system("evil")', {}))
        self.assertFalse(server._safe_eval('', {}))
        self.assertFalse(server._safe_eval('no_operator', {}))


# ---------------------------------------------------------------------------
# User management helpers
# ---------------------------------------------------------------------------
class TestUserManagement(unittest.TestCase):

    def setUp(self):
        with server.users_db_lock:
            server.users_db.clear()

    def tearDown(self):
        with server.users_db_lock:
            server.users_db.clear()

    def test_load_users_populates_db(self):
        # After module init the admin user should be present
        server.load_users()
        with server.users_db_lock:
            self.assertIn('admin', server.users_db)
            _, role = server.users_db['admin']
            self.assertEqual(role, 'admin')

    def test_save_and_reload_users(self):
        with server.users_db_lock:
            server.users_db['testuser'] = (server._pbkdf2_hash('TestPass1!'), 'viewer')
        server.save_users()
        server.load_users()
        with server.users_db_lock:
            self.assertIn('testuser', server.users_db)
            _, role = server.users_db['testuser']
            self.assertEqual(role, 'viewer')

    def test_users_file_has_restricted_permissions(self):
        with server.users_db_lock:
            server.users_db['perm_test'] = (server._pbkdf2_hash('TestPass1!'), 'viewer')
        server.save_users()
        if os.path.exists(server.USER_DB):
            stat = os.stat(server.USER_DB)
            # File should not be world-readable (mode & 0o007 == 0)
            self.assertEqual(stat.st_mode & 0o007, 0, "users.conf should not be world-readable")


# ---------------------------------------------------------------------------
# strip_ansi
# ---------------------------------------------------------------------------
class TestStripAnsi(unittest.TestCase):

    def test_removes_color_codes(self):
        s = '\033[0;32m[INFO]\033[0m Hello world'
        self.assertEqual(server.strip_ansi(s), '[INFO] Hello world')

    def test_passthrough_plain(self):
        s = 'plain text'
        self.assertEqual(server.strip_ansi(s), s)

    def test_empty_string(self):
        self.assertEqual(server.strip_ansi(''), '')


# ---------------------------------------------------------------------------
# format_duration helper (via noba-lib.sh — tested via Python port for parity)
# ---------------------------------------------------------------------------
class TestFormatDuration(unittest.TestCase):
    """Test the logic used in uptime formatting."""

    def _fmt(self, seconds):
        """Python equivalent of noba-lib.sh format_duration."""
        d = seconds // 86400
        h = (seconds % 86400) // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        parts = []
        if d: parts.append(f"{d}d")
        if h: parts.append(f"{h}h")
        if m: parts.append(f"{m}m")
        parts.append(f"{s}s")
        return ' '.join(parts)

    def test_seconds_only(self):
        self.assertEqual(self._fmt(45), '45s')

    def test_minutes_and_seconds(self):
        self.assertEqual(self._fmt(90), '1m 30s')

    def test_hours(self):
        self.assertEqual(self._fmt(3661), '1h 1m 1s')

    def test_days(self):
        self.assertEqual(self._fmt(86400 + 3600 + 60 + 1), '1d 1h 1m 1s')


if __name__ == '__main__':
    unittest.main()
