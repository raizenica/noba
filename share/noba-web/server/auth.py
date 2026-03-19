"""Noba – Authentication, token management, and rate limiting."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta

from .config import AUTH_CONFIG, USER_DB, TOKEN_TTL_H, _PW_MIN_LEN, VALID_ROLES

logger = logging.getLogger("noba")

_USERNAME_RE = re.compile(r"^[^\s:/\\]{1,64}$")
_PBKDF2_ITERS = 200_000

# ── Password helpers ──────────────────────────────────────────────────────────

def pbkdf2_hash(password: str, salt: str | None = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERS)
    return f"pbkdf2:{salt}:{dk.hex()}"


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


def verify_password(stored: str, password: str) -> bool:
    if not stored:
        return False
    if stored.startswith("pbkdf2:"):
        parts = stored.split(":", 2)
        if len(parts) != 3:
            return False
        _, salt, expected = parts
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERS)
        return secrets.compare_digest(expected, dk.hex())
    # legacy sha256 format: salt:hexhash
    if ":" not in stored:
        return False
    salt, expected = stored.split(":", 1)
    actual = hashlib.sha256((salt + password).encode()).hexdigest()
    return secrets.compare_digest(expected, actual)


# ── User store ────────────────────────────────────────────────────────────────

class UserStore:
    """Thread-safe file-backed user database."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._db: dict[str, tuple[str, str]] = {}  # username -> (hash, role)
        self.load()

    def load(self) -> None:
        new_db: dict[str, tuple[str, str]] = {}
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
                        hash_role = rest.rsplit(":", 1)
                        if len(hash_role) != 2:
                            continue
                        new_db[uname] = (hash_role[0], hash_role[1])
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
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with self._lock:
                with open(fd, "w", encoding="utf-8") as f:
                    for username, (hashval, role) in self._db.items():
                        f.write(f"{username}:{hashval}:{role}\n")
                os.replace(tmp, USER_DB)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def get(self, username: str) -> tuple[str, str] | None:
        with self._lock:
            return self._db.get(username)

    def add(self, username: str, hashval: str, role: str) -> None:
        with self._lock:
            self._db[username] = (hashval, role)
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
            self._db[username] = (hashval, self._db[username][1])
        self.save()
        return True

    def list_users(self) -> list[dict]:
        with self._lock:
            return [{"username": u, "role": r} for u, (_, r) in self._db.items()]

    def exists(self, username: str) -> bool:
        with self._lock:
            return username in self._db


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

class TokenStore:
    """In-memory JWT-style bearer token store with TTL."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, tuple[str, str, datetime]] = {}

    def generate(self, username: str, role: str) -> str:
        token = secrets.token_urlsafe(32)
        expires = datetime.now() + timedelta(hours=TOKEN_TTL_H)
        with self._lock:
            self._tokens[token] = (username, role, expires)
        return token

    def validate(self, token: str) -> tuple[str | None, str | None]:
        with self._lock:
            data = self._tokens.get(token)
            if data and data[2] > datetime.now():
                return data[0], data[1]
            self._tokens.pop(token, None)
        return None, None

    def revoke(self, token: str) -> None:
        with self._lock:
            self._tokens.pop(token, None)

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
            return sessions

    def revoke_by_prefix(self, prefix: str) -> bool:
        """Revoke a token by its first 8 characters."""
        with self._lock:
            for tok in list(self._tokens):
                if tok[:8] == prefix[:8]:
                    del self._tokens[tok]
                    return True
            return False

    def cleanup(self) -> None:
        now = datetime.now()
        with self._lock:
            expired = [t for t, (_, _, exp) in list(self._tokens.items()) if exp <= now]
            for t in expired:
                del self._tokens[t]


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

    def record_failure(self, ip: str) -> bool:
        now = datetime.now()
        with self._lock:
            cutoff   = now - timedelta(seconds=self.window_s)
            attempts = [t for t in self._attempts.get(ip, []) if t > cutoff]
            attempts.append(now)
            self._attempts[ip] = attempts
            if len(attempts) >= self.max_attempts:
                self._lockouts[ip] = now + timedelta(seconds=self.lockout_s)
                self._attempts.pop(ip, None)
                return True
        return False

    def reset(self, ip: str) -> None:
        with self._lock:
            self._attempts.pop(ip, None)
            self._lockouts.pop(ip, None)

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


# ── Global singletons ─────────────────────────────────────────────────────────
users        = UserStore()
token_store  = TokenStore()
rate_limiter = RateLimiter()


def authenticate(authorization: str = "") -> tuple[str | None, str | None]:
    """Extract and validate token from Authorization header."""
    if authorization.startswith("Bearer "):
        return token_store.validate(authorization[7:])
    return None, None
