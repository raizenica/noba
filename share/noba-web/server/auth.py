# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Authentication, token management, and rate limiting."""
from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta

from .config import _PW_MIN_LEN, AUTH_CONFIG, TOKEN_TTL_H, USER_DB


def _get_db():
    """Lazy import of DB to avoid circular imports at module load time."""
    from .db import db  # noqa: PLC0415
    return db

logger = logging.getLogger("noba")

_USERNAME_RE = re.compile(r"^[^\s:/\\]{1,64}$")
_PBKDF2_ITERS = 600_000  # OWASP minimum for PBKDF2-HMAC-SHA256

# ── Password helpers ──────────────────────────────────────────────────────────

def pbkdf2_hash(password: str, salt: str | None = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERS)
    return f"pbkdf2:{_PBKDF2_ITERS}:{salt}:{dk.hex()}"


def valid_username(name: str) -> bool:
    return bool(_USERNAME_RE.match(name))


def check_password_strength(password: str) -> str | None:
    if len(password) < _PW_MIN_LEN:
        return f"Password must be at least {_PW_MIN_LEN} characters"
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter"
    if not re.search(r"[0-9!@#$%^&*()_+\-=\[\]{};':\",./<>?\\|`~]", password):
        return "Password must contain at least one digit or special character"
    return None


def verify_password(stored: str, password: str, *, username: str = "") -> bool:
    if not stored:
        return False
    if stored.startswith("pbkdf2:"):
        parts = stored.split(":", 3)
        if len(parts) == 4:
            # New format: pbkdf2:iterations:salt:hash
            _, iters_str, salt, expected = parts
            try:
                iters = int(iters_str)
            except (ValueError, TypeError):
                return False
        elif len(parts) == 3:
            # Legacy format: pbkdf2:salt:hash (200k iterations)
            _, salt, expected = parts
            iters = 200_000
        else:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iters)
        match = secrets.compare_digest(expected, dk.hex())
        # Auto-upgrade to current iteration count on successful login
        if match and iters < _PBKDF2_ITERS and username:
            try:
                new_hash = pbkdf2_hash(password)
                users.update_password(username, new_hash)
                logging.getLogger("noba").info(
                    "Upgraded PBKDF2 iterations for %s: %d→%d",
                    username, iters, _PBKDF2_ITERS,
                )
            except Exception as exc:
                # Non-fatal: login still succeeds with the old-iteration
                # hash; the upgrade will retry on next successful login.
                logging.getLogger("noba").warning(
                    "PBKDF2 iteration upgrade failed for %s (will retry on next login): %s",
                    username, exc,
                )
        return match
    # legacy sha256 format: salt:hexhash — auto-migrate to pbkdf2 on success
    if ":" not in stored:
        return False
    salt, expected = stored.split(":", 1)
    actual = hashlib.sha256((salt + password).encode()).hexdigest()
    if secrets.compare_digest(expected, actual):
        if username:
            _migrate_legacy_hash(username, password)
        return True
    return False


def _migrate_legacy_hash(username: str, password: str) -> None:
    """Silently upgrade a legacy SHA256 hash to PBKDF2 on successful login."""
    try:
        new_hash = pbkdf2_hash(password)
        users.update_password(username, new_hash)
        logging.getLogger("noba").info("Migrated legacy hash for user %s to PBKDF2", username)
    except Exception as exc:
        # Non-fatal — login still succeeds with the legacy hash. Log so
        # operators can investigate persistent migration failures
        # (typically write-permission issues on users.conf).
        logging.getLogger("noba").warning(
            "Legacy hash migration failed for %s (will retry on next login): %s",
            username, exc,
        )


# ── TOTP helpers ──────────────────────────────────────────────────────────────

def generate_totp_secret() -> str:
    """Generate a new TOTP secret for 2FA setup."""
    try:
        import pyotp  # noqa: PLC0415
        return pyotp.random_base32()
    except ImportError as exc:
        raise RuntimeError(
            "pyotp package is required for TOTP 2FA but not installed"
        ) from exc

