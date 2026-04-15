# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Cache abstraction layer (Redis or in-memory fallback)."""
from __future__ import annotations

import json
import logging
import os
import threading
import time

logger = logging.getLogger("noba")

REDIS_URL = os.environ.get("NOBA_REDIS_URL", "")


class _InMemoryBackend:
    """Thread-safe in-memory cache backend."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}  # key -> (value_json, expires_at)
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            val, expires = entry
            if expires and time.time() > expires:
                del self._store[key]
                return None
            return val

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        expires = time.time() + ttl if ttl else 0
        with self._lock:
            self._store[key] = (value, expires)

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._store.pop(key, None) is not None

    def keys(self, pattern: str = "*") -> list[str]:
        """Simple glob-style key matching (only supports prefix*)."""
        with self._lock:
            now = time.time()
            if pattern == "*":
                return [k for k, (_, exp) in self._store.items() if not exp or now <= exp]
            prefix = pattern.rstrip("*")
            return [k for k, (_, exp) in self._store.items()
                    if k.startswith(prefix) and (not exp or now <= exp)]

    def incr(self, key: str) -> int:
        with self._lock:
            entry = self._store.get(key)
            if entry:
                val = int(entry[0]) + 1
                self._store[key] = (str(val), entry[1])
                return val
            self._store[key] = ("1", 0)
            return 1

    def expire(self, key: str, ttl: int) -> None:
        with self._lock:
            entry = self._store.get(key)
            if entry:
                self._store[key] = (entry[0], time.time() + ttl)

    def flush(self) -> None:
        with self._lock:
            self._store.clear()

    def cleanup(self) -> None:
        """Remove expired entries."""
        now = time.time()
        with self._lock:
            expired = [k for k, (_, exp) in self._store.items() if exp and now > exp]
            for k in expired:
                del self._store[k]

    @property
    def is_redis(self) -> bool:
        return False


class _RedisBackend:
    """Redis-backed cache backend."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client = None
        self._connect()

    def _connect(self) -> None:
        try:
            import redis  # noqa: PLC0415
            self._client = redis.from_url(self._url, decode_responses=True, socket_timeout=3)
            self._client.ping()
            logger.info("Redis cache connected: %s", self._url.split("@")[-1] if "@" in self._url else self._url)
        except Exception as e:
            logger.warning("Redis connection failed, falling back to in-memory: %s", e)
            self._client = None

    def _safe(self, fn, default=None):
        if not self._client:
            return default
        try:
            return fn()
        except Exception as e:
            logger.debug("Redis operation failed: %s", e)
            return default

    def get(self, key: str) -> str | None:
        return self._safe(lambda: self._client.get(key))

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        def _do():
            if ttl:
                self._client.setex(key, ttl, value)
            else:
                self._client.set(key, value)
        self._safe(_do)

    def delete(self, key: str) -> bool:
        result = self._safe(lambda: self._client.delete(key), 0)
        return result > 0 if result else False

    def keys(self, pattern: str = "*") -> list[str]:
        return self._safe(lambda: self._client.keys(pattern), [])

    def incr(self, key: str) -> int:
        return self._safe(lambda: self._client.incr(key), 0)

    def expire(self, key: str, ttl: int) -> None:
        self._safe(lambda: self._client.expire(key, ttl))

    def flush(self) -> None:
        # Only flush noba keys, not the entire Redis DB
        keys = self.keys("noba:*")
        if keys:
            self._safe(lambda: self._client.delete(*keys))

    def cleanup(self) -> None:
        pass  # Redis handles TTL expiry natively

    @property
    def is_redis(self) -> bool:
        return self._client is not None


def _create_backend():
    """Create the appropriate cache backend."""
    if REDIS_URL:
        backend = _RedisBackend(REDIS_URL)
        if backend.is_redis:
            return backend
        logger.warning("Redis unavailable, using in-memory cache")
    return _InMemoryBackend()


# ── High-level cache API ─────────────────────────────────────────────────────

class Cache:
    """Unified cache interface with JSON serialization."""

    def __init__(self) -> None:
        self._backend = _create_backend()

    @property
    def is_redis(self) -> bool:
        return self._backend.is_redis

    def get(self, key: str):
        """Get a value, deserializing from JSON."""
        raw = self._backend.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    def set(self, key: str, value, ttl: int | None = None) -> None:
        """Set a value, serializing to JSON."""
        self._backend.set(key, json.dumps(value), ttl)

    def delete(self, key: str) -> bool:
        return self._backend.delete(key)

    def get_raw(self, key: str) -> str | None:
        """Get raw string value without JSON deserialization."""
        return self._backend.get(key)

    def set_raw(self, key: str, value: str, ttl: int | None = None) -> None:
        """Set raw string value without JSON serialization."""
        self._backend.set(key, value, ttl)

    def keys(self, pattern: str = "*") -> list[str]:
        return self._backend.keys(pattern)

    def incr(self, key: str) -> int:
        return self._backend.incr(key)

    def expire(self, key: str, ttl: int) -> None:
        self._backend.expire(key, ttl)

    def cleanup(self) -> None:
        self._backend.cleanup()


# Singleton
cache = Cache()