def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code against a secret."""
    try:
        import pyotp
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)
    except ImportError:
        return False


# ── User store ────────────────────────────────────────────────────────────────

class UserStore:
    """Thread-safe file-backed user database."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._db: dict[str, tuple[str, str, str]] = {}  # username -> (hash, role, totp_secret)
        self.load()

    def load(self) -> None:
        new_db: dict[str, tuple[str, str, str]] = {}
        if os.path.exists(USER_DB):
            try:
                with open(USER_DB, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        user_rest = line.split(":", 1)
                        if len(user_rest) != 2:
                            continue
                        uname, rest = user_rest
                        # Try 3-field format: hash:role:totp_secret
                        # The hash itself may contain colons (e.g. pbkdf2:salt:dk),
                        # so we split from the right to get role and optional totp.
                        # 2-field legacy: rest = "hash:role"
                        # 3-field new:    rest = "hash:role:totp_secret"
                        # Since hash can contain ':', we rsplit to peel off fields.
                        # Try rsplit with maxsplit=2 to get (hash, role, totp)
                        parts = rest.rsplit(":", 2)
                        if len(parts) == 3:
                            # Could be (hash_part, role, totp) or (prefix, salt_dk, role)
                            # Determine if parts[1] is a valid role
                            if parts[1] in ("admin", "operator", "viewer"):
                                new_db[uname] = (parts[0], parts[1], parts[2])
                            else:
                                # Fall back to 2-field parse
                                hash_role = rest.rsplit(":", 1)
                                if len(hash_role) == 2:
                                    new_db[uname] = (hash_role[0], hash_role[1], "")
                        elif len(parts) == 2:
                            new_db[uname] = (parts[0], parts[1], "")
                        # len(parts) == 1 is malformed, skip
            except Exception as e:
                logger.error("Failed to load users: %s", e)
        with self._lock:
            self._db = new_db
        if not self._db:
            default_pass = secrets.token_urlsafe(12)
            self.add("admin", pbkdf2_hash(default_pass), "admin")
            logger.warning("=" * 60)
            logger.warning("FIRST RUN: Created default admin user.")
            logger.warning("  Username : admin")
            logger.warning("  Password : %s", default_pass)
            logger.warning("  Change this password immediately via Settings → Users.")
            logger.warning("=" * 60)

    def save(self) -> None:
        tmp = USER_DB + ".tmp"
        try:
            os.makedirs(os.path.dirname(USER_DB), exist_ok=True)
            with self._lock:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with open(fd, "w", encoding="utf-8") as f:
                    for username, (hashval, role, totp_secret) in self._db.items():
                        f.write(f"{username}:{hashval}:{role}:{totp_secret}\n")
                os.replace(tmp, USER_DB)
        except Exception:
            if os.path.exists(tmp):
                with contextlib.suppress(OSError):
                    os.unlink(tmp)

    def get(self, username: str) -> tuple[str, str] | None:
        with self._lock:
            data = self._db.get(username)
            if data:
                return (data[0], data[1])
        return None

    def add(self, username: str, hashval: str, role: str, totp_secret: str = "") -> None:
        with self._lock:
            self._db[username] = (hashval, role, totp_secret)
        self.save()

    def remove(self, username: str) -> bool:
        with self._lock:
            if username not in self._db:
                return False
            del self._db[username]
        self.save()
        return True

    def update_password(self, username: str, hashval: str) -> bool:
        with self._lock:
            if username not in self._db:
                return False
            old = self._db[username]
            self._db[username] = (hashval, old[1], old[2])
        self.save()
        return True

    def list_users(self) -> list[dict]:
        with self._lock:
            return [{"username": u, "role": r} for u, (_, r, _totp) in self._db.items()]

    def exists(self, username: str) -> bool:
        with self._lock:
            return username in self._db

    def get_totp_secret(self, username: str) -> str | None:
        """Get the TOTP secret for a user, if set."""
        with self._lock:
            data = self._db.get(username)
            if data and len(data) >= 3:
                return data[2] if data[2] else None
        return None

    def set_totp_secret(self, username: str, secret: str | None) -> bool:
        """Set or clear the TOTP secret for a user."""
        with self._lock:
            if username not in self._db:
                return False
            old = self._db[username]
            if len(old) >= 3:
                self._db[username] = (old[0], old[1], secret or "")
            else:
                self._db[username] = (old[0], old[1], secret or "")
        self.save()
        return True

    def has_totp(self, username: str) -> bool:
        """Check if user has TOTP enabled."""
        return bool(self.get_totp_secret(username))


# ── Legacy auth.conf reader ───────────────────────────────────────────────────
_user_cache: tuple | None = None
_user_cache_t: float = 0.0
_user_cache_lock = threading.Lock()
_USER_CACHE_TTL = 30.0


def load_legacy_user() -> tuple | None:
    global _user_cache, _user_cache_t
    with _user_cache_lock:
        if time.time() - _user_cache_t < _USER_CACHE_TTL:
            return _user_cache
    if not os.path.exists(AUTH_CONFIG):
        return None
    result = None
    try:
        with open(AUTH_CONFIG, encoding="utf-8") as f:
            line = f.readline().strip()
        if ":" in line:
            username, rest = line.split(":", 1)
            h = rest.rsplit(":", 1)[0] if rest.count(":") >= 2 else rest
            result = (username, h)
    except Exception:
        return None
    with _user_cache_lock:
        _user_cache = result
        _user_cache_t = time.time()
    return result


# ── Token store ───────────────────────────────────────────────────────────────

def _token_hash(token: str) -> str:
    """Return sha256 hex digest of a plaintext token."""
    return hashlib.sha256(token.encode()).hexdigest()


class TokenStore:
    """Bearer token store with in-memory cache and DB persistence.

    In-memory dict is keyed by plaintext token (original behavior).
    DB stores tokens hashed with sha256 so plaintext is never persisted.
    Tokens survive restarts: ``load_from_db()`` is called at startup to
    recover tokens from the previous run (they cannot be stored plaintext,
    so recovered tokens are keyed by their hash and validated via
    ``_validate_by_hash()``).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Keyed by plaintext token (fast path)
        self._tokens: dict[str, tuple[str, str, datetime]] = {}
        # Keyed by sha256 hash (populated from DB on startup restart recovery)
        self._tokens_by_hash: dict[str, tuple[str, str, datetime]] = {}

    # ── DB helpers ─────────────────────────────────────────────────────────────

    def _db_insert(self, token: str, username: str, role: str, expires: datetime) -> None:
        try:
            _get_db().insert_token(
                token_hash=_token_hash(token),
                username=username,
                role=role,
                created_at=int(time.time()),
                expires_at=int(expires.timestamp()),
            )
        except Exception as exc:
            logger.warning("TokenStore DB insert failed: %s", exc)

    def _db_delete(self, token: str) -> None:
        try:
            _get_db().delete_token(_token_hash(token))
        except Exception as exc:
            logger.warning("TokenStore DB delete failed: %s", exc)

    def _db_delete_by_hash(self, token_hash: str) -> None:
        try:
            _get_db().delete_token(token_hash)
        except Exception as exc:
            logger.warning("TokenStore DB delete_by_hash failed: %s", exc)

    # ── Public API ─────────────────────────────────────────────────────────────

    def load_from_db(self) -> None:
        """Hydrate hash-keyed store from DB on startup.

        We cannot reconstruct plaintext tokens, so recovered tokens are stored
        in ``_tokens_by_hash`` and validated when the client presents the token.
        """
        try:
            rows = _get_db().load_tokens()
            loaded = 0
            with self._lock:
                for row in rows:
                    h = row["token_hash"]
                    expires = datetime.fromtimestamp(row["expires_at"])
                    if expires > datetime.now():
                        self._tokens_by_hash[h] = (row["username"], row["role"], expires)
                        loaded += 1
            if loaded:
                logger.info("TokenStore: loaded %d token(s) from DB", loaded)
        except Exception as exc:
            logger.warning("TokenStore load_from_db failed: %s", exc)

    _MAX_TOKENS = 10_000  # safety cap — force cleanup if exceeded

    def generate(self, username: str, role: str) -> str:
        token = secrets.token_urlsafe(32)
        expires = datetime.now() + timedelta(hours=TOKEN_TTL_H)
        with self._lock:
            # Memory cap: if store is overflowing, force cleanup
            if len(self._tokens) + len(self._tokens_by_hash) > self._MAX_TOKENS:
                self._evict_expired_locked()
            self._tokens[token] = (username, role, expires)
        # Persist to DB (hashed — never plaintext)
        self._db_insert(token, username, role, expires)
        # Mirror to cache for cross-instance sharing
        from .cache import cache as _cache  # noqa: PLC0415

        if _cache.is_redis:
            _cache.set(f"noba:token:{token}", {"u": username, "r": role}, ttl=TOKEN_TTL_H * 3600)
        return token

    def validate(self, token: str) -> tuple[str | None, str | None]:
        # Fast path: check plaintext dict
        with self._lock:
            data = self._tokens.get(token)
            if data and data[2] > datetime.now():
                return data[0], data[1]
            self._tokens.pop(token, None)
        # Restart-recovery path: check hash dict (populated from DB)
        h = _token_hash(token)
        with self._lock:
            data = self._tokens_by_hash.get(h)
            if data and data[2] > datetime.now():
                # Promote to plaintext dict for faster future lookups
                self._tokens[token] = data
                self._tokens_by_hash.pop(h, None)
                return data[0], data[1]
            self._tokens_by_hash.pop(h, None)
        # DB fallback: check DB directly (for tokens from other processes)
        try:
            row = _get_db().get_token(h)
            if row:
                expires = datetime.fromtimestamp(row["expires_at"])
                if expires <= datetime.now():
                    return None, None
                with self._lock:
                    self._tokens[token] = (row["username"], row["role"], expires)
                return row["username"], row["role"]
        except Exception as exc:
            logger.warning("TokenStore DB fallback failed: %s", exc)
        # Redis fallback
        from .cache import cache as _cache  # noqa: PLC0415

        if _cache.is_redis:
            cached = _cache.get(f"noba:token:{token}")
            if cached:
                return cached.get("u"), cached.get("r")
        return None, None

    def revoke(self, token: str) -> None:
        with self._lock:
            self._tokens.pop(token, None)
            self._tokens_by_hash.pop(_token_hash(token), None)
        self._db_delete(token)
        from .cache import cache as _cache  # noqa: PLC0415

        if _cache.is_redis:
            _cache.delete(f"noba:token:{token}")

    def list_sessions(self) -> list[dict]:
        """List all active sessions (token prefix only for security)."""
        with self._lock:
            now = datetime.now()
            sessions = []
            for tok, (username, role, expires) in self._tokens.items():
                if expires > now:
                    sessions.append({
                        "prefix": tok[:8] + "\u2026",
                        "username": username,
                        "role": role,
                        "expires": expires.isoformat(),
                    })
            # Also include restart-recovered sessions (keyed by hash)
            for h, (username, role, expires) in self._tokens_by_hash.items():
                if expires > now:
                    sessions.append({
                        "prefix": h[:8] + "\u2026",
                        "username": username,
                        "role": role,
                        "expires": expires.isoformat(),
                    })
            return sessions

    def revoke_by_prefix(self, prefix: str) -> bool:
        """Revoke a token by its first 8 characters (plaintext token prefix)."""
        from .cache import cache as _cache  # noqa: PLC0415

        with self._lock:
            for tok in list(self._tokens):
                if tok[:8] == prefix[:8]:
                    del self._tokens[tok]
                    if _cache.is_redis:
                        _cache.delete(f"noba:token:{tok}")
                    self._db_delete_by_hash(_token_hash(tok))
                    return True
            # Also check hash-keyed tokens (restart-recovered sessions)
            for h in list(self._tokens_by_hash):
                if h[:8] == prefix[:8]:
                    del self._tokens_by_hash[h]
                    self._db_delete_by_hash(h)
                    return True
            return False

    def _evict_expired_locked(self) -> int:
        """Remove expired tokens while lock is held. Returns count removed."""
        now = datetime.now()
        expired = [t for t, (_, _, exp) in list(self._tokens.items()) if exp <= now]
        for t in expired:
            del self._tokens[t]
        expired_h = [h for h, (_, _, exp) in list(self._tokens_by_hash.items()) if exp <= now]
        for h in expired_h:
            del self._tokens_by_hash[h]
        return len(expired) + len(expired_h)

    def cleanup(self) -> None:
        with self._lock:
            self._evict_expired_locked()
        # Also clean expired rows from DB
        try:
            _get_db().cleanup_tokens()
        except Exception as exc:
            logger.warning("TokenStore DB cleanup failed: %s", exc)


# ── Rate limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    """Per-IP sliding-window rate limiter with lockout support."""

    def __init__(self, max_attempts: int = 5, window_s: int = 60, lockout_s: int = 300) -> None:
        self._lock = threading.Lock()
        self._attempts: dict[str, list] = {}
        self._lockouts: dict[str, datetime] = {}
        self.max_attempts = max_attempts
        self.window_s     = window_s
        self.lockout_s    = lockout_s

    def is_locked(self, ip: str) -> bool:
        with self._lock:
            expiry = self._lockouts.get(ip)
            if expiry and datetime.now() < expiry:
                return True
            self._lockouts.pop(ip, None)
        return False

    _MAX_ENTRIES = 50_000  # safety cap on tracked IPs

    def record_failure(self, ip: str) -> bool:
        now = datetime.now()
        with self._lock:
            # Memory cap: force cleanup if too many tracked IPs
            if len(self._attempts) > self._MAX_ENTRIES:
                cutoff_now = now - timedelta(seconds=self.window_s)
                self._attempts = {k: [t for t in v if t > cutoff_now]
                                  for k, v in self._attempts.items() if v}
            cutoff   = now - timedelta(seconds=self.window_s)
            attempts = [t for t in self._attempts.get(ip, []) if t > cutoff]
            attempts.append(now)
            self._attempts[ip] = attempts
            if len(attempts) >= self.max_attempts:
                self._lockouts[ip] = now + timedelta(seconds=self.lockout_s)
                self._attempts.pop(ip, None)
                return True
        return False

    def record_failure_user(self, ip: str, username: str) -> bool:
        """Track failures by both IP and username, lock out if either exceeds threshold."""
        ip_locked = self.record_failure(ip)
        user_key = f"user:{username}"
        now = datetime.now()
        with self._lock:
            cutoff = now - timedelta(seconds=self.window_s)
            attempts = [t for t in self._attempts.get(user_key, []) if t > cutoff]
            attempts.append(now)
            self._attempts[user_key] = attempts
            if len(attempts) >= self.max_attempts:
                self._lockouts[user_key] = now + timedelta(seconds=self.lockout_s)
                self._attempts.pop(user_key, None)
                return True
        return ip_locked

    def is_locked_user(self, username: str) -> bool:
        """Check if a username is locked out."""
        return self.is_locked(f"user:{username}")

    def reset(self, ip: str) -> None:
        with self._lock:
            self._attempts.pop(ip, None)
            self._lockouts.pop(ip, None)

    def reset_user(self, username: str) -> None:
        """Reset lockout state for a username."""
        self.reset(f"user:{username}")

    def cleanup(self) -> None:
        now = datetime.now()
        with self._lock:
            cutoff = now - timedelta(seconds=self.window_s)
            to_delete = []
            for ip, ts in self._attempts.items():
                pruned = [t for t in ts if t > cutoff]
                if pruned:
                    self._attempts[ip] = pruned
                else:
                    to_delete.append(ip)
            for ip in to_delete:
                del self._attempts[ip]
            expired = [ip for ip, exp in self._lockouts.items() if exp <= now]
            for ip in expired:
                del self._lockouts[ip]


# ── IP whitelist ──────────────────────────────────────────────────────────────

def check_ip_whitelist(ip: str, read_settings_fn) -> bool:
    """Return True if IP is allowed (whitelist empty = all allowed)."""
    cfg = read_settings_fn()
    whitelist = cfg.get("ipWhitelist", "")
    if not whitelist:
        return True
    allowed = [x.strip() for x in whitelist.split(",") if x.strip()]
    if not allowed:
        return True
    return ip in allowed


# ── Permissions ──────────────────────────────────────────────────────────────
PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset([
        "stats:read", "history:read", "integrations:read", "alerts:read",
        "automations:read", "backups:read", "plugins:read", "notifications:read",
        "dashboard:read", "dashboard:write",
    ]),
    "operator": frozenset([
        "stats:read", "history:read", "integrations:read", "alerts:read",
        "automations:read", "automations:run", "automations:write",
        "backups:read", "backups:restore",
        "plugins:read", "notifications:read",
        "dashboard:read", "dashboard:write",
        "services:control", "containers:control", "scripts:run",
        "webhooks:trigger", "compose:control", "wol:send", "dns:toggle",
        "hass:control",
    ]),
    "admin": frozenset([
        "stats:read", "history:read", "integrations:read", "alerts:read",
        "automations:read", "automations:run", "automations:write", "automations:delete",
        "backups:read", "backups:restore", "backups:manage",
        "plugins:read", "plugins:install",
        "notifications:read", "notifications:manage",
        "dashboard:read", "dashboard:write",
        "services:control", "containers:control", "scripts:run",
        "webhooks:trigger", "compose:control", "wol:send", "dns:toggle",
        "hass:control",
        "users:manage", "settings:write", "audit:read",
        "api_keys:manage", "ssh_keys:manage", "terminal:access",
        "config:backup", "config:restore",
        "system:governor", "cloud:manage",
    ]),
}


def has_permission(role: str, permission: str) -> bool:
    """Check if a role has a specific permission."""
    return permission in PERMISSIONS.get(role, frozenset())


def get_permissions(role: str) -> list[str]:
    """Get all permissions for a role."""
    return sorted(PERMISSIONS.get(role, frozenset()))


# ── WS handshake token store ──────────────────────────────────────────────────

class WsTokenStore:
    """Short-lived (30 s), one-time-use tokens for WebSocket/SSE authentication.

    Flow: client POSTs /api/ws-token → gets token → opens WS with ?token=<ws_token>
    Server calls consume() which validates and deletes in one atomic operation.
    """

    _TTL = 30  # seconds

    def __init__(self) -> None:
        self._tokens: dict[str, tuple[str, str, float]] = {}  # token → (username, role, expires)
        self._lock = threading.Lock()

    def issue(self, username: str, role: str) -> str:
        """Issue a new short-lived token bound to username and role."""
        token = secrets.token_urlsafe(32)
        expires = time.time() + self._TTL
        with self._lock:
            # Prune expired entries opportunistically to prevent unbounded growth
            now = time.time()
            expired = [k for k, (_, _, exp) in self._tokens.items() if exp < now]
            for k in expired:
                del self._tokens[k]
            self._tokens[token] = (username, role, expires)
        return token

    def consume(self, token: str) -> tuple[str | None, str | None]:
        """Validate and immediately invalidate token. Returns (username, role) or (None, None)."""
        with self._lock:
            entry = self._tokens.pop(token, None)
        if entry is None:
            return None, None
        username, role, expires = entry
        if time.time() > expires:
            return None, None
        return username, role


# ── Global singletons ─────────────────────────────────────────────────────────
users        = UserStore()
token_store  = TokenStore()
rate_limiter = RateLimiter()
ws_token_store = WsTokenStore()


def authenticate_ldap(username: str, password: str, read_settings_fn) -> tuple[str | None, str | None]:
    """Attempt LDAP authentication. Returns (username, role) or (None, None)."""
    cfg = read_settings_fn()
    ldap_url = cfg.get("ldapUrl", "")
    base_dn = cfg.get("ldapBaseDn", "")
    bind_dn = cfg.get("ldapBindDn", "")
    bind_pw = cfg.get("ldapBindPassword", "")
    if not ldap_url or not base_dn:
        return None, None
    try:
        import ldap3
        server = ldap3.Server(ldap_url, get_info=ldap3.NONE, connect_timeout=5)
        # First bind with service account to search for user
        conn = ldap3.Connection(server, user=bind_dn, password=bind_pw, auto_bind=True)
        # Escape LDAP special characters to prevent injection (RFC 4515)
        safe_name = _ldap_escape(username)
        conn.search(base_dn, f"(|(uid={safe_name})(sAMAccountName={safe_name})(mail={safe_name}))",
                    attributes=["memberOf", "cn"])
        if not conn.entries:
            conn.unbind()
            return None, None
        user_dn = conn.entries[0].entry_dn
        conn.unbind()
        # Bind as the user to verify password
        user_conn = ldap3.Connection(server, user=user_dn, password=password, auto_bind=True)
        user_conn.unbind()
        # Map role -- default to viewer, could check memberOf for admin/operator groups
        role = "viewer"
        return username, role
    except ImportError:
        logger.debug("ldap3 not installed -- LDAP auth unavailable")
        return None, None
    except Exception as e:
        logger.debug("LDAP auth failed for %s: %s", username, e)
        return None, None


_LDAP_SPECIALS = frozenset('\\*()\x00&|=~!')


def _ldap_escape(s: str) -> str:
    """RFC 4515 LDAP filter value escaping — all special characters."""
    out = []
    for c in s:
        if c in _LDAP_SPECIALS:
            out.append(f"\\{ord(c):02x}")
        elif ord(c) > 127:
            for b in c.encode("utf-8"):
                out.append(f"\\{b:02x}")
        else:
            out.append(c)
    return "".join(out)


def authenticate(authorization: str = "") -> tuple[str | None, str | None]:
    """Extract and validate token from Authorization header or API key."""
    if authorization.startswith("Bearer "):
        return token_store.validate(authorization[7:])
    # API key support
    if authorization.startswith("ApiKey "):
        key = authorization[7:]
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        from .db import db
        key_data = db.get_api_key(key_hash)
        if key_data:
            if key_data.get("expires_at") and key_data["expires_at"] < int(time.time()):
                return None, None
            return f"apikey:{key_data['name']}", key_data['role']
    return None, None
